"""Parameterised Writer and Calc actions, scoped to visible application controls."""

from __future__ import annotations

import re

from .bindings import Rule, app_present, button, dialog, edit, gone, has, input_value, key, observed_input, selected_text, viewport_changed, visible
from .gui import Frame, click, comparable, hotkey, labelled, typing
from .intent import Intent

SAVE_FORMAT = ("Use Word 2007 Format", "Use Word 2010-365 Format", "Use Excel 2007-365 Format",
               "Use Excel 2007 Format", "Use Microsoft Word Format", "Use Excel Format")
SAVE_AS = ("Save As", "Save As…", "Save As...", "File name")
CSV_FORMAT = ("Text CSV (.csv)", "Text CSV", "Text CSV (csv)", "Text CSV (.csv) (*.csv)")
CSV_OPTIONS = ("Export Text File", "Field delimiter", "Field Delimiter")


def focus_changed(before: Frame, after: Frame, intent: Intent, slots: dict[str, str]) -> bool:
    """Observe an editable field taking focus."""
    return has(after, lambda node: node.has("focused") and edit(node))


def safe_doc_key(*keys: str):
    """Restrict shortcuts to the current editor outside dialogs."""
    return key(*keys)


def combo(*names: str):
    """Prefer a labelled combo and allow a nearby field when its label is separate."""
    selector = labelled(*names)

    def resolve(frame: Frame, intent: Intent, slots: dict[str, str]) -> dict | None:
        controls = ("combo-box", "push-button", "menu-button")
        direct = click(frame, lambda node: node.role in controls and selector(node))
        if direct:
            return direct
        label = frame.control(selector)
        if label is None or label.box is None:
            return None
        x1, y1, x2, y2 = label.box
        return click(frame, lambda node: node.role in controls and node.box and node.window == label.window
                     and node.box[0] >= x1 and node.box[1] < y2 and node.box[3] > y1)

    return resolve


def editor_modified(frame: Frame, app: str) -> bool:
    """Look for the editor's enabled Save control or explicit modified title."""
    return has(frame, lambda node: (node.role == "frame" and "modified" in comparable(node.name))
               or (node.role == "push-button" and bool(labelled("Save", "Save Document")(node))
                   and node.has("enabled") and app in comparable(node.window)))


def saved(before: Frame, after: Frame, intent: Intent, slots: dict[str, str]) -> bool:
    """Verify save through the toolbar state or a storage-format confirmation."""
    return not editor_modified(after, intent.app) and not dialog(after) and (
        editor_modified(before, intent.app) or has(before, labelled(*SAVE_FORMAT))
    )


def save_effect(before: Frame, after: Frame, intent: Intent, slots: dict[str, str]) -> bool:
    """Distinguish a save confirmation from a completed write."""
    return has(after, labelled(*SAVE_FORMAT)) or saved(before, after, intent, slots)


def save_checkpoint(frame: Frame) -> str:
    """Identify which save outcome the guest actually presented."""
    return "save_format" if has(frame, labelled(*SAVE_FORMAT)) else "done"


def csv_checkpoint(frame: Frame) -> str:
    """Identify whether export first opened a format warning."""
    return "csv_options" if has(frame, labelled(*CSV_OPTIONS)) else "export"


def doc_start(before: Frame, after: Frame, intent: Intent, slots: dict[str, str]) -> bool:
    """Confirm the document remains focused near the observed top of its content."""
    paragraphs = after.find(lambda node: node.role in ("paragraph", "heading") and node.box and node.text)
    if not paragraphs:
        return selected_text(before, after, intent, slots)
    first = min(paragraphs, key=lambda node: node.box[1])
    return first.has("focused") or selected_text(before, after, intent, slots)


def apply_format(before: Frame, after: Frame, intent: Intent, slots: dict[str, str]) -> bool:
    """Require the editor to show a document change before scheduling save."""
    return editor_modified(after, intent.app) or viewport_changed(before, after, intent, slots)


def slot(name: str):
    """Resolve a live argument rather than a value from the teaching document."""
    return lambda intent, slots: slots.get(name, intent.values.get(name, ""))


def select_in_field(frame: Frame, intent: Intent, slots: dict[str, str]) -> dict | None:
    """Select the content of an observed editable field."""
    return hotkey("ctrl", "a") if focus_changed(frame, frame, intent, slots) else None


def search_open(before: Frame, after: Frame, intent: Intent, slots: dict[str, str]) -> bool:
    """Witness an editable Find control or toolbar."""
    return focus_changed(before, after, intent, slots) and has(
        after, lambda node: comparable(node.label).startswith(("find", "search")),
    )


