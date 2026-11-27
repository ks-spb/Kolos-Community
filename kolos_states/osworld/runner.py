"""Reset and score official tasks without sharing judge data with Kolos."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import subprocess
import time
from contextlib import contextmanager
from functools import partial
from importlib.metadata import version
from io import BytesIO
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from ..core import StateEngine
from ..ipc import atomic_json
from ..storage import Store
from .agent import MAX_ACTIONS, MAX_SECONDS, Session, Unconfirmed, run_agent, teach
from .bindings import app_present
from .curriculum import CONTROLS, DEMONSTRATIONS, Lesson, execute, steps
from .gui import SCREEN_SIZE, Frame
from .intent import interpret
from .manifest import REVISION
from .qemu import ARGUMENT, Snapshot

RELEASE = "1.0.3"
DOCKER_IMAGE = "happysixd/osworld-docker"
DOCKER_DIGEST = "sha256:0e6497a9295647cf05bf2b2af522fdd79bdeba2737595259cab310a3bcf6baa9"
VM_RAM = "4G"
VM_CPUS = "3"
VM_READY_TIMEOUT = 1200
DESKTOP_READY_TIMEOUT = 720
GNOME_START_TIMEOUT = 600
GNOME_UNIT = "org.gnome.Shell@x11.service"
SCREENSHOT_TIMEOUT = 45
A11Y_TIMEOUT = 120
logger = logging.getLogger(__name__)


class Guest:
    """Expose the observer and structured motor operation available to the agent."""

    def __init__(self, desktop) -> None:
        self._desktop = desktop

    def observe(self) -> Frame:
        """Read a fresh independent observation without taking another action."""
        return Frame.read(self._desktop._get_obs())

    def step(self, action: dict) -> Frame:
        """Send one GUI primitive through the original OSWorld action space."""
        raw, _, _, _ = self._desktop.step(action, pause=.5)
        return Frame.read(raw)


def image_digest() -> str:
    """Verify that the local Docker tag still points to the pinned runtime image."""
    data = subprocess.check_output(
        ["docker", "image", "inspect", DOCKER_IMAGE, "--format", "{{json .RepoDigests}}"], text=True,
    )
    digests = {item.rsplit("@", 1)[-1] for item in json.loads(data)}
    if DOCKER_DIGEST not in digests:
        raise RuntimeError(f"Pin {DOCKER_IMAGE} to {DOCKER_DIGEST} before running")
    return DOCKER_DIGEST


def sha256(path: Path) -> str:
    """Hash a file without loading the complete guest image into memory."""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def guest_digest(image: Path, output: Path) -> str:
    """Reuse an image digest across modes while the same local file is unchanged."""
    stamp = image_stamp(image)
    cache = output / "guest-image.json"
    if cache.exists():
        previous = json.loads(cache.read_text(encoding="utf-8"))
        digest = previous.get("sha256", "")
        if (previous.get("file") == stamp and isinstance(digest, str)
                and len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)):
            return digest
    digest = sha256(image)
    if image_stamp(image) != stamp:
        raise RuntimeError("The guest image changed during verification")
    atomic_json(cache, {"file": stamp, "sha256": digest})
    return digest


def image_stamp(image: Path) -> dict:
    """Identify a specific local disk image revision."""
    metadata = image.stat()
    return {"path": str(image), "inode": metadata.st_ino, "size": metadata.st_size,
            "modified": metadata.st_mtime_ns, "changed": metadata.st_ctime_ns}


def wait_for_desktop(server: str) -> None:
    """Require a visible window manager before saving the clean Ubuntu state."""
    import requests

    if not Path("/dev/kvm").exists():
        configure = f'''set -eu
folder="$HOME/.config/systemd/user/{GNOME_UNIT}.d"
mkdir -p "$folder"
printf '[Service]\\nTimeoutStartSec={GNOME_START_TIMEOUT}s\\n' > "$folder/kolos-osworld.conf"
systemctl --user daemon-reload
'''
        response = requests.post(f"{server}/execute", json={"command": ["bash", "-c", configure], "shell": False},
                                 timeout=90)
        response.raise_for_status()
        outcome = response.json()
        if outcome.get("returncode") != 0:
            raise RuntimeError(f"Could not prepare GNOME for software emulation: {outcome.get('error', '')}")
    window_manager = f"systemctl --user is-active --quiet {GNOME_UNIT} && exec wmctrl -m"
    probe = {"command": ["timeout", "8", "bash", "-c", window_manager], "shell": False}
    deadline = time.monotonic() + DESKTOP_READY_TIMEOUT
    while time.monotonic() < deadline:
        try:
            response = requests.post(f"{server}/execute", json=probe, timeout=20)
            response.raise_for_status()
            state = response.json()
            if state.get("returncode") == 0 and "Name: GNOME Shell" in state.get("output", ""):
                screen = requests.get(f"{server}/screenshot", timeout=SCREENSHOT_TIMEOUT)
                if screen.ok and rendered(screen.content):
                    logger.info("The guest's GNOME window manager and display are ready")
                    return
        except (requests.RequestException, ValueError):
            pass
        time.sleep(3)
    raise RuntimeError(f"Guest GNOME did not render a usable desktop in {DESKTOP_READY_TIMEOUT} seconds")


def rendered(screenshot: bytes) -> bool:
    """Reject blank frames even when the guest screenshot endpoint replies successfully."""
    from PIL import Image

    try:
        with Image.open(BytesIO(screenshot)) as image:
            sample = image.convert("L").resize((48, 27))
            low, _ = sample.getextrema()
            return sum(sample.histogram()[low + 24:]) >= 5
    except OSError:
        return False


def read_screenshot(controller) -> bytes | None:
    """Use the official screenshot endpoint with a budget for software emulation."""
    import requests

    for _ in range(controller.retry_times):
        try:
            response = requests.get(f"{controller.http_server}/screenshot", timeout=SCREENSHOT_TIMEOUT)
            response.raise_for_status()
            if controller._is_valid_image_response(response.headers.get("Content-Type"), response.content):
                return response.content
        except requests.RequestException as exc:
            logger.warning("OSWorld screenshot unavailable: %s", exc)
        time.sleep(controller.retry_interval)
    return None


def verify_restored_file(server: str, path: str) -> None:
    """Check a read-only marker after QEMU has re-established the guest connection."""
    import requests

    probe = {"command": ["test", "!", "-e", path], "shell": False}
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        try:
            response = requests.post(f"{server}/execute", json=probe, timeout=30)
            response.raise_for_status()
            status = response.json().get("returncode")
            if status == 0:
                return
            if status == 1:
                raise RuntimeError("The disposable marker remained after snapshot restoration")
        except (requests.RequestException, ValueError):
            pass
        time.sleep(3)
    raise RuntimeError("The restored guest did not respond for the disposable marker check")


class SetupConnection:
    """Use a no-op to check the guest connection without depending on terminal AT-SPI."""

    def __init__(self, client, server: str) -> None:
        self.client = client
        self.server = server

    def __getattr__(self, name: str):
        return getattr(self.client, name)

    def get(self, url: str, *args, **kwargs):
        if url == f"{self.server}/terminal":
            return self.client.post(f"{self.server}/execute", json={"command": ["true"], "shell": False}, **kwargs)
        return self.client.get(url, *args, **kwargs)


def setup_with_connection(setup, server: str, *args, **kwargs):
    """Keep the official setup and grader steps with a local connection probe."""
    from desktop_env.controllers import setup as upstream

    client = upstream.requests
    upstream.requests = SetupConnection(client, server)
    try:
        return setup(*args, **kwargs)
    finally:
        upstream.requests = client


@contextmanager
def desktop_session(vm_image: Path, cache: Path, *, fast_reset: bool = False, video_adapter: str = "virtio") -> Iterator:
    """Create only an isolated Docker guest using the published OSWorld environment."""
    if version("desktop-env") != RELEASE:
        raise RuntimeError(f"Install desktop-env=={RELEASE} in the benchmark environment")
    if os.environ.get("OSWORLD_VM_SECRET_MOUNTS"):
        raise RuntimeError("Clear OSWORLD_VM_SECRET_MOUNTS for benchmark isolation")
    from desktop_env.desktop_env import DesktopEnv
    from docker.errors import DockerException

    class LocalDesktop(DesktopEnv):
        """Fit both benchmark arms in the same WSL2 guest resource budget."""

        clean_snapshot: Snapshot | None = None
        snapshot_restored = False
        snapshot_enabled = fast_reset
        reset_method = "docker-restart"

        def _start_emulator(self) -> None:
            provider = self.provider
            if self.snapshot_restored:
                self.snapshot_restored = False
                return
            provider.environment.update(RAM_SIZE=VM_RAM, CPU_CORES=VM_CPUS, VGA=video_adapter)
            wait_for_ready = provider._wait_for_vm_ready
            provider._wait_for_vm_ready = partial(wait_for_ready, timeout=VM_READY_TIMEOUT)
            try:
                if self.snapshot_enabled:
                    provider.environment["ARGUMENTS"] = ARGUMENT
                super()._start_emulator()
                self._prepare_observer()
                self.reset_method = "docker-restart"
                if self.snapshot_enabled:
                    self._capture_clean_snapshot()
            except Exception:
                provider.stop_emulator(self.path_to_vm)
                raise
            finally:
                provider._wait_for_vm_ready = wait_for_ready

        def _prepare_observer(self) -> None:
            wait_for_desktop(self.setup_controller.http_server)
            if not Path("/dev/kvm").exists():
                self.controller.get_screenshot = partial(read_screenshot, self.controller)
                self.controller.request_timeout = A11Y_TIMEOUT
                setup = self.setup_controller
                setup.setup = partial(setup_with_connection, setup.setup, setup.http_server)

        def _capture_clean_snapshot(self) -> None:
            try:
                candidate = Snapshot(self.provider.container)
                candidate.state("save")
                path = f"/tmp/kolos-osworld-{uuid4().hex}"
                created = self.controller.execute_python_command(f"from pathlib import Path; Path({path!r}).touch(); print('created')")
                if not created or created.get("output", "").strip() != "created":
                    raise RuntimeError("could not create the disposable reset marker")
                candidate.state("load")
                verify_restored_file(self.setup_controller.http_server, path)
            except (DockerException, RuntimeError, ValueError, OSError) as exc:
                logger.warning("Fast reset verification failed, rebooting with Docker resets: %s", exc)
                self.snapshot_enabled = False
                self.provider.environment.pop("ARGUMENTS", None)
                self.provider.stop_emulator(self.path_to_vm)
                super()._start_emulator()
                self._prepare_observer()
            else:
                self.clean_snapshot = candidate
                logger.info("Verified the clean QEMU snapshot by restoring a disposable guest file")

        def _revert_to_snapshot(self) -> None:
            if self.clean_snapshot:
                try:
                    self.clean_snapshot.state("load")
                    if not self.controller.get_screenshot():
                        raise RuntimeError("The guest did not send a screenshot after snapshot restoration")
                except (DockerException, RuntimeError, ValueError, OSError) as exc:
                    self.snapshot_enabled = False
                    self.clean_snapshot = None
                    self.provider.environment.pop("ARGUMENTS", None)
                    logger.warning("Fast reset failed, switching to Docker restarts: %s", exc)
                else:
                    self.snapshot_restored = True
                    self.reset_method = "qemu-snapshot"
                    return
            super()._revert_to_snapshot()

    desktop = LocalDesktop(provider_name="docker", path_to_vm=str(vm_image), cache_dir=str(cache),
                           snapshot_name="init_state", action_space="computer_13", screen_size=SCREEN_SIZE,
                           headless=True, require_a11y_tree=True, require_terminal=False,
                           enable_proxy=False, recording_update="off")
    try:
        yield desktop
    finally:
        desktop.close()


def check_judge(desktop, task: dict) -> dict:
    """Calibrate upstream scoring on an excluded task with controlled initial and final states."""
    reset(desktop, task)
    initial = official_score(desktop, task)
    positive = execute("bash", "-ec", 'sinks=$(pactl list short sinks | cut -f1); test -n "$sinks"; '
                       'for sink in $sinks; do pactl set-sink-volume "$sink" 100%; done')
    reset(desktop, {**task, "config": [*task["config"], positive]})
    final = official_score(desktop, task)
    if (initial, final) != (0.0, 1.0):
        raise RuntimeError(f"Official judge calibration returned {initial} and {final}")
    return {"task": task["id"], "before": initial, "after": final}


def reset(desktop, task: dict) -> dict:
    """Normalize the upstream setup controller's generic exceptions for the retry loop."""
    try:
        return desktop.reset(task_config=task)
    except Exception as exc:
        raise RuntimeError(f"OSWorld reset for {task['id']}: {exc}") from exc


