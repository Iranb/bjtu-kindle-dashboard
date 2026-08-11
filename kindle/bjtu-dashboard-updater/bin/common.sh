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
ORIENTATION_FILE="$STATE_DIR/orientation"
CURL_CONFIG_FILE="$STATE_DIR/curl.conf"
FETCH_LOCK_DIR="/tmp/bjtu-dashboard-fetch.lock"
ASSET="$SCREENSAVER_DIR/assets/panel-base.png"
RENDER="$SCREENSAVER_DIR/bin/render-panel.sh"

is_uint() {
    case "$1" in
        ''|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

config_error() {
    printf '%s\n' "invalid config: $CONFIG_FILE:$1: $2" >&2
    return 1
}

config_uint_in_range() {
    CONFIG_VALUE="$1"
    CONFIG_MIN="$2"
    CONFIG_MAX="$3"
    is_uint "$CONFIG_VALUE" || return 1
    case "$CONFIG_VALUE" in
        0|[1-9]|[1-9][0-9]*) ;;
        *) return 1 ;;
    esac
    # Bound the digit count before using the shell's signed integer comparison.
    [ "${#CONFIG_VALUE}" -le 9 ] || return 1
    [ "$CONFIG_VALUE" -ge "$CONFIG_MIN" ] 2>/dev/null || return 1
    [ "$CONFIG_VALUE" -le "$CONFIG_MAX" ] 2>/dev/null
}

