#!/usr/bin/env bash
# ── CheetahClaws Installer ──────────────────────────────────────────────
# curl -fsSL https://raw.githubusercontent.com/SAIL-Research-Lab/cheetahclaws/main/scripts/install.sh | bash
#
# Works on: Linux, macOS, WSL2, Android (Termux)
# Requires: Python 3.10+, pip, git
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO="https://github.com/SAIL-Research-Lab/cheetahclaws.git"
INSTALL_DIR="$HOME/.cheetahclaws-src"
MIN_PYTHON="3.10"

# ── Colors ───────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
RESET='\033[0m'

info()  { echo -e "${CYAN}[info]${RESET} $*"; }
ok()    { echo -e "${GREEN}[ok]${RESET}   $*"; }
warn()  { echo -e "${YELLOW}[warn]${RESET} $*"; }
fail()  { echo -e "${RED}[fail]${RESET} $*"; exit 1; }

# ── Center helper (used for banners) ─────────────────────────────────────
center() {
    local txt="$1" w="$2"
    local len=${#txt}
    local pad_left=$(( (w - len) / 2 ))
    local pad_right=$(( w - len - pad_left ))
    printf "%${pad_left}s%s%${pad_right}s" "" "$txt" ""
}
BOX_W=42

# ── Banner ───────────────────────────────────────────────────────────────
B1=$(center "CheetahClaws Installer" $BOX_W)
B2=$(center "Fast AI Coding Assistant" $BOX_W)
echo ""
echo -e "${CYAN}  ╭──────────────────────────────────────────╮${RESET}"
echo -e "${CYAN}  │${B1}│${RESET}"
echo -e "${CYAN}  │${B2}│${RESET}"
echo -e "${CYAN}  ╰──────────────────────────────────────────╯${RESET}"
echo ""

# ── Check platform ──────────────────────────────────────────────────────
OS="$(uname -s)"
case "$OS" in
    Linux*)   PLATFORM="linux" ;;
    Darwin*)  PLATFORM="macos" ;;
    MINGW*|MSYS*|CYGWIN*)
        fail "Native Windows is not supported. Please install WSL2 and run this script inside WSL."
        ;;
    *)
        warn "Unknown platform: $OS — proceeding anyway."
        PLATFORM="linux"
        ;;
esac

# Detect Termux
if [ -n "${PREFIX:-}" ] && [[ "$PREFIX" == *com.termux* ]]; then
    PLATFORM="termux"
    info "Detected Termux (Android)"
fi

ok "Platform: $PLATFORM"

# ── Check Python ────────────────────────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    fail "Python 3.10+ is required but not found. Install it first:
  macOS:   brew install python@3.12
  Ubuntu:  sudo apt install python3.12 python3.12-venv
  Termux:  pkg install python"
fi

ok "Python: $($PYTHON --version)"

# ── Check git ───────────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    fail "git is required but not found. Install it first:
  macOS:   xcode-select --install
  Ubuntu:  sudo apt install git
  Termux:  pkg install git"
fi

ok "Git: $(git --version | head -1)"

# ── Check pip ───────────────────────────────────────────────────────────
if ! $PYTHON -m pip --version &>/dev/null; then
    warn "pip not found, installing..."
    $PYTHON -m ensurepip --default-pip 2>/dev/null || \
        fail "Cannot install pip. Install it manually: $PYTHON -m ensurepip"
fi

ok "pip: $($PYTHON -m pip --version | head -1)"

# ── Clone or update ────────────────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation..."
    cd "$INSTALL_DIR"
    git pull --quiet origin main
    ok "Updated to latest"
else
    info "Cloning CheetahClaws..."
    git clone --depth 1 "$REPO" "$INSTALL_DIR"
    ok "Cloned to $INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# ── Install with pip ───────────────────────────────────────────────────
info "Installing CheetahClaws..."

VENV_DIR="$HOME/.cheetahclaws-venv"
USE_VENV=false