def official_score(desktop, task: dict) -> float:
    """Report a failed grader as infrastructure and accept only a finite official score."""
    try:
        score = float(desktop.evaluate())
    except Exception as exc:
        raise RuntimeError(f"OSWorld evaluation for {task['id']}: {exc}") from exc
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise RuntimeError(f"Invalid official score for {task['id']}: {score}")
    return score


def preflight(desktop, tasks: list[tuple[str, dict]], calibration: dict, output: Path) -> dict:
    """Check all prompt bindings and a reset/observation in each workload family."""
    for _, task in tasks:
        interpret(task["instruction"])
    verified = {}
    expected_apps = {"libreoffice_writer": "writer", "libreoffice_calc": "calc"}
    for domain, task in tasks:
        if domain in verified:
            continue
        fresh = Frame.read(reset(desktop, task))
        usable = rendered(fresh.screenshot) and app_present(fresh, expected_apps.get(domain, "desktop"))
        verified[domain] = {"task": task["id"], "nodes": len(fresh.elements), "frame": len(fresh.screenshot),
                            "usable": usable}
        print(f"Preflight {domain}: {verified[domain]['nodes']} accessible elements", flush=True)
        atomic_json(output / "preflight-progress.json", {"domains": verified})
    unusable = [domain for domain, result in verified.items() if not result["usable"]]
    if unusable:
        raise RuntimeError(f"The guest did not provide a usable screen and application tree for {', '.join(unusable)}")
    example = next(lesson for lesson in DEMONSTRATIONS if lesson.name == "writer_subscript")
    frame = Frame.read(reset(desktop, example.task()))
    session = Session(Guest(desktop), interpret(example.instruction), frame)
    try:
        for index, name in enumerate(("subscript.find", "subscript.type"), 1):
            session.perform(f"preflight:{index}", {"kind": "gui", "binding": name})
    except Unconfirmed as exc:
        observed = desktop._get_obs()
        if observed.get("screenshot"):
            (output / "preflight-writer.png").write_bytes(observed["screenshot"])
        if observed.get("accessibility_tree"):
            (output / "preflight-writer.xml").write_text(observed["accessibility_tree"], encoding="utf-8")
        atomic_json(output / "preflight-progress.json", {"domains": verified, "motor": session.trace, "error": str(exc)})
        raise
    return {"domains": verified, "motor": session.trace, "judge": check_judge(desktop, calibration)}


