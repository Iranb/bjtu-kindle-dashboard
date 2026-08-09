# BJTU Kindle Dashboard

![Dashboard preview](assets/dashboard-preview.png)

A data-driven, grayscale cluster dashboard for a Kindle Paperwhite 3. Edit one
JSON file, render a pixel-accurate 1072 × 1448 PNG, and optionally deploy it to
a jailbroken Kindle over SSH.

## Features

- Updates GPU, CPU and job counters from JSON.
- Rebuilds GPU and per-node capacity blocks automatically.
- Updates four node states and six account activity cards.
- Produces an 8-bit grayscale PNG optimized for a PW3 display.
- Supports a blank header for the native sleep hook or standalone time,
  date and battery rendering.
- Can deploy and refresh the image through an existing SSH alias.

## Install

```bash
python -m pip install -r requirements.txt
```

The renderer looks for Arial and Georgia on Windows, Liberation fonts on
Linux, and common macOS system fonts.

## Update the data

Edit [`data/dashboard.json`](data/dashboard.json), then render:

```bash
python scripts/update_dashboard.py data/dashboard.json \
  --output panel-base.png
```

Use values from the JSON header in a standalone image:

```bash
python scripts/update_dashboard.py data/dashboard.json \
  --header-mode data \
  --output dashboard.png
```

Use the computer's current time and date:

```bash
python scripts/update_dashboard.py data/dashboard.json \
  --header-mode now \
  --output dashboard.png
```

## Deploy to Kindle

With an SSH alias such as `kindle-pw3` already configured:

```bash
python scripts/update_dashboard.py data/dashboard.json \
  --output panel-base.png \
  --deploy kindle-pw3
```

The default deployment target is:

```text
/mnt/us/extensions/bjtu-native-screensaver/assets/panel-base.png
```

The command then runs the installed native screen hook's `render-panel.sh`.
Override either path with `--remote-image` and `--remote-render`.

## Data layout

- `accounts` must contain six entries. Entries 1–3 are placed in the left
  column and entries 4–6 in the right column.
- Account status is one of `HEALTHY`, `WAITING`, or `SIGN-IN`.
- `nodes` must contain four entries; block widths adapt to each node's total.
- `gpus_free` cannot exceed `gpus_total`.

## Test

```bash
python -m unittest discover -s tests -v
```

## Kindle framebuffer capture

The image below was captured from the Kindle framebuffer after deployment:

![Kindle framebuffer](assets/kindle-framebuffer.png)

## License

MIT
