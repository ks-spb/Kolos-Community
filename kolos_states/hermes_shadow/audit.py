"""Inspect application ledger and exact executor messages without resuming agents."""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3


def read_state(path: Path) -> tuple[dict, dict]:
    """Take one immutable-in-memory read; never import the application's live store."""
    raw = path.read_bytes()
    state = json.loads(raw)
    if state.get('version') != 1 or not isinstance(state.get('proposals'), dict):
        raise ValueError('Unknown WB manager ledger schema')
    return state, dict(path=str(path.resolve()), sha256=hashlib.sha256(raw).hexdigest(),
                       captured_utc=datetime.now(timezone.utc).isoformat(), bytes=len(raw))


def database_schema(path: Path) -> dict:
    """Inspect only known public session tables through SQLite's read-only mode."""
    uri = path.resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
        connection.execute('PRAGMA query_only=ON')
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {table: [r[1] for r in connection.execute(f'PRAGMA table_info({table})')]
                for table in ('sessions', 'messages') if table in tables}


def inventory(state: dict) -> dict:
    """Separate historical application, unexecuted preview, and an outstanding attempt."""
    proposals = list(state['proposals'].values())
    commands = Counter((p['command'], p['status']) for p in proposals)
    active_id = state.get('ui_active_proposal')
    active = state['proposals'].get(active_id) if active_id else None
    counts = [dict(command=command, status=status, count=count)
              for (command, status), count in sorted(commands.items())]
    dispatches = Counter((p.get('profile'), p.get('purpose'), p.get('status'))
                         for p in state.get('hermes_dispatches', {}).values())
    return dict(proposal_counts=counts, active_attempt=None if not active else {
        key: active.get(key) for key in ('proposal_id', 'command', 'status', 'identity', 'submitted_at')},
        dispatch_counts=[dict(profile=p, purpose=purpose, status=s, count=c)
                         for (p, purpose, s), c in sorted(dispatches.items())],
        policy={key: state.get('supervisor_policy', {}).get(key)
                for key in ('enabled', 'starts_at', 'expires_at', 'allowed_commands')})


def redact(text: str) -> str:
    """Keep business instructions, masking credential-like strings if encountered."""
    text = re.sub(r'(?i)(bearer\s+)[A-Za-z0-9_.-]+', r'\1[REDACTED]', text)
    text = re.sub(r'''(?i)((?:api[_-]?key|access[_-]?token|password|secret)['"]?\s*[=:]\s*['"]?)[^'"\s,;]+''',
                  r'\1[REDACTED]', text)
    return text


def _kind(content: str, supervisor: str) -> str:
    """Classify provenance, never derive authorization from message wording."""
    if content.startswith("You've reached the maximum number"):
        return 'runtime_notice'
    if content.startswith('Message from ') and '@' + supervisor in content:
        return 'supervisor_instruction'
    if 'dispatch_id=hermes_independent_' in content:
        return 'migration_probe'
    return 'unclassified'


def _terminal(row: dict) -> bool:
    """Tool-calling assistant turns are not a delivered final result."""
    calls = row.get('tool_calls')
    if isinstance(calls, str):
        calls = json.loads(calls) if calls else None
    return row['role'] == 'assistant' and not calls and bool(row.get('content'))


def executor_messages(path: Path, proposal_ids: set[str], *, profile: str, supervisor: str) -> dict:
    """Read the exact profile's canonical chat, not tool results or authentication data."""
    uri = path.resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        sessions = connection.execute("SELECT id,title,profile_name,parent_session_id FROM sessions "
            "WHERE profile_name=? AND title=? AND archived=0", (profile, 'Bot Chat')).fetchall()
        if len(sessions) != 1 or sessions[0]['parent_session_id']:
            raise ValueError('Need one uncompressed canonical executor chat; use official ancestry reader otherwise')
        session = dict(sessions[0])
        rows = [dict(r) for r in connection.execute('SELECT id,role,content,tool_calls,timestamp FROM messages '
                "WHERE session_id=? AND role IN ('user','assistant') ORDER BY id", (session['id'],))]
    requests = [r for r in rows if r['role'] == 'user' and _kind(str(r['content']), supervisor) != 'runtime_notice']
    items = []
    for index, row in enumerate(requests):
        end = requests[index + 1]['id'] if index + 1 < len(requests) else float('inf')
        replies = [r for r in rows if row['id'] < r['id'] < end and _terminal(r)]
        text = redact(str(row['content']))
        match = re.search(r'(?<!\w)dispatch_id=([\w-]+)', text)
        items.append(dict(message_id=row['id'], timestamp=row['timestamp'], kind=_kind(text, supervisor),
            dispatch_id=match[1] if match else None, text=text,
            proposal_refs=sorted(proposal_ids.intersection(re.findall(r'(?<![a-f0-9])[a-f0-9]{64}(?![a-f0-9])', text))),
            reply_id=replies[-1]['id'] if replies else None,
            reply=redact(str(replies[-1]['content'])) if replies else None))
    return dict(source=str(path.resolve()), session=session, requests=items,
                counts=dict(Counter(i['kind'] for i in items)), complete=True)
