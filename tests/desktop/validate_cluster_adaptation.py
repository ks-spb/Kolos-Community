"""Audit procedure-change evidence offline, without any further model requests."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from kolos_states.cluster_replay.corpus import digest, save
from kolos_states.cluster_adaptation.suite import PHASES, source_hashes
from kolos_states.cluster_adaptation.world import REVIEW_ROLE, variants
from kolos_states.protocol import persistent_graph


def validate(directory: Path) -> dict:
    """Check paired coverage, privacy, preserved memory and independent process controls."""
    data = json.loads((directory / 'results.json').read_text(encoding='utf-8'))
    corpus = json.loads((directory / 'corpus.json').read_text(encoding='utf-8'))
    protocol, rows = data['protocol'], data['rows']
    assert data['sources'] == source_hashes(), 'Source changed after execution'
    assert digest(corpus) == protocol['corpus_hash']
    assert protocol['teaching_case'] not in protocol['heldout_cases']
    cases = [c for c in corpus['cases'] if c['id'] in protocol['heldout_cases']]
    expected = {(phase, c['id'], fault, selector) for phase in PHASES for c in cases
                for fault in (variants(c) if phase == 'adapted_v2' else ('clean',))
                for selector in protocol['selectors']}
    assert len(rows) == len(expected)
    assert {(r['phase'], r['case'], r['variant'], r['selector']) for r in rows} == expected
    usage = sum(_model(directory, corpus, row) for row in rows if row['selector'] == 'model_skill')
    for row in rows:
        _row(row)
    _memory(directory)
    restart = data['restart']
    assert restart['different_pid'] and restart['graph_equal'] and restart['graph_unchanged']
    assert len(restart['rows']) == len(cases)
    assert {r['case'] for r in restart['rows']} == set(protocol['heldout_cases'])
    assert all(r['correct_outcome'] for r in restart['rows'])
    assert data['lesion']['restorations_blocked'] == sum(c['target'] is False for c in cases)
    assert data['lesion']['exclusions_completed'] == sum(c['target'] is True for c in cases)
    result = dict(trials=len(rows), heldout_operations=len(cases), model_usage_records=usage,
        paired_complete=True, source_hashes_match=True, model_inputs_anonymized=True,
        v1_memory_preserved=True, restart_tasks=len(restart['rows']), restart_verified=True,
        lesion_tasks=len(data['lesion']['rows']), no_repeated_save=True)
    save(directory / 'validation.json', result)
    return result


def _row(row: dict) -> None:
    """Successful v2 restoration needs the new step in the correct place, not just a claim."""
    assert row['save_attempts'] <= 1 and not row['repeated_save']
    if row['selector'] != 'model_skill':
        assert row['llm_calls'] == row['input_tokens'] == row['output_tokens'] == 0
    if row['false_success']:
        assert row['status'] == 'complete' and not row['completed']
    if row['status'] == 'complete' and not row['false_success']:
        assert row['completed'] and row['applied'] == 1
        names = [o['role'] for o in row['operations']]
        assert names[-1] == 'Record result'
        if row['revision'] == 2 and row['restoration']:
            assert names.count(REVIEW_ROLE) == 1
            assert names.index('Draft excluded') < names.index(REVIEW_ROLE) < names.index('Save excluded')
        else:
            assert REVIEW_ROLE not in names
    if row['variant'] in ('wrong_identity', 'no_approval', 'already_applied', 'ambiguous_field',
                          'changed_after_begin', 'preview_no_effect', 'preview_invalidated'):
        assert row['applied'] == 0


def _memory(directory: Path) -> None:
    """Verify v1 nodes/edges survived, rather than trusting an experiment's boolean flag."""
    old = json.loads((directory / 'learned-v1.json').read_text(encoding='utf-8'))
    new = json.loads((directory / 'learned-v2.json').read_text(encoding='utf-8'))
    a, b = (persistent_graph(m['model']['memory']) for m in (old, new))
    assert all(item in b[key] for key in ('nodes', 'edges') for item in a[key])
    assert len(old['model']['episodeCommands']) == 1
    assert len(new['model']['episodeCommands']) == 2


def _model(directory: Path, corpus: dict, row: dict) -> int:
    """Check actual provider counters and every outgoing message independently."""
    path = directory / f'model-{row["phase"]}-{row["case"][:10]}-{row["variant"]}.json'
    envelope = json.loads(path.read_text(encoding='utf-8'))
    messages, response = envelope['request']['messages'], envelope['response']
    payload = json.loads(messages[1]['content'])
    assert payload['context']['task']['identity'] == dict(shop_id='demo-shop', nm_id='demo-product', vendor_code='demo-sku')
    assert payload['context']['task']['campaign_id'] == 'demo-campaign'
    assert payload['context']['task']['query'] == 'demo-cluster'
    assert payload['observation']['session'] == 'offline-replay'
    text = json.dumps(messages, ensure_ascii=False)
    for case in corpus['cases']:
        for value in (case['id'], case['identity']['nm_id'], case['identity']['vendor_code'],
                      case['campaign_id'], case['query'], case['evidence_ref']):
            assert str(value) not in text
    root = Path(__file__).resolve().parents[2] / 'kolos_states'
    skill = (root / 'cluster_replay/skill.md').read_text(encoding='utf-8')
    if row['phase'] != 'frozen_v2':
        skill += (root / 'cluster_adaptation/skill-v2.md').read_text(encoding='utf-8')
    assert messages[0]['content'] == skill
    if response.get('ok'):
        assert row['input_tokens'] == response['input_tokens'] >= 0
        assert row['output_tokens'] == response['output_tokens'] >= 0
        assert 0 <= row['cache_read_tokens'] <= row['input_tokens']
        return 1
    assert row['status'] == 'unavailable' and row['input_tokens'] is None
    return 0


def main() -> None:
    """Read completed artifacts only; do not re-run any controller."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.directory), ensure_ascii=False))


if __name__ == '__main__':
    main()
