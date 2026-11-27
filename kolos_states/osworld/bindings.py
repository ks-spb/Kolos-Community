"""Reusable bindings and independent evidence checks for guest GUI actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .gui import Frame, NodeFilter, click, comparable, hotkey, labelled, typing
from .intent import Intent

Slots = dict[str, str]
Resolve = Callable[[Frame, Intent, Slots], dict | None]
Evidence = Callable[[Frame, Frame, Intent, Slots], bool]


@dataclass(frozen=True)
class Rule:
    """Resolve one learned binding and verify its observable effect."""

    resolve: Resolve
    verify: Evidence
    checkpoint: str | Callable[[Frame], str]


def has(frame: Frame, selector: NodeFilter) -> bool:
    """Check that the accessible UI currently exposes a named state."""
    return any(selector(node) and (node.box or node.has("showing") or node.has("focused") or node.has("active"))
               for node in frame.elements)


def visible(*names: str) -> Evidence:
    """Confirm a named, visible control on the subsequent observation."""
    return lambda before, after, intent, slots: has(after, labelled(*names))


def gone(*names: str) -> Evidence:
    """Confirm that a control present before the action disappeared."""
    selector = labelled(*names)
    return lambda before, after, intent, slots: has(before, selector) and not has(after, selector)


def app_present(frame: Frame, app: str) -> bool:
    """Recognize the expected guest surface from roles or window names."""
    def matches(element):
        context = comparable(f"{element.app} {element.window}")
        return app in context or (app == "files" and "nautilus" in context)

    return app == "desktop" or any(matches(node) and (node.role == "application" or node.box) for node in frame.elements)


def dialog(frame: Frame) -> bool:
    """Find an active scoped dialog in the accessibility tree."""
    return has(frame, lambda node: node.role in ("dialog", "alert") and (node.box is not None or node.has("active")))


def viewport_changed(before: Frame, after: Frame, intent: Intent, slots: Slots) -> bool:
    """Witness a pixel change inside the application content area."""
    surface = lambda node: node.role in ("frame", "dialog") and node.box and app_match(node.window, intent.app)
    regions = before.find(surface)
    if not regions:
        return False
    x1, y1, x2, y2 = max((node.box for node in regions), key=lambda box: (box[2] - box[0]) * (box[3] - box[1]))
    box = x1 + 4, max(y1 + 28, 36), x2 - 4, y2 - 4
    return box[2] > box[0] and box[3] > box[1] and before.region(box) != after.region(box)


def app_match(window: str, app: str) -> bool:
    """Identify the application's window title."""
    return app in comparable(window).split()


def key(*keys: str, in_app: bool = True, permit_dialog: bool = False) -> Resolve:
    """Offer a key action only within its intended GUI context."""
    def resolve(frame: Frame, intent: Intent, slots: Slots) -> dict | None:
        if (not in_app or app_present(frame, intent.app)) and (permit_dialog or not dialog(frame)):
            return hotkey(*keys)
        return None

    return resolve


def button(*names: str, roles: tuple[str, ...] = (), action_type: str = "CLICK") -> Resolve:
    """Offer a single activation of a uniquely identified visible control."""
    selector = labelled(*names, roles=roles)
    return lambda frame, intent, slots: click(frame, selector, action_type)


def input_value(value: Callable[[Intent, Slots], str], focus: NodeFilter) -> Resolve:
    """Offer typing only into a verified focused, editable control."""
    def resolve(frame: Frame, intent: Intent, slots: Slots) -> dict | None:
        if has(frame, lambda node: node.has("focused") and focus(node)):
            return typing(value(intent, slots))
        return None

    return resolve


def observed_input(value: Callable[[Intent, Slots], str], focus: NodeFilter) -> Evidence:
    """Read back the typed value from the actual control."""
    return lambda before, after, intent, slots: has(
        after, lambda node: focus(node) and value(intent, slots) in (node.text, node.name),
    )


def edit(node) -> bool:
    """Recognize editable controls exported by GTK or LibreOffice."""
    return node.has("editable") or node.role in ("entry", "text", "password-text") and node.has("focused") and node.role != "password-text"


def selected_text(before: Frame, after: Frame, intent: Intent, slots: Slots) -> bool:
    """Require a visible selection or motion from the current document viewport."""
    selected = lambda node: node.role in ("paragraph", "text", "document-text", "table-cell") and node.has("selected")
    return after.find(selected) != before.find(selected) or viewport_changed(before, after, intent, slots)
