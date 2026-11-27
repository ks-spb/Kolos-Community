"""Official task selection and versioned environment lookup."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REVISION = "9d6f711d234b84cbff1b5199211610baa03b000c"
CALIBRATION = "28cc3b7e-b194-4bc9-8353-d04c0f4d56d2"
DATASET = {
    "os": (
        "5ea617a3-0e86-4ba6-aab2-dac9aa2e8d57",
        "bedcedc4-4d72-425e-ad62-21960b11fe0d",
        "f9be0997-4b7c-45c5-b05c-4612b44a6118",
    ),
    "libreoffice_writer": (
        "0810415c-bde4-4443-9047-d5f70165a697",
        "0b17a146-2934-46c7-8727-73ff6b6483e8",
        "0e763496-b6bb-4508-a427-fad0b6c3e195",
        "3ef2b351-8a84-4ff2-8724-d86eae9b842e",
    ),
    "libreoffice_calc": (
        "3aaa4e37-dc91-482e-99af-132a612d40f3",
        "0bf05a7d-b28b-44d2-955a-50b41e24012a",
        "51b11269-2ca8-4b2a-9163-f21758420e78",
    ),
}


def load_tasks(checkout: Path) -> list[tuple[str, dict]]:
    """Load exact upstream task definitions from a clean pinned checkout."""
    git = ["git", "-C", str(checkout)]
    head = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
    changes = subprocess.check_output([*git, "status", "--porcelain", "--untracked-files=no"], text=True)
    if head != REVISION or changes:
        raise ValueError(f"OSWorld checkout must be clean at {REVISION}; found {head}")
    examples = checkout / "evaluation_examples"
    official = json.loads((examples / "test_all.json").read_text(encoding="utf-8"))
    tasks = []
    for domain, selections in DATASET.items():
        for task_id in selections:
            path = examples / "examples" / domain / f"{task_id}.json"
            task = json.loads(path.read_text(encoding="utf-8"))
            if task_id not in official[domain] or task["id"] != task_id:
                raise ValueError(f"Task is missing from the official subset: {task_id}")
            tasks.append((domain, task))
    return tasks


def load_calibration(checkout: Path) -> dict:
    """Load the separate official task used to calibrate the judge."""
    path = checkout / "evaluation_examples" / "examples" / "os" / f"{CALIBRATION}.json"
    return json.loads(path.read_text(encoding="utf-8"))
