# Run Crosscheck with Docker

Docker packages the application and its Python dependencies. GLM models still run on Nebius, so you need an API key and internet access. No GPU or model downloads are required on your computer.

## Start

Install and start [Docker Desktop](https://docs.docker.com/desktop/), using Linux containers. On Linux, Docker Engine with the Compose plugin is also suitable.

```shell
git clone https://github.com/sameersin/crosscheck-crossword-agent.git
cd crosscheck-crossword-agent
```

On Windows PowerShell:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

On macOS/Linux:

```bash
[ -f .env ] || cp .env.example .env
# Open .env in your text editor.
```

Set `NEBIUS_API_KEY=your_key_here`, save, then run:

```shell
docker compose up --build
```

Open **http://127.0.0.1:8000**. The first build downloads the Python base image and locked dependencies; later builds reuse Docker's cache. The local image is named `crosscheck-crossword-agent:local`.

This setup builds the image from the checked-in Dockerfile. It does not require a prebuilt image from Docker Hub or GitHub Container Registry. See the [user guide](USER_GUIDE.md) for solving and evaluating puzzles.

## Existing app on port 8000

If the Python version of Crosscheck is already running, stop it or add this line to `.env`:

```dotenv
CROSSCHECK_PORT=8001
```

Run the same Compose command and open **http://127.0.0.1:8001**. The container still listens on port 8000 internally. The host port is bound only to `127.0.0.1`.

## Stop, restart and update

- Foreground mode: press Ctrl+C to stop.
- Background mode: `docker compose up --build -d`.
- Read logs: `docker compose logs -f crosscheck`.
- Stop and remove the container: `docker compose down`.
- After pulling code updates: `docker compose up --build -d`.

The named `crosscheck-history` volume preserves run history and approved keys when the container is recreated. It is separate from a native Python installation's `artifacts/private/` folder. Do not use `docker compose down --volumes` unless you intend to delete the Docker history.

## What is included

- A non-root Python application with locked runtime dependencies.
- The source, local browser assets, authored samples, and saved development cases.
- A health check that reads `/health`; it does not solve puzzles or call a model.
- A writable history volume; credentials are supplied only when the container starts.

`.env`, local databases, Git history, the separate comparison project, tests and development screenshots are excluded from the build context. This is the same single-user local application; Docker does not add authentication or make it suitable for public multi-user hosting.

No automated test suite runs during image building or startup.

## Troubleshooting

If Docker cannot connect to its daemon, start Docker Desktop and wait for its engine to be ready. If the port is occupied, use `CROSSCHECK_PORT` above. If the key changes, recreate the container with `docker compose up -d --force-recreate`. Keep `.env` out of Git and do not paste resolved container configuration containing credentials into bug reports.
