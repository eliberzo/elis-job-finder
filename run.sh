#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
cd "$project_dir/src"
if [ -x ../.venv/bin/python ]; then
  exec ../.venv/bin/python -m jobfinder "$@"
fi
exec python3 -m jobfinder "$@"
