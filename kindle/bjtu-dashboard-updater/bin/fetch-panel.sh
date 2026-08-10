#!/bin/sh

. /mnt/us/extensions/bjtu-dashboard-updater/bin/common.sh
load_config

INCOMING="$SCREENSAVER_DIR/assets/panel-base.png.incoming.$$"
HEADERS="/tmp/bjtu-dashboard-updater-headers.$$"
LOCK_OWNED=0

cleanup() {
    rm -f "$INCOMING" "$HEADERS"
    if [ "$LOCK_OWNED" -eq 1 ]; then
        rmdir "$FETCH_LOCK_DIR" >/dev/null 2>&1 || true
    fi
}

trap cleanup 0 1 2 15

fail() {
    log "fetch result=fail step=$1"
    write_state "$LAST_RESULT_FILE" "fail:$1:$(now_epoch)" >/dev/null 2>&1 || true
    exit 1
}

if mkdir "$FETCH_LOCK_DIR" 2>/dev/null; then
    LOCK_OWNED=1
else
    log "fetch result=cancelled reason=already_running"
    exit 20
fi

save_response_etag() {
    RESPONSE_ETAG=$(grep -i '^ETag:' "$HEADERS" 2>/dev/null | tail -n 1 | cut -d: -f2- | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    if [ -n "$RESPONSE_ETAG" ] && [ "${#RESPONSE_ETAG}" -le 256 ]; then
        write_state "$ETAG_FILE" "$RESPONSE_ETAG" >/dev/null 2>&1 || true
    fi
}

validate_png() {
    set -- $(od -An -tu1 -N26 "$1" 2>/dev/null)
    [ "$#" -eq 26 ] || return 1
    [ "$1" = 137 ] && [ "$2" = 80 ] && [ "$3" = 78 ] && [ "$4" = 71 ] || return 1
    [ "$5" = 13 ] && [ "$6" = 10 ] && [ "$7" = 26 ] && [ "$8" = 10 ] || return 1
    [ "${13}" = 73 ] && [ "${14}" = 72 ] && [ "${15}" = 68 ] && [ "${16}" = 82 ] || return 1

    WIDTH=$(( ${17} * 16777216 + ${18} * 65536 + ${19} * 256 + ${20} ))
    HEIGHT=$(( ${21} * 16777216 + ${22} * 65536 + ${23} * 256 + ${24} ))
    BIT_DEPTH="${25}"
    COLOR_TYPE="${26}"

    [ "$WIDTH" -eq 1072 ] && [ "$HEIGHT" -eq 1448 ] || return 1
    [ "$BIT_DEPTH" -eq 8 ] && [ "$COLOR_TYPE" -eq 0 ] || return 1
}

[ -n "$UPDATE_URL" ] || fail "missing_url"
case "$UPDATE_URL" in
    https://*) CURL_PROTO='=https' ;;
    http://*)
        [ "$ALLOW_HTTP" = "1" ] || fail "http_disabled"
        CURL_PROTO='=http,https'
        ;;
    *) fail "invalid_url_scheme" ;;
esac

[ -x /usr/bin/curl ] || fail "curl_missing"
[ -f "$CURL_CONFIG_FILE" ] || fail "curl_config_missing"
[ -d "$SCREENSAVER_DIR/assets" ] || fail "asset_directory_missing"

ETAG=""
if [ -f "$ETAG_FILE" ]; then
    ETAG=$(tr -d '\r\n' < "$ETAG_FILE" | cut -c1-256)
fi

log "fetch result=started"
if [ -n "$ETAG" ]; then
    HTTP_CODE=$(/usr/bin/curl \
        --config "$CURL_CONFIG_FILE" \
        --proto "$CURL_PROTO" \
        --tlsv1.2 \
        --connect-timeout "$WIFI_CONNECT_TIMEOUT_SECONDS" \
        --max-time "$DOWNLOAD_TIMEOUT_SECONDS" \
        --fail --silent --show-error \
        --header "If-None-Match: $ETAG" \
        --dump-header "$HEADERS" \
        --output "$INCOMING" \
        --write-out '%{http_code}' \
        "$UPDATE_URL" 2>> "$LOG_FILE")
