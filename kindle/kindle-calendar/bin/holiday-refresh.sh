#!/bin/sh

. /mnt/us/extensions/kindle-calendar/bin/common.sh
load_config || exit 2
[ "$CALENDAR_MODE" = offline ] || exit 0
[ "$(wifi_state)" = CONNECTED ] || exit 0

HOLIDAY_LOCK=/tmp/kindle-calendar-holiday.lock
CHILD=""
LOCKED=0

cleanup() {
    if [ -n "$CHILD" ]; then kill "$CHILD" >/dev/null 2>&1 || true; wait "$CHILD" 2>/dev/null || true; fi
    [ "$LOCKED" -eq 1 ] && rmdir "$HOLIDAY_LOCK" >/dev/null 2>&1 || true
    rm -f "$STATE_DIR/holiday-result.tmp" "$STATE_DIR/holiday-error.tmp"
}
trap cleanup 0
trap 'exit 143' 1 2 15

if mkdir "$HOLIDAY_LOCK" 2>/dev/null; then LOCKED=1; else exit 20; fi

"$EXT_DIR/bin/kindle-calendar" \
    -mode offline \
    -holiday-only \
    -refresh-holidays \
    -holiday-dir "$STATE_DIR/holidays" \
    -holiday-refresh-interval "${HOLIDAY_REFRESH_SECONDS}s" \
    -timezone "$DISPLAY_TIMEZONE" \
    -timeout "${UPDATE_TIMEOUT_SECONDS}s" \
    > "$STATE_DIR/holiday-result.tmp" 2> "$STATE_DIR/holiday-error.tmp" &
CHILD=$!
if wait "$CHILD"; then RC=0; else RC=$?; fi
CHILD=""
if [ "$RC" -ne 0 ]; then
    ERROR=$(tr '\n' ' ' < "$STATE_DIR/holiday-error.tmp" | cut -c1-160)
    log "holiday result=fail rc=$RC detail=$ERROR"
    exit "$RC"
fi
RESULT=$(tr '\n' ' ' < "$STATE_DIR/holiday-result.tmp" | cut -c1-160)
SAFE_RESULT=$(printf '%s\n' "$RESULT" | tr '\n' ' ' | cut -c1-160)
log "holiday $SAFE_RESULT"
UPDATED=$(printf '%s\n' "$RESULT" | sed -n 's/.* updated=\([0-9][0-9]*\).*/\1/p')
if is_uint "$UPDATED" && [ "$UPDATED" -gt 0 ]; then
    write_state "$NEXT_DUE_FILE" "$(now_epoch)" >/dev/null 2>&1 || true
fi
