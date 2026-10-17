#!/usr/bin/env bash
# Run a command with the API keys read from Bitwarden. Each key is the password of the item named
# after its environment variable (e.g. TYPESAFE_API_KEY). The keys live only in this process's
# environment; nothing is written to disk.
#
# Unlock once in your own terminal first:  (umask 077; bw unlock --raw > ~/.bw_session)
# Lock when done:                          bw lock
#
# Example:  scripts/with-keys.sh uv run python scripts/run_benchmark.py --model jev-1.13 --max-cost 0.10
set -euo pipefail

if [[ -z "${BW_SESSION:-}" ]]; then
  BW_SESSION="$(cat ~/.bw_session 2>/dev/null || true)"
  export BW_SESSION
fi
if [[ "$(bw status | python3 -c 'import json, sys; print(json.load(sys.stdin)["status"])')" != "unlocked" ]]; then
  echo "Bitwarden is locked. Run in your terminal: (umask 077; bw unlock --raw > ~/.bw_session)" >&2
  exit 1
fi

for name in ANTHROPIC_API_KEY GEMINI_API_KEY DEEPSEEK_API_KEY TYPESAFE_API_KEY; do
  value="$(bw get password "$name")"
  export "$name=$value"
done
unset value

exec "$@"
