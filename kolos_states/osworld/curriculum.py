"""Synthetic, independently seeded exercises for teaching and transfer checks."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath

from .intent import Intent, interpret


@dataclass(frozen=True)
class Lesson:
    """Teacher-only steps and a locally generated guest setup."""

    name: str
    instruction: str
    variant: int

    def task(self) -> dict:
        """Create a synthetic reset specification compatible with the guest runner."""
        intent = interpret(self.instruction)
        if intent.app == "writer":
            setup = writer_fixture(intent, self.variant)
        elif intent.app == "calc":
            setup = sheet_fixture(intent, self.variant)
        else:
            setup = desktop_fixture(intent, self.variant)
        return {"id": self.name, "snapshot": "init_state", "instruction": self.instruction,
                "config": [*setup, {"type": "sleep", "parameters": {"seconds": 2}}],
                "proxy": False, "evaluator": {"func": "infeasible"}}

    def path(self) -> str:
        """Return the synthetic file path only for independent transfer verification."""
        intent = interpret(self.instruction)
        if intent.app == "writer":
            name = f"Practice Notes {self.variant}.docx"
        elif intent.app == "calc":
            name = f"Practice Sheet {self.variant}.xlsx"
        else:
            name = f'{intent.values["file"]}.txt'
        return str(PurePosixPath("/home/user/Desktop") / name)


DEMONSTRATIONS = (
    Lesson("restore_notes", 'Restore "garden notes" from the Trash.', 1),
    Lesson("restore_draft", 'Restore "meeting draft" from the Trash.', 2),
    Lesson("dim_enable", "Set Dim screen when inactive to on.", 3),
    Lesson("dnd_enable", "Please turn on Do Not Disturb.", 4),
    Lesson("writer_font", 'Change the font to "DejaVu Serif" throughout this note.', 5),
    Lesson("writer_center", "Centre align the heading in this document.", 6),
    Lesson("writer_spacing", "Set the first two paragraphs to double line spacing.", 7),
    Lesson("writer_subscript", 'Please make the 2 in "CO2" a subscript.', 8),
    Lesson("calc_csv", "Export this sheet to CSV with its current name.", 9),
    Lesson("calc_pad", "Copy the 'Batch' column to the 'Padded Batch' column and pad to five digits.", 10),
    Lesson("calc_sort_up", "Sort the records by Weight ascending.", 11),
    Lesson("calc_sort_down", "Sort the records by Weight descending.", 12),
)

CONTROLS = (
    Lesson("control_restore", 'Recover "bird count" from the Trash.', 21),
    Lesson("control_font", 'Change the font to "Liberation Serif" throughout this draft.', 22),
    Lesson("control_sort", "Sort the records by Score ascending.", 23),
)


def steps(lesson: Lesson) -> tuple[str, ...]:
    """Use teacher steps on synthetic examples only."""
    intent = interpret(lesson.instruction)
    sequences = {
        "restore": ("files", "trash", "item", "apply"),
        "dim": ("overview", "search", "panel", "apply"),
        "dnd": ("panel", "apply"),
        "font": ("select", "field", "clear", "type", "apply", "save", "confirm"),
        "center": ("start", "apply", "save", "confirm"),
        "csv": ("dialog", "list", "choose", "save", "format", "confirm"),
        "pad": ("capture", "clear", "address", "cell", "formula", "commit", "name", "clear_range",
                "range", "select", "fill", "save", "confirm"),
        "sort": ("column", "apply", "save", "confirm"),
    }
    if intent.skill == "spacing":
        select = tuple(f"select_{index}" for index in range(1, int(intent.values["count"]) + 1))
        sequence = ("start", *select, "menu", "dialog", "list", "value", "apply", "save", "confirm")
    elif intent.skill == "subscript":
        advance = tuple(f"advance_{index}" for index in range(1, int(intent.values["offset"]) + 1))
        sequence = ("find", "type", "match", "close", "start", *advance, "select", "apply", "save", "confirm")
    else:
        sequence = sequences[intent.skill]
    return tuple(f"{intent.skill}.{step}" for step in sequence)


def execute(*command: str) -> dict:
    """Build a setup-only command that executes before agent control."""
    return {"type": "execute", "parameters": {"command": list(command)}}


def guest_file(name: str, data: bytes) -> tuple[str, dict]:
    """Materialize an original fixture in the disposable guest."""
    path = str(PurePosixPath("/home/user/Desktop") / name)
    payload = base64.b64encode(data).decode("ascii")
    writer = "import base64,pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(base64.b64decode(sys.argv[2]))"
    return path, execute("python3", "-c", writer, path, payload)


def open_file(path: str) -> dict:
    """Open the fixture as OSWorld opens its original task documents."""
    return {"type": "open", "parameters": {"path": path}}


def writer_fixture(intent: Intent, variant: int) -> list[dict]:
    """Generate a synthetic document with distinctive text and initial formatting."""
    from docx import Document
    from docx.shared import Inches

    document = Document()
    if variant > 20:
        document.sections[0].left_margin = Inches(1.75)
    document.add_heading(f"Field observations {variant}", level=1)
    document.add_paragraph(f"Observation {variant} includes {intent.values.get('find', 'N2O')} in this original sample.")
    document.add_paragraph("This line contains intentionally different content and layout.")
    document.add_paragraph("Unaffected paragraph for transfer verification.")
    contents = BytesIO()
    document.save(contents)
    path, create = guest_file(f"Practice Notes {variant}.docx", contents.getvalue())
    return [create, open_file(path)]


def sheet_fixture(intent: Intent, variant: int) -> list[dict]:
    """Generate a workbook with blank targets and a known data extent."""
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    if intent.skill == "pad":
        sheet.append([intent.values["source"], intent.values["target"], "Category"])
        for index in (3, 5, 2, 8):
            sheet.append([variant * index, None, f"Band {index}"])
    elif variant > 20:
        sheet.append(["Tag", "Class", intent.values.get("column", "Total")])
        for index in (4, 1, 3, 2):
            sheet.append([f"Row {index}", "Training", variant * index])
    else:
        sheet.append(["Tag", intent.values.get("column", "Total"), "Class"])
        for index in (4, 1, 3, 2):
            sheet.append([f"Row {index}", variant * index, "Training"])
    contents = BytesIO()
    book.save(contents)
    path, create = guest_file(f"Practice Sheet {variant}.xlsx", contents.getvalue())
    return [create, open_file(path)]


def desktop_fixture(intent: Intent, variant: int) -> list[dict]:
    """Set a synthetic desktop starting point to the opposite of the desired effect."""
    if intent.skill == "restore":
        path, create = guest_file(f'{intent.values["file"]}.txt', f"Sample {variant}".encode())
        if variant > 20:
            other, additional = guest_file("additional practice.txt", b"unrelated item")
            return [additional, execute("gio", "trash", other), create, execute("gio", "trash", path)]
        return [create, execute("gio", "trash", path)]
    if intent.skill == "dim":
        initial = "false" if intent.values["desired"] == "on" else "true"
        return [execute("gsettings", "set", "org.gnome.settings-daemon.plugins.power", "idle-dim", initial)]
    initial = "true" if intent.values["desired"] == "on" else "false"
    return [execute("gsettings", "set", "org.gnome.desktop.notifications", "show-banners", initial)]
