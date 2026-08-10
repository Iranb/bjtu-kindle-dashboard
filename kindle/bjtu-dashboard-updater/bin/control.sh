#!/bin/sh

. /mnt/us/extensions/bjtu-dashboard-updater/bin/common.sh
if ! load_config; then
    log "config result=fail reason=parse_error"
    exit 2
fi

JOB="bjtu-dashboard-updater"
ACTION="$1"

is_running() {
    [ -f "$PID_FILE" ] || return 1
    PID=$(cat "$PID_FILE" 2>/dev/null)
    is_uint "$PID" && kill -0 "$PID" 2>/dev/null
}

start_service() {
    /sbin/stop "$JOB" >/dev/null 2>&1 || true
    if ! /sbin/start "$JOB" >/dev/null 2>&1; then
        echo "could not start $JOB" >&2
        return 1
    fi
}

case "$ACTION" in
    enable)
        [ -n "$UPDATE_URL" ] || {
            echo "UPDATE_URL is empty; edit $CONFIG_FILE first" >&2
            exit 1
        }
        touch "$ENABLED_FILE"
        start_service
        echo "enabled"
        ;;
    disable)
        rm -f "$ENABLED_FILE"
        /sbin/stop "$JOB" >/dev/null 2>&1 || true
        echo "disabled"
        ;;
    restart)
        touch "$ENABLED_FILE"
        start_service
        echo "restarted"
        ;;
    status)
        if is_running; then
            RUN_STATE="running pid=$PID"
        elif is_enabled; then
            RUN_STATE="enabled not-running"
        else
            RUN_STATE="disabled"
        fi
        NEXT_DUE=$(read_uint_file "$NEXT_DUE_FILE" 2>/dev/null || printf none)
        LAST_RESULT=$(cat "$LAST_RESULT_FILE" 2>/dev/null || printf none)
        echo "$RUN_STATE next_due=$NEXT_DUE last_result=$LAST_RESULT"
        ;;
    fetch-now)
        BJTU_ALLOW_ACTIVE=1 BJTU_NO_RENDER=1 "$EXT_DIR/bin/fetch-panel.sh"
        ;;
    logs)
        tail -n "${2:-80}" "$LOG_FILE" 2>/dev/null
        ;;
    uninstall)
        exec /bin/sh "$EXT_DIR/install.sh" uninstall
        ;;
    *)
        echo "usage: $0 {enable|disable|restart|status|fetch-now|logs [lines]|uninstall}" >&2
        exit 2
        ;;
esac
