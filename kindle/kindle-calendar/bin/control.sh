#!/bin/sh

. /mnt/us/extensions/kindle-calendar/bin/common.sh
load_config || exit 2
ACTION=$1
DASHBOARD_DIR=/mnt/us/extensions/bjtu-dashboard-updater

stop_competing_dashboard() {
    if [ -f "$DASHBOARD_DIR/enabled" ]; then
        rm -f "$DASHBOARD_DIR/enabled"
        /sbin/stop bjtu-dashboard-updater >/dev/null 2>&1 || true
        echo "disabled competing BJTU dashboard updater"
    fi
}

case "$ACTION" in
    enable)
        stop_competing_dashboard
        touch "$EXT_DIR/enabled"
        /sbin/stop kindle-calendar >/dev/null 2>&1 || true
        /sbin/start kindle-calendar
        echo enabled ;;
    disable)
        rm -f "$EXT_DIR/enabled"
        /sbin/stop kindle-calendar >/dev/null 2>&1 || true
        echo disabled ;;
    refresh)
        "$EXT_DIR/bin/update.sh" ;;
    show)
        "$EXT_DIR/bin/show.sh" ;;
    status)
        if [ -f "$PID_FILE" ]; then STATUS=running; else STATUS=stopped; fi
        LAST=$(read_uint "$LAST_SUCCESS_FILE" 2>/dev/null || printf never)
        DUE=$(read_uint "$NEXT_DUE_FILE" 2>/dev/null || printf none)
        echo "status=$STATUS wifi=$(wifi_state) power=$(power_state) last_success=$LAST next_due=$DUE" ;;
    logs)
        tail -n "${2:-60}" "$LOG_FILE" 2>/dev/null ;;
    *) echo "usage: $0 {enable|disable|refresh|show|status|logs}" >&2; exit 2 ;;
esac
