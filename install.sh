#!/bin/sh
# simplelogin-cli installer.
#
#   curl -fsSL https://raw.githubusercontent.com/pyxl-dev/simplelogin-cli/main/install.sh | sh
#   ./install.sh               # from a clone: installs that clone
#   ./install.sh --uninstall
#
# Puts the code in ~/.local/share/simplelogin-cli (or uses this clone) and
# links the CLI into ~/.local/bin. Re-run it to update. Nothing outside your
# home folder is touched.
set -eu

REPO="${SIMPLELOGIN_CLI_REPO:-https://github.com/pyxl-dev/simplelogin-cli.git}"
DEST="${SIMPLELOGIN_CLI_HOME:-$HOME/.local/share/simplelogin-cli}"
BIN="$HOME/.local/bin"

if [ -t 1 ]; then B=$(printf '\033[1m'); G=$(printf '\033[32m'); Y=$(printf '\033[33m'); R=$(printf '\033[31m'); N=$(printf '\033[0m'); else B= G= Y= R= N=; fi
ok()   { printf '%s✓%s %s\n' "$G" "$N" "$1"; }
warn() { printf '%s!%s %s\n' "$Y" "$N" "$1"; }
die()  { printf '%s✗%s %s\n' "$R" "$N" "$1" >&2; exit 1; }

if [ "${1:-}" = "--uninstall" ]; then
  if [ -L "$BIN/simplelogin" ]; then rm -f "$BIN/simplelogin"; ok "removed $BIN/simplelogin"; else warn "$BIN/simplelogin is not a link made by this installer: left alone"; fi
  if [ -d "$DEST/.git" ]; then rm -rf "$DEST"; ok "removed $DEST"; fi
  echo "Left in place: ~/Library/Application Support/simplelogin-cli (config) and the Keychain item (service simplelogin-cli.api)."
  echo "To remove the API key:  security delete-generic-password -s simplelogin-cli.api"
  exit 0
fi

printf '%ssimplelogin-cli%s installer\n\n' "$B" "$N"
[ "$(uname -s)" = "Darwin" ] || die "macOS only (the API key is stored in the macOS Keychain)."

# 1. Code: this clone, or a managed one in ~/.local/share.
HERE=$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)
if [ -n "$HERE" ] && [ -f "$HERE/simplelogin.py" ] && [ -d "$HERE/tests" ]; then
  DEST="$HERE"
  ok "using this clone: $DEST"
elif [ -d "$DEST/.git" ]; then
  git -C "$DEST" pull --ff-only -q || die "could not update $DEST (local changes?)"
  ok "updated $DEST"
else
  command -v git >/dev/null || die "git is missing: run  xcode-select --install"
  mkdir -p "$(dirname "$DEST")"
  git clone -q --depth 1 "$REPO" "$DEST" || die "could not download $REPO"
  ok "downloaded to $DEST"
fi

# 2. Requirements.
command -v python3 >/dev/null || die "python3 is missing: run  xcode-select --install"
if python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then ok "python3 $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])') found"
else die "Python 3.9 or newer is needed."; fi
command -v curl >/dev/null && ok "curl found" || die "curl is missing."

# 3. CLI on the PATH.
mkdir -p "$BIN"
chmod +x "$DEST/simplelogin.py"
ln -sf "$DEST/simplelogin.py" "$BIN/simplelogin"
ok "linked $BIN/simplelogin"
case ":$PATH:" in *":$BIN:"*) ;; *) warn "$BIN is not on your PATH: add  export PATH=\"\$HOME/.local/bin:\$PATH\"  to ~/.zshrc";; esac

if [ -f "$HOME/Library/Application Support/simplelogin-cli/config.json" ]; then ok "already configured"
else echo "  Next: create an API key in SimpleLogin (Settings, API Keys), then run  simplelogin configure"; fi

printf '\n%sDone.%s Try:  simplelogin whoami\n' "$B" "$N"
