"""Extract limited desktop goals and their values from an English instruction."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Intent:
    """Desired effect and live arguments, independent of concrete GUI actions."""

    skill: str
    app: str
    values: dict[str, str] = field(default_factory=dict)

    def features(self, checkpoint: str) -> list[str]:
        """Return a stable goal-network state that omits document and UI instance IDs."""
        return [f"osworld:{self.skill}:{checkpoint}"]


NUMBER_WORDS = dict(one=1, two=2, three=3, four=4, five=5, six=6, seven=7, eight=8, nine=9)


def small_number(value: str) -> int:
    """Resolve the bounded positive integer forms used by the desktop grammar."""
    number = int(value) if value.isascii() and value.isdecimal() else NUMBER_WORDS.get(value.lower(), 0)
    if not 1 <= number <= 12:
        raise ValueError(f"Unsupported small integer: {value}")
    return number


def writer_intent(text: str) -> Intent | None:
    """Identify a requested text scope and format property."""
    if match := re.search(r'\bfont\b.+?\bto\s+"([^"]+)"', text, re.I):
        return Intent("font", "writer", {"font": match[1]})
    if match := re.search(r'\bfirst\s+(\w+)\s+paragraphs?.*?\b(single|double)\b', text, re.I):
        count = small_number(match[1])
        return Intent("spacing", "writer", {"count": str(count), "spacing": match[2].lower()})
    if match := re.search(r'\b([0-9])\s+in\s+"([a-z0-9]+)".*?\bsubscript\b', text, re.I):
        if match[2].count(match[1]) != 1:
            raise ValueError("The requested character is ambiguous within the text")
        return Intent("subscript", "writer", {"find": match[2], "offset": str(match[2].index(match[1]))})
    if re.search(r"\bcent(?:er|re)\b.*\bhead(?:ing|line)\b", text, re.I):
        return Intent("center", "writer")
    return None


def calc_intent(text: str) -> Intent | None:
    """Identify an export or a spreadsheet operation with input slots."""
    if re.search(r"\bexport\b.*\bcsv\b", text, re.I):
        return Intent("csv", "calc")
    if match := re.search(r"""['"]([^'"]+)['"]\s+column.*?['"]([^'"]+)['"]\s+column.*?\bpad\b.*?\b(\w+)\s+digits?\b""", text, re.I):
        width = small_number(match[3])
        return Intent("pad", "calc", {"source": match[1], "target": match[2], "width": str(width)})
    if match := re.search(r"\bsort\b.*?\b(?:by|to)\s+(?:the\s+)?([\w ]+?)\s+(ascending|descending)(?:ly)?\b", text, re.I):
        return Intent("sort", "calc", {"column": match[1].strip(), "direction": match[2].lower()})
    return None


def interpret(instruction: str) -> Intent:
    """Recognize supported intent families without looking at task IDs or the judge."""
    text = " ".join(instruction.translate(str.maketrans("“”‘’", "\"\"''")).split())
    if "\x00" in text or len(text) > 1600:
        raise ValueError("Unsupported instruction")
    if match := re.search(r"['\"]?dim screen when inactive['\"]?\s+to\s+(off|on)\b", text, re.I):
        return Intent("dim", "settings", {"desired": match[1].lower()})
    if re.search(r"\bdo not disturb\b", text, re.I):
        desired = "off" if re.search(r"\b(?:disable|turn off)\b", text, re.I) else "on"
        return Intent("dnd", "desktop", {"desired": desired})
    if re.search(r"\b(?:recover|restore)\b.*\btrash\b", text, re.I):
        quoted = re.search(r'\"([^"]+)\"', text)
        described = re.search(r"\bdeleted\s+(?:an?\s+)?([^.!?]+)", text, re.I)
        target = quoted or described
        if target:
            return Intent("restore", "files", {"file": target[1].strip()})
    goal = writer_intent(text) or calc_intent(text)
    if goal is None:
        raise ValueError("Instruction does not identify a supported goal")
    return goal
