#!/bin/sh

. /mnt/us/extensions/bjtu-dashboard-updater/bin/common.sh
if ! load_config; then
    log "config result=fail reason=parse_error"
    exit 2
fi

READY_PID=""
WAKE_PID=""
OUT_PID=""
WINDOW_PENDING=0
RTC_ARMED=0

cleanup() {
    trap - INT TERM EXIT
    [ -n "$READY_PID" ] && kill "$READY_PID" >/dev/null 2>&1 || true
    [ -n "$WAKE_PID" ] && kill "$WAKE_PID" >/dev/null 2>&1 || true
    [ -n "$OUT_PID" ] && kill "$OUT_PID" >/dev/null 2>&1 || true
    exec 3>&- 2>/dev/null || true
    exec 3<&- 2>/dev/null || true
    rm -f "$FIFO" "$PID_FILE"
    log "daemon result=stopped"
    exit 0
}

interval_now() {
    if is_charging; then
        printf '%s' "$CHARGING_INTERVAL_SECONDS"
    else
        printf '%s' "$BATTERY_INTERVAL_SECONDS"
    fi
}

set_next_due_after() {
    DELAY="$1"
    NOW=$(now_epoch)
    write_state "$NEXT_DUE_FILE" "$((NOW + DELAY))"
}

ensure_next_due() {
    NEXT_DUE=$(read_uint_file "$NEXT_DUE_FILE" 2>/dev/null)
    if ! is_uint "$NEXT_DUE"; then
        INTERVAL=$(interval_now)
        set_next_due_after "$INTERVAL"
        NEXT_DUE=$(read_uint_file "$NEXT_DUE_FILE")
    fi
    printf '%s' "$NEXT_DUE"
}

record_success() {
    write_state "$FAILURE_COUNT_FILE" 0 >/dev/null 2>&1 || true
    rm -f "$STATE_DIR/test-once"
    INTERVAL=$(interval_now)
    set_next_due_after "$INTERVAL"
    log "schedule result=success next_in=$INTERVAL"
}

record_cancelled() {
    rm -f "$STATE_DIR/test-once"
    INTERVAL=$(interval_now)
    set_next_due_after "$INTERVAL"
    log "schedule result=cancelled next_in=$INTERVAL"
}

record_failure() {
    COUNT=$(read_uint_file "$FAILURE_COUNT_FILE" 2>/dev/null)
    is_uint "$COUNT" || COUNT=0
    COUNT=$((COUNT + 1))
    write_state "$FAILURE_COUNT_FILE" "$COUNT" >/dev/null 2>&1 || true
    case "$COUNT" in
        1) BACKOFF="$FAILURE_BACKOFF_1_SECONDS" ;;
        2) BACKOFF="$FAILURE_BACKOFF_2_SECONDS" ;;
        3) BACKOFF="$FAILURE_BACKOFF_3_SECONDS" ;;
        *) BACKOFF="$FAILURE_BACKOFF_MAX_SECONDS" ;;
    esac
    set_next_due_after "$BACKOFF"
    log "schedule result=failure count=$COUNT next_in=$BACKOFF"
}

schedule_rtc() {
    [ -n "$UPDATE_URL" ] || {
        log "rtc result=skipped reason=missing_url"
        return
    }

    BATTERY=$(battery_level)
    is_uint "$BATTERY" || BATTERY=0
    if [ "$BATTERY" -lt "$LOW_BATTERY_PERCENT" ] && ! is_charging; then
        log "rtc result=skipped reason=low_battery battery=$BATTERY"
        return
    fi

    DUE=$(ensure_next_due)
    NOW=$(now_epoch)
    DELAY=$((DUE - NOW))
    if [ "$DELAY" -lt "$MIN_RTC_SECONDS" ]; then
        DELAY="$MIN_RTC_SECONDS"
    fi

    sleep "$RTC_FINAL_DELAY_SECONDS"
    [ "$(power_state)" = "readyToSuspend" ] || {
        log "rtc result=skipped reason=state_changed"
        return
    }

    if lipc-set-prop -i com.lab126.powerd rtcWakeup "$DELAY" >/dev/null 2>&1; then
        NOW=$(now_epoch)
        write_state "$SCHEDULED_EPOCH_FILE" "$((NOW + DELAY))" >/dev/null 2>&1 || true
        RTC_ARMED=1
        log "rtc result=armed seconds=$DELAY battery=$BATTERY"
    else
        log "rtc result=fail step=lipc_set"
        record_failure
    fi
}

