"""Read a frozen, minimal corpus; no WB modules, credentials or connectors."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def digest(value: object) -> str:
    """Fingerprint canonical JSON independent of object key ordering."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def extract(path: Path) -> dict:
    """Keep only independently verified cluster changes and their observed contracts."""
    raw = path.read_bytes()
    state = json.loads(raw)
    cases = []
    for proposal in state['proposals'].values():
        if proposal.get('command') != 'advertising.cluster.set_excluded' or proposal.get('status') != 'verified':
            continue
        cases.append(_case(proposal))
    if len(cases) < 3 or not {True, False}.issubset({c['target'] for c in cases}):
        raise ValueError('Need saved examples of both exclusion and restoration')
    return dict(schema='kolos-cluster-replay/1', source_path=str(path.resolve()),
                source_sha256=hashlib.sha256(raw).hexdigest(), cases=cases)


def _case(p: dict) -> dict:
    """Separate historical evidence from the simulated authorization used in replay."""
    before, evidence = p['preconditions'], p['verification']
    after = evidence['current']
    desired = p['payload']['excluded']
    if type(desired) is not bool or after['excluded'] != desired or before['excluded'] == desired:
        raise ValueError('Missing observed cluster transition')
    for key in ('campaign_id', 'norm_query'):
        if before.get(key) != after.get(key) or before[key] != p['payload'][key]:
            raise ValueError('Mismatched saved scope')
    return dict(id=p['proposal_id'], identity=p['identity'], campaign_id=before['campaign_id'],
                query=before['norm_query'], target=desired, before=before, after=after,
                historical_approval_origin=p.get('approval', {}).get('origin'),
                evidence_ref=evidence['source_ref'], evidence_sha256=digest(evidence),
                submitted_at=p['submitted_at'], observed_at=evidence['observed_at'])


def split(corpus: dict, *, teaching_product_id: int | None = None) -> tuple[dict, list[dict]]:
    """Select a restoration and keep every other case in the held-out set."""
    examples = corpus['cases']
    teaching = next((case for case in examples if case['target'] is False
                     and (teaching_product_id is None
                          or case['identity']['nm_id'] == teaching_product_id)), None)
    if teaching is None:
        raise ValueError('No restoration matches the requested teaching selection')
    return teaching, [case for case in examples if case['id'] != teaching['id']]


def save(path: Path, value: object) -> None:
    """Write experiment artifacts only under the caller's explicit output directory."""
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
