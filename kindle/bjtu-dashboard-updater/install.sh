#!/bin/sh

EXT_DIR="/mnt/us/extensions/bjtu-dashboard-updater"
STATE_DIR="/var/local/bjtu-dashboard"
JOB_NAME="bjtu-dashboard-updater"
JOB_SRC="$EXT_DIR/upstart/$JOB_NAME.conf"
JOB_DST="/etc/upstart/$JOB_NAME.conf"
RENDER_SRC="$EXT_DIR/integration/render-panel.sh"
RENDER_DST="/mnt/us/extensions/bjtu-native-screensaver/bin/render-panel.sh"
RENDER_BACKUP="$STATE_DIR/render-panel.before-orientation.sh"
ACTION="${1:-install}"

if [ "$(id -u)" != "0" ]; then
    echo "This installer must run as root." >&2
    exit 1
fi

root_rw() {
    if command -v mntroot >/dev/null 2>&1; then
        mntroot rw >/dev/null 2>&1
    else
        mount -o remount,rw / >/dev/null 2>&1
    fi
}

root_ro() {
    sync
    if command -v mntroot >/dev/null 2>&1; then
        mntroot ro >/dev/null 2>&1
    else
        mount -o remount,ro / >/dev/null 2>&1
    fi
}

install_job() {
    root_rw || return 1
    if ! cp -f "$JOB_SRC" "$JOB_DST" || ! chmod 644 "$JOB_DST"; then
        root_ro >/dev/null 2>&1 || true
        return 1
    fi
    root_ro
}

remove_job() {
    root_rw || return 1
    if ! rm -f "$JOB_DST"; then
        root_ro >/dev/null 2>&1 || true
        return 1
    fi
    root_ro
}

install_render_hook() {
    [ -f "$RENDER_SRC" ] && [ -x "$RENDER_DST" ] || return 1
    if [ ! -f "$RENDER_BACKUP" ]; then
        cp "$RENDER_DST" "$RENDER_BACKUP" || return 1
        chmod 700 "$RENDER_BACKUP" || return 1
    fi
    cp "$RENDER_SRC" "$RENDER_DST" || return 1
    chmod 755 "$RENDER_DST"
}

restore_render_hook() {
    if [ -f "$RENDER_BACKUP" ]; then
        cp "$RENDER_BACKUP" "$RENDER_DST" || return 1
        chmod 755 "$RENDER_DST" || return 1
    fi
}

case "$ACTION" in
    install)
        [ -f "$JOB_SRC" ] || { echo "Missing $JOB_SRC" >&2; exit 1; }
        [ -x /mnt/us/extensions/bjtu-native-screensaver/bin/render-panel.sh ] || {
            echo "Install bjtu-native-screensaver first." >&2
            exit 1
        }

        chmod 755 "$EXT_DIR/install.sh" "$EXT_DIR/bin/"*.sh "$RENDER_SRC"
        chmod 644 "$JOB_SRC" "$EXT_DIR/update.conf.example" "$EXT_DIR/config.xml" "$EXT_DIR/menu.json"
        mkdir -p "$EXT_DIR/logs" "$STATE_DIR"
        chmod 700 "$STATE_DIR"

        if [ ! -f "$EXT_DIR/update.conf" ]; then
            cp "$EXT_DIR/update.conf.example" "$EXT_DIR/update.conf"
            chmod 644 "$EXT_DIR/update.conf"
        fi
        if [ ! -f "$STATE_DIR/curl.conf" ]; then
            umask 077
            printf '%s\n' \
                '# curl options stored outside the USB user partition.' \
                '# For a private endpoint, add for example:' \
                '# header = "Authorization: Bearer REPLACE_ME"' \
                > "$STATE_DIR/curl.conf"
        fi
        chmod 600 "$STATE_DIR/curl.conf"

        install_render_hook || {
            echo "Could not install the orientation-aware render hook." >&2
            exit 1
        }

        install_job || { echo "Could not install the Upstart job." >&2; exit 1; }

        touch "$EXT_DIR/enabled"
        /sbin/stop "$JOB_NAME" >/dev/null 2>&1 || true
        if ! /sbin/start "$JOB_NAME" >/dev/null 2>&1; then
            rm -f "$EXT_DIR/enabled"
            echo "The Upstart job was installed but could not be started." >&2
            exit 1
        fi
        echo "installed and enabled"
        ;;
    uninstall|purge)
        rm -f "$EXT_DIR/enabled"
        /sbin/stop "$JOB_NAME" >/dev/null 2>&1 || true
        if [ -f /tmp/bjtu-dashboard-updater.pid ]; then
            PID=$(cat /tmp/bjtu-dashboard-updater.pid 2>/dev/null)
            case "$PID" in
                ''|*[!0-9]*) ;;
                *) kill "$PID" >/dev/null 2>&1 || true ;;
            esac
        fi
        remove_job || { echo "Could not remove the Upstart job." >&2; exit 1; }
        restore_render_hook || {
            echo "Updater removed but the previous render hook could not be restored." >&2
            exit 1
        }
        if [ "$ACTION" = "purge" ]; then
            rm -rf "$STATE_DIR"
            echo "uninstalled and private state removed"
        else
            echo "uninstalled; private state preserved"
        fi
        ;;
    *)
        echo "usage: $0 {install|uninstall|purge}" >&2
        exit 2
        ;;
esac