def writer_rules(intent: Intent) -> dict[str, Rule]:
    """Build edit bindings for reusable Writer selection and formatting operations."""
    effects = {
        "font.select": Rule(safe_doc_key("ctrl", "a"), selected_text, "selected"),
        "font.field": Rule(button("Font Name", "Font name"), focus_changed, "font_field"),
        "font.clear": Rule(select_in_field, focus_changed, "font_selected"),
        "font.type": Rule(input_value(slot("font"), edit), observed_input(slot("font"), edit), "font_typed"),
        "font.apply": Rule(key("enter"), apply_format, "edited"),
        "center.start": Rule(safe_doc_key("ctrl", "home"), doc_start, "top"),
        "center.apply": Rule(safe_doc_key("ctrl", "e"), apply_format, "edited"),
        "spacing.start": Rule(safe_doc_key("ctrl", "home"), doc_start, "top"),
        "spacing.menu": Rule(button("Format", roles=("menu", "menu-item")), visible("Paragraph"), "format_menu"),
        "spacing.dialog": Rule(button("Paragraph"), visible("Line Spacing", "Line spacing"), "paragraph_dialog"),
        "spacing.list": Rule(combo("Line Spacing"), visible("Double", "Double spacing"), "spacing_list"),
        "spacing.value": Rule(button("Double", "Double spacing") if intent.values.get("spacing") == "double" else button("Single"),
                              viewport_changed, "spacing_chosen"),
        "spacing.apply": Rule(button("OK", roles=("push-button",)), gone("Line Spacing", "Line spacing"), "edited"),
        "subscript.find": Rule(safe_doc_key("ctrl", "f"), search_open, "find"),
        "subscript.type": Rule(input_value(slot("find"), edit), observed_input(slot("find"), edit), "find_typed"),
        "subscript.match": Rule(key("enter"), selected_text, "matched"),
        "subscript.close": Rule(key("esc"), viewport_changed, "find_closed"),
        "subscript.start": Rule(safe_doc_key("left"), selected_text, "at_start"),
        "subscript.select": Rule(safe_doc_key("shift", "right"), selected_text, "selected"),
        "subscript.apply": Rule(safe_doc_key("ctrl", "shift", "b"), apply_format, "edited"),
    }
    if intent.skill == "spacing":
        for index in range(1, int(intent.values["count"]) + 1):
            effects[f"spacing.select_{index}"] = Rule(safe_doc_key("ctrl", "shift", "down"), selected_text, f"paragraph_{index}")
    if intent.skill == "subscript":
        for index in range(1, int(intent.values["offset"]) + 1):
            effects[f"subscript.advance_{index}"] = Rule(safe_doc_key("right"), selected_text, f"character_{index}")
    return effects


def column_name(value: str) -> str:
    """Normalize visible labels including singular and plural variants."""
    return comparable(value).removesuffix("s")


def cell_address(node) -> re.Match | None:
    """Extract a visible Calc grid coordinate from its accessibility name."""
    return re.match(r"^\$?([A-Z]{1,3})\$?([1-9]\d{0,6})(?=$|\s|:)", node.name)


def cell_value(node) -> str:
    """Separate the observed value from the coordinate prefix when exported together."""
    address = cell_address(node)
    return node.text or (node.name[address.end():].lstrip(" :") if address else node.name)


def calc_header(frame: Frame, text: str):
    """Find a single matching visible column header with a coordinate."""
    return frame.control(lambda node: node.role == "table-cell" and cell_address(node) is not None
                         and column_name(cell_value(node)) == column_name(text))


def calc_sort_column(frame: Frame, intent: Intent, slots: dict[str, str]) -> dict | None:
    """Pick a visible cell by its column name."""
    lookup = calc_header(frame, intent.values["column"])
    return click(frame, lambda node: node is lookup)


def sort_column_selected(before: Frame, after: Frame, intent: Intent, slots: dict[str, str]) -> bool:
    """Verify that the designated column is currently active."""
    target = calc_header(after, intent.values["column"])
    if target is None:
        return False
    address = cell_address(target)[0]
    return target.has("focused") or target.has("selected") or has(
        after, lambda node: node.name == "Name Box" and node.text.replace("$", "") == address.replace("$", ""),
    )


