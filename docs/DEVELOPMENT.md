# Developer guide

## Setup and conventions

Use the [setup guide](SETUP.md), then install development dependencies only if you need them:

```shell
uv sync --frozen --extra dev
```

Python uses a `src/` layout, typed Pydantic boundary models and Ruff formatting. Browser code uses native ES modules and local CSS; there is no npm build or frontend runtime dependency. `.editorconfig` defines whitespace conventions.

## Where to make changes

| Concern | Location |
|---|---|
| Puzzle/result schemas | `models.py` |
| Numbering, crossings and hard rules | `domain.py` |
| Candidate search | `search.py` |
| Agent policy, repair and budgets | `agent.py` |
| Model transport and proposals | `providers/` |
| Image geometry and exact arithmetic | `vision.py`, `arithmetic.py` |
| Correctness scoring and stored history | `evaluation.py`, `evaluation_store.py` |
| HTTP composition and routes | `web/application.py`, `web/routes/` |
| Upload/body validation | `web/uploads.py`, `web/middleware.py` |
| Shared browser state/helpers | `static/js/state.js`, `static/js/shared.js` |
| Workspace, drawing and input | `static/js/workspace.js`, `puzzle-view.js`, `puzzle-import.js` |
| Key review, scores and history | `static/js/evaluation.js` |
| Browser entry and styles | `static/app.js`, `static/css/` |

Keep the domain solver independent of FastAPI. Providers propose candidates; code enforces hard constraints. Evaluation reads separate keys and must never feed them into solving. Original run snapshots are immutable; key changes create reference versions.

`api.py` retains the existing `app`/`create_app` entry points and helper imports. New HTTP functionality belongs in `web/`. Each app instance owns its jobs, extraction limit and history dependencies.

## Optional checks — run only when you choose

No automated tests were run during the organization refactor. Historical results do not validate the refactored runtime. You can run offline checks locally:

```shell
uv run --frozen --extra dev ruff check src tests scripts
uv run --frozen --extra dev ruff format --check src tests scripts
uv run --frozen --extra dev pytest -q
```

Offline tests use controlled providers; they do not need a real API key or model calls. Node is optional for parse-only JavaScript checks, for example `node --check src/crossword_agent/static/app.js`.

GitHub's workflow is **manual-only**, with no push or pull-request triggers. Choose **Actions → Manual offline checks → Run workflow** if you want GitHub to run it. It checks Python 3.11 and 3.12.

For a paid live benchmark, explicitly run:

```shell
uv run --frozen crossword evaluate --split test --output-dir artifacts/private/my-evaluation
```

This consumes API quota. The separate output directory preserves checked-in historical reports. Review [methodology](EVALUATION.md) before presenting aggregate results.

## Packaging and local operation

```shell
uv build --wheel
uv run --frozen python scripts/package_submission.py
```

The ZIP appears in `artifacts/submission/`. Packaging uses an explicit project-directory allowlist and excludes credentials and private runtime data. The repository checkout is the supported runtime distribution: sample datasets live outside the Python wheel.

The [Docker setup](DOCKER.md) includes those datasets and runtime assets in one image. Regenerate its hashed, runtime-only lock after intentional dependency updates with `uv export --frozen --no-dev --no-emit-project -o requirements-runtime.lock`. Compose builds do not run tests.

Keep `.env`, SQLite history, user uploads and unrelated local projects out of Git. The default server is a single local process; do not expose it publicly or start multiple workers without adding user isolation, authentication and durable job infrastructure. See [architecture](ARCHITECTURE.md).
