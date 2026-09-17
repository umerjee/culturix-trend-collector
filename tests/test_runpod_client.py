"""Tests for the ephemeral-pod lifecycle helpers in
app/media/runpod_client.py (terminate_pod/wait_for_ssh_ready), used by
app/media/runpod_volume_relay.py's short-lived carrier pods and
app/scheduler.py's orphan-pod reaper — both mocked at the httpx boundary
against the GraphQL API, RunPod's real API is never touched."""
import os

os.environ.setdefault("RUNPOD_API_KEY", "test-key")

import pytest

from app.media.runpod_client import terminate_pod, wait_for_ssh_ready, RunPodError


def _mock_graphql_response(mocker, data=None, errors=None):
    resp = mocker.Mock()
    resp.raise_for_status = mocker.Mock()
    resp.json.return_value = {"data": data or {}, "errors": errors}
    return resp


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
