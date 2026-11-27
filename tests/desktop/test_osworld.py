"""Verify the OSWorld wiring at the native graph and authoritative judge boundaries."""

import json
from io import BytesIO
from types import SimpleNamespace

from PIL import Image, ImageDraw

from kolos_states.core import StateEngine
from kolos_states.osworld.agent import Session, run_agent, teach
from kolos_states.osworld.gui import Frame
from kolos_states.osworld.intent import interpret
from kolos_states.osworld.manifest import DATASET
from kolos_states.osworld.office import source_range
from kolos_states.osworld import runner
from kolos_states.protocol import persistent_graph


INSTRUCTION = "Please turn on Do Not Disturb."


def snapshot(xml="", x=30):
    """Create an accessibility frame containing a switch at a chosen location."""
    data = f'<desktop><application name="gnome-shell">{xml.format(x=x)}</application></desktop>'
    return {"accessibility_tree": data, "screenshot": data.encode()}


SWITCH = ('<toggle-button name="Do Not Disturb" screencoord="({x}, 60)" size="(20, 20)" '
          'enabled="true" checked="{state}"/>')


def switch(state, x):
    """Build the observed notification switch before or after a click."""
    return snapshot(SWITCH.replace("{state}", state), x)


class MockGuest:
    """Remote GUI only. Every guest step consumes one real observation fixture."""

    def __init__(self, x=30, change=True):
        self.frames = [switch("false", x), switch("true" if change else "false", x)]
        self.actions = []
        self.current = snapshot()

    def observe(self):
        """Return the most recent guest observation without another action."""
        return Frame.read(self.current)

    def step(self, action):
        """Return the observation made after this individual action."""
        self.actions.append(action)
        self.current = self.frames.pop(0)
        return self.observe()


def session(guest):
    """Run the exact same agent interface during training and evaluation."""
    return Session(guest, interpret(INSTRUCTION), guest.observe())


def learned_engine():
    """Build the real native graph using verified sample receipts."""
    guest = MockGuest()
    engine = StateEngine()
    engine.configure(plasticity=0)
    teach(engine, session(guest), "synthetic-dnd", ("dnd.panel", "dnd.apply"))
    return engine


def test_native_memory_reuses_observed_transition_with_new_coordinates():
    guest = MockGuest(x=500)
    engine = learned_engine()
    before = persistent_graph(engine.model["memory"])
    result = run_agent(engine, session(guest))
    assert result["agent_status"] == "complete", result
    assert [action["action_type"] for action in guest.actions] == ["HOTKEY", "CLICK"]
    assert guest.actions[-1]["parameters"] == {"x": 510, "y": 70}
    assert before == persistent_graph(engine.model["memory"])


def test_cold_and_unconfirmed_leave_no_hidden_dispatch_or_retry():
    guest = MockGuest()
    assert run_agent(StateEngine(), session(guest))["agent_status"] == "unknown"
    assert guest.actions == []

    stuck = MockGuest(change=False)
    blocked = run_agent(learned_engine(), session(stuck))
    assert blocked["agent_status"] == "blocked"
    assert [action["action_type"] for action in stuck.actions] == ["HOTKEY", "CLICK"]


def test_ambiguous_switch_blocks_without_clicking():
    guest = MockGuest()
    node = SWITCH.replace("{state}", "false")
    guest.frames[0] = snapshot(node.replace("{x}", "30") + node.replace("{x}", "80"))
    outcome = run_agent(learned_engine(), session(guest))
    assert outcome["agent_status"] == "blocked"
    assert [action["action_type"] for action in guest.actions] == ["HOTKEY"]


def test_sheet_rule_requires_a_visible_end_and_reads_live_cell_references():
    goal = interpret("Copy the 'Batch' column to the 'Padded Batch' column and pad to six digits.")
    cells = (
        '<table-cell name="C1" screencoord="(40, 50)" size="(12, 12)">Batch</table-cell>'
        '<table-cell name="E1" screencoord="(60, 50)" size="(12, 12)">Padded Batch</table-cell>'
        '<table-cell name="C2">17</table-cell>'
        '<table-cell name="C3">29</table-cell>'
    )
    assert source_range(Frame.read(snapshot(cells)), goal) is None
    frame = Frame.read(snapshot(cells + '<table-cell name="C4"/>'))
    assert source_range(frame, goal) == {"first": "E2", "range": "E2:E3", "formula": '=TEXT(C2;"000000")'}


