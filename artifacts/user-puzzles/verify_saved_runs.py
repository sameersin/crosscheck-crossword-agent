"""Local verification harness; consumes saved results and never calls a model."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from crossword_agent.domain import parse_entries, render_grid, validate_assignments
from crossword_agent.evaluation import evaluate_result
from crossword_agent.models import Puzzle, SolveResult

ROOT = Path(__file__).resolve().parent
MODEL = "zai-org/GLM-5.3-Flash"
PUBLISHER_URL = "https://www.word-game-world.com/support-files/cocoa-crossword.pdf"


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def normalized_clue(text):
    text = text.translate(str.maketrans({"−": "-", "–": "-", "—": "-", "’": "'"}))
    text = re.sub(r"_+", " ", text)
    return " ".join(text.strip().rstrip(".").split()).casefold()


def verify(ident, result_filename):
    extraction = read(f"{ident}-extraction.json")
    reference = read(f"{ident}-reference.json")
    puzzle = Puzzle.model_validate(read(f"{ident}.puzzle.json"))
    result = SolveResult.model_validate(read(result_filename))
    source = Puzzle.model_validate(reference["puzzle"])
    expected = (
        reference["reference"]["assignments"] if ident == "math" else reference["assignments"]
    )
    reference_grid = render_grid(source, expected)
    source_entries, actual_entries = parse_entries(source), parse_entries(puzzle)
    source_geometry = {entry.id: (entry.row, entry.col, entry.length) for entry in source_entries}
    actual_geometry = {entry.id: (entry.row, entry.col, entry.length) for entry in actual_entries}
    source_clues = {entry.id: entry.clue for entry in source_entries}
    differences = [
        {"entry_id": entry.id, "reference": source_clues.get(entry.id), "extracted": entry.clue}
        for entry in actual_entries
        if normalized_clue(entry.clue) != normalized_clue(source_clues.get(entry.id, ""))
    ]
    arithmetic = []
    if ident == "math":
        for entry in source_entries:
            match = re.fullmatch(r"\s*(\d+)\s*([+\-−–])\s*(\d+)\s*", entry.clue)
            if not match:
                raise ValueError(f"Unrecognized arithmetic reference: {entry.clue}")
            left, operator, right = match.groups()
            answer = str(int(left) + int(right) if operator == "+" else int(left) - int(right))
            arithmetic.append(
                {
                    "entry_id": entry.id,
                    "printed_expression": entry.clue,
                    "computed": answer,
                    "reference_matches": answer == expected[entry.id],
                    "result_matches": answer == result.assignments.get(entry.id),
                }
            )
    metrics = evaluate_result(puzzle, reference_grid, result)
    comparison = [
        {
            "entry_id": entry.id,
            "expected": expected[entry.id],
            "actual": result.assignments.get(entry.id),
            "matches": expected[entry.id] == result.assignments.get(entry.id),
        }
        for entry in source_entries
    ]
    if ident == "pets":
        provenance = {
            "kind": "independent_manual_visual_transcription",
            "official_key_checked": False,
            "basis": "Answers manually derived from visible clues and verified against all crossings; no official publisher answer key was used.",
        }
    elif ident == "math":
        provenance = {
            "kind": "independent_arithmetic_reference",
            "official_key_checked": False,
            "basis": "All 48 printed arithmetic expressions independently recomputed with integer addition/subtraction and checked against crossings.",
        }
    else:
        provenance = {
            "kind": "manual_reference_with_official_publisher_confirmation",
            "official_key_checked": True,
            "publisher_key_url": PUBLISHER_URL,
            "publisher_key_page": 2,
            "confirmed_entry": "6D",
            "publisher_answer": "NESQUIK",
            "basis": "Manual reference was prepared independently before solver output. Publisher PDF answer-grid text confirms the intended 6D answer NESQUIK, resolving the only first-run answer discrepancy.",
        }
    warning_review = []
    if ident == "cocoa":
        warning_review = [
            "The recorded warning that clue numbers are not printed is contradicted by the visible numbered worksheet. It is model-generated warning text, not a verified fact.",
            "The extracted cell mask and every entry number/length match the independent visual reference despite the recorded approximate-geometry warning.",
        ]
    if ident == "math":
        warning_review = [
            "Grid and all 48 clue expressions match the independent reference after equivalent Unicode minus/dash normalization; model uncertainty is preserved separately."
        ]
    extraction_usage = extraction["usage"]
    report = {
        "id": ident,
        "source_name": extraction["source_name"],
        "result_file": result_filename,
        "verified_at": datetime.now(UTC).isoformat(),
        "scope": "Verification of this saved image-extraction and solving run, not a held-out benchmark or guarantee for other photos.",
        "reference": provenance,
        "extraction": {
            "model": MODEL,
            "model_provenance": "Actual provider invocation identified by the run owner; extraction artifact records token usage but omits model ID.",
            "elapsed_seconds": extraction["seconds"],
            "usage": extraction_usage,
            "grid_matches_reference": puzzle.grid == source.grid,
            "entry_geometry_matches_reference": source_geometry == actual_geometry,
            "clue_semantics_match_after_typography_normalization": not differences,
            "clue_text_differences": differences,
            "recorded_warnings": extraction.get("warnings", []),
            "independent_warning_review": warning_review,
        },
        "solve": {
            "model": result.model,
            "status": result.status,
            "stop_reason": result.stop_reason,
            "elapsed_seconds": result.elapsed_seconds,
            "usage": result.usage.model_dump(),
            "assigned_entries": len(result.assignments),
            "total_entries": len(source_entries),
            "constraint_violations": validate_assignments(puzzle, result.assignments),
        },
        "combined_stages": {
            "attempted_model_calls": extraction_usage["model_calls"] + result.usage.model_calls,
            "elapsed_seconds_sum": round(extraction["seconds"] + result.elapsed_seconds, 3),
            "total_tokens": extraction_usage["total_tokens"] + result.usage.total_tokens,
            "note": "Sum of separately recorded extraction and solve durations; excludes human review/dwell time. Failed attempts count when recorded. Unpriced dollar cost is unknown.",
        },
        "metrics_against_reference": metrics,
        "entries": comparison,
        "reference_keys_supplied_to_solver": False,
    }
    if arithmetic:
        report["independent_arithmetic_checks"] = arithmetic
    if ident == "cocoa":
        report["semantic_note"] = (
            "NESTLES and NESQUIK both satisfy the seven-cell length and checked E at their second position; the publisher key establishes NESQUIK as the intended answer. Crossing consistency alone cannot resolve this clue."
        )
        initial = result.initial_candidates.get("6D", [])
        report["review_evidence"] = {
            "review_events": sum(event.kind == "review" for event in result.events),
            "initial_6D_candidates": [candidate.model_dump() for candidate in initial],
            "final_6D_candidates": [
                candidate.model_dump() for candidate in result.candidates.get("6D", [])
            ],
            "final_6D_answer": result.assignments.get("6D"),
            "answer_changed_from_initial_top_candidate": bool(initial)
            and initial[0].answer != result.assignments.get("6D"),
            "causal_limit": "The latest saved run already proposed NESQUIK initially. Its independent review ran, but the trace does not show review correcting NESTLES to NESQUIK. The difference from the first run is observed run-to-run variation, not proof of review benefit.",
        }
    return report


def main():
    reports = []
    for ident in ("pets", "cocoa", "math"):
        report = verify(ident, f"{ident}.result.json")
        (ROOT / f"{ident}.verification.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        reports.append(report)
    first_run = ROOT / "cocoa.first-run.verification.json"
    if not first_run.exists():
        report = verify("cocoa", "cocoa.first-run.result.json")
        first_run.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for report in reports:
        metrics = report["metrics_against_reference"]
        print(
            report["id"],
            {
                "geometry": report["extraction"]["grid_matches_reference"],
                "clues": report["extraction"][
                    "clue_semantics_match_after_typography_normalization"
                ],
                "correct_entries": metrics["correct_entries"],
                "correct_cells": metrics["correct_cells"],
                "exact": metrics["exact_puzzle"],
                "combined": report["combined_stages"],
            },
        )


if __name__ == "__main__":
    main()
