#!/bin/sh

. /mnt/us/extensions/bjtu-dashboard-updater/bin/common.sh
load_config

FETCH_PID=""

cleanup() {
    if [ -n "$FETCH_PID" ]; then
        kill "$FETCH_PID" >/dev/null 2>&1 || true
        wait "$FETCH_PID" 2>/dev/null || true
    fi
}

trap cleanup 0 1 2 15

ATTEMPT=0
while [ "$ATTEMPT" -lt "$WIFI_CONNECT_TIMEOUT_SECONDS" ]; do
    if [ "$(power_state)" = "active" ]; then
        log "window result=cancelled reason=user_active_before_wifi"
        exit 20
    fi
    if [ "$(wifi_state)" = "CONNECTED" ]; then
        break
    fi
    ATTEMPT=$((ATTEMPT + 1))
    sleep 1
done

[ "$(wifi_state)" = "CONNECTED" ] || {
    log "window result=fail step=wifi_timeout attempts=$ATTEMPT"
    exit 1
}
log "window wifi=connected attempts=$ATTEMPT power=$(power_state)"

"$EXT_DIR/bin/fetch-panel.sh" &
FETCH_PID=$!
ELAPSED=0
while kill -0 "$FETCH_PID" 2>/dev/null; do
    if ! is_enabled; then
        kill "$FETCH_PID" >/dev/null 2>&1 || true
        wait "$FETCH_PID" 2>/dev/null || true
        FETCH_PID=""
        log "window result=cancelled reason=disabled"
        exit 20
    fi
    if [ "$(power_state)" = "active" ]; then
        kill "$FETCH_PID" >/dev/null 2>&1 || true
        wait "$FETCH_PID" 2>/dev/null || true
        FETCH_PID=""
        log "window result=cancelled reason=user_active"
        exit 20
    fi
    if [ "$ELAPSED" -ge "$NETWORK_WINDOW_TIMEOUT_SECONDS" ]; then
        kill "$FETCH_PID" >/dev/null 2>&1 || true
        wait "$FETCH_PID" 2>/dev/null || true
        FETCH_PID=""
        log "window result=fail step=hard_timeout"
        exit 1
    fi
    ELAPSED=$((ELAPSED + 1))
    sleep 1
done

if wait "$FETCH_PID"; then
    FETCH_RC=0
else
    FETCH_RC=$?
fi
FETCH_PID=""
log "window result=complete fetch_rc=$FETCH_RC elapsed=$ELAPSED"
exit "$FETCH_RC"
