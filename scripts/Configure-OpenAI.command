#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")/.."
umask 077
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python -m godseye.provider_setup --port 0
else
  exec python3 -m godseye.provider_setup --port 0
fi
