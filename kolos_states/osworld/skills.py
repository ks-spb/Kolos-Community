"""Bindings for the Ubuntu desktop and the two LibreOffice test applications."""

from __future__ import annotations

from . import office
from .bindings import Evidence, Rule, app_present, button, has, key, visible
from .gui import Frame, click, comparable, labelled, typing
from .intent import Intent

DIM = ("Dim Screen", "Dim screen when inactive")
DND = ("Do Not Disturb",)


def toggle_choice(frame: Frame, names: tuple[str, ...]):
    """Resolve a labelled switch, or a switch on the same row as its accessible label."""
    roles = ("switch", "toggle-button", "check-box", "check-menu-item")
    named = frame.control(labelled(*names, roles=roles))
    if named:
        return named
    label = frame.control(labelled(*names))
    if label is None or label.box is None:
        return None
    x1, y1, x2, y2 = label.box
    same_row = lambda node: (node.role in roles and node.box and node.window == label.window
                            and node.box[0] >= x1 and node.box[1] < y2 and node.box[3] > y1)
    return frame.control(same_row)


def toggle(names: tuple[str, ...], applied: bool = True):
    """Check the desired switch state or prepare a click for a known opposite state."""
    def correct(frame, intent):
        switch = toggle_choice(frame, names)
        if switch is None:
            return None
        on = switch.has("checked") or switch.has("pressed") or switch.has("active")
        return on == (intent.values["desired"] == "on")

    if applied:
        return lambda before, after, intent, slots: correct(after, intent) is True
    def resolve(frame, intent, slots):
        switch = toggle_choice(frame, names)
        if switch and correct(frame, intent) is False:
            return click(frame, lambda node: node is switch)
        return None

    return resolve


def file_selector(intent: Intent):
    """Match the described file only inside the file manager."""
    words = set(comparable(intent.values["file"]).split()) - {"a", "an", "the", "of", "file"}
    return lambda node: bool(words) and node.role in ("icon", "table-cell", "list-item", "label") and (
        "nautilus" in comparable(node.app) or "trash" in comparable(node.window)
    ) and words <= set(comparable(node.label).split())


def target_file(frame: Frame, intent: Intent, slots: dict[str, str]):
    """Open the context menu of the uniquely matched current file."""
    return click(frame, file_selector(intent), "RIGHT_CLICK")


def restored(before: Frame, after: Frame, intent: Intent, slots: dict[str, str]) -> bool:
    """Observe the named item leave the trash after activating Restore."""
    selector = file_selector(intent)
    return app_present(after, "files") and has(before, selector) and not has(after, selector)


def file_manager(before: Frame, after: Frame, intent: Intent, slots: dict[str, str]) -> bool:
    """Observe the file-manager window opened by the system shortcut."""
    return app_present(after, "files")


def trash_open(before: Frame, after: Frame, intent: Intent, slots: dict[str, str]) -> bool:
    """Distinguish the opened Trash from the sidebar link visible beforehand."""
    return has(after, lambda node: node.role in ("frame", "window") and "trash" in comparable(node.name)) or has(
        after, labelled("Empty Trash"),
    )


def overview_open(before: Frame, after: Frame, intent: Intent, slots: dict[str, str]) -> bool:
    """Observe the GNOME system search field."""
    return has(after, lambda node: node.has("focused") and ("search" in comparable(node.label) or node.role == "entry"))


def system_search(frame: Frame, intent: Intent, slots: dict[str, str]) -> dict | None:
    """Type a settings-panel name into the observed overview search field."""
    return typing("Power") if overview_open(frame, frame, intent, slots) else None


def power_search(before: Frame, after: Frame, intent: Intent, slots: dict[str, str]) -> bool:
    """Read back the query and its accessible search result."""
    return has(after, lambda node: node.has("focused") and node.text == "Power") and has(after, labelled("Power"))


def switch_visible(names: tuple[str, ...]) -> Evidence:
    """Recognize the panel containing the expected setting."""
    return lambda before, after, intent, slots: toggle_choice(after, names) is not None


DESKTOP_RULES = {
    "restore.files": Rule(key("win", "e", in_app=False), file_manager, "files"),
    "restore.trash": Rule(button("Trash", "Wastebasket"), trash_open, "trash"),
    "restore.item": Rule(target_file, visible("Restore", "Restore from Trash"), "menu"),
    "restore.apply": Rule(button("Restore", "Restore from Trash"), restored, "done"),
    "dim.overview": Rule(key("win", in_app=False), overview_open, "overview"),
    "dim.search": Rule(system_search, power_search, "search"),
    "dim.panel": Rule(button("Power"), switch_visible(DIM), "panel"),
    "dim.apply": Rule(toggle(DIM, False), toggle(DIM), "done"),
    "dnd.panel": Rule(key("win", "v", in_app=False), switch_visible(DND), "panel"),
    "dnd.apply": Rule(toggle(DND, False), toggle(DND), "done"),
}


def bindings(intent: Intent) -> dict[str, Rule]:
    """Expose available learned binding names for the current goal family."""
    prefix = intent.skill + "."
    return {name: rule for name, rule in (DESKTOP_RULES | office.rules(intent)).items() if name.startswith(prefix)}