def save_memory(path: Path, engine: StateEngine) -> None:
    """Persist learning evidence in a dedicated v4 Store."""
    store = Store(path)
    try:
        store.save(engine)
    finally:
        store.close()


def load_memory(path: Path) -> StateEngine:
    """Load a frozen v4 snapshot without writing score-time state."""
    store = Store(path)
    try:
        return store.load()
    finally:
        store.close()


def run_lesson(desktop, engine: StateEngine, lesson: Lesson) -> dict:
    """Teach one exercise and preserve its observed action trace."""
    session = Session(Guest(desktop), interpret(lesson.instruction), Frame.read(reset(desktop, lesson.task())))
    try:
        teach(engine, session, lesson.name, steps(lesson))
    except Unconfirmed as exc:
        return {"name": lesson.name, "learned": False, "reason": str(exc), "trace": session.trace}
    return {"name": lesson.name, "learned": True, "trace": session.trace}


def verify_control(desktop, lesson: Lesson) -> bool:
    """Inspect held-out synthetic output after the agent has released the guest."""
    content = desktop.controller.get_file(lesson.path())
    if not content:
        return False
    intent = interpret(lesson.instruction)
    if intent.skill == "restore":
        return content == f"Sample {lesson.variant}".encode()
    if intent.skill == "font":
        from docx import Document

        runs = [run for paragraph in Document(BytesIO(content)).paragraphs for run in paragraph.runs if run.text.strip()]
        return bool(runs) and all(run.font.name == intent.values["font"] for run in runs)
    from openpyxl import load_workbook

    rows = list(load_workbook(BytesIO(content), read_only=True).active.values)
    if not rows:
        return False
    index = rows[0].index(intent.values["column"])
    values = [row[index] for row in rows[1:]]
    return values == [lesson.variant * number for number in (1, 2, 3, 4)]


