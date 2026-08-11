#!/bin/sh

set -eu

EDGE_ROOT=${BJTU_EDGE_ROOT:-"$HOME/.local/share/bjtu-kindle-edge"}
PYTHON=${BJTU_EDGE_PYTHON:-python3}
SERVER="$EDGE_ROOT/app/serve_kindle_panel.py"
PANEL="$EDGE_ROOT/www/panel-base.png"
RIGHT_PANEL="$EDGE_ROOT/www/panel-base-right.png"
CERT="$EDGE_ROOT/pki/server.crt"
KEY="$EDGE_ROOT/pki/server.key"
PID_FILE="$EDGE_ROOT/run/server.pid"
LOG_FILE="$EDGE_ROOT/log/server.log"
PORT=${BJTU_EDGE_PORT:-41443}

is_uint() {
    case "$1" in ''|*[!0-9]*) return 1 ;; *) return 0 ;; esac
}

is_running() {
    [ -f "$PID_FILE" ] || return 1
    PID=$(tr -d '\r\n' < "$PID_FILE")
    is_uint "$PID" || return 1
    kill -0 "$PID" 2>/dev/null || return 1
    [ -r "/proc/$PID/cmdline" ] || return 1
    tr '\000' ' ' < "/proc/$PID/cmdline" | grep -F "$SERVER" >/dev/null 2>&1
}

start_server() {
    if is_running; then
        return 0
    fi
    mkdir -p "$EDGE_ROOT/run" "$EDGE_ROOT/log"
    umask 077
    nohup "$PYTHON" "$SERVER" \
        --panel "$PANEL" \
        --right-panel "$RIGHT_PANEL" \
        --cert "$CERT" \
        --key "$KEY" \
        --port "$PORT" \
        >> "$LOG_FILE" 2>&1 &
    NEW_PID=$!
    printf '%s\n' "$NEW_PID" > "$PID_FILE"
    sleep 1
    if ! is_running; then
        rm -f "$PID_FILE"
        return 1
    fi
}

stop_server() {
    if ! is_running; then
        rm -f "$PID_FILE"
        return 0
    fi
    kill "$PID"
    COUNT=0
    while kill -0 "$PID" 2>/dev/null && [ "$COUNT" -lt 10 ]; do
        sleep 1
        COUNT=$((COUNT + 1))
    done
    if kill -0 "$PID" 2>/dev/null; then
        return 1
    fi
    rm -f "$PID_FILE"
}

case "${1:-status}" in
    start|ensure) start_server ;;
    stop) stop_server ;;
    restart) stop_server; start_server ;;
    status)
        if is_running; then
            printf '%s\n' running
        else
            printf '%s\n' stopped
            exit 1
        fi
        ;;
    *) printf '%s\n' "usage: $0 {start|ensure|stop|restart|status}" >&2; exit 2 ;;
esac
