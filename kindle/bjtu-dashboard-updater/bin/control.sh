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

save_config_value() {
    CONFIG_KEY="$1"
    CONFIG_NEW_VALUE="$2"
    [ -f "$CONFIG_FILE" ] || {
        echo "missing config: $CONFIG_FILE" >&2
        return 1
    }
    CONFIG_TMP="$CONFIG_FILE.tmp.$$"
    umask 022
    if ! awk -v key="$CONFIG_KEY" -v value="$CONFIG_NEW_VALUE" '
        BEGIN { replaced = 0 }
        substr($0, 1, length(key) + 1) == key "=" {
            if (!replaced) print key "=" value
            replaced = 1
            next
        }
        { print }
        END { if (!replaced) print key "=" value }
    ' "$CONFIG_FILE" > "$CONFIG_TMP"; then
        rm -f "$CONFIG_TMP"
        return 1
    fi
    chmod 644 "$CONFIG_TMP" || { rm -f "$CONFIG_TMP"; return 1; }
    mv -f "$CONFIG_TMP" "$CONFIG_FILE"
}

refetch_display() {
    LABEL="$1"
    VALUE="$2"
    WAS_ENABLED=0
    if is_enabled; then
        WAS_ENABLED=1
        /sbin/stop "$JOB" >/dev/null 2>&1 || true
    fi
    if ! BJTU_ALLOW_ACTIVE=1 BJTU_NO_RENDER=1 "$EXT_DIR/bin/fetch-panel.sh"; then
        if [ "$WAS_ENABLED" -eq 1 ]; then
            start_service >/dev/null 2>&1 || true
        fi
        echo "$LABEL saved but matching panel fetch failed" >&2
        return 1
    fi
    if [ "$WAS_ENABLED" -eq 1 ]; then
        start_service || return 1
    fi
    echo "$LABEL=$VALUE"
}

set_orientation() {
    NEW_ORIENTATION="$1"
    case "$NEW_ORIENTATION" in
        portrait|right) ;;
        *) echo "orientation must be portrait or right" >&2; return 2 ;;
    esac
    save_config_value DISPLAY_ORIENTATION "$NEW_ORIENTATION" || return 1
    refetch_display orientation "$NEW_ORIENTATION"
}

toggle_orientation() {
    CURRENT_ORIENTATION="$DISPLAY_ORIENTATION"
    if [ -f "$ORIENTATION_FILE" ]; then
        STORED_ORIENTATION=$(tr -d '\r\n' < "$ORIENTATION_FILE" | cut -c1-16)
        case "$STORED_ORIENTATION" in
            portrait|right) CURRENT_ORIENTATION="$STORED_ORIENTATION" ;;
        esac
    fi
    case "$CURRENT_ORIENTATION" in
        right) set_orientation portrait ;;
        *) set_orientation right ;;
    esac
}

set_content_mode() {
    NEW_CONTENT_MODE="$1"
    case "$NEW_CONTENT_MODE" in
        dashboard|calendar) ;;
        *) echo "content mode must be dashboard or calendar" >&2; return 2 ;;
    esac
    if [ "$NEW_CONTENT_MODE" = "calendar" ]; then
        case "$DISPLAY_ORIENTATION" in
            right) [ -n "$UPDATE_URL_CALENDAR_RIGHT" ] ;;
            *) [ -n "$UPDATE_URL_CALENDAR" ] ;;
        esac || {
            echo "calendar panel URL is not configured" >&2
            return 1
        }
    fi
    save_config_value DISPLAY_CONTENT_MODE "$NEW_CONTENT_MODE" || return 1
    refetch_display content_mode "$NEW_CONTENT_MODE"
}

toggle_content_mode() {
    CURRENT_CONTENT_MODE="$DISPLAY_CONTENT_MODE"
    if [ -f "$CONTENT_MODE_FILE" ]; then
        STORED_CONTENT_MODE=$(tr -d '\r\n' < "$CONTENT_MODE_FILE" | cut -c1-16)
        case "$STORED_CONTENT_MODE" in
            dashboard|calendar) CURRENT_CONTENT_MODE="$STORED_CONTENT_MODE" ;;
        esac
    fi
    case "$CURRENT_CONTENT_MODE" in
        calendar) set_content_mode dashboard ;;
        *) set_content_mode calendar ;;
    esac
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
        echo "$RUN_STATE orientation=$DISPLAY_ORIENTATION content_mode=$DISPLAY_CONTENT_MODE next_due=$NEXT_DUE last_result=$LAST_RESULT"
        ;;
    fetch-now)
        BJTU_ALLOW_ACTIVE=1 BJTU_NO_RENDER=1 "$EXT_DIR/bin/fetch-panel.sh"
        ;;
    orientation)
        case "$2" in
            toggle) toggle_orientation ;;
            *) set_orientation "$2" ;;
        esac
        ;;
    calendar)
        case "$2" in
            toggle) toggle_content_mode ;;
            on) set_content_mode calendar ;;
            off) set_content_mode dashboard ;;
            *) echo "usage: $0 calendar {on|off|toggle}" >&2; exit 2 ;;
        esac
        ;;
    logs)
        tail -n "${2:-80}" "$LOG_FILE" 2>/dev/null
        ;;
    uninstall)
        exec /bin/sh "$EXT_DIR/install.sh" uninstall
        ;;
    *)
        echo "usage: $0 {enable|disable|restart|status|fetch-now|orientation {portrait|right|toggle}|calendar {on|off|toggle}|logs [lines]|uninstall}" >&2
        exit 2
        ;;
esac