else
    HTTP_CODE=$(/usr/bin/curl \
        --config "$CURL_CONFIG_FILE" \
        --proto "$CURL_PROTO" \
        --tlsv1.2 \
        --connect-timeout "$WIFI_CONNECT_TIMEOUT_SECONDS" \
        --max-time "$DOWNLOAD_TIMEOUT_SECONDS" \
        --fail --silent --show-error \
        --dump-header "$HEADERS" \
        --output "$INCOMING" \
        --write-out '%{http_code}' \
        "$UPDATE_URL" 2>> "$LOG_FILE")
fi
CURL_RC=$?

[ "$CURL_RC" -eq 0 ] || fail "curl_$CURL_RC"
case "$HTTP_CODE" in
    304)
        save_response_etag
        write_state "$LAST_SUCCESS_FILE" "$(now_epoch)" >/dev/null 2>&1 || true
        write_state "$LAST_RESULT_FILE" "not-modified:$(now_epoch)" >/dev/null 2>&1 || true
        log "fetch result=not_modified http=304"
        exit 0
        ;;
    200) ;;
    *) fail "http_$HTTP_CODE" ;;
esac

[ -f "$INCOMING" ] || fail "response_missing"
SIZE=$(wc -c < "$INCOMING" 2>/dev/null)
is_uint "$SIZE" || fail "size_invalid"
[ "$SIZE" -gt 0 ] && [ "$SIZE" -le "$MAX_IMAGE_BYTES" ] || fail "size_out_of_range"

CONTENT_TYPE=$(grep -i '^Content-Type:' "$HEADERS" 2>/dev/null | tail -n 1 | cut -d: -f2- | tr -d '\r' | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//;s/[;[:space:]].*$//')
[ "$CONTENT_TYPE" = "image/png" ] || fail "content_type"
validate_png "$INCOMING" || fail "png_validation"

NEW_HASH=$(sha256sum "$INCOMING" 2>/dev/null | awk '{print $1}')
[ -n "$NEW_HASH" ] || fail "hash_failed"
OLD_HASH=""
if [ -f "$ASSET" ]; then
    OLD_HASH=$(sha256sum "$ASSET" 2>/dev/null | awk '{print $1}')
fi

if [ "$NEW_HASH" = "$OLD_HASH" ]; then
    save_response_etag
    write_state "$LAST_SUCCESS_FILE" "$(now_epoch)" >/dev/null 2>&1 || true
    write_state "$LAST_RESULT_FILE" "unchanged:$(now_epoch)" >/dev/null 2>&1 || true
    log "fetch result=unchanged http=200 bytes=$SIZE"
    exit 0
fi

if [ "${BJTU_ALLOW_ACTIVE:-0}" != "1" ] && [ "$(power_state)" = "active" ]; then
    log "fetch result=cancelled reason=user_active"
    exit 20
fi

chmod 644 "$INCOMING" || fail "chmod"
mv -f "$INCOMING" "$ASSET" || fail "atomic_replace"
save_response_etag
write_state "$STATE_DIR/last-hash" "$NEW_HASH" >/dev/null 2>&1 || true
write_state "$LAST_SUCCESS_FILE" "$(now_epoch)" >/dev/null 2>&1 || true

if [ "${BJTU_NO_RENDER:-0}" != "1" ] && [ "$(power_state)" != "active" ]; then
    "$RENDER" >> "$LOG_FILE" 2>&1 || fail "render"
    RESULT="updated-rendered"
else
    RESULT="updated-deferred-render"
fi

write_state "$LAST_RESULT_FILE" "$RESULT:$(now_epoch)" >/dev/null 2>&1 || true
log "fetch result=$RESULT http=200 bytes=$SIZE"
exit 0
