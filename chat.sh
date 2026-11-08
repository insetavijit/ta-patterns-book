#!/usr/bin/env bash
# ==============================================================================
# chat.sh — Unified Antigravity Agent Session Launcher & Manager
# ------------------------------------------------------------------------------
# 1. Tmux Gatekeeper: Ensures execution is inside a dedicated tmux session.
# 2. Runtime Detection: Detects Python project and auto-activates .venv.
# 3. Interactive Gatekeeper: Prompts to Resume Active Chat or Start New Chat.
# 4. CLI Argument Bypass: Direct flags (new, cont, plan, etc.) skip menu.
# 5. Shell Longevity: Keeps tmux pane alive in activated shell upon agent exit.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_NAME="$(basename "$SCRIPT_DIR")"

# Project-specific configuration (customize per repository)
SESSION_NAME="${CHAT_SESSION_NAME:-tapatterns-chat}"
CURRENT_CONVERSATION_ID="45b92444-03c8-40df-98b9-4eafabec5ba2"

# Optional .active-chat file override (git-ignored)
ACTIVE_CHAT_FILE="$SCRIPT_DIR/.active-chat"
if [ -f "$ACTIVE_CHAT_FILE" ]; then
    SAVED_ID="$(head -n 1 "$ACTIVE_CHAT_FILE" | tr -d '[:space:]')"
    if [ -n "$SAVED_ID" ]; then
        CURRENT_CONVERSATION_ID="$SAVED_ID"
    fi
fi

# Detect virtual environment (.venv in script directory or parent directory)
VENV_ACTIVATE=""
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    VENV_ACTIVATE="$SCRIPT_DIR/.venv/bin/activate"
elif [ -f "$SCRIPT_DIR/../../.venv/bin/activate" ]; then
    VENV_ACTIVATE="$SCRIPT_DIR/../../.venv/bin/activate"
fi

