"""A new restoration-only preview gate over the unchanged offline replay host."""
from __future__ import annotations

import copy

from ..cluster_replay.corpus import digest
from ..cluster_replay.world import Blocked, STEPS, VARIANTS, World as OriginalWorld

REVIEW_ROLE = 'Review restoration preview'
PREVIEW_ROLE = 'Restoration preview'
REVIEW = dict(kind='activate', role=REVIEW_ROLE)
NEW_FAULTS = ('preview_no_effect', 'preview_invalidated')


def operations(review_required: bool) -> list[dict]:
    """The revised script explicitly inserts one operation; old recipes stay frozen."""
    result = [dict(kind=k, role=r) for k, r in STEPS]
    if review_required:
        result.insert(4, dict(REVIEW))
    return result


def variants(case: dict) -> tuple[str, ...]:
    """Preview faults apply to restorations; exclusions retain their original contract."""
    return VARIANTS + NEW_FAULTS if case['target'] is False else VARIANTS


class World(OriginalWorld):
    """No business transport: a local new step with independently observed effects."""

    def __init__(self, case: dict, variant: str = 'clean', layout: int = 0, revision: int = 2):
        """Expose the new gate only on revised restoration forms."""
        if revision not in (1, 2) or variant not in variants(case):
            raise ValueError('Unsupported procedure revision or fault')
        super().__init__(case, 'clean' if variant in NEW_FAULTS else variant, layout)
        self.variant, self.revision = variant, revision
        self.review_required = revision == 2 and case['target'] is False
        self.review_scope = None
        self.review_calls, self.review_rejections = 0, 0
        if self.review_required:
            self.data[PREVIEW_ROLE] = 'required'

    def _object(self, name: str, value: str) -> dict:
        """Use the same role schema, with one additional observable button."""
        result = super()._object(name, value)
        if name == REVIEW_ROLE:
            result['descriptor']['kind'] = 'button'
        return result

    def observe(self) -> dict:
        """Fresh evidence, new runtime IDs and no hidden fault label in observations."""
        result = super().observe()
        if self.review_required:
            result['objects'].append(self._object(REVIEW_ROLE, ''))
        return result

    def execute(self, request: dict) -> dict:
        """Dispatch the single new primitive locally, everything else through the old host."""
        action = request['action']
        if action.get('kind') != 'activate' or action.get('object') != f'layout{self.layout}:{REVIEW_ROLE}':
            return super().execute(request)
        if not self.review_required:
            raise Blocked('Restoration review is not present on this form')
        before = self.observe()
        self.operations.append(dict(kind='activate', role=REVIEW_ROLE, value=None))
        self._review()
        return dict(id=request['id'], action=copy.deepcopy(action), ok=True,
                    before=before, after=self.observe())

    def _binding(self) -> str:
        """Tie the preview to this scope, requested value and current draft."""
        return digest([self.observed_scope, self.target, self.data['Draft excluded']])

    def _review(self) -> None:
        """A review is valid only after reservation and preparation of the exact draft."""
        self._check_scope()
        if self.data['Stage'] != 'begun' or self.data['Draft excluded'] != self.target:
            raise Blocked('Prepare the restoration draft before reviewing it')
        self.review_calls += 1
        if self.variant != 'preview_no_effect':
            self.data[PREVIEW_ROLE] = 'confirmed'
            self.review_scope = self._binding()

    def _save(self) -> None:
        """Reject the old route before an effect; a vanished preview cannot authorize Save."""
        if self.review_required:
            if self.variant == 'preview_invalidated':
                self.review_scope = None
            if self.data[PREVIEW_ROLE] != 'confirmed' or self.review_scope != self._binding():
                self.save_attempts += 1
                self.review_rejections += 1
                raise Blocked('Restoration preview is required before Save')
        super()._save()

    def oracle(self, status: str) -> dict:
        """Include evidence that the new gate was used and that unrelated actions were retained."""
        result = super().oracle(status)
        result.update(review_calls=self.review_calls, review_rejections=self.review_rejections,
                      restoration=self.case['target'] is False, revision=self.revision)
        return result
