"""Tests for the training-pod lifecycle additions in
app/media/runpod_client.py (create_training_pod/terminate_pod/
wait_for_ssh_ready). create_training_pod uses RunPod's REST API (a list of
fallback GPU types), the rest still use the GraphQL API — both mocked at
the httpx boundary, RunPod's real APIs are never touched."""
import os

os.environ.setdefault("RUNPOD_API_KEY", "test-key")

import pytest

from app.media.runpod_client import (
    create_training_pod, create_training_pod_with_retry, terminate_pod, wait_for_ssh_ready, RunPodError,
    _DEFAULT_TRAINING_GPU_TYPE_IDS,
)


def _mock_graphql_response(mocker, data=None, errors=None):
    resp = mocker.Mock()
    resp.raise_for_status = mocker.Mock()
    resp.json.return_value = {"data": data or {}, "errors": errors}
    return resp


def _mock_rest_response(mocker, status_code=201, json_body=None, text=""):
    resp = mocker.Mock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.text = text
    return resp


class TestCreateTrainingPod:
    def test_missing_image_raises_without_calling_runpod(self, mocker, monkeypatch):
        monkeypatch.delenv("RUNPOD_TRAINING_IMAGE", raising=False)
        mock_post = mocker.patch("httpx.post")
        with pytest.raises(RuntimeError):
            create_training_pod()
        mock_post.assert_not_called()

    def test_gpu_type_id_env_var_is_optional(self, mocker, monkeypatch):
        # Confirmed live 2026-08-20: pinning to one exact GPU type is too
        # fragile against real availability swings — the built-in fallback
        # list is used automatically when this isn't set at all.
        monkeypatch.delenv("RUNPOD_TRAINING_GPU_TYPE_ID", raising=False)
        monkeypatch.setenv("RUNPOD_TRAINING_IMAGE", "my/training-image")
        mocker.patch("httpx.post", return_value=_mock_rest_response(
            mocker, json_body={"id": "pod-new"},
        ))
        assert create_training_pod() == "pod-new"

    def test_success_returns_pod_id(self, mocker, monkeypatch):
        monkeypatch.delenv("RUNPOD_TRAINING_GPU_TYPE_ID", raising=False)
        monkeypatch.setenv("RUNPOD_TRAINING_IMAGE", "my/training-image")
        mocker.patch("httpx.post", return_value=_mock_rest_response(
            mocker, json_body={"id": "pod-new"},
        ))
        assert create_training_pod() == "pod-new"

    def test_requests_fallback_list_with_availability_priority(self, mocker, monkeypatch):
        monkeypatch.delenv("RUNPOD_TRAINING_GPU_TYPE_ID", raising=False)
        monkeypatch.setenv("RUNPOD_TRAINING_IMAGE", "my/training-image")
        mock_post = mocker.patch("httpx.post", return_value=_mock_rest_response(
            mocker, json_body={"id": "pod-new"},
        ))
        create_training_pod()
        sent = mock_post.call_args.kwargs["json"]
        assert sent["gpuTypeIds"] == _DEFAULT_TRAINING_GPU_TYPE_IDS
        assert sent["gpuTypePriority"] == "availability"

    def test_gpu_type_id_override_is_prepended_not_replaced(self, mocker, monkeypatch):
        monkeypatch.setenv("RUNPOD_TRAINING_GPU_TYPE_ID", "NVIDIA H100 80GB HBM3")
        monkeypatch.setenv("RUNPOD_TRAINING_IMAGE", "my/training-image")
        mock_post = mocker.patch("httpx.post", return_value=_mock_rest_response(
            mocker, json_body={"id": "pod-new"},
        ))
        create_training_pod()
        sent = mock_post.call_args.kwargs["json"]
        assert sent["gpuTypeIds"][0] == "NVIDIA H100 80GB HBM3"
        assert set(sent["gpuTypeIds"]) == {"NVIDIA H100 80GB HBM3", *_DEFAULT_TRAINING_GPU_TYPE_IDS}

    def test_does_not_request_a_network_volume_mount(self, mocker, monkeypatch):
        # The training pod and the Network Volume's inference region
        # frequently aren't the same region — see
        # app/services/culturetoon_lora.py's docstring — so pod creation
        # must not request a volume mount at all.
        monkeypatch.delenv("RUNPOD_TRAINING_GPU_TYPE_ID", raising=False)
        monkeypatch.setenv("RUNPOD_TRAINING_IMAGE", "my/training-image")
        mock_post = mocker.patch("httpx.post", return_value=_mock_rest_response(
            mocker, json_body={"id": "pod-new"},
        ))
        create_training_pod()
        sent = mock_post.call_args.kwargs["json"]
        assert "networkVolumeId" not in sent

    def test_uses_community_cloud_not_secure(self, mocker, monkeypatch):
        # Confirmed live 2026-08-20: SECURE-cloud hit a real
        # SUPPLY_CONSTRAINT error on the first live attempt. COMMUNITY is a
        # broader, generally better-available pool — an acceptable
        # tradeoff for an ephemeral one-shot training pod.
        monkeypatch.delenv("RUNPOD_TRAINING_GPU_TYPE_ID", raising=False)
        monkeypatch.setenv("RUNPOD_TRAINING_IMAGE", "my/training-image")
        mock_post = mocker.patch("httpx.post", return_value=_mock_rest_response(
            mocker, json_body={"id": "pod-new"},
        ))
        create_training_pod()
        sent = mock_post.call_args.kwargs["json"]
        assert sent["cloudType"] == "COMMUNITY"

    def test_no_pod_returned_raises(self, mocker, monkeypatch):
        monkeypatch.delenv("RUNPOD_TRAINING_GPU_TYPE_ID", raising=False)
        monkeypatch.setenv("RUNPOD_TRAINING_IMAGE", "my/training-image")
        mocker.patch("httpx.post", return_value=_mock_rest_response(
            mocker, json_body={},
        ))
        with pytest.raises(RunPodError):
            create_training_pod()

    def test_error_status_raises(self, mocker, monkeypatch):
        monkeypatch.delenv("RUNPOD_TRAINING_GPU_TYPE_ID", raising=False)
        monkeypatch.setenv("RUNPOD_TRAINING_IMAGE", "my/training-image")
        mocker.patch("httpx.post", return_value=_mock_rest_response(
            mocker, status_code=400, text="insufficient GPU availability",
        ))
        with pytest.raises(RunPodError, match="insufficient GPU availability"):
            create_training_pod()