# Detect PEP 668 externally-managed Python (Homebrew Python 3.12+, Debian 12+, etc.)
# Check for the EXTERNALLY-MANAGED marker file that pip reads
STDLIB_PATH=$($PYTHON -c "import sysconfig; print(sysconfig.get_path('stdlib'))" 2>/dev/null || echo "")
if [ -n "$STDLIB_PATH" ] && [ -f "$STDLIB_PATH/EXTERNALLY-MANAGED" ]; then
    USE_VENV=true
    info "Detected externally-managed Python (PEP 668) — using virtual environment."
fi

# macOS: always use venv (Homebrew, system Python, or any managed env)
if [ "$PLATFORM" = "macos" ] && [ "$USE_VENV" = false ]; then
    # Check if pip would refuse (belt-and-suspenders)
    if ! $PYTHON -m pip install --quiet --dry-run pip 2>/dev/null; then
        USE_VENV=true
        info "macOS pip restricted — using virtual environment."
    fi
fi

if [ "$USE_VENV" = true ]; then
    # Create or reuse a dedicated venv
    if [ ! -d "$VENV_DIR" ]; then
        info "Creating virtual environment at $VENV_DIR ..."
        $PYTHON -m venv "$VENV_DIR" || fail "Failed to create venv. Install python3-venv: sudo apt install python3-venv"
        ok "Virtual environment created"
    else
        info "Using existing virtual environment at $VENV_DIR"
    fi
    # Activate venv for this script
    source "$VENV_DIR/bin/activate"
    PYTHON="python3"  # use venv python
    PIP_BIN="$VENV_DIR/bin"

    # Install inside venv (no --break-system-packages needed)
    $PYTHON -m pip install --quiet . 2>/dev/null || \
        $PYTHON -m pip install . || fail "pip install failed"

elif [ "$PLATFORM" = "termux" ]; then
    # Termux: skip optional deps that may fail on Android
    $PYTHON -m pip install --quiet --break-system-packages . 2>/dev/null || \
        $PYTHON -m pip install --quiet . 2>/dev/null || \
        $PYTHON -m pip install . || fail "pip install failed"
    PIP_BIN="$($PYTHON -m site --user-base 2>/dev/null)/bin"
else
    # Standard install (Linux with system Python, conda, etc.)
    $PYTHON -m pip install --quiet . 2>/dev/null || \
        $PYTHON -m pip install . || fail "pip install failed"
    PIP_BIN="$($PYTHON -m site --user-base 2>/dev/null)/bin"
fi

ok "CheetahClaws installed"

# ── Verify installation & expose on PATH for future shells ────────────
# Determine where pip/venv placed the entry point.
if [ "$USE_VENV" = true ]; then
    BIN_DIR="$VENV_DIR/bin"
else
    BIN_DIR="$PIP_BIN"
fi

# Decide which directory to put on PATH (EXPOSE_DIR).
#   - venv install: symlink ONLY the cheetahclaws entry point into
#     ~/.local/bin. Putting the whole venv/bin on PATH would shadow the
#     user's python/pip in every new shell — pipx avoids this the same way.
#   - user install: PIP_BIN itself is the directory to expose.
# NOTE: we deliberately do NOT short-circuit on `command -v cheetahclaws`.
# When we installed into a venv that this script just `source`d, the binary
# is on PATH for THIS shell only — not for the new shells the user opens.
# Trusting it here was the bug that left .zshrc untouched on macOS.
EXPOSE_DIR=""
if [ -f "$BIN_DIR/cheetahclaws" ]; then
    if [ "$USE_VENV" = true ]; then
        LOCAL_BIN="$HOME/.local/bin"
        mkdir -p "$LOCAL_BIN"
        ln -sf "$BIN_DIR/cheetahclaws" "$LOCAL_BIN/cheetahclaws"
        EXPOSE_DIR="$LOCAL_BIN"
        ok "Linked cheetahclaws into $LOCAL_BIN"
    else
        EXPOSE_DIR="$BIN_DIR"
    fi
