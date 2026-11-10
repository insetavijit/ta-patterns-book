#!/usr/bin/env bash
# ==============================================================================
# chat.sh — Unified Antigravity Agent Session Launcher & Multi-Chat Manager
# ------------------------------------------------------------------------------
# 1. Environment & Runtime Detection:
#    - Activates local project .venv first (preventing outer venv hijacking).
#    - Detects if pyenv or active virtualenv is in use.
#    - Displays active python interpreter & tmux pane details.
# 2. Multi-Session Tmux Gatekeeper:
#    - Operates directly inside an existing tmux pane if already in tmux.
#    - Auto-allocates non-colliding sessions (e.g. repo-chat-2) if session is attached.
#    - Prevents argument loss on reconnecting to existing sessions.
# 3. Project Conversation Selector:
#    - Queries Antigravity SQLite DB (~/.gemini/antigravity-cli/conversation_summaries.db).
#    - Filters strictly by exact project workspace URI (no cross-project pollution).
#    - Displays recent conversations with formatted dates and clean titles.
# 4. CLI Argument Subcommands:
#    - Supports: list, resume, new, continue, plan, set <UUID>, shell, or raw UUID/index.
# 5. Shell Longevity:
#    - Retains terminal pane in active environment upon agent exit only inside tmux.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_NAME="$(basename "$SCRIPT_DIR")"

# Project-specific configuration (customize per repository)
CURRENT_CONVERSATION_ID="45b92444-03c8-40df-98b9-4eafabec5ba2"
BASE_SESSION_NAME="${CHAT_SESSION_NAME:-${REPO_NAME}-chat}"
ACTIVE_CHAT_FILE="$SCRIPT_DIR/.active-chat"

# ------------------------------------------------------------------------------
# Helper Functions: Runtime, Database, and Multi-Session
# ------------------------------------------------------------------------------

detect_and_activate_python() {
    # 1. Priority: Check local project .venv first (prevents parent Codespace venv hijacking)
    if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
        # shellcheck disable=SC1090
        source "$SCRIPT_DIR/.venv/bin/activate"
        local LOCAL_PY
        LOCAL_PY="$("$SCRIPT_DIR/.venv/bin/python" --version 2>/dev/null || echo "Python")"
        echo -e "\033[0;32m✓ Activated project virtualenv:\033[0m \033[1m${LOCAL_PY}\033[0m ($SCRIPT_DIR/.venv)"
        return 0
    fi

    # 2. Check if virtualenv is already active in current shell
    if [ -n "${VIRTUAL_ENV:-}" ]; then
        local PY_VER
        PY_VER="$("$VIRTUAL_ENV/bin/python" --version 2>/dev/null || python --version 2>/dev/null || echo "Python")"
        echo -e "\033[0;32m✓ Python environment active:\033[0m \033[1m${PY_VER}\033[0m (${VIRTUAL_ENV})"
        return 0
    fi

    # 3. Check if pyenv environment is active
    if command -v pyenv >/dev/null 2>&1; then
        local PYENV_VER
        PYENV_VER="$(pyenv version-name 2>/dev/null || true)"
        if [ -n "$PYENV_VER" ] && [ "$PYENV_VER" != "system" ]; then
            local PYENV_BIN
            PYENV_BIN="$(pyenv which python 2>/dev/null || echo "python")"
            echo -e "\033[0;32m✓ pyenv environment active:\033[0m \033[1m${PYENV_VER}\033[0m (${PYENV_BIN})"
            return 0
        fi
    fi

    # 4. Check parent workspace .venv fallback (e.g. for tools without local venv)
    if [ -f "$SCRIPT_DIR/../../.venv/bin/activate" ]; then
        # shellcheck disable=SC1090
        source "$SCRIPT_DIR/../../.venv/bin/activate"
        local PARENT_PY
        PARENT_PY="$("$SCRIPT_DIR/../../.venv/bin/python" --version 2>/dev/null || echo "Python")"
        echo -e "\033[0;32m✓ Activated workspace virtualenv:\033[0m \033[1m${PARENT_PY}\033[0m ($SCRIPT_DIR/../../.venv)"
        return 0
    fi

    # 5. Fallback notice
    if [ -f "$SCRIPT_DIR/pyproject.toml" ] || [ -f "$SCRIPT_DIR/requirements.txt" ]; then
        local SYS_PY
        SYS_PY="$(python3 --version 2>/dev/null || echo "Python")"
        echo -e "\033[0;33mℹ Python project detected, but no .venv found. Using system ${SYS_PY}.\033[0m"
    fi
}