run_chat_loop() {
    # 1. Python runtime activation
    if [ -n "$VENV_ACTIVATE" ]; then
        # shellcheck disable=SC1090
        source "$VENV_ACTIVATE"
        VENV_PYTHON="$("$VENV_ACTIVATE/../python" --version 2>/dev/null || echo "Python")"
        echo -e "\033[0;32m✓ Python environment active: \033[1m$VENV_PYTHON\033[0m ($VENV_ACTIVATE)"
    elif [ -f "$SCRIPT_DIR/pyproject.toml" ] || [ -f "$SCRIPT_DIR/requirements.txt" ]; then
        echo -e "\033[0;33mℹ Python project detected, but .venv not found. Running in system environment.\033[0m"
    fi

    # 2. Argument Bypass / Interactive Selection
    local SELECTED_MODE="resume"
    local TARGET_CONV="$CURRENT_CONVERSATION_ID"

    if [ $# -gt 0 ]; then
        local ARG_NORM="$(echo "$1" | tr '[:upper:]' '[:lower:]')"
        case "$ARG_NORM" in
            1|resume|r)
                SELECTED_MODE="resume"
                shift
                ;;
            2|new|fresh|n)
                SELECTED_MODE="new"
                TARGET_CONV=""
                shift
                ;;
            3|cont|continue|last|c)
                SELECTED_MODE="continue"
                TARGET_CONV=""
                shift
                ;;
            4|plan|p)
                SELECTED_MODE="plan"
                TARGET_CONV=""
                shift
                ;;
            shell|sh)
                echo "Dropping into interactive shell with active environment..."
                exec "${SHELL:-/bin/bash}"
                ;;
            *)
                # Pass all raw arguments directly to agy
                SELECTED_MODE="passthrough"
                ;;
        esac
    elif [ -t 0 ]; then
        echo ""
        echo "=================================================================="
        echo -e " \033[1mAntigravity AI Assistant: ${SESSION_NAME}\033[0m"
        echo "=================================================================="
        if [ -n "$CURRENT_CONVERSATION_ID" ]; then
            echo -e " Active Conversation : \033[0;36m${CURRENT_CONVERSATION_ID}\033[0m"
        else
            echo -e " Active Conversation : \033[0;33m[None configured]\033[0m"
        fi
        echo " Project Location    : ${SCRIPT_DIR}"
        echo ""
        echo " Select an option:"
        if [ -n "$CURRENT_CONVERSATION_ID" ]; then
            echo "   1) Resume active conversation [DEFAULT - press Enter]"
            echo "   2) Start a fresh new conversation"
            echo "   3) Continue most recent conversation (--continue)"
            echo "   4) Start new conversation in Planning Mode (--mode plan)"
            echo "   5) Drop to interactive shell"
            echo ""
            read -r -p " Enter choice [1/2/3/4/5] (default: 1): " choice || true
        else
            echo "   1) Start a fresh new conversation [DEFAULT - press Enter]"
            echo "   2) Continue most recent conversation (--continue)"
            echo "   3) Start new conversation in Planning Mode (--mode plan)"
            echo "   4) Drop to interactive shell"
            echo ""
            read -r -p " Enter choice [1/2/3/4] (default: 1): " choice || true
        fi
        echo ""

        local CHOICE_NORM="$(echo "${choice:-}" | tr '[:upper:]' '[:lower:]')"
        if [ -n "$CURRENT_CONVERSATION_ID" ]; then
            case "$CHOICE_NORM" in
                2|new|fresh|n)
                    SELECTED_MODE="new"
                    TARGET_CONV=""
                    ;;
                3|cont|continue|c)
                    SELECTED_MODE="continue"
                    TARGET_CONV=""
                    ;;
                4|plan|p)
                    SELECTED_MODE="plan"
                    TARGET_CONV=""
                    ;;
                5|shell|sh)
                    echo "Dropping into shell..."
                    exec "${SHELL:-/bin/bash}"
                    ;;
                *)
                    SELECTED_MODE="resume"
                    ;;
            esac
        else
            case "$CHOICE_NORM" in
                2|cont|continue|c)
                    SELECTED_MODE="continue"
                    TARGET_CONV=""
                    ;;
                3|plan|p)
                    SELECTED_MODE="plan"
                    TARGET_CONV=""
                    ;;
                4|shell|sh)
                    echo "Dropping into shell..."
                    exec "${SHELL:-/bin/bash}"
                    ;;
                *)
                    SELECTED_MODE="new"
                    TARGET_CONV=""
                    ;;
            esac
        fi
    fi

    # 3. Execution Dispatch
    case "$SELECTED_MODE" in
        resume)
            if [ -n "$TARGET_CONV" ]; then
                echo "Resuming conversation: $TARGET_CONV..."
                agy --conversation "$TARGET_CONV" --dangerously-skip-permissions "$@" || true
            else
                echo "No conversation ID configured. Starting fresh conversation..."
                agy --dangerously-skip-permissions "$@" || true
            fi
            ;;
        new)
            echo "Starting fresh conversation..."
            agy --dangerously-skip-permissions "$@" || true
            ;;
        continue)
            echo "Continuing most recent conversation (--continue)..."
            agy --continue --dangerously-skip-permissions "$@" || true
            ;;
        plan)
            echo "Starting new conversation in Planning Mode (--mode plan)..."
            agy --mode plan --dangerously-skip-permissions "$@" || true
            ;;
        passthrough)
            agy --dangerously-skip-permissions "$@" || true
            ;;
    esac

    # 4. Keep tmux window alive in active shell upon exit
    echo ""
    echo -e "\033[0;34m[Session ended. Dropping to interactive shell in ${REPO_NAME}...]\033[0m"
    exec "${SHELL:-/bin/bash}"
}

# ------------------------------------------------------------------------------
# Tmux Gatekeeper Loop
# ------------------------------------------------------------------------------
# If already inside the target tmux session, execute chat loop directly
if [ -n "${TMUX:-}" ]; then
    CURRENT_TMUX_SESSION="$(tmux display-message -p "#S" 2>/dev/null || true)"
    if [ "$CURRENT_TMUX_SESSION" = "$SESSION_NAME" ]; then
        run_chat_loop "$@"
    fi
fi

# If tmux is not installed, fallback gracefully to current shell
if ! command -v tmux >/dev/null 2>&1; then
    echo "Notice: tmux is not installed. Running agent directly in current shell..."
    run_chat_loop "$@"
fi

# If running without an interactive terminal (e.g. pipe, automated tool), run directly
if [ ! -t 0 ] && [ -z "${TMUX:-}" ]; then
    run_chat_loop "$@"
fi

# Ensure target tmux session exists
if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    tmux new-session -d -s "$SESSION_NAME" -c "$SCRIPT_DIR" "$SCRIPT_DIR/chat.sh" "$@"
fi

# Attach or switch to session
if [ -n "${TMUX:-}" ]; then
    exec tmux switch-client -t "$SESSION_NAME"
else
    exec tmux attach-session -t "$SESSION_NAME"
fi
