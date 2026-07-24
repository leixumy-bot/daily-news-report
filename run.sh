#!/bin/bash
# Convenience wrapper for crontab or manual run
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export ANTHROPIC_AUTH_TOKEN="$(
  /Users/xulei/venv/bin/python3 -c "
import json
print(json.load(open('$HOME/.claude/settings.json'))['env']['ANTHROPIC_AUTH_TOKEN'])
"
)"
exec /Users/xulei/venv/bin/python3 daily_report.py "$@"
