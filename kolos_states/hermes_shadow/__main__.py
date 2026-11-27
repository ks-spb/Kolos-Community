"""Read-only integration audit, shadow routing, and replay against frozen local inputs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from . import audit, replay, routing

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'tests' / 'desktop-output'
BINDINGS = ROOT / '.local-data' / 'hermes-shadow.json'


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def source_hashes() -> dict:
    files = list(Path(__file__).parent.glob('*.py'))
    files += [ROOT / 'kolos_states' / name for name in ('core.py', 'episodes.py', 'episode_browser.py')]
    files += list((ROOT / 'kolos_states' / 'cluster_replay').glob('*.py'))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def read_bindings(path: Path) -> tuple[str, str, str]:
    """Read the required local case and executor identifiers without logging them."""
    config = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(config, dict) or set(config) != {'teaching_id', 'owner', 'supervisor'}:
        raise ValueError('Hermes shadow bindings require teaching_id, owner and supervisor')
    if any(not isinstance(n, str) or not n.strip() for n in config.values()):
        raise ValueError('Hermes shadow binding values must be nonempty strings')
    return config['teaching_id'], config['owner'], config['supervisor']


def run(args: argparse.Namespace) -> dict:
    """Snapshot once; all subsequent cases use that snapshot without live ledger mutations."""
    teaching_id, owner, supervisor = read_bindings(args.bindings)
    output = args.output.resolve()
    if not output.is_relative_to(OUTPUT.resolve()) or output.exists():
        raise ValueError('Use a new directory inside tests/desktop-output')
    output.mkdir(parents=True)
    state, source = audit.read_state(args.state)
    write(output / 'state-snapshot.json', state)
    messages = audit.executor_messages(args.executor_db, set(state['proposals']), profile=owner, supervisor=supervisor)
    write(output / 'executor-messages.json', messages)
    now = datetime.now(timezone.utc)
    decisions = [routing.route(p, state, now, owner=owner) for p in state['proposals'].values()]
    write(output / 'routing.json', decisions)
    available, proposals = replay.cases(state)
    if teaching_id not in proposals:
        raise ValueError('Historical training case not present')
    heldout = [c for c in available if c['id'] != teaching_id]
    write(output / 'cases.json', dict(cases=heldout, proposals=proposals, training_case_excluded=teaching_id))
    learned = json.loads(args.memory.read_text(encoding='utf-8'))
    write(output / 'learned.json', learned)
    # Freeze only the inspected pure matcher, not a second application/production root.
    (output / 'goal-policy.py').write_bytes(args.goal_policy.read_bytes())
    result = replay.rehearse(heldout, proposals, learned, output / 'goal-policy.py')
    write(output / 'replay.json', result)
    meta = dict(source=source, inventory=audit.inventory(state), executor_message_counts=messages['counts'],
                captured_utc=now.isoformat(), heldout=len(heldout), source_sha256=source_hashes(),
                memory_source_sha256=hashlib.sha256(args.memory.read_bytes()).hexdigest(),
                goal_policy_source_sha256=hashlib.sha256(args.goal_policy.read_bytes()).hexdigest(),
                production_modified=False, external_messages_sent=0)
    write(output / 'audit.json', meta)
    return dict(output=str(output), heldout=len(heldout), trials=len(result['rows']),
                correct=sum(r['correct_outcome'] for r in result['rows']),
                controls=len(result['memory_off']), messages=messages['counts'])


def fresh(args: argparse.Namespace) -> dict:
    base = args.output.resolve()
    if not base.is_relative_to(OUTPUT.resolve()) or not (base / 'cases.json').exists():
        raise ValueError('Restart requires an existing local audit')
    cases = json.loads((base / 'cases.json').read_text(encoding='utf-8'))
    learned = json.loads((base / 'learned.json').read_text(encoding='utf-8'))
    result = replay.restart(cases['cases'], cases['proposals'], learned, base / 'goal-policy.py')
    write(base / 'restart.json', result)
    return dict(pid=result['pid'], cases=len(result['rows']),
                correct=sum(r['correct_outcome'] for r in result['rows']))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('audit', 'restart'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--bindings', type=Path, default=BINDINGS)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--executor-db', type=Path)
    parser.add_argument('--memory', type=Path)
    parser.add_argument('--goal-policy', type=Path)
    args = parser.parse_args()
    if args.mode == 'audit' and not all((args.state, args.executor_db, args.memory, args.goal_policy)):
        parser.error('Audit requires state, executor-db, memory, goal-policy')
    print(json.dumps(run(args) if args.mode == 'audit' else fresh(args), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
