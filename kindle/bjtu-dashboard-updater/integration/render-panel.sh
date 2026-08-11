#!/bin/sh

# Draw the active native-size panel. Portrait mode adds current device status;
# right mode is already pre-rotated and must not receive portrait-coordinate text.

EXT_DIR="/mnt/us/extensions/bjtu-native-screensaver"
ASSET="$EXT_DIR/assets/panel-base.png"
ORIENTATION_FILE="/var/local/bjtu-dashboard/orientation"
FBINK="/mnt/us/usbnet/bin/fbink"
FONT_REGULAR="/usr/java/lib/fonts/Helvetica_LT_65_Medium.ttf"
FONT_BOLD="/usr/java/lib/fonts/Helvetica_LT_75_Bold.ttf"

for CANDIDATE in \
    /mnt/us/usbnet/bin/fbink \
    /mnt/us/libkh/bin/fbink \
    /mnt/us/koreader/fbink
do
    if [ -x "$CANDIDATE" ]; then
        FBINK="$CANDIDATE"
        break
    fi
done

if [ ! -x "$FBINK" ] || [ ! -f "$ASSET" ]; then
    echo "render-panel: FBInk or panel asset missing" >&2
    exit 1
fi

ORIENTATION=portrait
if [ -f "$ORIENTATION_FILE" ]; then
    CANDIDATE_ORIENTATION=$(tr -d '\r\n' < "$ORIENTATION_FILE" | cut -c1-16)
    case "$CANDIDATE_ORIENTATION" in
        portrait|right) ORIENTATION=$CANDIDATE_ORIENTATION ;;
    esac
fi

"$FBINK" -q -b -i "$ASSET" >/dev/null 2>&1 || exit 1

if [ "$ORIENTATION" = "portrait" ]; then
    draw_text() {
        TEXT="$1"
        PX="$2"
        TOP="$3"
        BOTTOM="$4"
        LEFT="$5"
        RIGHT="$6"
        STYLE="$7"

        "$FBINK" -q -b -m \
            -t "regular=$FONT_REGULAR,bold=$FONT_BOLD,px=$PX,top=$TOP,bottom=$BOTTOM,left=$LEFT,right=$RIGHT,style=$STYLE" \
            "$TEXT" >/dev/null 2>&1
    }

    TIME_TEXT=$(date '+%H:%M')
    DATE_TEXT=$(LC_ALL=C date '+%a . %b %d' | tr '[:lower:]' '[:upper:]' | sed 's/ 0/ /')
    BATTERY=$(lipc-get-prop com.lab126.powerd battLevel 2>/dev/null)
    case "$BATTERY" in
        ''|*[!0-9]*) BATTERY="--" ;;
    esac

    draw_text "$TIME_TEXT" 42 42 1358 685 237 BOLD || exit 1
    draw_text "$DATE_TEXT" 18 88 1332 680 232 REGULAR || exit 1
    draw_text "${BATTERY}%" 29 48 1360 915 52 BOLD || exit 1
    draw_text "BATTERY" 17 88 1332 910 42 REGULAR || exit 1
fi

"$FBINK" -q -f -W GC16 -w -s >/dev/null 2>&1
