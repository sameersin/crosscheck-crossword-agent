"""Reproducible command-line entry points for running, solving and evaluating."""

import argparse
import json
from pathlib import Path

from crossword_agent.config import PROJECT_ROOT, Settings
from crossword_agent.models import Puzzle, SolveOptions


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="crossword", description="Crosscheck crossword-solving agent"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Start the local browser app")
    serve.add_argument("--port", type=int, default=8000)
    solve = commands.add_parser("solve", help="Solve a puzzle JSON file")
    solve.add_argument("puzzle", type=Path)
    solve.add_argument("--output", type=Path)
    solve.add_argument("--seconds", type=float, default=180)
    solve.add_argument("--rounds", type=int, default=4)
    evaluate = commands.add_parser(
        "evaluate", help="Run the paired evaluation against separate answer keys"
    )
    evaluate.add_argument("--split", choices=["dev", "test", "all"], default="test")
    evaluate.add_argument(
        "--output-dir", type=Path, default=PROJECT_ROOT / "artifacts" / "evaluation"
    )
    evaluate.add_argument("--seconds", type=float, default=180)
    evaluate.add_argument("--rounds", type=int, default=4)
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn

        uvicorn.run("crossword_agent.api:app", host="127.0.0.1", port=args.port, log_level="info")
        return
    from crossword_agent.agent import CrosswordAgent
    from crossword_agent.providers.nebius import NebiusProvider

    settings = Settings()
    if not settings.provider_ready:
        parser.error("Set NEBIUS_API_KEY in .env first (see .env.example).")
    provider = NebiusProvider(settings)
    try:
        options = SolveOptions(max_seconds=args.seconds, max_rounds=args.rounds)
        if args.command == "solve":
            puzzle = Puzzle.model_validate_json(args.puzzle.read_text(encoding="utf-8"))
            result = CrosswordAgent(provider, settings.nebius_model).solve(puzzle, options)
            payload = result.model_dump_json(indent=2)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(payload, encoding="utf-8")
                print(
                    f"{result.status}: {len(result.assignments)} entries, {result.usage.model_calls} calls. Saved {args.output}"
                )
            else:
                print(payload)
        else:
            from crossword_agent.evaluation import run_evaluation

            report = run_evaluation(
                provider,
                settings.nebius_model,
                data_dir=PROJECT_ROOT / "data",
                output_dir=args.output_dir,
                split=args.split,
                options=options,
            )
            print(json.dumps(report.get("summary", report), indent=2))
    finally:
        provider.close()


if __name__ == "__main__":
    main()
