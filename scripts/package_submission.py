"""Create a local submission ZIP from an explicit allowlist, never local secrets."""

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_DIRS = ["src", "tests", "data", "docs", "scripts", ".github"]
ALLOWED_FILES = [
    "README.md",
    "pyproject.toml",
    "uv.lock",
    "requirements.lock",
    ".gitignore",
    ".gitattributes",
    ".env.example",
]


def main():
    destination = ROOT / "artifacts/submission/crosscheck-assessment.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = [ROOT / name for name in ALLOWED_FILES if (ROOT / name).is_file()]
    for folder in ALLOWED_DIRS + [
        "artifacts/evaluation",
        "artifacts/evaluation-dev",
        "artifacts/verification",
        "artifacts/screenshots",
        "artifacts/demo",
    ]:
        files.extend(path for path in (ROOT / folder).rglob("*") if path.is_file())
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(files)):
            relative = path.relative_to(ROOT)
            if any(
                part.startswith("__pycache__")
                or part in {".pytest_cache", ".ruff_cache", "private"}
                for part in relative.parts
            ):
                continue
            if path.suffix in {".pyc", ".log"} or path.name == ".env":
                continue
            archive.write(path, Path("crosscheck-assessment") / relative)
    print(
        f"Created {destination} ({destination.stat().st_size:,} bytes). Local .env and runtime caches excluded."
    )


if __name__ == "__main__":
    main()
