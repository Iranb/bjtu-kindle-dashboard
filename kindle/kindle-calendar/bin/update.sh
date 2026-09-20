#!/bin/sh

. /mnt/us/extensions/kindle-calendar/bin/common.sh
load_config || exit 2
CHILD=""
LOCKED=0

cleanup() {
    if [ -n "$CHILD" ]; then kill "$CHILD" >/dev/null 2>&1 || true; wait "$CHILD" 2>/dev/null || true; fi
    [ "$LOCKED" -eq 1 ] && rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
}
trap cleanup 0
trap 'exit 143' 1 2 15

if mkdir "$LOCK_DIR" 2>/dev/null; then LOCKED=1; else exit 20; fi
if [ "$CALENDAR_MODE" = ics ]; then
    [ -s "$FEED_FILE" ] || { log "update result=skipped reason=feed_missing"; exit 2; }
    [ "$(wifi_state)" = CONNECTED ] || { log "update result=skipped reason=wifi_disconnected"; exit 1; }
fi

write_state "$LAST_ATTEMPT_FILE" "$(now_epoch)" || exit 1
set -- "$EXT_DIR/bin/kindle-calendar" \
    -mode "$CALENDAR_MODE" \
    -feed-file "$FEED_FILE" \
    -cache-file "$STATE_DIR/calendar.ics" \
    -metadata-file "$STATE_DIR/http.json" \
    -output "$IMAGE_FILE" \
    -holiday-dir "$STATE_DIR/holidays" \
    -holiday-refresh-interval "${HOLIDAY_REFRESH_SECONDS}s" \
    -timezone "$DISPLAY_TIMEZONE" \
    -width "$DISPLAY_WIDTH" \
    -height "$DISPLAY_HEIGHT" \
    -daily-hour "$DAILY_REFRESH_HOUR" \
    -daily-minute "$DAILY_REFRESH_MINUTE" \
    -timeout "${UPDATE_TIMEOUT_SECONDS}s"
if [ -f "$CA_FILE" ]; then
    [ "$(stat -c '%a' "$CA_FILE" 2>/dev/null)" = 600 ] || { log "update result=fail reason=ca_permissions"; exit 2; }
    set -- "$@" -ca-file "$CA_FILE"
fi
"$@" > "$STATE_DIR/update-result.tmp" 2> "$STATE_DIR/update-error.tmp" &
CHILD=$!
if wait "$CHILD"; then RC=0; else RC=$?; fi
CHILD=""
if [ "$RC" -ne 0 ]; then
    ERROR=$(tr '\n' ' ' < "$STATE_DIR/update-error.tmp" | cut -c1-160)
    log "update result=fail rc=$RC detail=$ERROR"
    rm -f "$STATE_DIR/update-result.tmp" "$STATE_DIR/update-error.tmp"
    exit "$RC"
fi

RESULT=$(tr '\n' ' ' < "$STATE_DIR/update-result.tmp" | cut -c1-160)
rm -f "$STATE_DIR/update-result.tmp" "$STATE_DIR/update-error.tmp"
write_state "$LAST_SUCCESS_FILE" "$(now_epoch)" >/dev/null 2>&1 || true
NEXT_DUE=$(printf '%s\n' "$RESULT" | sed -n 's/.* next_due=\([0-9][0-9]*\).*/\1/p')
if ! is_uint "$NEXT_DUE"; then NEXT_DUE=$(($(now_epoch) + BATTERY_RTC_INTERVAL_SECONDS)); fi
write_state "$NEXT_DUE_FILE" "$NEXT_DUE" >/dev/null 2>&1 || true
log "update $RESULT"
"$EXT_DIR/bin/ensure-screensaver.sh" >/dev/null 2>&1 || true
if [ "${NO_DISPLAY:-0}" != 1 ] && [ "$(power_state)" != active ]; then
    "$EXT_DIR/bin/show.sh" || true
fi
