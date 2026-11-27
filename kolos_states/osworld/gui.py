"""Translate an OSWorld accessibility snapshot into bounded computer-use primitives."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from io import BytesIO
from typing import Callable

SCREEN_SIZE = (1920, 1080)
NodeFilter = Callable[["Element"], bool]
STRUCTURAL_ROLES = {"application", "frame", "window", "dialog", "panel", "scroll-pane", "desktop-frame"}


def comparable(value: str) -> str:
    """Keep words and numbers for matching descriptive UI labels."""
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def element_box(attrs: dict[str, str]) -> tuple[int, int, int, int] | None:
    """Read the AT-SPI component geometry in guest screen coordinates."""
    position = re.fullmatch(r"\((-?\d+),\s*(-?\d+)\)", attrs.get("screencoord", ""))
    size = re.fullmatch(r"\((\d+),\s*(\d+)\)", attrs.get("size", ""))
    if not position or not size:
        return None
    x, y = map(int, position.groups())
    width, height = map(int, size.groups())
    if not width or not height or x >= SCREEN_SIZE[0] or y >= SCREEN_SIZE[1] or x + width <= 0 or y + height <= 0:
        return None
    return max(0, x), max(0, y), min(SCREEN_SIZE[0], x + width), min(SCREEN_SIZE[1], y + height)


@dataclass(frozen=True)
class Element:
    """Visible guest control with its role, state and nearest window scope."""

    role: str
    name: str
    text: str
    attrs: dict[str, str]
    app: str
    window: str
    box: tuple[int, int, int, int] | None

    def has(self, key: str) -> bool:
        """Return the state exported by the guest."""
        return self.attrs.get(key) == "true"

    @property
    def label(self) -> str:
        """Return the user-facing name or visible text."""
        return self.name or self.text


def read_elements(root: ET.Element) -> tuple[Element, ...]:
    """Preserve app/window context while keeping the observed element list flat."""
    elements = []
    stack = [(root, "", "", False)]
    while stack:
        node, app, window, hidden = stack.pop()
        attrs = {key.rsplit("}", 1)[-1]: value for key, value in node.attrib.items()}
        role = node.tag.rsplit("}", 1)[-1]
        name = attrs.get("name", "")
        if role == "application":
            app = name
        if role in {"frame", "dialog", "window"}:
            window = name
        hidden = hidden or attrs.get("showing") == "false" or attrs.get("visible") == "false"
        if not hidden:
            elements.append(Element(role, name, (node.text or "").strip(), attrs, app, window, element_box(attrs)))
            stack.extend((child, app, window, hidden) for child in reversed(node))
    return tuple(elements)


@dataclass(frozen=True)
class Frame:
    """Only screenshot and accessible controls from an actual observation."""

    screenshot: bytes
    elements: tuple[Element, ...]

    @classmethod
    def read(cls, raw: dict) -> "Frame":
        """Reject absent, oversized or malformed accessibility XML."""
        tree, image = raw.get("accessibility_tree"), raw.get("screenshot")
        if not isinstance(tree, str) or not tree or len(tree) > 16_000_000 or not isinstance(image, bytes) or not image:
            raise RuntimeError("The guest did not supply both a screenshot and a usable accessibility tree")
        try:
            return cls(image, read_elements(ET.fromstring(tree)))
        except ET.ParseError as exc:
            raise RuntimeError("Invalid guest accessibility XML") from exc

    def find(self, matches: NodeFilter) -> list[Element]:
        """Find relevant elements, including nonclickable evidence such as window titles."""
        return [element for element in self.elements if matches(element)]

    def control(self, matches: NodeFilter) -> Element | None:
        """Resolve exactly one enabled visible control by geometry."""
        candidates = {}
        for element in self.elements:
            if element.box and not element.has("defunct") and element.attrs.get("enabled") != "false" and matches(element):
                candidates.setdefault(element.box, element)
        return next(iter(candidates.values())) if len(candidates) == 1 else None

    def region(self, box: tuple[int, int, int, int]) -> bytes:
        """Get a digest of pixels in a specific guest surface, excluding the top bar."""
        from PIL import Image

        with Image.open(BytesIO(self.screenshot)) as image:
            return hashlib.sha256(image.crop(box).tobytes()).digest()


def labelled(*names: str, roles: tuple[str, ...] = ()) -> NodeFilter:
    """Build a strict role and human-readable label selector."""
    choices = {comparable(name) for name in names}
    return lambda element: (not roles or element.role in roles) and comparable(element.label) in choices


def click(frame: Frame, matches: NodeFilter, action_type: str = "CLICK") -> dict | None:
    """Build one click using the current accessible box."""
    element = frame.control(lambda node: node.role not in STRUCTURAL_ROLES and matches(node))
    if element is None or element.box is None:
        return None
    x1, y1, x2, y2 = element.box
    return command(action_type, x=(x1 + x2) // 2, y=(y1 + y2) // 2)


def command(action_type: str, **parameters: object) -> dict:
    """Use the structured OSWorld computer_13 action representation."""
    return {"action_type": action_type, "parameters": parameters}


def hotkey(*keys: str) -> dict:
    """Create one keyboard shortcut in the guest."""
    return command("PRESS", key=keys[0]) if len(keys) == 1 else command("HOTKEY", keys=list(keys))


def typing(value: str) -> dict | None:
    """Pass only printable ASCII supported by the upstream keyboard primitive."""
    if value and len(value) <= 500 and value.isascii() and all(char.isprintable() for char in value):
        return command("TYPING", text=value)
    return None
