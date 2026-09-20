#!/bin/sh

. /mnt/us/extensions/kindle-calendar/bin/common.sh
[ -f "$IMAGE_FILE" ] || exit 1
[ "$(power_state)" != active ] || exit 20

FBINK=""
FBINK_MODE=legacy
for CANDIDATE in \
    /mnt/us/extensions/custom-screensaver/bin/fbink_hf \
    /mnt/us/usbnet/bin/fbink \
    /mnt/us/libkh/bin/fbink \
    /mnt/us/koreader/fbink
do
    if [ -x "$CANDIDATE" ]; then
        FBINK=$CANDIDATE
        [ "$CANDIDATE" = /mnt/us/extensions/custom-screensaver/bin/fbink_hf ] && FBINK_MODE=custom
        break
    fi
done
[ -n "$FBINK" ] || { log "display result=fail reason=fbink_missing"; exit 1; }

if [ "$FBINK_MODE" = custom ]; then
    "$FBINK" -g "file=$IMAGE_FILE,w=-1,h=-1" -f >/dev/null 2>&1 || exit 1
else
    "$FBINK" -q -b -i "$IMAGE_FILE" >/dev/null 2>&1 || exit 1
    "$FBINK" -q -f -W GC16 -w -s >/dev/null 2>&1 || true
fi
log "display result=ok"