def teach_curriculum(desktop, output: Path, provenance: dict) -> dict:
    """Build frozen memory, reload it and measure synthetic transfer controls."""
    cold = StateEngine()
    cold.configure(plasticity=0)
    save_memory(output / "cold", cold)
    warm = StateEngine()
    warm.configure(plasticity=0)
    lessons = []
    for lesson in DEMONSTRATIONS:
        try:
            result = run_lesson(desktop, warm, lesson)
        except (RuntimeError, ValueError, OSError) as exc:
            result = {"name": lesson.name, "learned": False, "reason": str(exc), "trace": []}
        lessons.append(result)
        print(f"Teaching {lesson.name}: {result.get('reason', 'learned')}", flush=True)
        save_memory(output / "warm", warm)
        atomic_json(output / "teaching-progress.json", {"lessons": lessons})
    controls = []
    for lesson in CONTROLS:
        try:
            raw = reset(desktop, lesson.task())
            session = Session(Guest(desktop), interpret(lesson.instruction), Frame.read(raw))
            result = run_agent(load_memory(output / "warm"), session)
            result["verified"] = verify_control(desktop, lesson)
        except (RuntimeError, ValueError, OSError) as exc:
            result = {"agent_status": "infra_error", "reason": str(exc)}
        controls.append({"name": lesson.name, **result})
    qualified = all(item["learned"] for item in lessons) and all(
        item["agent_status"] == "complete" and item["verified"] for item in controls
    )
    report = {"provenance": provenance, "qualified": qualified, "lessons": lessons, "controls": controls,
              "snapshots": {arm: sha256(output / arm / "memory.json") for arm in ("cold", "warm")}}
    atomic_json(output / "teaching.json", report)
    return report


