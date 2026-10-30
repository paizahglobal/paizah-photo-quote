#!/bin/bash
# The reading worker: runs on this Mac because Meta Model API refuses Railway's servers.
cd "$(dirname "$0")"
export MODEL_API_KEY="$(tr -d '\n ' < .meta_key)" BRAND=prezr
exec .venv/bin/python -u src/worker.py
