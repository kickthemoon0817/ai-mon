#!/bin/bash
set -e
cd "$(dirname "$0")"
uv sync
uv run uvicorn app:app --port 8550 --reload
