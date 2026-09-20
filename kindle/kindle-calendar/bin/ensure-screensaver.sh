#!/bin/sh

. /mnt/us/extensions/kindle-calendar/bin/common.sh

CUSTOM_DIR=/mnt/us/extensions/custom-screensaver
CUSTOM_DAEMON=$CUSTOM_DIR/custom_ss_daemon.sh
CUSTOM_PID=/tmp/custom_ss_daemon.pid

if [ -x "$CUSTOM_DAEMON" ]; then
    PID=$(cat "$CUSTOM_PID" 2>/dev/null)
    case "$PID" in
        ''|*[!0-9]*) ;;
        *)
            if kill -0 "$PID" 2>/dev/null; then exit 0; fi
            ;;
    esac
    [ -f "$IMAGE_FILE" ] || exit 0
    /bin/sh "$CUSTOM_DAEMON" >/dev/null 2>&1 &
    sleep 1
    PID=$(cat "$CUSTOM_PID" 2>/dev/null)
    case "$PID" in
        ''|*[!0-9]*) log "screensaver result=fail runtime=custom"; exit 1 ;;
        *) kill -0 "$PID" 2>/dev/null || { log "screensaver result=fail runtime=custom"; exit 1; } ;;
    esac
    log "screensaver result=started runtime=custom"
    exit 0
fi

if [ -x /mnt/us/extensions/bjtu-native-screensaver/bin/render-panel.sh ]; then
    exit 0
fi

log "screensaver result=fail reason=runtime_missing"
exit 1

