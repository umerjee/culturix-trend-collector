"""Tests for the training-pod lifecycle additions in
app/media/runpod_client.py (create_training_pod/terminate_pod/
wait_for_ssh_ready) — mocked at the httpx boundary, RunPod's real GraphQL
API is never touched."""
import os

os.environ.setdefault("RUNPOD_API_KEY", "test-key")

import pytest

from app.media.runpod_client import create_training_pod, terminate_pod, wait_for_ssh_ready, RunPodError


def _mock_graphql_response(mocker, data=None, errors=None):
    resp = mocker.Mock()
    resp.raise_for_status = mocker.Mock()
    resp.json.return_value = {"data": data or {}, "errors": errors}
    return resp


class TestCreateTrainingPod:
    def test_missing_config_raises_without_calling_runpod(self, mocker, monkeypatch):
        monkeypatch.delenv("RUNPOD_TRAINING_GPU_TYPE_ID", raising=False)
        monkeypatch.delenv("RUNPOD_TRAINING_IMAGE", raising=False)
        mock_post = mocker.patch("httpx.post")
        with pytest.raises(RuntimeError):
            create_training_pod()
        mock_post.assert_not_called()

    def test_success_returns_pod_id(self, mocker, monkeypatch):
        monkeypatch.setenv("RUNPOD_TRAINING_GPU_TYPE_ID", "NVIDIA A100 80GB PCIe")
        monkeypatch.setenv("RUNPOD_TRAINING_IMAGE", "my/training-image")
        mocker.patch("httpx.post", return_value=_mock_graphql_response(
            mocker, data={"podFindAndDeployOnDemand": {"id": "pod-new", "desiredStatus": "RUNNING"}},
        ))
        assert create_training_pod() == "pod-new"

    def test_does_not_request_a_network_volume_mount(self, mocker, monkeypatch):
        # The training pod (A100 PCIe) and the Network Volume's inference
        # region (RTX 4090) frequently aren't the same region — see
        # app/services/culturetoon_lora.py's docstring — so pod creation
        # must not request a volume mount at all.
        monkeypatch.setenv("RUNPOD_TRAINING_GPU_TYPE_ID", "NVIDIA A100 80GB PCIe")
        monkeypatch.setenv("RUNPOD_TRAINING_IMAGE", "my/training-image")
        monkeypatch.delenv("RUNPOD_NETWORK_VOLUME_ID", raising=False)
        mock_post = mocker.patch("httpx.post", return_value=_mock_graphql_response(
            mocker, data={"podFindAndDeployOnDemand": {"id": "pod-new", "desiredStatus": "RUNNING"}},
        ))
        create_training_pod()
        sent_variables = mock_post.call_args.kwargs["json"]["variables"]
        assert "networkVolumeId" not in sent_variables["input"]

    def test_no_pod_returned_raises(self, mocker, monkeypatch):
        monkeypatch.setenv("RUNPOD_TRAINING_GPU_TYPE_ID", "NVIDIA A100 80GB PCIe")
        monkeypatch.setenv("RUNPOD_TRAINING_IMAGE", "my/training-image")
        mocker.patch("httpx.post", return_value=_mock_graphql_response(
            mocker, data={"podFindAndDeployOnDemand": None},
        ))
        with pytest.raises(RunPodError):
            create_training_pod()

    def test_graphql_error_raises(self, mocker, monkeypatch):
        monkeypatch.setenv("RUNPOD_TRAINING_GPU_TYPE_ID", "NVIDIA A100 80GB PCIe")
        monkeypatch.setenv("RUNPOD_TRAINING_IMAGE", "my/training-image")
        mocker.patch("httpx.post", return_value=_mock_graphql_response(
            mocker, errors=[{"message": "insufficient GPU availability"}],
        ))
        with pytest.raises(RunPodError, match="insufficient GPU availability"):
            create_training_pod()


class TestTerminatePod:
    def test_success(self, mocker):
        mock_post = mocker.patch("httpx.post", return_value=_mock_graphql_response(
            mocker, data={"podTerminate": True},
        ))
        terminate_pod("pod-1")
        mock_post.assert_called_once()

    def test_swallows_and_logs_on_failure(self, mocker):
        mocker.patch("httpx.post", side_effect=RuntimeError("network blip"))
        terminate_pod("pod-1")  # must not raise


class TestWaitForSshReady:
    def test_returns_ssh_info_once_running(self, mocker):
        running_pod = {
            "pod": {
                "id": "pod-1", "desiredStatus": "RUNNING",
                "runtime": {"ports": [{"ip": "1.2.3.4", "privatePort": 22, "publicPort": 2222}]},
            },
        }
        mocker.patch("httpx.post", return_value=_mock_graphql_response(mocker, data=running_pod))
        mocker.patch("time.sleep")
        host, port = wait_for_ssh_ready("pod-1", timeout_seconds=30)
        assert (host, port) == ("1.2.3.4", 2222)

    def test_no_ssh_port_raises(self, mocker):
        running_pod = {"pod": {"id": "pod-1", "desiredStatus": "RUNNING", "runtime": {"ports": []}}}
        mocker.patch("httpx.post", return_value=_mock_graphql_response(mocker, data=running_pod))
        mocker.patch("time.sleep")
        with pytest.raises(RunPodError):
            wait_for_ssh_ready("pod-1", timeout_seconds=30)
