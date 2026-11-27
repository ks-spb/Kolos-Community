"""Read-only presentation of commands confirmed through demonstration learning."""
from __future__ import annotations

from .core import action_text


def confirmed_tasks(lessons: list[dict]) -> list[dict]:
    """Group approved demonstrations by their exact query, preserving order."""
    tasks = {}
    for lesson in lessons:
        query = lesson['query']
        actions = [action_text(receipt['action']) for receipt in lesson['receipts']]
        if query not in tasks:
            tasks[query] = dict(query=query, demonstrations=0, actions=[])
        task = tasks[query]
        task['demonstrations'] += 1
        task['actions'] = actions
    return list(tasks.values())