elif command -v cheetahclaws &>/dev/null; then
    # pip put it somewhere already on PATH — expose that directory.
    EXPOSE_DIR="$(dirname "$(command -v cheetahclaws)")"
else
    warn "cheetahclaws binary not found at $BIN_DIR — you may need to add pip's bin directory to PATH manually."
fi

if [ -n "$EXPOSE_DIR" ]; then
    # Pick the rc file the user's login shell actually reads, creating it if
    # missing (macOS ships no default .zshrc, so a fresh zsh user has none).
    SHELL_RC=""
    IS_FISH=false
    CURRENT_SH="$(basename "${SHELL:-bash}")"
    if [ "$CURRENT_SH" = "zsh" ]; then
        SHELL_RC="$HOME/.zshrc"
        touch "$SHELL_RC"
    elif [ "$CURRENT_SH" = "fish" ]; then
        SHELL_RC="$HOME/.config/fish/config.fish"
        IS_FISH=true
        mkdir -p "$(dirname "$SHELL_RC")"
        touch "$SHELL_RC"
    elif [ "$CURRENT_SH" = "bash" ]; then
        # macOS bash loads .bash_profile for login shells; Linux loads .bashrc.
        if [ "$PLATFORM" = "macos" ]; then
            SHELL_RC="$HOME/.bash_profile"
        else
            SHELL_RC="$HOME/.bashrc"
        fi
        touch "$SHELL_RC"
    elif [ -f "$HOME/.bashrc" ]; then
        SHELL_RC="$HOME/.bashrc"
    elif [ -f "$HOME/.bash_profile" ]; then
        SHELL_RC="$HOME/.bash_profile"
    fi

    if [ -n "$SHELL_RC" ]; then
        if ! grep -q "$EXPOSE_DIR" "$SHELL_RC" 2>/dev/null; then
            if [ "$IS_FISH" = true ]; then
                {
                    echo ""
                    echo "# CheetahClaws"
                    echo "set -gx PATH \"$EXPOSE_DIR\" \$PATH"
                } >> "$SHELL_RC"
            else
                {
                    echo ""
                    echo "# CheetahClaws"
                    echo "export PATH=\"$EXPOSE_DIR:\$PATH\""
                } >> "$SHELL_RC"
            fi
            ok "Added $EXPOSE_DIR to PATH in $SHELL_RC"
        else
            ok "PATH already configured in $SHELL_RC"
        fi
    fi
    export PATH="$EXPOSE_DIR:$PATH"
fi

# ── Print version ──────────────────────────────────────────────────────
VERSION=$(cheetahclaws --version 2>/dev/null || echo "installed")
L1=$(center "Installation complete!" $BOX_W)
L2=$(center "$VERSION" $BOX_W)
echo ""
echo -e "${GREEN}  ╭──────────────────────────────────────────╮${RESET}"
echo -e "${GREEN}  │${L1}│${RESET}"
echo -e "${GREEN}  │${L2}│${RESET}"
echo -e "${GREEN}  ╰──────────────────────────────────────────╯${RESET}"
echo ""
# Detect the user's shell for the reload hint
CURRENT_SHELL="$(basename "${SHELL:-bash}")"
if [ "$CURRENT_SHELL" = "zsh" ]; then
    RELOAD_CMD="source ~/.zshrc"
elif [ "$CURRENT_SHELL" = "fish" ]; then
    RELOAD_CMD="source ~/.config/fish/config.fish"
elif [ "$CURRENT_SHELL" = "bash" ] && [ "$PLATFORM" = "macos" ]; then
    RELOAD_CMD="source ~/.bash_profile"
else
    RELOAD_CMD="source ~/.bashrc"
fi

echo -e "  ${DIM}Reload your shell, then start:${RESET}"
echo ""
echo -e "    ${RELOAD_CMD}"
echo -e "    cheetahclaws        ${DIM}# start the REPL${RESET}"
echo ""
echo -e "  ${DIM}First run will guide you through setup (API key, model).${RESET}"
echo -e "  ${DIM}Or run: cheetahclaws --setup${RESET}"
echo ""