handle_wakeup() {
    CURRENT_STATE=$(power_state)
    NOW=$(now_epoch)
    DUE=$(read_uint_file "$NEXT_DUE_FILE" 2>/dev/null)
    SCHEDULED=$(read_uint_file "$SCHEDULED_EPOCH_FILE" 2>/dev/null)

    if [ "$CURRENT_STATE" = "active" ]; then
        WINDOW_PENDING=0
        RTC_ARMED=0
        rm -f "$SCHEDULED_EPOCH_FILE"
        log "wake result=user_or_external state=$CURRENT_STATE"
        return
    fi

    if is_uint "$DUE" && is_uint "$SCHEDULED" && \
       [ "$((NOW + WAKE_EARLY_TOLERANCE_SECONDS))" -ge "$SCHEDULED" ] && \
       [ "$NOW" -le "$((SCHEDULED + WAKE_EARLY_TOLERANCE_SECONDS))" ] && \
       [ "$((NOW + WAKE_EARLY_TOLERANCE_SECONDS))" -ge "$DUE" ]; then
        WINDOW_PENDING=1
        log "wake result=scheduled state=$CURRENT_STATE delta=$((NOW - SCHEDULED))"
    else
        WINDOW_PENDING=0
        log "wake result=other state=$CURRENT_STATE now=$NOW due=${DUE:-none} scheduled=${SCHEDULED:-none}"
    fi
}

run_network_window() {
    [ "$(power_state)" = "readyToSuspend" ] || {
        WINDOW_PENDING=0
        log "window result=skipped reason=state_changed"
        return
    }

    if ! lipc-set-prop -i com.lab126.powerd abortSuspend 1 >/dev/null 2>&1; then
        WINDOW_PENDING=0
        log "window result=fail step=abort_suspend"
        record_failure
        return
    fi
    log "window action=abortSuspend power=$(power_state) wifi=$(wifi_state)"
    WINDOW_PENDING=0
    RTC_ARMED=0
    rm -f "$SCHEDULED_EPOCH_FILE"

    if "$EXT_DIR/bin/network-window.sh"; then
        record_success
    else
        WINDOW_RC=$?
        if [ "$WINDOW_RC" -eq 20 ]; then
            record_cancelled
        else
            record_failure
        fi
    fi
}

if ! is_enabled; then
    exit 0
fi

mkdir -p "$STATE_DIR" "$LOG_DIR"
chmod 700 "$STATE_DIR" >/dev/null 2>&1 || true

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if is_uint "$OLD_PID" && kill -0 "$OLD_PID" 2>/dev/null; then
        log "daemon result=skipped reason=already_running pid=$OLD_PID"
        exit 0
    fi
fi

echo $$ > "$PID_FILE"
trap cleanup INT TERM EXIT
log "daemon result=started pid=$$"

rm -f "$FIFO"
mkfifo "$FIFO" || exit 1
exec 3<>"$FIFO"

lipc-wait-event -m com.lab126.powerd readyToSuspend >&3 2>/dev/null &
READY_PID=$!
lipc-wait-event -m com.lab126.powerd wakeupFromSuspend >&3 2>/dev/null &
WAKE_PID=$!
lipc-wait-event -m com.lab126.powerd outOfScreenSaver >&3 2>/dev/null &
OUT_PID=$!

while read -r EVENT_LINE <&3; do
    case "$EVENT_LINE" in
        *wakeupFromSuspend*)
            handle_wakeup
            ;;
        *outOfScreenSaver*)
            WINDOW_PENDING=0
            log "wake result=out_of_screensaver"
            ;;
        *readyToSuspend*)
            LEVEL=$(printf '%s\n' "$EVENT_LINE" | awk '{print $NF}')
            case "$LEVEL" in
                10)
                    if [ "$WINDOW_PENDING" -eq 1 ]; then
                        run_network_window
                    fi
                    ;;
                1)
                    if [ "$WINDOW_PENDING" -eq 0 ]; then
                        schedule_rtc
                    fi
                    ;;
            esac
            ;;
    esac
done

cleanup
