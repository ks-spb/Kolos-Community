"""Use the native Kolos graph to learn and replay independently observed effects."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Protocol

from ..core import STOP, StateEngine
from .gui import Frame
from .intent import Intent
from .skills import bindings

MAX_ACTIONS = 50
MAX_SECONDS = 300


class ObservationPort(Protocol):
    """The agent's two capabilities once the environment has been reset."""

    def observe(self) -> Frame:
        """Read a fresh screenshot and accessibility tree."""

    def step(self, action: dict) -> Frame:
        """Send a single structured computer-use action and return its observation."""


class Unconfirmed(ValueError):
    """A GUI binding is unavailable or its required effect was not observed."""


@dataclass
class Session:
    """Track only the current instruction, confirmed observations and transient values."""

    port: ObservationPort
    intent: Intent
    frame: Frame
    checkpoint: str = "start"
    slots: dict[str, str] = field(default_factory=dict)
    receipts: list[dict] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Compile only the independent GUI bindings for the interpreted task."""
        self.rules = bindings(self.intent)

    def observe(self) -> dict:
        """Project the observed effect and available bindings into the native graph."""
        available = [name for name, rule in self.rules.items() if rule.resolve(self.frame, self.intent, self.slots)]
        return {
            "features": self.intent.features(self.checkpoint), "gui_actions": available,
            "icons": [], "selected": "", "focus": "", "output": "", "cursor": {"x": 0, "y": 0},
        }

    def perform(self, request_id: str, action: dict) -> dict:
        """Send an action once, then bind a new checkpoint only to observed evidence."""
        before = self.observe()
        name = action["binding"]
        if name not in before["gui_actions"]:
            raise Unconfirmed(f"Unavailable binding {name} at {self.checkpoint}")
        rule = self.rules[name]
        command = rule.resolve(self.frame, self.intent, self.slots)
        entry = {"binding": name, "action_type": command["action_type"], "from": self.checkpoint}
        self.trace.append(entry)
        latest = self.port.step(command)
        fresh = self.wait_for_effect(rule, latest)
        entry["frame_sha256"] = hashlib.sha256(fresh.screenshot).hexdigest()
        self.frame = fresh
        self.checkpoint = rule.checkpoint(fresh) if callable(rule.checkpoint) else rule.checkpoint
        entry["to"] = self.checkpoint
        receipt = {"id": request_id, "action": action, "before": before, "after": self.observe(),
                   "ok": True, "effect_observed": True, "verified_by": "osworld-observation"}
        self.receipts.append(receipt)
        return receipt

    def wait_for_effect(self, rule, latest: Frame) -> Frame:
        """Poll the observer, with no second dispatch of the pending action."""
        for attempt in range(3):
            if rule.verify(self.frame, latest, self.intent, self.slots):
                return latest
            if attempt < 2:
                latest = self.port.observe()
        raise Unconfirmed(f"Action effect was not observed at {self.checkpoint}")


def teach(engine: StateEngine, session: Session, name: str, sequence: tuple[str, ...]) -> None:
    """Feed the native learner a successful GUI demonstration with verified receipts."""
    for action in sequence:
        if session.checkpoint == "done":
            break
        if action.endswith(".confirm") and session.checkpoint != "save_format" and session.intent.skill != "csv":
            continue
        if action == "csv.format" and session.checkpoint == "csv_options":
            continue
        session.perform(f"{name}:{len(session.receipts) + 1}", {"kind": "gui", "binding": action})
    if session.checkpoint != "done":
        raise Unconfirmed(f"Teaching example stopped at {session.checkpoint}")
    engine.learn({"query": name, "receipts": session.receipts})


def run_agent(engine: StateEngine, session: Session) -> dict:
    """Follow only native graph dispatches until completion or a declared limit."""
    started = time.monotonic()
    status, reason = "unknown", ""
    try:
        engine.start_goals([{"kind": "state", "features": session.intent.features("done")}],
                           session.observe(), {"routeThreshold": .05, "maxWaves": 150})
    except ValueError as exc:
        reason = str(exc)
    else:
        status, reason = execute_goal(engine, session, started)
    return {"agent_status": status, "reason": reason, "actions": len(session.trace),
            "seconds": round(time.monotonic() - started, 3), "trace": session.trace}


def execute_goal(engine: StateEngine, session: Session, started: float) -> tuple[str, str]:
    """Execute at most one guest action per tick and acknowledge its fresh evidence."""
    while engine.model["status"] not in STOP:
        if len(session.trace) >= MAX_ACTIONS or time.monotonic() - started >= MAX_SECONDS:
            return "limit", "Action or time budget exhausted"
        event = engine.tick()
        if event["kind"] != "dispatch":
            continue
        try:
            receipt = session.perform(event["request"], event["action"])
        except Unconfirmed as exc:
            return "blocked", str(exc)
        acknowledged = engine.accept_receipt(receipt)
        if acknowledged["kind"] != "ack":
            return "blocked", "Observed effect did not match the learned transition"
    return engine.model["status"], engine.model["message"]
