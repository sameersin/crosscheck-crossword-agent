import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from crossword_agent.agent import CrosswordAgent
from crossword_agent.evaluation_store import EvaluationStore, puzzle_fingerprint
from crossword_agent.models import Clues, Puzzle


@pytest.fixture
def solved_numeric():
    puzzle = Puzzle(
        id="numeric-test",
        title="Small arithmetic",
        answer_type="digits",
        grid=["1.", ".."],
        clues=Clues(across={"1": "6 + 6", "3": "30 + 4"}, down={"1": "10 + 3", "2": "20 + 4"}),
    )
    result = CrosswordAgent(object(), model="test-model").solve(puzzle)
    assert result.grid == ["12", "34"]
    return puzzle, result


def test_reference_versions_survive_restart_without_changing_original(tmp_path, solved_numeric):
    puzzle, result = solved_numeric
    path = tmp_path / "history.sqlite3"
    store = EvaluationStore(path)
    store.record_run("run", puzzle, result)
    original = store.get_run("run")["original_result"]
    first = store.evaluate("run", ["19", "94"], source="human_entered", approved=True)
    second = store.evaluate("run", ["12", "34"], source="publisher_key", approved=True)
    assert first["metrics"]["cell_accuracy"] == 0.5
    assert first["metrics"]["completion"] == 1
    assert first["metrics"]["answer_accuracy"] == 0
    assert second["metrics"]["exact_puzzle"] is True
    assert second["reference_version"] == 2
    reopened = EvaluationStore(path).get_run("run")
    assert reopened["original_result"] == original == result.model_dump()
    assert reopened["puzzle"] == puzzle.model_dump()
    assert len(reopened["evaluations"]) == 2
    assert reopened["latest_evaluation"]["source"] == "publisher_key"
    assert reopened["latest_evaluation"]["approval_kind"] == "user_approved"


def test_partial_result_blanks_remain_wrong_with_full_denominators(tmp_path, solved_numeric):
    puzzle, result = solved_numeric
    partial = result.model_copy(
        update={
            "grid": ["12", ".."],
            "assignments": {"1A": "12"},
            "filled_cells": 2,
            "status": "partial",
        }
    )
    store = EvaluationStore(tmp_path / "history.sqlite3")
    store.record_run("partial", puzzle, partial)
    metrics = store.evaluate("partial", ["12", "34"], source="human_entered", approved=True)[
        "metrics"
    ]
    assert metrics["correct_cells"] == 2 and metrics["total_cells"] == 4
    assert metrics["correct_entries"] == 1 and metrics["total_entries"] == 4
    assert metrics["cell_accuracy"] == metrics["completion"] == 0.5
    assert metrics["unknown_cell_accuracy"] == pytest.approx(1 / 3)
    assert not metrics["exact_puzzle"]


@pytest.mark.parametrize(
    "grid", [["12", "3."], ["12"], ["12", "345"], ["12", "3#"], ["92", "34"], ["AB", "CD"]]
)
def test_invalid_key_never_creates_grade(tmp_path, solved_numeric, grid):
    puzzle, result = solved_numeric
    store = EvaluationStore(tmp_path / "history.sqlite3")
    store.record_run("run", puzzle, result)
    with pytest.raises(ValueError):
        store.evaluate("run", grid, source="human_entered", approved=True)
    assert store.get_run("run")["evaluations"] == []


def test_run_snapshot_is_insert_only_and_cannot_bind_other_puzzle(tmp_path, solved_numeric):
    puzzle, result = solved_numeric
    store = EvaluationStore(tmp_path / "history.sqlite3")
    store.record_run("run", puzzle, result)
    store.record_run("run", puzzle, result)
    with pytest.raises(ValueError, match="immutable"):
        store.record_run("run", puzzle, result.model_copy(update={"grid": ["12", "39"]}))
    with pytest.raises(ValueError, match="does not belong"):
        store.record_run("other", puzzle, result.model_copy(update={"puzzle_id": "wrong"}))
    with pytest.raises(ValueError, match="fingerprint"):
        store.evaluate(
            "run",
            ["12", "34"],
            source="uploaded_json",
            approved=True,
            expected_fingerprint="0" * 64,
        )
    assert store.list_runs()["total_count"] == 1
    assert store.get_run("run")["puzzle_fingerprint"] == puzzle_fingerprint(puzzle)


def test_concurrent_approval_retry_is_idempotent(tmp_path, solved_numeric):
    puzzle, result = solved_numeric
    store = EvaluationStore(tmp_path / "history.sqlite3")
    store.record_run("run", puzzle, result)

    def approve(_):
        return store.evaluate("run", ["12", "34"], source="uploaded_json", approved=True)

    with ThreadPoolExecutor(max_workers=4) as executor:
        grades = list(executor.map(approve, range(8)))
    assert {grade["reference_version"] for grade in grades} == {1}
    assert len({grade["evaluation_id"] for grade in grades}) == 1
    assert len(store.get_run("run")["evaluations"]) == 1


def test_saved_import_is_idempotent_and_never_invents_human_approval(tmp_path, solved_numeric):
    puzzle, result = solved_numeric
    directory = tmp_path / "saved"
    directory.mkdir()
    (directory / "manifest.json").write_text(
        json.dumps({"puzzles": [{"id": "numeric"}, {"id": "../private"}]})
    )
    (directory / "numeric.puzzle.json").write_text(puzzle.model_dump_json())
    (directory / "numeric.result.json").write_text(result.model_dump_json())
    (directory / "numeric.verification.json").write_text('{"reviewed":true,"exact_puzzle":true}')
    store = EvaluationStore(tmp_path / "history.sqlite3")
    store.import_saved_runs(directory)
    store.import_saved_runs(directory)
    history = store.list_runs()
    assert history["total_count"] == 1
    assert history["runs"][0]["latest_evaluation"] is None
    assert history["runs"][0]["source"] == "saved_import"
    assert history["runs"][0]["timestamp_basis"] == "imported_at"


def test_no_result_failure_stays_visible_without_fabricated_metrics(tmp_path, solved_numeric):
    puzzle, _ = solved_numeric
    store = EvaluationStore(tmp_path / "history.sqlite3")
    store.record_run("failed", puzzle, None, error="Safe error", context={"model": "test-model"})
    history = store.list_runs()["runs"]
    assert len(history) == 1 and history[0]["status"] == "failed"
    assert history[0]["gradeable"] is False and history[0]["filled_cells"] is None
    assert history[0]["usage"] is None and history[0]["model"] == "test-model"
    with pytest.raises(ValueError, match="no original result"):
        store.evaluate("failed", ["12", "34"], source="human_entered", approved=True)
