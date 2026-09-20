# Quick start — a new ESP32, from box to wall socket

The linear path for a board you just unboxed. `README.md` next to this file is
the reference (which sketch, which board to buy, wiring, protocol); this is the
checklist. Budget ~20 minutes the first time, ~3 minutes for every board after.

Two rules that explain most of what follows:

- **Flash and test on USB first, move to the wall last.** The serial monitor is
  the only thing that tells you *why* something failed, and it disappears the
  moment the board is on a wall socket.
- **The board is addressed by name, not IP.** It stays on DHCP and answers to
  `audioviz.local`, so nothing you type here goes stale when the router hands
  it a new address. Step 6 covers the IP anyway, for the networks where mDNS
  is blocked.

---

## 1. Install the toolchain (once per Mac)

1. Install the [Arduino IDE](https://www.arduino.cc/en/software).
2. **Boards Manager** (the chip icon) → search `esp32` → install **esp32 by
   Espressif**. Take the latest 3.x.
3. **Library Manager** (the books icon) → install **FastLED**, 3.7.0 or newer.
   *Addressable strips only — skip it for an analog 12V strip.*

Older FastLED will not build against core 3.x, so if the upload fails with
FastLED errors, that mismatch is the reason.

## 2. Pick your sketch

By the strip's pins, not by its description:

| Strip pins | Open | `--led-count` |
|---|---|---|
| `5V GND DIN DOUT` (WS2812/SK6812) | `firmware/esp32_udp_ws2812/esp32_udp_ws2812.ino` | your LED count, e.g. `60` |
| `+12V R G B` (analog, common anode) | `firmware/esp32_udp_analog/esp32_udp_analog.ino` | `1` |

Open the `.ino` by **double-clicking it** — the Arduino IDE compiles only the
headers sitting beside it, so opening the folder's file is what pulls in
`av_proto.h` and `av_net.h`.

## 3. Put in your WiFi credentials

Credentials live in a gitignored file beside the sketch, never in the `.ino`:

```bash
cd firmware/esp32_udp_ws2812          # or esp32_udp_analog
cp wifi_secrets.example.h wifi_secrets.h
```

Edit `wifi_secrets.h`:

```c
#define WIFI_SSID_VALUE "YourNetwork"
#define WIFI_PASS_VALUE "YourPassword"
```

**It must be a 2.4GHz network.** ESP32s have no 5GHz radio at all. If your
router merges both bands under one SSID it usually still works, but a network
that is 5GHz-only, a guest network, or anything with a captive portal will
never connect.

Then, in the `.ino` itself, under `---- configure me ----`:

- **`LED_COUNT`** (WS2812 only) — the real number of LEDs. It must match
  `--led-count` on the Mac later.
- **`HOSTNAME`** — leave it as `audioviz` **unless this is your second board**,
  in which case give it its own name (`audioviz2`, `desk`, …). Two boards
  answering to one name is a genuinely confusing failure.
- **`INVERT_OUTPUT`** (analog only) — leave `false` for now; step 7 says when
  to flip it.

## 4. Flash it over USB

1. Plug the board into the Mac with a **data** USB cable. Charge-only cables
   are a real and silent failure — if no port appears, try another cable first.
2. **Tools → Board** → *ESP32 Dev Module* (or your specific board).
3. **Tools → Port** → the `/dev/cu.usbserial-*` or `/dev/cu.SLAB_USBtoUART`
   entry that appeared when you plugged it in.
4. Click **Upload**.

If it hangs on `Connecting........_____`, hold the board's **BOOT** button
while the upload starts and let go once it says `Writing`. Some clones need
this every time; it's normal.

## 5. Read the serial monitor — this is the whole verification step

**Tools → Serial Monitor**, set the baud dropdown to **115200**, then tap the
board's **EN/RST** button so you see the boot from the start:

```
audioviz LED receiver ready
  UDP port  : 4210
  LEDs      : 60

WiFi up
  name : audioviz.local
  IP   : 192.168.1.50  (DHCP -- may change; prefer the name)
```

Two things to confirm here, in this order:

- **The strip is breathing** before any Python runs. That is the firmware's
  built-in idle animation, and seeing it means power, wiring and the sketch are
  all good — every remaining problem is network-side.
- **`WiFi up` appears with a name and an IP.** Dots forever means the radio
  never joined: re-check step 3, especially the 2.4GHz requirement.

## 6. About that IP — save it or ignore it

Normally you **ignore it** and use `audioviz.local` everywhere. The board is on
DHCP by design: it lives on a wall socket, gets unplugged, and comes back with
whatever address the router feels like. The mDNS name absorbs that.

Verify the name works before you trust it:

```bash
ping audioviz.local
```

If that answers, you're done here — skip to step 7.

If it *doesn't* answer but the serial monitor showed an IP, mDNS is blocked on
your network (some mesh routers and most guest networks do this). Then you do
want the address pinned, and the right place is the router, not the sketch:

1. Note the MAC address the router shows for the `audioviz` lease.
2. In the router's admin page, add a **DHCP reservation** for it.
3. Use the raw IP on the Mac: `--leds udp://192.168.1.50:4210`. Python skips
   name resolution entirely, which is also slightly faster to start.

A static IP configured *on the board* is deliberately not an option here — it
is one more thing to get wrong on every new network.

## 7. Prove it end to end, still on USB

Leave the board plugged into the Mac and run:

```bash
python tools/find_leds.py --led-count 60     # 1 for an analog strip
```

It waits for the name to resolve, pings the address DHCP gave out, then drives
the strip solid **red → green → blue**. Getting those three colors in that
order means network, firmware, wiring and channel order are all correct.

Wrong colors on an analog strip (green where red should be) means the R/G/B
gate wires are swapped — fix the wiring, or swap `PIN_R`/`PIN_G`/`PIN_B`.
Everything full-on when it should be dark means you have a common-cathode strip
or an inverting driver: set `INVERT_OUTPUT true` and reflash.

Then run the real thing:

```bash
python run.py --source loopback --spotify --leds udp://audioviz.local:4210 --led-count 60
```

Press `h` for the HUD — the `leds` line shows the target and the frame count
climbing. Press `l` for the tuning panel (brightness, gamma, color scheme).

Last check: quit `run.py`. After ~1 second the strip should return to
breathing, and pick straight back up when you restart it.

## 8. Move it to the wall

Unplug from the Mac, plug into a USB wall adapter (5V, 1A or better) near the
strip. Nothing needs reconfiguring — the board rejoins WiFi by itself, and
joining is non-blocking, so plugging it in before the router has finished
booting is fine.

There is no serial monitor now, which is exactly what `find_leds.py` replaces:

```bash
python tools/find_leds.py --led-count 60
```

Same command as step 7. If it resolves and the strip walks R/G/B, the board is
up on wall power and your normal `run.py` command line works unchanged —
across reboots, lease changes, and moving the board to another room.

---

## If something's wrong

| Symptom | First thing to check |
|---|---|
| No port in **Tools → Port** | Charge-only USB cable, or missing CP2102/CH340 driver |
| Upload hangs on `Connecting...` | Hold **BOOT** while the upload starts |
| Dots forever, never `WiFi up` | 2.4GHz only; check SSID/password in `wifi_secrets.h` |
| `WiFi up`, but strip never stops breathing | Frames aren't arriving: different VLAN/network, or the macOS firewall is blocking outbound UDP |
| `audioviz.local` won't resolve | mDNS blocked — use the raw IP (step 6) |
| Strip dark, no idle animation either | Power or wiring; the sketch never reached "ready" |
| Only part of the strip lights | `--led-count` is lower than `LED_COUNT` in the sketch |
| First LED glitches, rest fine | WS2812 level shifting — 74AHCT125, see `README.md` |

The full table, plus wiring diagrams and parts, is in
[`README.md`](README.md).
