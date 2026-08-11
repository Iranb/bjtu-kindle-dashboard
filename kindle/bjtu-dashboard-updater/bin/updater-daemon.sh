#!/bin/sh

. /mnt/us/extensions/bjtu-dashboard-updater/bin/common.sh
if ! load_config; then
    log "config result=fail reason=parse_error"
    exit 2
fi

READY_PID=""
WAKE_PID=""
OUT_PID=""
TICK_PID=""
WINDOW_PENDING=0
RTC_ARMED=0
KEEP_AWAKE_HELD=0

release_keep_awake() {
    if [ "$KEEP_AWAKE_HELD" -eq 1 ]; then
        lipc-set-prop -i com.lab126.powerd suspendGrace 0 >/dev/null 2>&1 || true
        lipc-set-prop -i com.lab126.powerd deferSuspend 0 >/dev/null 2>&1 || true
        KEEP_AWAKE_HELD=0
        log "keep_awake result=released"
    fi
}

cleanup() {
    trap - INT TERM EXIT
    [ -n "$READY_PID" ] && kill "$READY_PID" >/dev/null 2>&1 || true
    [ -n "$WAKE_PID" ] && kill "$WAKE_PID" >/dev/null 2>&1 || true
    [ -n "$OUT_PID" ] && kill "$OUT_PID" >/dev/null 2>&1 || true
    [ -n "$TICK_PID" ] && kill "$TICK_PID" >/dev/null 2>&1 || true
    release_keep_awake
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

should_keep_awake() {
    [ "$CHARGING_KEEP_AWAKE" = "1" ] && is_charging && [ "$(power_state)" = "screenSaver" ]
}

renew_keep_awake() {
    should_keep_awake || return 1
    if ! lipc-set-prop -i com.lab126.powerd suspendGrace "$KEEP_AWAKE_GRACE_SECONDS" >/dev/null 2>&1; then
        log "keep_awake result=fail step=suspend_grace"
        return 1
    fi
    # Some firmware applies deferSuspend only in readyToSuspend. The confirmed
    # hold here is suspendGrace; deferSuspend is a harmless second guard.
    lipc-set-prop -i com.lab126.powerd deferSuspend "$KEEP_AWAKE_GRACE_SECONDS" >/dev/null 2>&1 || true
    if [ "$KEEP_AWAKE_HELD" -eq 0 ]; then
        log "keep_awake result=held grace=$KEEP_AWAKE_GRACE_SECONDS renew=$KEEP_AWAKE_RENEW_SECONDS"
    fi
    KEEP_AWAKE_HELD=1
    return 0
}

run_charging_window_if_due() {
    should_keep_awake || return 0
    DUE=$(ensure_next_due)
    NOW=$(now_epoch)
    [ "$NOW" -ge "$DUE" ] || return 0

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

handle_keep_awake_tick() {
    if renew_keep_awake; then
        run_charging_window_if_due
    else
        release_keep_awake
    fi
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

(
    while sleep "$KEEP_AWAKE_RENEW_SECONDS"; do
        printf '%s\n' keepAwakeTick > "$FIFO" || exit 0
    done
) &
TICK_PID=$!

handle_keep_awake_tick

while read -r EVENT_LINE <&3; do
    case "$EVENT_LINE" in
        *wakeupFromSuspend*)
            handle_wakeup
            ;;
        *outOfScreenSaver*)
            WINDOW_PENDING=0
            release_keep_awake
            log "wake result=out_of_screensaver"
            ;;
        *keepAwakeTick*)
            handle_keep_awake_tick
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
                    if [ "$WINDOW_PENDING" -eq 0 ] && renew_keep_awake; then
                        RTC_ARMED=0
                        rm -f "$SCHEDULED_EPOCH_FILE"
                        run_charging_window_if_due
                    elif [ "$WINDOW_PENDING" -eq 0 ]; then
                        schedule_rtc
                    fi
                    ;;
            esac
            ;;
    esac
done

cleanup
