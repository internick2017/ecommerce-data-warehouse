"""Builds dist/pipeline_lambda.zip — the AWS Lambda deployment package.

Vendors Linux-platform wheels (so the compiled psycopg wheel matches Lambda's
runtime, not the host's), copies the runtime source packages, and zips them.
Run on any OS:

    python infra/build_lambda.py

Excludes dev/test-only deps (pytest, fastapi, uvicorn, pyodbc): the scheduled
batch Lambda needs none of them.
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "lambda"
DIST = ROOT / "dist"
ZIP_PATH = DIST / "pipeline_lambda.zip"

# Source packages/modules the handler imports at runtime.
SOURCE_ITEMS = ["lambda_app", "extract", "load", "transform", "pipeline.py"]

# Runtime deps only.
RUNTIME_DEPS = [
    "requests>=2.31",
    "pydantic>=2.5",
    "psycopg[binary]>=3.1",
    "python-dotenv>=1.0",
]
PLATFORM = "manylinux2014_x86_64"
PY_VERSION = "312"


def clean():
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)
    DIST.mkdir(exist_ok=True)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()


def vendor_deps():
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--platform", PLATFORM,
            "--python-version", PY_VERSION,
            "--implementation", "cp",
            "--only-binary=:all:",
            "--target", str(BUILD),
            *RUNTIME_DEPS,
        ],
        check=True,
    )


def copy_sources():
    for item in SOURCE_ITEMS:
        src = ROOT / item
        dest = BUILD / item
        if src.is_dir():
            shutil.copytree(
                src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
        else:
            shutil.copy2(src, dest)


def make_zip():
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in BUILD.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(BUILD))


def main():
    clean()
    vendor_deps()
    copy_sources()
    make_zip()
    size_kb = ZIP_PATH.stat().st_size // 1024
    print(f"built {ZIP_PATH} ({size_kb} KB)")


if __name__ == "__main__":
    main()