class TestCreateTrainingPodWithRetry:
    def test_succeeds_immediately_without_sleeping(self, mocker):
        mocker.patch("app.media.runpod_client.create_training_pod", return_value="pod-1")
        mock_sleep = mocker.patch("time.sleep")
        assert create_training_pod_with_retry() == "pod-1"
        mock_sleep.assert_not_called()

    def test_retries_past_a_supply_constraint_then_succeeds(self, mocker):
        # Real error confirmed live: RunPod's own SUPPLY_CONSTRAINT
        # message when a GPU tier has no matching host available.
        mock_create = mocker.patch(
            "app.media.runpod_client.create_training_pod",
            side_effect=[RunPodError("SUPPLY_CONSTRAINT: no instances available"), "pod-2"],
        )
        mocker.patch("time.sleep")
        assert create_training_pod_with_retry(max_retries=2, backoff_seconds=0.01) == "pod-2"
        assert mock_create.call_count == 2

    def test_raises_after_exhausting_retries(self, mocker):
        mocker.patch("app.media.runpod_client.create_training_pod", side_effect=RunPodError("still no supply"))
        mocker.patch("time.sleep")
        with pytest.raises(RunPodError, match="failed to allocate after 3 attempt"):
            create_training_pod_with_retry(max_retries=2, backoff_seconds=0.01)

    def test_retry_knobs_read_from_env_when_not_passed(self, mocker, monkeypatch):
        monkeypatch.setenv("RUNPOD_TRAINING_ALLOCATION_MAX_RETRIES", "1")
        monkeypatch.setenv("RUNPOD_TRAINING_ALLOCATION_BACKOFF_SECONDS", "0.01")
        mock_create = mocker.patch(
            "app.media.runpod_client.create_training_pod",
            side_effect=[RunPodError("no supply"), "pod-3"],
        )
        mocker.patch("time.sleep")
        assert create_training_pod_with_retry() == "pod-3"
        assert mock_create.call_count == 2


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

    def test_no_ssh_port_raises_once_deadline_passes(self, mocker):
        running_pod = {"pod": {"id": "pod-1", "desiredStatus": "RUNNING", "runtime": {"ports": []}}}
        mocker.patch("httpx.post", return_value=_mock_graphql_response(mocker, data=running_pod))
        mocker.patch("time.sleep")  # keeps the retry loop from actually waiting in real time
        with pytest.raises(RunPodError):
            wait_for_ssh_ready("pod-1", timeout_seconds=0.05)  # tiny — just needs the deadline to pass quickly

    def test_ssh_port_appearing_on_a_later_poll_still_succeeds(self, mocker):
        # Confirmed live 2026-08-20: a pod can report RUNNING before
        # RunPod's own port-forwarding info has populated — this is that
        # exact race, and the fix is polling get_pod_ssh_info instead of
        # checking it once.
        not_yet = {"pod": {"id": "pod-1", "desiredStatus": "RUNNING", "runtime": {"ports": []}}}
        ready = {
            "pod": {
                "id": "pod-1", "desiredStatus": "RUNNING",
                "runtime": {"ports": [{"ip": "1.2.3.4", "privatePort": 22, "publicPort": 2222}]},
            },
        }
        mocker.patch("httpx.post", side_effect=[
            _mock_graphql_response(mocker, data=not_yet),  # _wait_until_running's check
            _mock_graphql_response(mocker, data=not_yet),  # get_pod_ssh_info, 1st try — no port yet
            _mock_graphql_response(mocker, data=ready),    # get_pod_ssh_info, 2nd try — now ready
        ])
        mocker.patch("time.sleep")
        host, port = wait_for_ssh_ready("pod-1", timeout_seconds=30)
        assert (host, port) == ("1.2.3.4", 2222)
