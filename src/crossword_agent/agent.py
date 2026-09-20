"""State-dependent propose/check/repair loop with explicit resource budgets."""

import time
from collections.abc import Callable
from threading import Event

from crossword_agent.domain import (
    Entry,
    entry_pattern,
    normalize_answer,
    parse_entries,
    render_grid,
    validate_assignments,
)
from crossword_agent.models import AgentEvent, Candidate, Puzzle, SolveOptions, SolveResult, Usage
from crossword_agent.providers.base import CandidateProvider, ProviderError
from crossword_agent.search import solve_constraints


def add_usage(total: Usage, extra: Usage) -> Usage:
    """Keep unknown prices unknown; report only costs supported by configured pricing."""
    cost = None
    if extra.estimated_cost_usd is not None and (
        total.model_calls == 0 or total.estimated_cost_usd is not None
    ):
        cost = (total.estimated_cost_usd or 0) + extra.estimated_cost_usd
    return Usage(
        model_calls=total.model_calls + extra.model_calls,
        prompt_tokens=total.prompt_tokens + extra.prompt_tokens,
        completion_tokens=total.completion_tokens + extra.completion_tokens,
        total_tokens=total.total_tokens + extra.total_tokens,
        estimated_cost_usd=cost,
    )


def merge_candidates(
    puzzle: Puzzle,
    entries: list[Entry],
    pool: dict[str, list[Candidate]],
    incoming: dict[str, list[Candidate]],
) -> tuple[int, int]:
    accepted = rejected = 0
    for entry in entries:
        current = {item.answer: item for item in pool.get(entry.id, [])}
        fixed = entry_pattern(puzzle, entry)
        for candidate in incoming.get(entry.id, []):
            word = normalize_answer(candidate.answer)
            if (
                len(word) != entry.length
                or not all("A" <= c <= "Z" for c in word)
                or any(c != "." and c != word[i] for i, c in enumerate(fixed))
            ):
                rejected += 1
                continue
            if word not in current:
                current[word] = Candidate(answer=word, score=candidate.score)
                accepted += 1
            elif candidate.score > current[word].score:
                current[word] = Candidate(answer=word, score=candidate.score)
        # Bounded across all retries. Keep the strongest candidates for each entry.
        pool[entry.id] = sorted(current.values(), key=lambda c: (-c.score, c.answer))[:100]
    return accepted, rejected


def repair_targets(
    entries: list[Entry], assignments: dict[str, str], blocked: list[str], attempts: dict[str, int]
) -> list[Entry]:
    """Revisit unresolved entries and their neighbors, allowing earlier guesses to change."""
    unresolved = {e.id for e in entries if e.id not in assignments} | set(blocked)
    affected_cells = {cell for e in entries if e.id in unresolved for cell in e.cells}
    targets = [
        e for e in entries if e.id in unresolved or any(c in affected_cells for c in e.cells)
    ]
    return sorted(
        targets,
        key=lambda e: (attempts.get(e.id, 0), e.id not in unresolved, e.number, e.direction),
    )


