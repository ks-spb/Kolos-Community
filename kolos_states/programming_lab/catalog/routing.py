"""Learn request-to-program associations in the existing Kolos graph."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from math import inf, nextafter
import re

from ...core import StateEngine
from ..calculator.intent import COMMAND_WORDS, VOCABULARY, Clarification, recognize as calculator_intent
from ..reconcile.intent import FILLER as CSV_WORDS, TERMS, recognize as reconcile_intent
from ..repair.policy import _activation, _remember
from .corpus import Request
from .spec import Clarify, KINDS, Spec, normalized, parse, unsupported

_WORDS = re.compile(r'[^\W_]+')
_STOP = frozenset('и с в на по из только мне можно для как это который что где когда которой '
                  'чтобы нужно нужны задаче сделай помоги можешь пожалуйста данной локальной '
                  'проверки этой хочу пример сделай программу скрипт практики запустить файла'.split())
_KEYWORDS = (
    ('калькулятор', 'арифметическ'), ('свер', 'сравн', 'расхожд', 'отличия', 'между'),
    ('суммир', 'суммар', 'сложи', 'итоги', 'сумму'), ('итог', 'группиров', 'суммарн', 'группы', 'после'),
    ('числ', 'список', 'числов', 'оставь', 'отбери'), ('числ', 'сколько', 'посчит', 'подсчит', 'счетчик'),
    ('csv', 'строк', 'запис', 'отфильтр', 'отсей', 'отбор'), ('сортир', 'порядок', 'упорядоч', 'расставь'),
    ('сколько строк', 'число строк', 'количество строк', 'число записей', 'частот'),
    ('одинаков', 'дубликат', 'копии', 'уникальн', 'первое вхожд'),
)
_LEGACY = (
    ('calculator', calculator_intent, COMMAND_WORDS | frozenset(word for group in VOCABULARY.values() for word in group),
     (frozenset(VOCABULARY['calculator']),)),
    ('reconcile', reconcile_intent, CSV_WORDS | frozenset(word for group in TERMS.values() for word in group),
     (frozenset(TERMS['compare']), frozenset(TERMS['csv']))),
)


@dataclass(frozen=True)
class Policy:
    """Vocabulary and calibrated thresholds paired with a frozen graph snapshot."""

    lexicon: tuple[str, ...] = ()
    floor: float = 1.1
    margin: float = 0.1


@dataclass(frozen=True)
class Decision:
    """Capture family selection separately from successful parameter extraction."""

    kind: str | None = None
    spec: Spec | None = None
    question: str | None = None


def features(request: str) -> frozenset[str]:
    """Use word stems and adjacent pairs, masking numeric values only during routing."""
    words = ['#' if word.isdecimal() else word[:5] for word in _WORDS.findall(normalized(request))
             if word not in _STOP]
    return frozenset([*words, *(f'{left} {right}' for left, right in zip(words, words[1:]))])


def choose_lexicon(first_hundred: Iterable[Request]) -> tuple[str, ...]:
    """Reserve capacity for every family using only the first balanced training prefix."""
    counts: dict[str, Counter] = defaultdict(Counter)
    for row in first_hundred:
        for token in features(row.text):
            counts[token][row.expected.kind] += 1

    def relevance(token: str, kind: str) -> float:
        votes = counts[token]
        return votes[kind] ** 2 / sum(votes.values())

    chosen: dict[str, None] = {}
    for kind in KINDS:
        candidates = sorted((t for t, votes in counts.items() if votes[kind] >= 2),
                            key=lambda t: (-relevance(t, kind), t))
        chosen.update(dict.fromkeys(candidates[:4]))
    remaining = sorted(counts, key=lambda t: (-max(relevance(t, kind) for kind in KINDS), t))
    return tuple(dict.fromkeys((*chosen, *remaining)))[:48]


class Trainer:
    """Keep counters off-graph and write only the bounded persistent associations."""

    def __init__(self, engine: StateEngine, lexicon: tuple[str, ...]) -> None:
        self.engine = engine
        self.lexicon = frozenset(lexicon)
        self.counts: dict[str, Counter] = defaultdict(Counter)
        self.total = 0

    def learn(self, lessons: Iterable[Request]) -> None:
        """Append one disjoint interval of lessons and synchronize graph weights."""
        for row in lessons:
            if row.expected is None or parse(row.expected.kind, row.text) != row.expected:
                raise ValueError(f'Некорректный учебный пример {row.id}.')
            for token in features(row.text) & self.lexicon:
                self.counts[token][row.expected.kind] += 1
            self.total += 1
        for token, votes in sorted(self.counts.items()):
            total = sum(votes.values())
            for kind in KINDS:
                passed = votes[kind]
                _remember(self.engine, _key(token, kind), passed, total - passed, exact=True)


def _key(token: str, kind: str) -> str:
    """Address one catalog association without modifying older skill namespaces."""
    return f'catalog/route/{token}/{kind}'


class Router:
    """Use frozen weights with a fallback to the original two lexical skills."""

    def __init__(self, engine: StateEngine, policy: Policy) -> None:
        self.engine, self.policy = engine, policy
        self.lexicon = frozenset(policy.lexicon)
        self.weights = {(token, kind): _activation(engine, _key(token, kind))
                        for token in policy.lexicon for kind in KINDS}
        self._ranks: dict[str, tuple[str, float, float]] = {}
        self._legacy: dict[str, str | None] = {}

    def ranks(self, text: str) -> tuple[str, float, float]:
        """Compute the average native score and lead over the next choice."""
        if text not in self._ranks:
            words = features(text) & self.lexicon
            scale = max(1, len(words))
            votes = sorted(((sum(self.weights[t, k] for t in sorted(words)) / scale, k) for k in KINDS),
                           reverse=True)
            first, second = votes[:2]
            self._ranks[text] = first[1], first[0], first[0] - second[0]
        return self._ranks[text]

    def legacy(self, text: str) -> str | None:
        """Keep the old exact vocabulary available even at the zero-lesson checkpoint."""
        if text not in self._legacy:
            words = frozenset(_WORDS.findall(text))
            for kind, check, allowed, required in _LEGACY:
                if not words <= allowed or not all(words & group for group in required):
                    continue
                try:
                    check(text, self.engine)
                except Clarification:
                    continue
                self._legacy[text] = kind
                break
            else:
                self._legacy[text] = None
        return self._legacy[text]

    def pick(self, text: str, policy: Policy | None = None) -> str | None:
        """Apply learned evidence and the calibrated confidence thresholds."""
        limits = policy or self.policy
        kind, first, lead = self.ranks(text)
        if first >= limits.floor and lead >= limits.margin:
            return kind
        return self.legacy(text)


def keywords(text: str) -> str | None:
    """Choose a family by transparent keyword voting, with no learned graph."""
    votes = sorted(((sum(word in text for word in words), kind)
                    for kind, words in zip(KINDS, _KEYWORDS, strict=True)), reverse=True)
    first, second = votes[:2]
    return first[1] if first[0] > second[0] else None


def decide(request: str, pick: Callable[[str], str | None]) -> Decision:
    """Share scope checking and parameter extraction across all selection strategies."""
    text = normalized(request)
    if unsupported(text):
        return Decision(question='Эта операция выходит за рамки каталога. Укажите нужное действие из списка.')
    kind = pick(text)
    if kind is None:
        hint = keywords(text)
        if hint is not None:
            try:
                parse(hint, text)
            except Clarify as exc:
                return Decision(question=str(exc))
        return Decision(question='Уточните тип программы, например калькулятор, сверка CSV или фильтрация.')
    try:
        return Decision(kind, parse(kind, text))
    except Clarify as exc:
        return Decision(kind=kind, question=str(exc))


def calibrate(router: Router, rows: tuple[Request, ...]) -> tuple[Policy, dict]:
    """Examine every change of decision observable on the development prompts."""
    cases = _calibration_cases(router, rows)
    floors = _cutoffs(score for score, _, _, _ in cases)
    margins = _cutoffs(lead for _, lead, _, _ in cases)
    best: tuple | None = None
    for floor in floors:
        for margin in margins:
            counts = [0, 0, 0, 0]
            for score, lead, learned, fallback in cases:
                counts[learned if score >= floor and lead >= margin else fallback] += 1
            _, correct, wrong, false = counts
            # Prefer covering supported requests once mistaken control deliveries are excluded.
            quality = (-false, correct, -wrong, -floor, -margin)
            if best is None or quality > best[0]:
                best = (quality, Policy(router.policy.lexicon, floor, margin),
                        dict(correct=correct, wrong=wrong, false_accepts=false))
    return best[1], best[2]


def _cutoffs(values: Iterable[float]) -> list[float]:
    """Include a boundary just above each observed positive score or lead."""
    return sorted({0.01, 1.1, *(nextafter(v, inf) for v in values if v >= 0.01)})


def _calibration_cases(router: Router, rows: tuple[Request, ...]) -> list[tuple[float, float, int, int]]:
    """Precompute exactly what the shared parser would publish under either choice."""
    cases = []
    for row in rows:
        label, score, lead = router.ranks(normalized(row.text))
        learned = decide(row.text, lambda _: label).spec
        fallback = decide(row.text, router.legacy).spec

        def category(spec: Spec | None) -> int:
            if spec is None:
                return 0
            if row.expected is None:
                return 3
            return 1 if spec == row.expected else 2

        cases.append((score, lead, category(learned), category(fallback)))
    return cases