def score_attempt(desktop, task: dict, memory: Path) -> dict:
    """Run a new agent on the original task and score the final guest with OSWorld."""
    raw = reset(desktop, task)
    intent = interpret(task["instruction"])
    session = Session(Guest(desktop), intent, Frame.read(raw))
    result = run_agent(load_memory(memory), session)
    score = official_score(desktop, task)
    return {**result, "score": score, "reset_method": getattr(desktop, "reset_method", "docker-restart")}


def attempt_with_retry(desktop, task: dict, memory: Path) -> dict:
    """Repeat one infrastructure failure after a fresh reset, never a scored attempt."""
    errors = []
    for _ in range(2):
        try:
            return {**score_attempt(desktop, task, memory), "technical_errors": errors}
        except (RuntimeError, ValueError, OSError) as exc:
            errors.append(str(exc))
    return {"agent_status": "infra_error", "score": None, "technical_errors": errors}


def write_results(output: Path, report: dict) -> None:
    """Persist an auditable partial or final result after each attempt."""
    rows = report["attempts"]
    report["scored"] = sum(row["score"] is not None for row in rows)
    report["solved"] = {arm: sum(row["arm"] == arm and row["score"] == 1 for row in rows) for arm in ("cold", "warm")}
    atomic_json(output / "results.json", report)


def prior_scores(output: Path, report: dict, cases: set[tuple[str, str]]) -> dict[tuple[str, str], dict]:
    """Reuse completed scores from an interrupted run of the same frozen inputs."""
    path = output / "results.json"
    if not path.exists():
        return {}
    previous = json.loads(path.read_text(encoding="utf-8"))
    if any(previous.get(key) != value for key, value in report.items() if key != "attempts"):
        return {}
    rows = previous["attempts"]
    keys = [(row["task"], row["arm"]) for row in rows]
    if len(set(keys)) != len(keys) or not set(keys) <= cases:
        raise ValueError("The previous report contains invalid task and arm pairs")
    return {key: row for key, row in zip(keys, rows) if row["score"] is not None}


def benchmark(desktop, tasks: list[tuple[str, dict]], output: Path, provenance: dict) -> dict:
    """Evaluate the same fixed tasks with both immutable snapshots."""
    training = json.loads((output / "teaching.json").read_text(encoding="utf-8"))
    if training["provenance"] != provenance:
        raise ValueError("The training snapshots belong to a different benchmark environment")
    frozen = training["snapshots"]
    report = {"provenance": provenance, "upstream": REVISION, "snapshots": frozen,
              "training_qualified": training["qualified"],
              "learned_lessons": sum(lesson["learned"] for lesson in training["lessons"]),
              "limits": {"actions": MAX_ACTIONS, "seconds": MAX_SECONDS}, "attempts": []}
    cases = {(task["id"], arm) for _, task in tasks for arm in ("cold", "warm")}
    previous = prior_scores(output, report, cases)
    report["attempts"] = list(previous.values())
    for domain, task in tasks:
        for arm in ("cold", "warm"):
            memory = output / arm
            expected = frozen[arm]
            if sha256(memory / "memory.json") != expected:
                raise ValueError(f"{arm} memory changed since it was frozen")
            if (task["id"], arm) in previous:
                continue
            result = attempt_with_retry(desktop, task, memory)
            if sha256(memory / "memory.json") != expected:
                raise ValueError(f"{arm} memory changed during a scored attempt")
            report["attempts"].append({"task": task["id"], "domain": domain, "arm": arm, **result})
            write_results(output, report)
            print(f"{domain}/{task['id']} {arm}: {result['score']} · {result['agent_status']}", flush=True)
    order = {task["id"]: index for index, (_, task) in enumerate(tasks)}
    report["attempts"].sort(key=lambda row: (order[row["task"]], row["arm"]))
    write_results(output, report)
    return report