def calc_ranges(frame: Frame, intent: Intent, slots: dict[str, str]) -> dict | None:
    """Focus the name box when both headers and the full contiguous extent are visible."""
    if "first" not in slots and source_range(frame, intent) is None:
        return None
    return button("Name Box", "Name box")(frame, intent, slots)


def source_range(frame: Frame, intent: Intent) -> dict[str, str] | None:
    """Read column coordinates and stop at the first observed empty source cell."""
    source = calc_header(frame, intent.values["source"])
    target = calc_header(frame, intent.values["target"])
    if source is None or target is None:
        return None
    source_col, header = cell_address(source).groups()
    target_col, target_header = cell_address(target).groups()
    if header != target_header or source_col == target_col:
        return None
    cells = {}
    for node in frame.elements:
        address = cell_address(node) if node.role == "table-cell" else None
        if address and address[1] == source_col:
            cells[int(address[2])] = cell_value(node)
    first = int(header) + 1
    end = first
    while cells.get(end):
        end += 1
    if end == first or end not in cells:
        return None
    return {"first": f"{target_col}{first}", "range": f"{target_col}{first}:{target_col}{end - 1}",
            "formula": f'=TEXT({source_col}{first};"{int(intent.values["width"]) * "0"}")'}


def remember_range(before: Frame, after: Frame, intent: Intent, slots: dict[str, str]) -> bool:
    """Keep live references read from the sheet while its name box takes focus."""
    if not focus_changed(before, after, intent, slots):
        return False
    values = source_range(before, intent)
    if not values:
        return False
    slots.update(values)
    return True


def saved_csv(before: Frame, after: Frame, intent: Intent, slots: dict[str, str]) -> bool:
    """Observe a CSV document in the editor after completing export."""
    return not dialog(after) and has(after, lambda node: node.role == "frame" and ".csv" in node.name.lower())


def calc_rules(intent: Intent) -> dict[str, Rule]:
    """Build the GUI bindings used for spreadsheet operations."""
    sort_label = "Sort Ascending" if intent.values.get("direction") == "ascending" else "Sort Descending"
    return {
        "csv.dialog": Rule(key("ctrl", "shift", "s"), visible(*SAVE_AS), "save_as"),
        "csv.list": Rule(combo("File type", "Save as type", "All Formats"), visible(*CSV_FORMAT), "formats"),
        "csv.choose": Rule(button(*CSV_FORMAT), visible(*CSV_FORMAT), "csv_type"),
        "csv.save": Rule(button("Save", roles=("push-button",)), visible(*CSV_OPTIONS, "Use Text CSV Format", "Use CSV Format"), csv_checkpoint),
        "csv.format": Rule(button("Use Text CSV Format", "Use CSV Format"), visible(*CSV_OPTIONS), "csv_options"),
        "csv.confirm": Rule(button("OK", roles=("push-button",)), saved_csv, "done"),
        "sort.column": Rule(calc_sort_column, sort_column_selected, "column"),
        "sort.apply": Rule(button(sort_label), apply_format, "edited"),
        "pad.capture": Rule(calc_ranges, remember_range, "name_box"),
        "pad.clear": Rule(select_in_field, focus_changed, "address_selected"),
        "pad.address": Rule(input_value(slot("first"), edit), observed_input(slot("first"), edit), "address"),
        "pad.cell": Rule(key("enter"), selected_text, "cell"),
        "pad.formula": Rule(lambda frame, goal, slots: typing(slots.get("formula", "")) if app_present(frame, "calc") and not dialog(frame) else None,
                            observed_input(slot("formula"), edit), "formula"),
        "pad.commit": Rule(key("enter"), apply_format, "computed"),
        "pad.name": Rule(button("Name Box", "Name box"), focus_changed, "range_box"),
        "pad.clear_range": Rule(select_in_field, focus_changed, "range_selected"),
        "pad.range": Rule(input_value(slot("range"), edit), observed_input(slot("range"), edit), "range"),
        "pad.select": Rule(key("enter"), selected_text, "cells"),
        "pad.fill": Rule(key("ctrl", "d"), apply_format, "edited"),
    }


def rules(intent: Intent) -> dict[str, Rule]:
    """Return rules for the current editor including a verified save."""
    if intent.app not in {"writer", "calc"}:
        return {}
    result = writer_rules(intent) if intent.app == "writer" else calc_rules(intent)
    if intent.skill != "csv":
        result[f"{intent.skill}.save"] = Rule(key("ctrl", "s"), save_effect, save_checkpoint)
        result[f"{intent.skill}.confirm"] = Rule(button(*SAVE_FORMAT), saved, "done")
    return result
