# Kindle scheduled updater payload

This directory is copied to:

```text
/mnt/us/extensions/bjtu-dashboard-updater
```

Install it after `bjtu-native-screensaver`:

```sh
/bin/sh /mnt/us/extensions/bjtu-dashboard-updater/install.sh install
```

KUAL discovers this extension through `config.xml`, which registers the
dynamic `menu.json`. Reopen KUAL after first deployment so it rescans the
extensions directory.

The installer creates a separate Upstart service and stores private curl options in
`/var/local/bjtu-dashboard/curl.conf` with mode `0600`. `update.conf` is USB-visible
and must never contain a token. The root service parses it as data rather than shell:
only the keys in `update.conf.example` are accepted, duplicates and shell syntax are
rejected, and integer values must fall within these inclusive ranges:

| Setting | Range |
| --- | ---: |
| `DISPLAY_ORIENTATION` | `portrait` or `right` |
| `DISPLAY_CONTENT_MODE` | `dashboard` or `calendar` |
| `BATTERY_INTERVAL_SECONDS` | 180–604800 |
| `CHARGING_INTERVAL_SECONDS` | 180–86400 |
| `CHARGING_KEEP_AWAKE` | 0 or 1 |
| `KEEP_AWAKE_GRACE_SECONDS` | 60–3600 |
| `KEEP_AWAKE_RENEW_SECONDS` | 10–600 and less than grace |
| `LOW_BATTERY_PERCENT` | 0–100 |
| `MIN_RTC_SECONDS` | 60–86400 |
| `RTC_FINAL_DELAY_SECONDS` | 0–30 |
| `WAKE_EARLY_TOLERANCE_SECONDS` | 0–3600 |
| `WIFI_CONNECT_TIMEOUT_SECONDS` | 1–300 |
| `DOWNLOAD_TIMEOUT_SECONDS` | 1–600 |
| `NETWORK_WINDOW_TIMEOUT_SECONDS` | 1–900 |
| `MAX_IMAGE_BYTES` | 1024–16777216 |
| each failure backoff | 60–604800 |
| `ALLOW_HTTP` | 0 or 1 |

Numeric values use canonical decimal form without a sign or leading zero. URLs may
be empty or begin with `https://`/`http://`, are limited to 2048 visible characters,
use a conservative ASCII URL-character allowlist, and HTTP still requires
`ALLOW_HTTP=1`.

`UPDATE_URL` serves the portrait image and `UPDATE_URL_RIGHT` serves the
clockwise-placement image. A direction change never reuses the other mode's
ETag: it forces one full validated fetch before the root-private orientation
state changes.

`UPDATE_URL_CALENDAR` and `UPDATE_URL_CALENDAR_RIGHT` select authenticated month-view
images. Their Bearer header belongs only in root-owned `curl.conf`; calendar
titles must never be placed in `update.conf` or logs. An ETag is reused only
when both orientation and content mode match the root-private applied state.

Useful commands:

```sh
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh status
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh fetch-now
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh orientation portrait
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh orientation right
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh orientation toggle
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh calendar toggle
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh calendar on
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh calendar off
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh disable
```

The service never simulates a power-button event. RTC tests require the user to lock
the device. While locked and charging, the default configuration renews a short
`suspendGrace`: the screen remains in screen-saver mode, Wi-Fi stays reachable, and
ETag checks run every five minutes. Unlocking releases the hold immediately; unplugging
releases it on the next 30-second watchdog tick. If the daemon dies, the 120-second
grace expires without leaving a permanent power-management override.

The default timing profile is five minutes while charging, one hour between battery
RTC updates, a three-minute minimum RTC delay, two seconds before the final RTC write,
60 seconds of wake-classification tolerance, 45 seconds for Wi-Fi, 30 seconds for the
download, and a 60-second post-connect network-window deadline.
