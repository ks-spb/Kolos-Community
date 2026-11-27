"""Check that the lab learns its edit from the demonstration and preserves source."""
import pytest

from kolos_states.core import StateEngine
from kolos_states.programming_lab.episode import run_episode, teach_episode
from kolos_states.programming_lab.fixtures import ALTERNATE, ALTERNATE_DEMO_AFTER, DEMO, DEMO_AFTER, HELD_OUT, Case, behavior
from kolos_states.programming_lab.transform import apply_guard, learn_guard


@pytest.mark.parametrize('case', HELD_OUT, ids=lambda case: case.key)
def test_transfer_to_unseen_function(case: Case) -> None:
    """Independent examples prove the fix and preserve behavior on valid inputs."""
    rule = learn_guard(DEMO.source, DEMO_AFTER, DEMO.name)
    before = behavior(case, case.source)
    after = behavior(case, apply_guard(case.source, case.name, rule))
    assert [row['passed'] for row in before] == [False] + [True] * (len(before) - 1)
    assert all(row['passed'] for row in after)


def test_insertion_respects_docstring_and_preserves_surrounding_source() -> None:
    """A different function and its comment survive the edit verbatim."""
    case = HELD_OUT[0]
    rule = learn_guard(DEMO.source, DEMO_AFTER, DEMO.name)
    anchor = '    return text.strip().upper()  # keep inline comment'
    expected = case.source.replace(anchor, '    if text is None:\n        return None\n' + anchor)
    assert apply_guard(case.source, case.name, rule) == expected


def test_comparison_result_and_anchor_come_from_the_demonstration() -> None:
    """A changed lesson yields a different comparison, return value and location."""
    rule = learn_guard(DEMO.source, ALTERNATE_DEMO_AFTER, DEMO.name)
    after = apply_guard(ALTERNATE.source, ALTERNATE.name, rule)
    expected = ALTERNATE.source.replace('    return trimmed.upper()',
                                        "    if label == 'skip':\n        return 99\n    return trimmed.upper()")
    assert rule.index == 1
    assert after == expected
    assert all(row['passed'] for row in behavior(ALTERNATE, after))


def test_reject_demonstration_that_also_changes_existing_code() -> None:
    """Extraneous teaching edits are rejected instead of silently absorbed."""
    after = DEMO_AFTER.replace('return len(normalized)', 'return 99')
    with pytest.raises(ValueError, match='unambiguous anchor'):
        learn_guard(DEMO.source, after, DEMO.name)


def test_release_only_after_behavioral_verification() -> None:
    """A plausible but incorrect edit fails and makes no candidate available."""
    primary = learn_guard(DEMO.source, DEMO_AFTER, DEMO.name)
    alternate = learn_guard(DEMO.source, ALTERNATE_DEMO_AFTER, DEMO.name)
    engine = StateEngine()
    teach_episode(engine, primary)
    row, candidate = run_episode(engine, HELD_OUT[2], alternate)
    assert row['status'] == 'failed'
    assert row['checks'][0]['argument'] is None
    assert not row['checks'][0]['passed']
    assert row['memory_unchanged']
    assert candidate is None
