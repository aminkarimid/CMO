#!/usr/bin/env zsh

# Launch the X3P Content & Marketing app via Streamlit.
# Double-click this file in Finder to start the app in a new Terminal window.

# Ensure pyenv (and its shims) are in the PATH when running non-interactively.
export PATH="$HOME/.pyenv/bin:$HOME/.pyenv/shims:$PATH"

if command -v pyenv >/dev/null 2>&1; then
  eval "$(pyenv init -)"
  if command -v pyenv-virtualenv-init >/dev/null 2>&1; then
    eval "$(pyenv virtualenv-init -)"
  fi
fi

# Load user shell config if available (API keys, aliases, etc.).
if [ -f "$HOME/.zshrc" ]; then
  source "$HOME/.zshrc"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$ROOT_DIR" || exit 1

python -m streamlit run app.py