detect_tmux_status() {
    if [ -n "${TMUX:-}" ]; then
        local CURR_SESS CURR_WIN CURR_PANE
        CURR_SESS="$(tmux display-message -p "#S" 2>/dev/null || echo "unknown")"
        CURR_WIN="$(tmux display-message -p "#I:#W" 2>/dev/null || echo "0")"
        CURR_PANE="$(tmux display-message -p "#P" 2>/dev/null || echo "0")"
        echo -e "\033[0;32m✓ Tmux active:\033[0m Session '\033[1m${CURR_SESS}\033[0m' (window ${CURR_WIN}, pane ${CURR_PANE})"
        return 0
    else
        echo -e "\033[0;36mℹ Tmux status:\033[0m Not inside tmux session"
        return 1
    fi
}

get_project_conversations() {
    local db_path="${HOME}/.gemini/antigravity-cli/conversation_summaries.db"
    if [ ! -f "$db_path" ]; then
        return 0
    fi
    python3 - <<EOF 2>/dev/null || true
import sqlite3, os, json

db = os.path.expanduser("$db_path")
proj = os.path.realpath("$SCRIPT_DIR")
target_uri = f"file://{proj}".rstrip("/")

if os.path.exists(db):
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1.0)
        cur = conn.cursor()
        cur.execute("""
            SELECT conversation_id, title, datetime(last_modified_time) as lmt, workspace_uris
            FROM conversation_summaries
            ORDER BY last_modified_time DESC
        """)
        count = 0
        for cid, title, lmt, uris_raw in cur.fetchall():
            try:
                uris = json.loads(uris_raw) if uris_raw else []
            except Exception:
                uris = []
            
            # Exact workspace URI matching
            if any(os.path.realpath(u.replace("file://", "")).rstrip("/") == proj for u in uris):
                t = (title or "").strip() or "(Untitled conversation)"
                t = t.replace("\n", " ").replace("|", "-")
                print(f"{cid}|{lmt or ''}|{t}")
                count += 1
                if count >= 10:
                    break
    except Exception:
        pass
EOF
}

list_active_tmux_sessions() {
    if ! command -v tmux >/dev/null 2>&1; then
        echo "  (tmux not installed)"
        return 0
    fi
    local sessions
    sessions="$(tmux list-sessions -F "  • #{session_name} (#{session_windows} win, #{session_attached} attached)" 2>/dev/null || true)"
    if [ -n "$sessions" ]; then
        echo "$sessions"
    else
        echo "  (no active tmux sessions)"
    fi
}

get_next_session_name() {
    local base="${1:-chat}"
    if ! tmux has-session -t "$base" 2>/dev/null; then
        echo "$base"
        return
    fi
    local i=2
    while tmux has-session -t "${base}-${i}" 2>/dev/null; do
        ((i++))
    done
    echo "${base}-${i}"
}

# ------------------------------------------------------------------------------
# Core Chat Loop Execution
# ------------------------------------------------------------------------------

