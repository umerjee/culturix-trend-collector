"""Remote command execution on a RunPod pod over SSH — used to trigger
ltx-trainer for LoRA training (app/services/culturetoon_lora.py) without
requiring a human to SSH in and run it by hand.

Requires RUNPOD_SSH_PRIVATE_KEY (the PEM-format private key content, or a
path to a file containing it — see _load_private_key). The matching public
key must be added to RunPod console -> Settings -> SSH Public Keys before a
pod exposes SSH access to it.
"""
import io
import logging
import os

logger = logging.getLogger("culturix.media.runpod_ssh")

_SSH_USER = "root"  # RunPod's ComfyUI pod template's default SSH user
_CONNECT_TIMEOUT = 30


class RunPodSSHError(Exception):
    pass


def _load_private_key():
    import paramiko

    raw = os.getenv("RUNPOD_SSH_PRIVATE_KEY", "")
    if not raw:
        raise RuntimeError("RUNPOD_SSH_PRIVATE_KEY must be set")
    # Accept either the key content directly (e.g. a Railway secret var) or
    # a path to a file containing it (e.g. a mounted secret file) — the
    # content case is detected by its PEM header, same disambiguation
    # convention as other providers in this codebase that accept either a
    # literal secret or a file path.
    if os.path.exists(raw):
        with open(raw, "r", encoding="utf-8") as f:
            raw = f.read()
    key_file = io.StringIO(raw)
    for key_cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
        try:
            key_file.seek(0)
            return key_cls.from_private_key(key_file)
        except paramiko.SSHException:
            continue
    raise RunPodSSHError("RUNPOD_SSH_PRIVATE_KEY is not a recognized private key format (tried RSA/Ed25519/ECDSA)")


def _connect(host: str, port: int):
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host, port=port, username=_SSH_USER, pkey=_load_private_key(),
        timeout=_CONNECT_TIMEOUT,
    )
    return client


def run_remote_command(host: str, port: int, command: str, timeout_seconds: int = 1800) -> tuple:
    """Runs `command` on the pod over SSH. Returns (exit_code, stdout, stderr).
    Blocks until the command exits or timeout_seconds elapses."""
    client = _connect(host, port)
    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout_seconds)
        exit_code = stdout.channel.recv_exit_status()
        return exit_code, stdout.read().decode("utf-8", errors="replace"), stderr.read().decode("utf-8", errors="replace")
    finally:
        client.close()


def download_file(host: str, port: int, remote_path: str) -> bytes:
    """Fetches a file from the pod via SFTP — used for retrieving trained
    LoRA files (can be tens-hundreds of MB), where piping through
    exec_command's stdout (e.g. base64-encoded) would be both slower and
    memory-heavier than a proper file transfer."""
    client = _connect(host, port)
    try:
        sftp = client.open_sftp()
        try:
            with sftp.open(remote_path, "rb") as f:
                return f.read()
        finally:
            sftp.close()
    finally:
        client.close()
