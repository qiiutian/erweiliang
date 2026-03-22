#!/bin/zsh

set -e

PROJECT_DIR="/Users/qiutian/Desktop/codex"
PYTHON_BIN="/Users/qiutian/miniconda3/envs/venv/bin/python"
export MPLCONFIGDIR="${PROJECT_DIR}/.mplconfig"

cd "$PROJECT_DIR"
exec "$PYTHON_BIN" -m pip install -r requirements.txt "$@"
