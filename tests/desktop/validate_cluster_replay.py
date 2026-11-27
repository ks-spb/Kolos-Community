"""Audit saved paired evidence, privacy and provider measurements without another model call."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from kolos_states.cluster_replay.corpus import digest, save
from kolos_states.cluster_replay.suite import source_hashes


def validate(directory: Path) -> dict:
    """Check completeness and invariants without requiring algorithms to have succeeded."""
    data = json.loads((directory / 'results.json').read_text(encoding='utf-8'))
    corpus = json.loads((directory / 'corpus.json').read_text(encoding='utf-8'))
    protocol, rows = data['protocol'], data['rows']
    assert data['sources'] == source_hashes(), 'Source changed after execution'
    assert digest(corpus) == protocol['corpus_hash'], 'Corpus differs from preregistered input'
    assert protocol['teaching_case'] not in protocol['heldout_cases']
    expected = {(case, variant, selector) for case in protocol['heldout_cases']
                for variant in protocol['variants'] for selector in protocol['controls']}
    assert len(rows) == len(expected)
    assert {(r['case'], r['variant'], r['selector']) for r in rows} == expected
    measured = 0
    for row in rows:
        if row['selector'] == 'model_skill':
            measured += _model(directory, corpus, row)
        else:
            assert row['llm_calls'] == row['input_tokens'] == row['output_tokens'] == 0
        assert row['save_attempts'] <= 1, 'Repeated save in replay'
        if row['variant'] in ('wrong_identity', 'no_approval', 'already_applied', 'ambiguous_field', 'changed_after_begin'):
            assert row['applied'] == 0, 'Unexpected simulated write'
    result = dict(trials=len(rows), heldout_operations=len(protocol['heldout_cases']),
                  teaching_operations=1, model_usage_records=measured, source_hashes_match=True,
                  corpus_hash_match=True, paired_complete=True, model_input_anonymized=True,
                  no_repeated_save=True, unsafe_condition_writes=0)
    save(directory / 'validation.json', result)
    return result


def _model(directory: Path, corpus: dict, row: dict) -> int:
    """Compare provider totals with raw replies and independently inspect outgoing inputs."""
    name = f'model-{row["case"][:10]}-{row["variant"]}.json'
    envelope = json.loads((directory / name).read_text(encoding='utf-8'))
    request, response = envelope['request'], envelope['response']
    messages = request['messages']
    payload = json.loads(messages[1]['content'])
    assert payload['context']['task']['identity'] == dict(shop_id='demo-shop', nm_id='demo-product', vendor_code='demo-sku')
    assert payload['context']['task']['campaign_id'] == 'demo-campaign'
    assert payload['context']['task']['query'] == 'demo-cluster'
    assert payload['observation']['session'] == 'offline-replay'
    text = json.dumps(messages, ensure_ascii=False)
    for case in corpus['cases']:
        for value in (case['id'], case['identity']['nm_id'], case['identity']['vendor_code'],
                      case['campaign_id'], case['query'], case['evidence_ref']):
            assert str(value) not in text, 'Business identifier leaked into model input'
    if response.get('ok'):
        assert row['input_tokens'] == response['input_tokens'] >= 0
        assert row['output_tokens'] == response['output_tokens'] >= 0
        assert 0 <= row['cache_read_tokens'] <= row['input_tokens']
        return 1
    assert row['status'] == 'unavailable' and row['input_tokens'] is None
    return 0


def main() -> None:
    """Use a completed output directory; validation has no provider dependency."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.directory), ensure_ascii=False))


if __name__ == '__main__':
    main()