run_chat_loop() {
    echo ""
    echo "=================================================================="
    echo -e " \033[1mAntigravity AI Assistant: ${REPO_NAME}\033[0m"
    echo "=================================================================="

    # 1. Environment & Runtime Detection
    detect_and_activate_python
    detect_tmux_status || true
    echo " Project Location    : ${SCRIPT_DIR}"

    # 2. Load recent conversations for this workspace
    local conv_ids=()
    local conv_dates=()
    local conv_titles=()

    while IFS='|' read -r cid cdate ctitle; do
        [ -n "$cid" ] || continue
        conv_ids+=("$cid")
        conv_dates+=("$cdate")
        conv_titles+=("$ctitle")
    done < <(get_project_conversations)

    # Resolve default active conversation
    local DEFAULT_CONV=""
    if [ -f "$ACTIVE_CHAT_FILE" ]; then
        local SAVED_ID
        SAVED_ID="$(head -n 1 "$ACTIVE_CHAT_FILE" 2>/dev/null | tr -d '[:space:]' || true)"
        if [ -n "$SAVED_ID" ]; then
            DEFAULT_CONV="$SAVED_ID"
        fi
    fi
    if [ -z "$DEFAULT_CONV" ] && [ -n "${CURRENT_CONVERSATION_ID:-}" ]; then
        DEFAULT_CONV="$CURRENT_CONVERSATION_ID"
    fi
    if [ -z "$DEFAULT_CONV" ] && [ ${#conv_ids[@]} -gt 0 ]; then
        DEFAULT_CONV="${conv_ids[0]}"
    fi

    # 3. Process Subcommands / Arguments or Interactive Selection
    local SELECTED_MODE="resume"
    local TARGET_CONV="$DEFAULT_CONV"

    if [ $# -gt 0 ]; then
        local ARG_NORM
        ARG_NORM="$(echo "$1" | tr '[:upper:]' '[:lower:]')"
        case "$ARG_NORM" in
            help|-h|--help)
                echo ""
                echo "Usage: ./chat.sh [OPTIONS] [COMMAND | INDEX | UUID]"
                echo ""
                echo "Options:"
                echo "  -s, --session <name>   Specify target tmux session name (default: ${BASE_SESSION_NAME})"
                echo "  --no-tmux              Run directly in terminal without tmux"
                echo "  -h, --help             Show this help guide"
                echo ""
                echo "Commands:"
                echo "  (no args)              Interactive menu to resume or start chats"
                echo "  1, 2, ...              Directly resume corresponding recent conversation"
                echo "  resume, r [ID|INDEX]   Resume latest, by list index, or by UUID"
                echo "  <UUID>                 Resume specific conversation UUID directly"
                echo "  new, n                 Start a fresh new conversation"
                echo "  continue, c            Continue most recent conversation (--continue)"
                echo "  plan, p                Start new conversation in Planning Mode (--mode plan)"
                echo "  list, l                Display active tmux sessions and recent project conversations"
                echo "  set <UUID>             Persist target UUID into .active-chat as project default"
                echo "  shell, sh              Drop into environment shell with active Python/venv"
                echo ""
                exit 0
                ;;
            list|l)
                echo ""
                echo "------------------------------------------------------------------"
                echo -e " \033[1mActive Tmux Sessions:\033[0m"
                list_active_tmux_sessions
                echo ""
                echo -e " \033[1mRecent Project Conversations (${#conv_ids[@]} found):\033[0m"
                if [ ${#conv_ids[@]} -gt 0 ]; then
                    for idx in "${!conv_ids[@]}"; do
                        local num=$((idx + 1))
                        local marker=""
                        if [ "${conv_ids[idx]}" = "$DEFAULT_CONV" ]; then
                            marker=" \033[0;32m[ACTIVE]\033[0m"
                        fi
                        local display_title="${conv_titles[idx]}"
                        if [ "${#display_title}" -gt 48 ]; then
                            display_title="${display_title:0:45}..."
                        fi
                        echo -e "   ${num}) [${conv_ids[idx]:0:8}] \033[1m${display_title}\033[0m (${conv_dates[idx]})${marker}"
                    done
                else
                    echo "   (No previous conversations found in project database)"
                fi
                echo "------------------------------------------------------------------"
                exit 0
                ;;
            set)
                shift
                if [ $# -gt 0 ]; then
                    local NEW_ID="$1"
                    echo "$NEW_ID" > "$ACTIVE_CHAT_FILE"
                    echo -e "\033[0;32m✓ Active conversation set to:\033[0m \033[1m${NEW_ID}\033[0m"
                    exit 0
                else
                    echo "Usage: ./chat.sh set <conversation-uuid>" >&2
                    exit 1
                fi
                ;;
            resume|r)
                SELECTED_MODE="resume"
                shift
                if [ $# -gt 0 ]; then
                    local RESUME_TARGET="$1"
                    shift
                    if [[ "$RESUME_TARGET" =~ ^[0-9]+$ ]] && [ "$RESUME_TARGET" -ge 1 ] && [ "$RESUME_TARGET" -le "${#conv_ids[@]}" ]; then
                        TARGET_CONV="${conv_ids[$((RESUME_TARGET - 1))]}"
                    else
                        TARGET_CONV="$RESUME_TARGET"
                    fi
                fi
                ;;
            new|fresh|n)
                SELECTED_MODE="new"
                TARGET_CONV=""
                shift
                ;;
            cont|continue|last|c)
                SELECTED_MODE="continue"
                TARGET_CONV=""
                shift
                ;;
            plan|p)
                SELECTED_MODE="plan"
                TARGET_CONV=""
                shift
                ;;
            shell|sh)
                echo "Dropping into interactive shell with active environment..."
                exec "${SHELL:-/bin/bash}"
                ;;
            # UUID direct resume detection (e.g. 5d49526f-5a24-... or 8+ hex chars)
            [0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]*)
                SELECTED_MODE="resume"
                TARGET_CONV="$1"
                shift
                ;;
            *)
                # Direct integer resume shortcut (e.g. ./chat.sh 1 or ./chat.sh 2)
                if [[ "$ARG_NORM" =~ ^[0-9]+$ ]] && [ "$ARG_NORM" -ge 1 ] && [ "$ARG_NORM" -le "${#conv_ids[@]}" ]; then
                    SELECTED_MODE="resume"
                    TARGET_CONV="${conv_ids[$((ARG_NORM - 1))]}"
                    shift
                else
                    # Passthrough all other arguments to agy
                    SELECTED_MODE="passthrough"
                fi
                ;;
        esac
    elif [ -t 0 ]; then
        echo ""
        echo " Recent Conversations for ${REPO_NAME}:"
        if [ ${#conv_ids[@]} -gt 0 ]; then
            for idx in "${!conv_ids[@]}"; do
                local num=$((idx + 1))
                local marker=""
                if [ "${conv_ids[idx]}" = "$DEFAULT_CONV" ]; then
                    marker=" \033[0;32m[DEFAULT]\033[0m"
                fi
                local display_title="${conv_titles[idx]}"
                if [ "${#display_title}" -gt 48 ]; then
                    display_title="${display_title:0:45}..."
                fi
                echo -e "   \033[1m[${num}]\033[0m [${conv_ids[idx]:0:8}] \033[1m${display_title}\033[0m (${conv_dates[idx]})${marker}"
            done
        else
            echo "   [None recorded yet in project database]"
        fi

        echo ""
        echo " Select conversation to resume, or choose an action:"
        if [ ${#conv_ids[@]} -gt 0 ]; then
            echo "   [1..${#conv_ids[@]}] Resume corresponding conversation (Enter = [1])"
        elif [ -n "$DEFAULT_CONV" ]; then
            echo "   [1] Resume configured conversation ($DEFAULT_CONV)"
        fi
        echo "   [n] Start a fresh NEW conversation"
        echo "   [c] Continue most recent conversation (--continue)"
        echo "   [p] Start new conversation in Planning Mode (--mode plan)"
        echo "   [u] Enter custom Conversation UUID"
        echo "   [s] Drop to interactive shell"
        echo ""
        read -r -p " Enter selection (default: 1): " user_choice || true
        echo ""

        local CHOICE_NORM
        CHOICE_NORM="$(echo "${user_choice:-1}" | tr '[:upper:]' '[:lower:]')"

        case "$CHOICE_NORM" in
            n|new|fresh)
                SELECTED_MODE="new"
                TARGET_CONV=""
                ;;
            c|cont|continue)
                SELECTED_MODE="continue"
                TARGET_CONV=""
                ;;
            p|plan)
                SELECTED_MODE="plan"
                TARGET_CONV=""
                ;;
            s|shell|sh)
                echo "Dropping into shell..."
                exec "${SHELL:-/bin/bash}"
                ;;
            u|uuid|custom)
                read -r -p " Enter conversation UUID: " custom_uuid || true
                TARGET_CONV="$(echo "${custom_uuid:-}" | tr -d '[:space:]')"
                SELECTED_MODE="resume"
                ;;
            *)
                # Check if user entered an index number
                if [[ "$CHOICE_NORM" =~ ^[0-9]+$ ]] && [ "$CHOICE_NORM" -ge 1 ] && [ "$CHOICE_NORM" -le "${#conv_ids[@]}" ]; then
                    SELECTED_MODE="resume"
                    TARGET_CONV="${conv_ids[$((CHOICE_NORM - 1))]}"
                elif [[ "$CHOICE_NORM" =~ ^[0-9a-fA-F-]{8,}$ ]]; then
                    SELECTED_MODE="resume"
                    TARGET_CONV="$CHOICE_NORM"
                else
                    SELECTED_MODE="resume"
                    TARGET_CONV="$DEFAULT_CONV"
                fi
                ;;
        esac
    fi

    # 4. Save selected conversation to .active-chat for future default
    if [ -n "$TARGET_CONV" ]; then
        echo "$TARGET_CONV" > "$ACTIVE_CHAT_FILE" 2>/dev/null || true
    fi

    # 5. Dispatch Execution
    case "$SELECTED_MODE" in
        resume)
            if [ -n "$TARGET_CONV" ]; then
                echo -e "Resuming conversation: \033[0;36m$TARGET_CONV\033[0m..."
                if [ -n "${TMUX:-}" ]; then
                    tmux rename-window "chat:${TARGET_CONV:0:8}" 2>/dev/null || true
                fi
                agy --conversation "$TARGET_CONV" --dangerously-skip-permissions "$@"
            else
                echo "No conversation ID resolved. Starting fresh conversation..."
                if [ -n "${TMUX:-}" ]; then
                    tmux rename-window "chat:new" 2>/dev/null || true
                fi
                agy --dangerously-skip-permissions "$@"
            fi
            ;;
        new)
            echo "Starting fresh conversation..."
            if [ -n "${TMUX:-}" ]; then
                tmux rename-window "chat:new" 2>/dev/null || true
            fi
            agy --dangerously-skip-permissions "$@"
            ;;
        continue)
            echo "Continuing most recent conversation (--continue)..."
            if [ -n "${TMUX:-}" ]; then
                tmux rename-window "chat:cont" 2>/dev/null || true
            fi
            agy --continue --dangerously-skip-permissions "$@"
            ;;
        plan)
            echo "Starting new conversation in Planning Mode (--mode plan)..."
            if [ -n "${TMUX:-}" ]; then
                tmux rename-window "chat:plan" 2>/dev/null || true
            fi
            agy --mode plan --dangerously-skip-permissions "$@"
            ;;
        passthrough)
            agy --dangerously-skip-permissions "$@"
            ;;
    esac

    # 6. Keep terminal alive upon exit inside tmux
    if [ -n "${TMUX:-}" ]; then
        echo ""
        echo -e "\033[0;34m[Agent exited. Terminal remaining active in ${REPO_NAME}...]\033[0m"
        exec "${SHELL:-/bin/bash}"
    else
        exit 0
    fi
}

