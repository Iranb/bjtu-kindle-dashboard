#!/bin/sh

. /mnt/us/extensions/kindle-calendar/bin/common.sh
load_config || exit 2
UPDATE_PID=""
POWER_PID=""
NETWORK_PID=""
TICK_PID=""
SCHEDULED_WAKE=0

cleanup() {
    trap - INT TERM EXIT
    for CHILD in "$UPDATE_PID" "$POWER_PID" "$NETWORK_PID" "$TICK_PID"; do
        [ -n "$CHILD" ] && kill "$CHILD" >/dev/null 2>&1 || true
    done
    rm -f "$FIFO" "$PID_FILE"
    exit 0
}
trap cleanup INT TERM EXIT

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
echo $$ > "$PID_FILE"
rm -f "$FIFO"
mkfifo "$FIFO" || exit 1
exec 3<>"$FIFO"

start_update() {
    FORCE=$1
    if [ -n "$UPDATE_PID" ] && kill -0 "$UPDATE_PID" 2>/dev/null; then return; fi
    UPDATE_PID=""
    [ "$(wifi_state)" = CONNECTED ] || return
    if [ "$FORCE" -ne 1 ]; then
        DUE=$(read_uint "$NEXT_DUE_FILE" 2>/dev/null)
        NOW=$(now_epoch)
        is_uint "$DUE" && [ "$NOW" -lt "$DUE" ] && return
    fi
    "$EXT_DIR/bin/update.sh" &
    UPDATE_PID=$!
}

cancel_active_update() {
    if [ -n "$UPDATE_PID" ] && kill -0 "$UPDATE_PID" 2>/dev/null; then
        kill "$UPDATE_PID" >/dev/null 2>&1 || true
        wait "$UPDATE_PID" 2>/dev/null || true
        log "update result=cancelled reason=user_active"
    fi
    UPDATE_PID=""
}

arm_rtc() {
    BATTERY=$(battery_level)
    is_uint "$BATTERY" || BATTERY=0
    [ "$BATTERY" -ge "$LOW_BATTERY_PERCENT" ] || { log "rtc result=skipped reason=low_battery"; return; }
    NOW=$(now_epoch)
    DUE=$(read_uint "$NEXT_DUE_FILE" 2>/dev/null)
    if ! is_uint "$DUE" || [ "$DUE" -le "$NOW" ]; then DUE=$((NOW + BATTERY_RTC_INTERVAL_SECONDS)); fi
    DELAY=$((DUE - NOW))
    [ "$DELAY" -ge 180 ] || DELAY=180
    if lipc-set-prop -i com.lab126.powerd rtcWakeup "$DELAY" >/dev/null 2>&1; then
        write_state "$SCHEDULED_FILE" "$((NOW + DELAY))" >/dev/null 2>&1 || true
        log "rtc result=armed seconds=$DELAY"
    fi
}

(
    while lipc-wait-event -m com.lab126.powerd goingToScreenSaver,outOfScreenSaver,wakeupFromSuspend,readyToSuspend 2>/dev/null; do :; done
) >&3 &
POWER_PID=$!
(
    while lipc-wait-event -m com.lab126.cmd connectionAvailable 2>/dev/null; do :; done
) >&3 &
NETWORK_PID=$!
(
    while sleep 30; do printf '%s\n' timerTick; done
) > "$FIFO" &
TICK_PID=$!

log "daemon result=started"
"$EXT_DIR/bin/ensure-screensaver.sh" >/dev/null 2>&1 || true
start_update 1
while read -r EVENT <&3; do
    case "$EVENT" in
        *connectionAvailable*) start_update 1 ;;
        *goingToScreenSaver*) "$EXT_DIR/bin/show.sh" >/dev/null 2>&1 || true; start_update 0 ;;
        *outOfScreenSaver*|*exitingScreenSaver*) cancel_active_update ;;
        *wakeupFromSuspend*)
            NOW=$(now_epoch)
            EXPECTED=$(read_uint "$SCHEDULED_FILE" 2>/dev/null)
            if is_uint "$EXPECTED" && [ "$NOW" -ge "$((EXPECTED - 90))" ] && [ "$NOW" -le "$((EXPECTED + 90))" ]; then SCHEDULED_WAKE=1; else SCHEDULED_WAKE=0; fi
            ;;
        *readyToSuspend*10*)
            if [ "$SCHEDULED_WAKE" -eq 1 ]; then
                SCHEDULED_WAKE=0
                rm -f "$SCHEDULED_FILE"
                if lipc-set-prop -i com.lab126.powerd abortSuspend 1 >/dev/null 2>&1; then
                    WAITED=0
                    while [ "$WAITED" -lt "$WIFI_CONNECT_TIMEOUT_SECONDS" ] && [ "$(wifi_state)" != CONNECTED ]; do sleep 1; WAITED=$((WAITED + 1)); done
                    start_update 1
                fi
            fi
            ;;
        *readyToSuspend*1*) arm_rtc ;;
        *timerTick*)
            "$EXT_DIR/bin/ensure-screensaver.sh" >/dev/null 2>&1 || true
            if [ "$(power_state)" = active ]; then start_update 0; else start_update 0; fi
            ;;
    esac
done