class CrosswordAgent:
    def __init__(self, provider: CandidateProvider, model: str = ""):
        self.provider = provider
        self.model = model

    def solve(
        self,
        puzzle: Puzzle,
        options: SolveOptions | None = None,
        on_event: Callable[[AgentEvent], None] | None = None,
        cancel_event: Event | None = None,
        *,
        initial_candidates: dict[str, list[Candidate]] | None = None,
        initial_usage: Usage | None = None,
    ) -> SolveResult:
        options = options or SolveOptions()
        entries = parse_entries(puzzle)
        started = time.monotonic()
        deadline = started + options.max_seconds
        cancelled = cancel_event or Event()
        events: list[AgentEvent] = []
        candidates: dict[str, list[Candidate]] = {}
        usage = initial_usage.model_copy(deep=True) if initial_usage else Usage()
        assignments: dict[str, str] = {}
        attempts: dict[str, int] = {}
        first_candidates: dict[str, list[Candidate]] = {}
        nodes = rounds = 0
        stop_reason = "round_budget"
        provider_failed = False
        blocked: list[str] = []
        stagnant_rounds = 0

        def emit(kind: str, message: str, **data: object) -> None:
            event = AgentEvent(
                sequence=len(events) + 1,
                kind=kind,
                message=message,
                elapsed_seconds=round(time.monotonic() - started, 3),
                data=data,
            )
            events.append(event)
            if on_event:
                on_event(event)

        def budget_reason() -> str | None:
            if cancelled.is_set():
                return "cancelled"
            if time.monotonic() >= deadline:
                return "time_budget"
            return None

        emit(
            "started",
            f"Validated {len(entries)} entries. Beginning bounded solve.",
            entry_count=len(entries),
            grid=puzzle.grid,
            model=self.model,
        )
        if initial_candidates is not None:
            merge_candidates(puzzle, entries, candidates, initial_candidates)

        for round_index in range(options.max_rounds):
            if reason := budget_reason():
                stop_reason = reason
                break
            rounds = round_index + 1
            new_count = 0
            if round_index == 0:
                targets = entries if initial_candidates is None else []
            else:
                targets = repair_targets(entries, assignments, blocked, attempts)
                emit(
                    "repair",
                    f"Revisiting {len(targets)} unresolved or neighboring entries; earlier guesses remain reversible.",
                    entry_ids=[e.id for e in targets],
                    round=rounds,
                )
            for offset in range(0, len(targets), options.batch_size):
                if reason := budget_reason():
                    stop_reason = reason
                    break
                if usage.model_calls >= options.max_calls:
                    stop_reason = "call_budget"
                    break
                batch = targets[offset : offset + options.batch_size]
                # Avoid feeding an entry's own previous answer back as a fixed pattern.
                patterns = {
                    e.id: entry_pattern(
                        puzzle, e, {k: v for k, v in assignments.items() if k != e.id}
                    )
                    for e in batch
                }
                previous = {e.id: [c.answer for c in candidates.get(e.id, [])] for e in batch}
                for entry in batch:
                    attempts[entry.id] = attempts.get(entry.id, 0) + 1
                for transport_attempt in range(2):
                    if reason := budget_reason():
                        stop_reason = reason
                        break
                    if usage.model_calls >= options.max_calls:
                        stop_reason = "call_budget"
                        break
                    emit(
                        "generating",
                        f"Requesting candidates for {', '.join(e.id for e in batch)}.",
                        entry_ids=[e.id for e in batch],
                        round=rounds,
                        call=usage.model_calls + 1,
                    )
                    try:
                        generated = self.provider.generate(
                            batch,
                            patterns=patterns,
                            previous=previous,
                            limit=options.candidates_per_clue,
                            timeout=max(0.1, deadline - time.monotonic()),
                        )
                        usage = add_usage(usage, generated.usage)
                        accepted, rejected = merge_candidates(
                            puzzle, batch, candidates, generated.candidates
                        )
                        new_count += accepted
                        emit(
                            "candidates_generated",
                            f"Accepted {accepted} new candidates; rejected {rejected} invalid fits.",
                            entry_ids=[e.id for e in batch],
                            accepted=accepted,
                            rejected=rejected,
                            model_calls=usage.model_calls,
                        )
                        break
                    except ProviderError as exc:
                        usage = add_usage(usage, exc.usage)
                        emit("provider_warning", str(exc), retryable=exc.retryable)
                        if not exc.retryable or transport_attempt == 1:
                            provider_failed = True
                            stop_reason = "provider_error"
                            break
                        delay = min(
                            0.5 * (transport_attempt + 1), max(0, deadline - time.monotonic())
                        )
                        cancelled.wait(delay)
                if provider_failed:
                    break
            if round_index == 0:
                first_candidates = {key: list(values) for key, values in candidates.items()}
            # Search with all current candidates; guessed letters are never permanently fixed.
            if (
                time.monotonic() < deadline
                and not cancelled.is_set()
                and nodes < options.max_search_nodes
            ):
                emit(
                    "searching",
                    "Checking candidate combinations against lengths, fixed letters, and crossings.",
                )
                search = solve_constraints(
                    puzzle,
                    candidates,
                    max_nodes=options.max_search_nodes - nodes,
                    deadline=deadline,
                    cancel_event=cancelled,
                )
                nodes += search.nodes
                blocked = search.blocked_entries
                if len(search.assignments) >= len(assignments):
                    assignments = search.assignments
                grid = render_grid(puzzle, assignments)
                emit(
                    "search_complete",
                    f"Placed {len(assignments)} of {len(entries)} entries consistently.",
                    grid=grid,
                    assignments=assignments,
                    nodes=nodes,
                    round=rounds,
                    filled_cells=sum(c not in ".#" for row in grid for c in row),
                    total_cells=sum(c != "#" for row in puzzle.grid for c in row),
                )
                if cancelled.is_set():
                    stop_reason = "cancelled"
                    break
                if search.complete:
                    stop_reason = "complete_consistent"
                    break
            if provider_failed or budget_reason():
                stop_reason = budget_reason() or stop_reason
                break
            if nodes >= options.max_search_nodes:
                stop_reason = "search_budget"
                break
            if usage.model_calls >= options.max_calls:
                stop_reason = "call_budget"
                break
            stagnant_rounds = stagnant_rounds + 1 if new_count == 0 and round_index > 0 else 0
            if stagnant_rounds >= 2:
                stop_reason = "no_new_candidates"
                break

        grid = render_grid(puzzle, assignments)
        violations = validate_assignments(puzzle, assignments)
        if cancelled.is_set() or stop_reason == "cancelled":
            status = "cancelled"
            stop_reason = "cancelled"
        elif len(assignments) == len(entries) and not violations:
            status = "complete_consistent"
            stop_reason = "complete_consistent"
        elif provider_failed:
            status = "provider_error"
        else:
            status = "partial"
        emit(
            "finished",
            "All entries fit. Correctness requires an independent answer key."
            if status == "complete_consistent"
            else f"Stopped with a usable partial result ({stop_reason}).",
            status=status,
            stop_reason=stop_reason,
        )
        return SolveResult(
            puzzle_id=puzzle.id,
            status=status,
            grid=grid,
            assignments=assignments,
            unresolved_entries=[e.id for e in entries if e.id not in assignments],
            constraint_violations=violations,
            filled_cells=sum(c not in ".#" for row in grid for c in row),
            total_cells=sum(c != "#" for row in puzzle.grid for c in row),
            elapsed_seconds=round(time.monotonic() - started, 3),
            rounds=rounds,
            search_nodes=nodes,
            stop_reason=stop_reason,
            usage=usage,
            candidates=candidates,
            initial_candidates=first_candidates,
            events=events,
            model=self.model,
        )
