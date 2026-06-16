"""Builds dist/pipeline_lambda.zip — the AWS Lambda deployment package.

Vendors Linux-platform wheels (so the compiled psycopg wheel matches Lambda's
runtime, not the host's), copies the runtime source packages, and zips them.
Run on any OS:

    python infra/build_lambda.py

Excludes dev/test-only deps (pytest, fastapi, uvicorn, pyodbc): the scheduled
batch Lambda needs none of them.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "lambda"
DIST = ROOT / "dist"
ZIP_PATH = DIST / "pipeline_lambda.zip"

# Source packages/modules the handler imports at runtime.
SOURCE_ITEMS = ["lambda_app", "extract", "load", "transform", "pipeline.py"]

# Runtime deps only. Upper bounds keep the build reproducible across major releases.
RUNTIME_DEPS = [
    "requests>=2.31,<3",
    "pydantic>=2.5,<3",
    "psycopg[binary]>=3.1,<4",
    "python-dotenv>=1.0,<2",
]
PLATFORM = "manylinux2014_x86_64"
PY_VERSION = "312"  # pip --python-version format: no dot (e.g. "313" for 3.13)


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
        if not src.exists():
            raise FileNotFoundError(f"SOURCE_ITEMS entry not found: {src}")
        dest = BUILD / item
        if src.is_dir():
            shutil.copytree(
                src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
        else:
            shutil.copy2(src, dest)


def make_zip():
    # Write to a temp file then rename atomically, so a mid-write failure never
    # leaves a truncated zip behind.
    fd, tmp = tempfile.mkstemp(dir=DIST, suffix=".zip")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in BUILD.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(BUILD))
        tmp_path.replace(ZIP_PATH)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def main():
    clean()
    vendor_deps()
    copy_sources()
    make_zip()
    size_kb = ZIP_PATH.stat().st_size / 1024
    print(f"built {ZIP_PATH} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
