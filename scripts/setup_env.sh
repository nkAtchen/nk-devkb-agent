#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python}"
INSTALL_MARKITDOWN=0

for arg in "$@"; do
  case "$arg" in
    --with-markitdown)
      INSTALL_MARKITDOWN=1
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Usage: scripts/setup_env.sh [--with-markitdown]" >&2
      exit 2
      ;;
  esac
done

cd "$ROOT_DIR"

echo "==> Checking Python"
"$PYTHON_BIN" - <<'PY'
import sys

required = (3, 11)
if sys.version_info < required:
    raise SystemExit(
        f"Python {required[0]}.{required[1]}+ is required, got {sys.version.split()[0]}"
    )
print(f"Python {sys.version.split()[0]}")
PY

echo "==> Creating virtual environment at ${VENV_DIR}"
"$PYTHON_BIN" -m venv "$VENV_DIR"

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

echo "==> Upgrading pip"
python -m pip install --upgrade pip

echo "==> Installing project in editable mode"
python -m pip install -e .

echo "==> Installing test dependency"
python -m pip install pytest

if [[ "$INSTALL_MARKITDOWN" == "1" ]]; then
  echo "==> Installing optional PDF/DOCX converter: markitdown"
  python -m pip install markitdown
else
  echo "==> Skipping optional MarkItDown install"
  echo "    Re-run with: scripts/setup_env.sh --with-markitdown"
fi

echo "==> Running tests"
PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider

echo "==> Setup complete"
echo "Activate the environment with:"
echo "  source .venv/bin/activate"
echo "Try the CLI:"
echo "  kb init"
echo "  kb ingest file ./architecture.md"
echo "  kb ask \"这个系统的问答链路是什么？\""
