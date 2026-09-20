"""Bounded ranked search: model suggestions in, consistent assignments out.

The search first attempts a complete assignment of every nonempty candidate
pool. Only after proving that impossible does it explore omitting entries. An
incumbent partial fill is retained even when propagation detects impossibility
or a budget interrupts the search. Scores rank suggestions; they are not
calibrated probabilities or evidence of reference-answer correctness.
"""

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Event

from .domain import normalize_answer, parse_entries
from .models import Candidate, Puzzle


@dataclass(slots=True)
class SearchResult:
    assignments: dict[str, str]
    complete: bool
    nodes: int
    exhausted: bool
    blocked_entries: list[str]
    score: float


@dataclass(frozen=True, slots=True)
class _Choice:
    answer: str
    score: float


def solve_constraints(
    puzzle: Puzzle,
    candidates: dict[str, list[Candidate]],
    *,
    max_nodes: int = 100000,
    deadline: float | None = None,
    cancel_event: Event | None = None,
) -> SearchResult:
    """Return a full consistent fill or the best consistent partial found.

    Partial fills are compared by number of assigned entries, then summed model
    scores. A successful complete-fill search stops at its first ranked solution;
    this function does not promise global score optimality. ``exhausted`` means a
    time/node limit or cancellation prevented further search, not that candidate
    pools ran out. ``deadline`` uses ``time.monotonic()`` and is absolute.
    """
    if max_nodes < 0:
        raise ValueError("max_nodes must be nonnegative.")
    entries = parse_entries(puzzle)
    entry_order = {entry.id: i for i, entry in enumerate(entries)}
    domains: dict[str, list[_Choice]] = {}
    owners: dict[tuple[int, int], list[tuple[str, int]]] = defaultdict(list)
    for entry in entries:
        unique: dict[str, float] = {}
        for candidate in candidates.get(entry.id, []):
            answer = normalize_answer(candidate.answer)
            if len(answer) != entry.length or not all("A" <= char <= "Z" for char in answer):
                continue
            if any(
                puzzle.grid[row][col] not in (".", char)
                for (row, col), char in zip(entry.cells, answer, strict=True)
            ):
                continue
            unique[answer] = max(unique.get(answer, -1.0), candidate.score)
        if unique:
            domains[entry.id] = sorted(
                (_Choice(answer, score) for answer, score in unique.items()),
                key=lambda choice: (-choice.score, choice.answer),
            )
        for position, cell in enumerate(entry.cells):
            owners[cell].append((entry.id, position))

    # Each standard across/down pair can share at most one cell.
    crossings: dict[str, dict[str, tuple[int, int]]] = {entry.id: {} for entry in entries}
    for cell_owners in owners.values():
        if len(cell_owners) == 2:
            (left, li), (right, ri) = cell_owners
            crossings[left][right] = (li, ri)
            crossings[right][left] = (ri, li)

    nodes = 0
    exhausted = False
    best: dict[str, str] = {}
    best_score = 0.0

    def time_available() -> bool:
        nonlocal exhausted
        if cancel_event is not None and cancel_event.is_set():
            exhausted = True
            return False
        if deadline is not None and time.monotonic() >= deadline:
            exhausted = True
            return False
        return True

    def visit() -> bool:
        nonlocal nodes, exhausted
        if not time_available():
            return False
        if nodes >= max_nodes:
            exhausted = True
            return False
        nodes += 1
        return True

    def remember(assigned: dict[str, str], score: float) -> None:
        nonlocal best, best_score
        if (len(assigned), score) > (len(best), best_score):
            best, best_score = assigned.copy(), score

    def choose(current: dict[str, list[_Choice]]) -> str:
        return min(
            current,
            key=lambda key: (
                len(current[key]),
                -sum(neighbor in current for neighbor in crossings[key]),
                entry_order[key],
            ),
        )

    def ranked(key: str, current: dict[str, list[_Choice]]) -> list[_Choice]:
        # At equal score, prefer the answer that leaves more crossing choices.
        def support(choice: _Choice) -> int:
            return sum(
                sum(choice.answer[i] == other.answer[j] for other in current[neighbor])
                for neighbor, (i, j) in crossings[key].items()
                if neighbor in current
            )

        return sorted(
            current[key], key=lambda choice: (-choice.score, -support(choice), choice.answer)
        )

    def restrict(
        current: dict[str, list[_Choice]], key: str, choice: _Choice, *, allow_missing: bool
    ) -> dict[str, list[_Choice]] | None:
        following = {other: values for other, values in current.items() if other != key}
        for neighbor, (i, j) in crossings[key].items():
            if neighbor not in following:
                continue
            compatible = [
                value for value in following[neighbor] if value.answer[j] == choice.answer[i]
            ]
            if compatible:
                following[neighbor] = compatible
            elif allow_missing:
                del following[neighbor]
            else:
                return None
        return following

    def propagate(current: dict[str, list[_Choice]]) -> bool:
        """AC-3 pruning is sound only when every remaining entry is required."""
        queue = deque(
            (left, right) for left in current for right in crossings[left] if right in current
        )
        while queue:
            if not time_available():
                return False
            left, right = queue.popleft()
            li, ri = crossings[left][right]
            supported_letters = {value.answer[ri] for value in current[right]}
            revised = [value for value in current[left] if value.answer[li] in supported_letters]
            if len(revised) == len(current[left]):
                continue
            if not revised:
                return False
            current[left] = revised
            queue.extend(
                (neighbor, left)
                for neighbor in crossings[left]
                if neighbor != right and neighbor in current
            )
        return True

    # Keep a useful incumbent before AC-3 is allowed to wipe out a whole domain.
    greedy_domains = domains.copy()
    greedy: dict[str, str] = {}
    greedy_score = 0.0
    while greedy_domains and not exhausted:
        if not visit():
            break
        key = choose(greedy_domains)
        choice = ranked(key, greedy_domains)[0]
        greedy[key] = choice.answer
        greedy_score += choice.score
        remember(greedy, greedy_score)
        greedy_domains = restrict(greedy_domains, key, choice, allow_missing=True) or {}

    def complete_search(
        current: dict[str, list[_Choice]], assigned: dict[str, str], score: float
    ) -> bool:
        if not current:
            remember(assigned, score)
            return True
        key = choose(current)
        for choice in ranked(key, current):
            if not visit():
                return False
            following_assignments = {**assigned, key: choice.answer}
            following_score = score + choice.score
            remember(following_assignments, following_score)
            following = restrict(current, key, choice, allow_missing=False)
            if following is not None and propagate(following):
                if complete_search(following, following_assignments, following_score):
                    return True
            if exhausted:
                return False
        return False

    def partial_search(
        current: dict[str, list[_Choice]], assigned: dict[str, str], score: float
    ) -> None:
        if not current or exhausted:
            return
        upper_count = len(assigned) + len(current)
        if upper_count < len(best):
            return
        if (
            upper_count == len(best)
            and score + sum(max(v.score for v in values) for values in current.values())
            <= best_score
        ):
            return
        key = choose(current)
        for choice in ranked(key, current):
            if not visit():
                return
            following_assignments = {**assigned, key: choice.answer}
            following_score = score + choice.score
            remember(following_assignments, following_score)
            following = restrict(current, key, choice, allow_missing=True)
            partial_search(following or {}, following_assignments, following_score)
            if exhausted:
                return
        # Skipping is explored only in the fallback, after trying actual answers.
        if visit():
            partial_search(
                {other: values for other, values in current.items() if other != key},
                assigned,
                score,
            )

    if len(best) < len(domains) and not exhausted:
        required = domains.copy()
        found = propagate(required) and complete_search(required, {}, 0.0)
        if not found and not exhausted:
            partial_search(domains.copy(), {}, 0.0)

    blocked = [entry.id for entry in entries if entry.id not in best]
    return SearchResult(
        assignments=best,
        complete=not blocked,
        nodes=nodes,
        exhausted=exhausted,
        blocked_entries=blocked,
        score=best_score,
    )
