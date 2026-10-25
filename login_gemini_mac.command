#!/bin/zsh
# Official Google client owns the browser login and credential storage.
set -e
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
unset GEMINI_API_KEY GOOGLE_API_KEY GOOGLE_GENAI_USE_VERTEXAI GOOGLE_APPLICATION_CREDENTIALS
if ! command -v agy >/dev/null 2>&1; then
  print 'Install Google Antigravity CLI from https://antigravity.google/docs/cli/install/'
  read 'reply?Press Enter to close.'
  exit 1
fi
login_dir=$(mktemp -d "${TMPDIR:-/tmp/}research-council-login.XXXXXX")
cd "$login_dir"
exec agy