# ------------------------------------------------------------------------------
# Outer Tmux Multi-Session Gatekeeper
# ------------------------------------------------------------------------------

# Parse CLI options for tmux management: --session / -s and --no-tmux
TARGET_SESSION="$BASE_SESSION_NAME"
USE_TMUX=1
FORWARD_ARGS=()

while [ $# -gt 0 ]; do
    case "$1" in
        --session|-s)
            TARGET_SESSION="${2:-$BASE_SESSION_NAME}"
            shift 2
            ;;
        --no-tmux)
            USE_TMUX=0
            shift
            ;;
        --help|-h)
            run_chat_loop "--help"
            ;;
        list|l)
            run_chat_loop "list"
            ;;
        *)
            FORWARD_ARGS+=("$1")
            shift
            ;;
    esac
done

# If already inside Tmux: run directly in the active tmux pane (enables multi-chat inside tmux)
if [ -n "${TMUX:-}" ]; then
    run_chat_loop "${FORWARD_ARGS[@]}"
fi

# If user requested --no-tmux or tmux is not installed: run directly
if [ "$USE_TMUX" -eq 0 ] || ! command -v tmux >/dev/null 2>&1; then
    run_chat_loop "${FORWARD_ARGS[@]}"
fi

# If non-interactive stdin (pipe or automation): run directly
if [ ! -t 0 ]; then
    run_chat_loop "${FORWARD_ARGS[@]}"
