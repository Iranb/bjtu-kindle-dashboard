#!/bin/sh

EXT_DIR=/mnt/us/extensions/kindle-calendar
STATE_DIR=/var/local/kindle-calendar
CONFIG_FILE=$EXT_DIR/calendar.conf
FEED_FILE=$STATE_DIR/feed.url
CA_FILE=$STATE_DIR/ca.pem
IMAGE_FILE=/mnt/us/screensavers/kindle-calendar.png
LOG_FILE=$EXT_DIR/calendar.log
PID_FILE=/tmp/kindle-calendar.pid
FIFO=/tmp/kindle-calendar-events.fifo
LOCK_DIR=/tmp/kindle-calendar-update.lock
LAST_ATTEMPT_FILE=$STATE_DIR/last-attempt
LAST_SUCCESS_FILE=$STATE_DIR/last-success
NEXT_DUE_FILE=$STATE_DIR/next-due
SCHEDULED_FILE=$STATE_DIR/scheduled-epoch

is_uint() {
    case "$1" in ''|*[!0-9]*) return 1 ;; *) return 0 ;; esac
}

in_range() {
    is_uint "$1" && [ "${#1}" -le 9 ] && [ "$1" -ge "$2" ] 2>/dev/null && [ "$1" -le "$3" ] 2>/dev/null
}

config_error() {
    printf '%s\n' "invalid config: $CONFIG_FILE:$1: $2" >&2
    return 1
}

load_config() {
    SYNC_INTERVAL_SECONDS=900
    BATTERY_RTC_INTERVAL_SECONDS=3600
    LOW_BATTERY_PERCENT=20
    WIFI_CONNECT_TIMEOUT_SECONDS=45
    UPDATE_TIMEOUT_SECONDS=40
    DISPLAY_WIDTH=1072
    DISPLAY_HEIGHT=1448
    DISPLAY_TIMEZONE=Asia/Shanghai
    [ -f "$CONFIG_FILE" ] || return 0

    LINE_NUMBER=0
    SEEN=""
    CR=$(printf '\r')
    while IFS= read -r LINE || [ -n "$LINE" ]; do
        LINE_NUMBER=$((LINE_NUMBER + 1))
        case "$LINE" in *"$CR") LINE=${LINE%"$CR"} ;; esac
        case "$LINE" in *"$CR"*) config_error "$LINE_NUMBER" "embedded carriage return"; return 1 ;; esac
        case "$LINE" in ''|'#'*) continue ;; *=*) ;; *) config_error "$LINE_NUMBER" "expected KEY=VALUE"; return 1 ;; esac
        KEY=${LINE%%=*}
        VALUE=${LINE#*=}
        case "$KEY" in ''|*[!A-Z0-9_]*) config_error "$LINE_NUMBER" "invalid key"; return 1 ;; esac
        case " $SEEN " in *" $KEY "*) config_error "$LINE_NUMBER" "duplicate key: $KEY"; return 1 ;; esac
        SEEN="$SEEN $KEY"
        case "$VALUE" in *[!A-Za-z0-9_./+-]*) config_error "$LINE_NUMBER" "unsupported value"; return 1 ;; esac
        case "$KEY" in
            SYNC_INTERVAL_SECONDS)
                in_range "$VALUE" 300 86400 || { config_error "$LINE_NUMBER" "$KEY must be 300..86400"; return 1; }
                SYNC_INTERVAL_SECONDS=$VALUE ;;
            BATTERY_RTC_INTERVAL_SECONDS)
                in_range "$VALUE" 900 604800 || { config_error "$LINE_NUMBER" "$KEY must be 900..604800"; return 1; }
                BATTERY_RTC_INTERVAL_SECONDS=$VALUE ;;
            LOW_BATTERY_PERCENT)
                in_range "$VALUE" 0 100 || { config_error "$LINE_NUMBER" "$KEY must be 0..100"; return 1; }
                LOW_BATTERY_PERCENT=$VALUE ;;
            WIFI_CONNECT_TIMEOUT_SECONDS)
                in_range "$VALUE" 1 300 || { config_error "$LINE_NUMBER" "$KEY must be 1..300"; return 1; }
                WIFI_CONNECT_TIMEOUT_SECONDS=$VALUE ;;
            UPDATE_TIMEOUT_SECONDS)
                in_range "$VALUE" 5 300 || { config_error "$LINE_NUMBER" "$KEY must be 5..300"; return 1; }
                UPDATE_TIMEOUT_SECONDS=$VALUE ;;
            DISPLAY_WIDTH)
                in_range "$VALUE" 600 2000 || { config_error "$LINE_NUMBER" "$KEY must be 600..2000"; return 1; }
                DISPLAY_WIDTH=$VALUE ;;
            DISPLAY_HEIGHT)
                in_range "$VALUE" 800 2500 || { config_error "$LINE_NUMBER" "$KEY must be 800..2500"; return 1; }
                DISPLAY_HEIGHT=$VALUE ;;
            DISPLAY_TIMEZONE)
                case "$VALUE" in */*) ;; *) config_error "$LINE_NUMBER" "$KEY must be an IANA timezone"; return 1 ;; esac
                DISPLAY_TIMEZONE=$VALUE ;;
            *) config_error "$LINE_NUMBER" "unknown key: $KEY"; return 1 ;;
        esac
    done < "$CONFIG_FILE"
}

log() {
    if [ -f "$LOG_FILE" ] && [ "$(wc -c < "$LOG_FILE" 2>/dev/null)" -gt 131072 ]; then
        mv -f "$LOG_FILE" "$LOG_FILE.1"
    fi
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"
}

write_state() {
    TARGET=$1
    VALUE=$2
    TMP=$TARGET.tmp.$$
    umask 077
    printf '%s\n' "$VALUE" > "$TMP" && mv -f "$TMP" "$TARGET"
}

read_uint() {
    VALUE=$(cat "$1" 2>/dev/null)
    is_uint "$VALUE" && printf '%s' "$VALUE"
}

power_state() { lipc-get-prop com.lab126.powerd state 2>/dev/null || printf unknown; }
wifi_state() { lipc-get-prop com.lab126.wifid cmState 2>/dev/null || printf unknown; }
battery_level() { lipc-get-prop com.lab126.powerd battLevel 2>/dev/null || printf 0; }
now_epoch() { date '+%s'; }
