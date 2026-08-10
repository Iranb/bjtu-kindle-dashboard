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
and must never contain a token.

Useful commands:

```sh
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh status
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh fetch-now
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh test 180
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh disable
```

The normal service never simulates a power-button event. The explicit `test` command
does so once to enter the screensaver and validate a short RTC cycle.