load_config() {
    UPDATE_URL=""
    UPDATE_URL_RIGHT=""
    DISPLAY_ORIENTATION=portrait
    BATTERY_INTERVAL_SECONDS=3600
    CHARGING_INTERVAL_SECONDS=300
    CHARGING_KEEP_AWAKE=1
    KEEP_AWAKE_GRACE_SECONDS=120
    KEEP_AWAKE_RENEW_SECONDS=30
    LOW_BATTERY_PERCENT=20
    MIN_RTC_SECONDS=180
    RTC_FINAL_DELAY_SECONDS=2
    WAKE_EARLY_TOLERANCE_SECONDS=60
    WIFI_CONNECT_TIMEOUT_SECONDS=45
    DOWNLOAD_TIMEOUT_SECONDS=30
    NETWORK_WINDOW_TIMEOUT_SECONDS=60
    MAX_IMAGE_BYTES=2097152
    FAILURE_BACKOFF_1_SECONDS=3600
    FAILURE_BACKOFF_2_SECONDS=7200
    FAILURE_BACKOFF_3_SECONDS=14400
    FAILURE_BACKOFF_MAX_SECONDS=21600
    ALLOW_HTTP=0

    [ -f "$CONFIG_FILE" ] || return 0

    # update.conf is on USB-visible storage and is therefore untrusted input.
    # Parse assignments as data: never source it and never pass values to eval.
    CONFIG_LINE_NUMBER=0
    CONFIG_SEEN_KEYS=""
    CONFIG_CR=$(printf '\r')
    while IFS= read -r CONFIG_LINE || [ -n "$CONFIG_LINE" ]; do
        CONFIG_LINE_NUMBER=$((CONFIG_LINE_NUMBER + 1))
        case "$CONFIG_LINE" in
            *"$CONFIG_CR") CONFIG_LINE=${CONFIG_LINE%"$CONFIG_CR"} ;;
        esac
        case "$CONFIG_LINE" in
            *"$CONFIG_CR"*)
                config_error "$CONFIG_LINE_NUMBER" "embedded carriage return"
                return 1
                ;;
            ''|'#'*) continue ;;
            *=*) ;;
            *)
                config_error "$CONFIG_LINE_NUMBER" "expected KEY=VALUE"
                return 1
                ;;
        esac

        CONFIG_KEY=${CONFIG_LINE%%=*}
        CONFIG_VALUE=${CONFIG_LINE#*=}
        case "$CONFIG_KEY" in
            ''|*[!A-Z0-9_]*)
                config_error "$CONFIG_LINE_NUMBER" "invalid key syntax"
                return 1
                ;;
        esac
        case " $CONFIG_SEEN_KEYS " in
            *" $CONFIG_KEY "*)
                config_error "$CONFIG_LINE_NUMBER" "duplicate key: $CONFIG_KEY"
                return 1
                ;;
        esac
        CONFIG_SEEN_KEYS="$CONFIG_SEEN_KEYS $CONFIG_KEY"

        case "$CONFIG_VALUE" in
            \"*\") CONFIG_VALUE=${CONFIG_VALUE#\"}; CONFIG_VALUE=${CONFIG_VALUE%\"} ;;
            \'*\') CONFIG_VALUE=${CONFIG_VALUE#\'}; CONFIG_VALUE=${CONFIG_VALUE%\'} ;;
        esac
        case "$CONFIG_VALUE" in
            *\"*|*\'*)
                config_error "$CONFIG_LINE_NUMBER" "unmatched or embedded quote"
                return 1
                ;;
        esac

        case "$CONFIG_KEY" in
            UPDATE_URL|UPDATE_URL_RIGHT)
                [ "${#CONFIG_VALUE}" -le 2048 ] || {
                    config_error "$CONFIG_LINE_NUMBER" "$CONFIG_KEY is too long"
                    return 1
                }
                case "$CONFIG_VALUE" in
                    ''|https://*|http://*) ;;
                    *)
                        config_error "$CONFIG_LINE_NUMBER" "$CONFIG_KEY must be empty, http, or https"
                        return 1
                        ;;
                esac
                case "$CONFIG_VALUE" in
                    *[!A-Za-z0-9:/?\&=._~%+#@,-]*)
                        config_error "$CONFIG_LINE_NUMBER" "$CONFIG_KEY contains unsupported characters"
                        return 1
                        ;;
                esac
                case "$CONFIG_KEY" in
                    UPDATE_URL) UPDATE_URL=$CONFIG_VALUE ;;
                    UPDATE_URL_RIGHT) UPDATE_URL_RIGHT=$CONFIG_VALUE ;;
                esac
                ;;
            DISPLAY_ORIENTATION)
                case "$CONFIG_VALUE" in
                    portrait|right) DISPLAY_ORIENTATION=$CONFIG_VALUE ;;
                    *)
                        config_error "$CONFIG_LINE_NUMBER" "DISPLAY_ORIENTATION must be portrait or right"
                        return 1
                        ;;
                esac
                ;;
            BATTERY_INTERVAL_SECONDS)
                config_uint_in_range "$CONFIG_VALUE" 180 604800 || {
                    config_error "$CONFIG_LINE_NUMBER" "BATTERY_INTERVAL_SECONDS must be 180..604800"
                    return 1
                }
                BATTERY_INTERVAL_SECONDS=$CONFIG_VALUE
                ;;
            CHARGING_INTERVAL_SECONDS)
                config_uint_in_range "$CONFIG_VALUE" 180 86400 || {
                    config_error "$CONFIG_LINE_NUMBER" "CHARGING_INTERVAL_SECONDS must be 180..86400"
                    return 1
                }
                CHARGING_INTERVAL_SECONDS=$CONFIG_VALUE
                ;;
            CHARGING_KEEP_AWAKE)
                config_uint_in_range "$CONFIG_VALUE" 0 1 || {
                    config_error "$CONFIG_LINE_NUMBER" "CHARGING_KEEP_AWAKE must be 0 or 1"
                    return 1
                }
                CHARGING_KEEP_AWAKE=$CONFIG_VALUE
                ;;
            KEEP_AWAKE_GRACE_SECONDS)
                config_uint_in_range "$CONFIG_VALUE" 60 3600 || {
                    config_error "$CONFIG_LINE_NUMBER" "KEEP_AWAKE_GRACE_SECONDS must be 60..3600"
                    return 1
                }
                KEEP_AWAKE_GRACE_SECONDS=$CONFIG_VALUE
                ;;
            KEEP_AWAKE_RENEW_SECONDS)
                config_uint_in_range "$CONFIG_VALUE" 10 600 || {
                    config_error "$CONFIG_LINE_NUMBER" "KEEP_AWAKE_RENEW_SECONDS must be 10..600"
                    return 1
                }
                KEEP_AWAKE_RENEW_SECONDS=$CONFIG_VALUE
                ;;
            LOW_BATTERY_PERCENT)
                config_uint_in_range "$CONFIG_VALUE" 0 100 || {
                    config_error "$CONFIG_LINE_NUMBER" "LOW_BATTERY_PERCENT must be 0..100"
                    return 1
                }
                LOW_BATTERY_PERCENT=$CONFIG_VALUE
                ;;
            MIN_RTC_SECONDS)
                config_uint_in_range "$CONFIG_VALUE" 60 86400 || {
                    config_error "$CONFIG_LINE_NUMBER" "MIN_RTC_SECONDS must be 60..86400"
                    return 1
                }
                MIN_RTC_SECONDS=$CONFIG_VALUE
                ;;
            RTC_FINAL_DELAY_SECONDS)
                config_uint_in_range "$CONFIG_VALUE" 0 30 || {
                    config_error "$CONFIG_LINE_NUMBER" "RTC_FINAL_DELAY_SECONDS must be 0..30"
                    return 1
                }
                RTC_FINAL_DELAY_SECONDS=$CONFIG_VALUE
                ;;
            WAKE_EARLY_TOLERANCE_SECONDS)
                config_uint_in_range "$CONFIG_VALUE" 0 3600 || {
                    config_error "$CONFIG_LINE_NUMBER" "WAKE_EARLY_TOLERANCE_SECONDS must be 0..3600"
                    return 1
                }
                WAKE_EARLY_TOLERANCE_SECONDS=$CONFIG_VALUE
                ;;
            WIFI_CONNECT_TIMEOUT_SECONDS)
                config_uint_in_range "$CONFIG_VALUE" 1 300 || {
                    config_error "$CONFIG_LINE_NUMBER" "WIFI_CONNECT_TIMEOUT_SECONDS must be 1..300"
                    return 1
                }
                WIFI_CONNECT_TIMEOUT_SECONDS=$CONFIG_VALUE
                ;;
            DOWNLOAD_TIMEOUT_SECONDS)
                config_uint_in_range "$CONFIG_VALUE" 1 600 || {
                    config_error "$CONFIG_LINE_NUMBER" "DOWNLOAD_TIMEOUT_SECONDS must be 1..600"
                    return 1
                }
                DOWNLOAD_TIMEOUT_SECONDS=$CONFIG_VALUE
                ;;
            NETWORK_WINDOW_TIMEOUT_SECONDS)
                config_uint_in_range "$CONFIG_VALUE" 1 900 || {
                    config_error "$CONFIG_LINE_NUMBER" "NETWORK_WINDOW_TIMEOUT_SECONDS must be 1..900"
                    return 1
                }
                NETWORK_WINDOW_TIMEOUT_SECONDS=$CONFIG_VALUE
                ;;
            MAX_IMAGE_BYTES)
                config_uint_in_range "$CONFIG_VALUE" 1024 16777216 || {
                    config_error "$CONFIG_LINE_NUMBER" "MAX_IMAGE_BYTES must be 1024..16777216"
                    return 1
                }
                MAX_IMAGE_BYTES=$CONFIG_VALUE
                ;;
            FAILURE_BACKOFF_1_SECONDS|FAILURE_BACKOFF_2_SECONDS|FAILURE_BACKOFF_3_SECONDS|FAILURE_BACKOFF_MAX_SECONDS)
                config_uint_in_range "$CONFIG_VALUE" 60 604800 || {
                    config_error "$CONFIG_LINE_NUMBER" "$CONFIG_KEY must be 60..604800"
                    return 1
                }
                case "$CONFIG_KEY" in
                    FAILURE_BACKOFF_1_SECONDS) FAILURE_BACKOFF_1_SECONDS=$CONFIG_VALUE ;;
                    FAILURE_BACKOFF_2_SECONDS) FAILURE_BACKOFF_2_SECONDS=$CONFIG_VALUE ;;
                    FAILURE_BACKOFF_3_SECONDS) FAILURE_BACKOFF_3_SECONDS=$CONFIG_VALUE ;;
                    FAILURE_BACKOFF_MAX_SECONDS) FAILURE_BACKOFF_MAX_SECONDS=$CONFIG_VALUE ;;
                esac
                ;;
            ALLOW_HTTP)
                config_uint_in_range "$CONFIG_VALUE" 0 1 || {
                    config_error "$CONFIG_LINE_NUMBER" "ALLOW_HTTP must be 0 or 1"
                    return 1
                }
                ALLOW_HTTP=$CONFIG_VALUE
                ;;
            *)
                config_error "$CONFIG_LINE_NUMBER" "unknown key: $CONFIG_KEY"
                return 1
                ;;
        esac
    done < "$CONFIG_FILE"

    if [ "$KEEP_AWAKE_RENEW_SECONDS" -ge "$KEEP_AWAKE_GRACE_SECONDS" ]; then
        config_error "$CONFIG_LINE_NUMBER" "KEEP_AWAKE_RENEW_SECONDS must be less than KEEP_AWAKE_GRACE_SECONDS"
        return 1
    fi
    return 0
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