def test_official_judge_runs_even_on_cold_refusal(monkeypatch):
    calls = []

    def reset(task_config):
        calls.append(("reset", task_config["id"]))
        return snapshot()

    def evaluate():
        calls.append(("score",))
        return .25

    monkeypatch.setattr(runner, "load_memory", lambda path: StateEngine())
    guest = SimpleNamespace(reset=reset, evaluate=evaluate)
    result = runner.score_attempt(guest, {"id": "judge-only-id", "instruction": INSTRUCTION}, None)
    assert result["score"] == .25 and result["agent_status"] == "unknown"
    assert result["actions"] == 0
    assert calls == [("reset", "judge-only-id"), ("score",)]


def test_infrastructure_retry_is_bounded_and_scores_are_preserved(monkeypatch):
    calls = []

    def score(desktop, task, memory):
        calls.append(task)
        if len(calls) == 1:
            raise RuntimeError("guest reset failed")
        return {"score": 0.0, "agent_status": "blocked"}

    monkeypatch.setattr(runner, "score_attempt", score)
    outcome = runner.attempt_with_retry(None, "case", None)
    assert outcome["score"] == 0.0
    assert calls == ["case", "case"]
    assert outcome["technical_errors"] == ["guest reset failed"]
    assert sum(map(len, DATASET.values())) == 10


def test_frozen_snapshots_are_paired_for_all_ten_tasks(tmp_path, monkeypatch):
    """Keep the original judge score range, terminal status and per-arm totals."""
    for arm, engine in (("cold", StateEngine()), ("warm", learned_engine())):
        runner.save_memory(tmp_path / arm, engine)
    assert len(runner.load_memory(tmp_path / "warm").model["lessons"]) == 1
    hashes = {arm: runner.sha256(tmp_path / arm / "memory.json") for arm in ("cold", "warm")}
    info = {"provenance": {"test": True}, "qualified": False, "lessons": [{"learned": True}], "snapshots": hashes}
    (tmp_path / "teaching.json").write_text(json.dumps(info), encoding="utf-8")
    order = []

    def score(desktop, task, memory):
        order.append((task["id"], memory.name))
        return {"score": float(memory.name == "warm"), "agent_status": "complete"}

    monkeypatch.setattr(runner, "attempt_with_retry", score)
    tasks = [(domain, {"id": task_id}) for domain, ids in DATASET.items() for task_id in ids]
    outcome = runner.benchmark(None, tasks, tmp_path, info["provenance"])
    assert order == [(task["id"], arm) for _, task in tasks for arm in ("cold", "warm")]
    assert outcome["scored"] == 20
    assert outcome["solved"] == {"cold": 0, "warm": 10}
    assert not outcome["training_qualified"]
    assert json.loads((tmp_path / "results.json").read_text(encoding="utf-8")) == outcome
    order.clear()
    assert runner.benchmark(None, tasks, tmp_path, info["provenance"]) == outcome
    assert order == []


def test_guest_digest_is_invalidated_by_an_image_change(tmp_path, monkeypatch):
    """Hash a new VM revision and reuse the hash for an unchanged guest file."""
    image = tmp_path / "Ubuntu.qcow2"
    image.write_bytes(b"first")
    calculated = runner.sha256
    reads = []

    def track(path):
        reads.append(path)
        return calculated(path)

    monkeypatch.setattr(runner, "sha256", track)
    original = runner.guest_digest(image, tmp_path)
    assert runner.guest_digest(image, tmp_path) == original
    assert reads == [image]
    image.write_bytes(b"second revision")
    assert runner.guest_digest(image, tmp_path) != original
    assert reads == [image, image]


def test_a_cursor_on_a_black_screen_is_not_a_usable_desktop():
    screenshot = Image.new("RGB", (1920, 1080))
    draw = ImageDraw.Draw(screenshot)
    draw.rectangle((8, 8, 18, 19), fill="white")
    cursor_only = BytesIO()
    screenshot.save(cursor_only, format="PNG")
    assert not runner.rendered(cursor_only.getvalue())

    draw.rectangle((200, 200, 1200, 900), fill="gray")
    visible_window = BytesIO()
    screenshot.save(visible_window, format="PNG")
    assert runner.rendered(visible_window.getvalue())