fi

# Outside Tmux: Check for existing sessions to avoid hijacking concurrent sessions
if tmux has-session -t "$TARGET_SESSION" 2>/dev/null; then
    ATTACHED_COUNT="$(tmux list-sessions -F "#{session_name} #{session_attached}" 2>/dev/null | awk -v s="$TARGET_SESSION" '$1==s {print $2}')"
    if [ "${ATTACHED_COUNT:-0}" -gt 0 ]; then
        NEXT_AVAIL="$(get_next_session_name "$TARGET_SESSION")"
        if [ ${#FORWARD_ARGS[@]} -gt 0 ]; then
            # Command arguments passed: automatically spin up dedicated concurrent session
            TARGET_SESSION="$NEXT_AVAIL"
        else
            echo ""
            echo -e " \033[0;33mNotice:\033[0m Tmux session '\033[1m${TARGET_SESSION}\033[0m' is currently active and attached."
            echo " Select an option:"
            echo -e "   1) Start a \033[1mNEW concurrent session (${NEXT_AVAIL})\033[0m [DEFAULT - press Enter]"
            echo -e "   2) Attach to '${TARGET_SESSION}' (share/mirror active terminal)"
            echo -e "   3) Run directly in this terminal (no tmux)"
            echo ""
            read -r -p " Enter choice [1/2/3] (default: 1): " sess_choice || true
            case "${sess_choice:-1}" in
                2)
                    # Keep TARGET_SESSION as is and attach
                    ;;
                3)
                    run_chat_loop "${FORWARD_ARGS[@]}"
                    ;;
                *)
                    TARGET_SESSION="$NEXT_AVAIL"
                    ;;
            esac
        fi
    elif [ ${#FORWARD_ARGS[@]} -gt 0 ]; then
        # Session exists but is detached, AND user provided specific run arguments (e.g. new, plan, UUID)
        # Kill the stale detached session to ensure forwarded arguments are executed cleanly
        tmux kill-session -t "$TARGET_SESSION" 2>/dev/null || true
    fi
fi

# Ensure target tmux session exists
if ! tmux has-session -t "$TARGET_SESSION" 2>/dev/null; then
    tmux new-session -d -s "$TARGET_SESSION" -c "$SCRIPT_DIR" "$SCRIPT_DIR/chat.sh" --session "$TARGET_SESSION" "${FORWARD_ARGS[@]}"
fi

# Attach to session
exec tmux attach-session -t "$TARGET_SESSION"
