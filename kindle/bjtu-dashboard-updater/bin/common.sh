#!/bin/sh

EXT_DIR="/mnt/us/extensions/bjtu-dashboard-updater"
SCREENSAVER_DIR="/mnt/us/extensions/bjtu-native-screensaver"
STATE_DIR="/var/local/bjtu-dashboard"
CONFIG_FILE="$EXT_DIR/update.conf"
ENABLED_FILE="$EXT_DIR/enabled"
LOG_DIR="$EXT_DIR/logs"
LOG_FILE="$LOG_DIR/updater.log"
PID_FILE="/tmp/bjtu-dashboard-updater.pid"
FIFO="/tmp/bjtu-dashboard-updater-events.fifo"
NEXT_DUE_FILE="$STATE_DIR/next-due"
SCHEDULED_EPOCH_FILE="$STATE_DIR/scheduled-epoch"
FAILURE_COUNT_FILE="$STATE_DIR/failure-count"
LAST_RESULT_FILE="$STATE_DIR/last-result"
LAST_SUCCESS_FILE="$STATE_DIR/last-success"
ETAG_FILE="$STATE_DIR/etag"
CURL_CONFIG_FILE="$STATE_DIR/curl.conf"
FETCH_LOCK_DIR="/tmp/bjtu-dashboard-fetch.lock"
ASSET="$SCREENSAVER_DIR/assets/panel-base.png"
RENDER="$SCREENSAVER_DIR/bin/render-panel.sh"

load_config() {
    UPDATE_URL=""
    BATTERY_INTERVAL_SECONDS=3600
    CHARGING_INTERVAL_SECONDS=600
    LOW_BATTERY_PERCENT=20
    MIN_RTC_SECONDS=180
    RTC_FINAL_DELAY_SECONDS=2
    WAKE_EARLY_TOLERANCE_SECONDS=60
    WIFI_CONNECT_TIMEOUT_SECONDS=12
    DOWNLOAD_TIMEOUT_SECONDS=12
    NETWORK_WINDOW_TIMEOUT_SECONDS=30
    MAX_IMAGE_BYTES=2097152
    FAILURE_BACKOFF_1_SECONDS=3600
    FAILURE_BACKOFF_2_SECONDS=7200
    FAILURE_BACKOFF_3_SECONDS=14400
    FAILURE_BACKOFF_MAX_SECONDS=21600
    ALLOW_HTTP=0

    if [ -f "$CONFIG_FILE" ]; then
        # The config contains settings only. Credentials belong in curl.conf.
        . "$CONFIG_FILE"
    fi
}

rotate_log() {
    if [ -f "$LOG_FILE" ]; then
        LOG_SIZE=$(wc -c < "$LOG_FILE" 2>/dev/null)
        if [ "${LOG_SIZE:-0}" -gt 262144 ]; then
            mv -f "$LOG_FILE" "$LOG_FILE.1"
        fi
    fi
}

log() {
    mkdir -p "$LOG_DIR"
    rotate_log
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"
}

is_uint() {
    case "$1" in
        ''|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

read_uint_file() {
    VALUE=$(cat "$1" 2>/dev/null)
    if is_uint "$VALUE"; then
        printf '%s' "$VALUE"
        return 0
    fi
    return 1
}

write_state() {
    TARGET="$1"
    VALUE="$2"
    TMP="$TARGET.tmp.$$"
    umask 077
    printf '%s\n' "$VALUE" > "$TMP" || return 1
    mv -f "$TMP" "$TARGET"
}

power_state() {
    lipc-get-prop com.lab126.powerd state 2>/dev/null || printf unknown
}

wifi_state() {
    lipc-get-prop com.lab126.wifid cmState 2>/dev/null || printf unknown
}

battery_level() {
    lipc-get-prop com.lab126.powerd battLevel 2>/dev/null || printf 0
}

is_charging() {
    [ "$(lipc-get-prop com.lab126.powerd isCharging 2>/dev/null)" = "1" ]
}

is_enabled() {
    [ -f "$ENABLED_FILE" ]
}

now_epoch() {
    date '+%s'
}
