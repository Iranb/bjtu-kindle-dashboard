# Kindle scheduled updater payload

This directory is copied to:

```text
/mnt/us/extensions/bjtu-dashboard-updater
```

Install it after `bjtu-native-screensaver`:

```sh
/bin/sh /mnt/us/extensions/bjtu-dashboard-updater/install.sh install
```

The installer creates a separate Upstart service and stores private curl options in
`/var/local/bjtu-dashboard/curl.conf` with mode `0600`. `update.conf` is USB-visible
and must never contain a token. The root service parses it as data rather than shell:
only the keys in `update.conf.example` are accepted, duplicates and shell syntax are
rejected, and integer values must fall within these inclusive ranges:

| Setting | Range |
| --- | ---: |
| `BATTERY_INTERVAL_SECONDS` | 180–604800 |
| `CHARGING_INTERVAL_SECONDS` | 180–86400 |
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

Useful commands:

```sh
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh status
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh fetch-now
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh test 180
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh disable
```

The normal service never simulates a power-button event. The explicit `test` command
does so once to enter the screensaver and validate a short RTC cycle.
