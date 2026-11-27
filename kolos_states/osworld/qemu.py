"""Restore a running Docker guest to its clean boot state between episodes."""

from __future__ import annotations

import json
import time

SOCKET = "/tmp/kolos-osworld-qmp.sock"
ARGUMENT = f"-qmp unix:{SOCKET},server=on,wait=off"
TAG = "kolos-osworld-clean"
READ_REPLY = f"""\
coproc QMP {{ exec nc -q 0 -U {SOCKET}; }}
exec 3>&"${{QMP[1]}}" 4<&"${{QMP[0]}}"
printf '%s\\n' "$@" >&3
while IFS= read -r -t 40 reply <&4; do
    printf '%s\\n' "$reply"
    case "$reply" in *'"id"'*'"kolos"'*) exit 0 ;; esac
done
"""


class MonitorUnavailable(RuntimeError):
    """The monitor did not confirm whether it accepted a request."""


class Snapshot:
    """Use the writable guest overlay and leave the original backing image read-only."""

    def __init__(self, container) -> None:
        self.container = container
        blocks = self.command("query-block")
        disk = next((block["inserted"] for block in blocks if block.get("inserted", {}).get("file") == "/boot.qcow2"), {})
        self.disk = disk.get("node-name")
        if not self.disk or disk.get("drv") != "qcow2":
            raise RuntimeError("QEMU did not expose the expected writable guest overlay")

    def command(self, name: str, **arguments):
        """Execute a QMP request on the private Unix socket inside this container."""
        handshake = json.dumps({"execute": "qmp_capabilities", "id": "hello"})
        request = json.dumps({"execute": name, "arguments": arguments, "id": "kolos"})
        code, output = self.container.exec_run([
            "timeout", "45", "bash", "-c", READ_REPLY, "qmp", handshake, request,
        ])
        for line in output.splitlines():
            try:
                reply = json.loads(line)
            except json.JSONDecodeError:
                continue
            if reply.get("id") == "kolos":
                if "error" in reply:
                    raise RuntimeError(f"QEMU {name}: {reply['error']['desc']}")
                return reply["return"]
        raise MonitorUnavailable(f"QEMU monitor did not return a response to {name} (exit {code})")

    def state(self, operation: str) -> None:
        """Wait for the asynchronous snapshot operation before exposing the guest."""
        job_id = f"kolos-{operation}"
        deadline = time.monotonic() + 180
        try:
            self.command(f"snapshot-{operation}", **{
                "job-id": job_id, "tag": TAG, "vmstate": self.disk, "devices": [self.disk],
            })
        except MonitorUnavailable:
            pass  # The operation may already be running. Query its ID before taking another action.
        while time.monotonic() < deadline:
            try:
                jobs = self.command("query-jobs")
            except MonitorUnavailable:
                continue
            job = next((value for value in jobs if value["id"] == job_id), None)
            if job and job["status"] == "concluded":
                self.command("job-dismiss", id=job_id)
                if job.get("error"):
                    raise RuntimeError(f"QEMU {operation} failed: {job['error']}")
                return
            time.sleep(.5)
        raise RuntimeError(f"QEMU {operation} did not finish in time")
