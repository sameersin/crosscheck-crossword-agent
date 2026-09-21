# Setup and troubleshooting

For an installation that only requires Docker and your API key, use [Docker setup](DOCKER.md). The instructions below are for running Python directly.

## Requirements

- Python 3.11+ and Git.
- Recommended: [uv](https://docs.astral.sh/uv/getting-started/installation/) for the locked environment.
- A Nebius API key with access to the configured text and vision models.
- Internet access for dependency installation and model requests. The dashboard itself has no CDN dependencies.

Clone the repository and run all commands from its root. Use the [README quick start](../README.md) for the recommended uv path. `uv sync --frozen` installs the locked runtime dependencies; it does not run tests.

## Install without uv

On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock
.venv\Scripts\python.exe -m pip install --no-deps -e .
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
# Set NEBIUS_API_KEY, save, then run:
.venv\Scripts\python.exe -m crossword_agent.cli serve
```

On macOS/Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
[ -f .env ] || cp .env.example .env
# Set NEBIUS_API_KEY in .env, save, then run:
.venv/bin/python -m crossword_agent.cli serve
```

The pip lock also includes development tools; installing them does not execute them. Editable installation keeps the package connected to this checkout and its fixture data. Run from the checkout; the wheel alone is not a complete distribution of the root-level sample/evaluation datasets.

## Configure models

The supplied `.env.example` contains:

```dotenv
NEBIUS_API_KEY=
NEBIUS_BASE_URL=https://api.tokenfactory.us-north1.nebius.com/v1/
NEBIUS_MODEL=zai-org/GLM-5.3
NEBIUS_VISION_MODEL=zai-org/GLM-5.3-Flash
MODEL_TIMEOUT_SECONDS=180
MODEL_MAX_TOKENS=10000
```

Put your key only in `.env` or the process environment. Environment variables override `.env`. Restart after changing settings. Workspace → Solver limits displays the selected models.

The two model settings are deliberate: the [official GLM-5.3 documentation](https://docs.z.ai/guides/llm/glm-5.3) specifies text-only input, while the [GLM-5.3-Flash model card](https://huggingface.co/zai-org/GLM-5.3-Flash) documents image input. Both IDs are available in the configured Nebius account. Flash transcribes images; GLM-5.3 receives the resulting text and proposes crossword answers. Keeping settings separate also allows either stage to change independently.

Optional token prices are documented in `.env.example`. Leave them unset if unknown; an unknown cost is displayed as unknown rather than zero. Model calls use your Nebius quota. Reviewing/approving a JSON or manually edited answer key makes no model call; reading an image does.

## Start, stop and change the port

```shell
uv run --frozen crossword serve
uv run --frozen crossword serve --port 8001
```

Use the corresponding address, such as `http://127.0.0.1:8001`. Keep one server process per local history database. Press Ctrl+C to stop; stop any active solve first when possible. The dashboard is a locally served application, not a file to open directly from disk.

SQLite history is created automatically at `artifacts/private/evaluations.sqlite3`. Completed snapshots and approved keys persist across restarts. In-flight jobs do not resume. Back up that file with the server stopped if you need to preserve your history. It is excluded from Git and submission packages.

## Troubleshooting

| Symptom | Action |
|---|---|
| `uv` not found | Install uv using its official instructions, reopen the terminal, or use the pip steps above |
| Python version error | Install Python 3.11+; confirm `python --version` / `python3 --version` |
| Model not configured | Check `NEBIUS_API_KEY` in the repository-root `.env`, then restart |
| Provider rejects a request | Check the key, available quota, endpoint and access to both configured model IDs |
| Port already in use | Stop your existing server or use `--port 8001` |
| Image extraction is wrong | Include the full grid and clues, use a clear upright image, and correct the preview; OCR is not guaranteed |
| Cannot approve an answer key | Fill every open cell, preserve givens/blocks, and check that the key belongs to the selected puzzle |
| Clipboard access is denied | Use Ctrl+V, the JSON text field, or Browse files |
| Page still shows old controls after updating | Restart the server and hard-refresh the browser (Ctrl+Shift+R on Windows) |

Uploads support PNG/JPEG/WebP, up to 10 MB and 16 million pixels by default. Images are normalized before being sent to Nebius. The application does not retain uploaded image bytes in run history. Avoid uploading sensitive content you do not intend to send to the model provider.
