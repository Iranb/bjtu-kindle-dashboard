#!/bin/sh

EXT_DIR=/mnt/us/extensions/kindle-calendar
STATE_DIR=/var/local/kindle-calendar
JOB=/etc/upstart/kindle-calendar.conf
ACTION=${1:-install}

[ "$(id -u)" = 0 ] || { echo "installer must run as root" >&2; exit 1; }

root_rw() { command -v mntroot >/dev/null 2>&1 && mntroot rw >/dev/null 2>&1 || mount -o remount,rw /; }
root_ro() { sync; command -v mntroot >/dev/null 2>&1 && mntroot ro >/dev/null 2>&1 || mount -o remount,ro /; }

case "$ACTION" in
    install)
        [ -x "$EXT_DIR/bin/kindle-calendar" ] || { echo "missing device renderer binary" >&2; exit 1; }
        if [ ! -x /mnt/us/extensions/custom-screensaver/custom_ss_daemon.sh ] && \
           [ ! -x /mnt/us/extensions/bjtu-native-screensaver/bin/render-panel.sh ]; then
            echo "install a compatible custom-screensaver/FBInk runtime first" >&2
            exit 1
        fi
        mkdir -p "$STATE_DIR/holidays" /mnt/us/screensavers
        chmod 700 "$STATE_DIR"
        chmod 700 "$STATE_DIR/holidays"
        if [ ! -f "$STATE_DIR/feed.url" ]; then umask 077; : > "$STATE_DIR/feed.url"; fi
        chmod 600 "$STATE_DIR/feed.url"
        [ -f "$EXT_DIR/calendar.conf" ] || cp "$EXT_DIR/calendar.conf.example" "$EXT_DIR/calendar.conf"
        chmod 755 "$EXT_DIR/install.sh" "$EXT_DIR/bin/"*.sh "$EXT_DIR/bin/kindle-calendar"
        chmod 644 "$EXT_DIR/calendar.conf" "$EXT_DIR/calendar.conf.example" "$EXT_DIR/menu.json" "$EXT_DIR/config.xml" "$EXT_DIR/THIRD_PARTY_NOTICES.md"
        root_rw || exit 1
        cp -f "$EXT_DIR/upstart/kindle-calendar.conf" "$JOB" && chmod 644 "$JOB"
        RC=$?
        root_ro >/dev/null 2>&1 || true
        [ "$RC" -eq 0 ] || exit 1
        touch "$EXT_DIR/enabled"
        /sbin/stop kindle-calendar >/dev/null 2>&1 || true
        /sbin/start kindle-calendar
        echo "installed; offline calendar is ready" ;;
    uninstall|purge)
        rm -f "$EXT_DIR/enabled"
        /sbin/stop kindle-calendar >/dev/null 2>&1 || true
        root_rw || exit 1
        rm -f "$JOB"
        root_ro >/dev/null 2>&1 || true
        if [ "$ACTION" = purge ]; then rm -rf "$STATE_DIR"; fi
        echo uninstalled ;;
    *) echo "usage: $0 {install|uninstall|purge}" >&2; exit 2 ;;
esac
