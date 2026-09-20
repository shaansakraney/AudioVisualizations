# Firmware — driving an LED strip from the visuals

The Mac decides every color and streams finished RGB frames over WiFi; the
ESP32 is a dumb driver that writes what it's told. Color schemes are therefore
tuned in Python, with no reflashing — and if frames stop arriving for a second,
the sketch falls back to its own breathing animation so the strip never just
goes dead.

```
run.py ──UDP:4210──> ESP32 ──> strip
```

**Setting up a board right now?** [`QUICKSTART.md`](QUICKSTART.md) is the
linear checklist — toolchain, credentials, flashing, the serial-monitor check,
the IP question, and moving the board to a wall socket. This file is the
reference behind it.

## Which sketch?

Identify your strip by its pins — this is the one thing that actually matters:

| Pins | Strip | Sketch | `--led-count` |
|---|---|---|---|
| `5V GND DIN DOUT` | Addressable WS2812/SK6812 | `esp32_udp_ws2812/` | your LED count, e.g. `60` |
| `+12V R G B` | Analog RGB, common anode | `esp32_udp_analog/` | `1` |

Addressable strips show a different color per LED, so the spectrum can spread
across the strip. Analog strips are one color end to end — still very good with
`PulseScene`, and `LedSink` averages the scene's colors down to that one value
automatically. **Nothing on the Python side changes between the two**, so you
can build and test everything before deciding.

A plain Arduino Uno/Nano has no WiFi. If that's what you have, either use an
ESP32 (~$8) or fall back to USB: `--leds serial:///dev/tty.usbmodemXXXX`
(needs `pip install pyserial`).

## Choosing a board

**Buy a classic ESP32 (ESP32-WROOM-32) dev board.** These sketches are written
for it, every tutorial and pinout diagram online matches it, and it's the
cheapest option. Search terms that land on the right thing:

- **ESP32 DevKit V1** (DOIT, 30-pin) — the default, ~$6–8
- **NodeMCU-32S** — same chip, 38-pin, same code
- **ESP32-DevKitC-32E** — Espressif's own, from DigiKey/Mouser if you want a
  known-genuine part
- **Adafruit HUZZAH32 Feather** / **SparkFun ESP32 Thing Plus** — ~$20, better
  regulators and USB-C, worth it if you'd rather not debug a clone

### Minimum specs to check on the listing

| Requirement | Why |
|---|---|
| Chip is **ESP32**, ESP32-S3, or ESP32-C3 | The three that have WiFi *and* enough pins |
| **WiFi 802.11 b/g/n (2.4 GHz)** | The transport. 2.4GHz only — see the SSID trap below |
| **Onboard USB-to-serial** (CP2102 or CH340) + USB port | Otherwise you need a separate FTDI programmer |
| **Headers pre-soldered** | Bare modules need soldering to be breadboardable |
| 4MB flash | Standard on everything above; the sketch is tiny |

### What to avoid

- **ESP32-H2 — has no WiFi at all** (802.15.4/BLE only). The name looks right
  and the board looks identical. This is the one genuine trap.
- **ESP8266** — has WiFi, but it's a different chip; these sketches won't
  compile for it.
- **ESP32-CAM** — no USB port, needs an external programmer to flash.
- **Bare ESP32-WROOM-32 modules** (castellated, no carrier board) — these are
  for reflow, not for you.

### If you buy an S3 or C3 instead

Both work, but they have different pin numbers. In `esp32_udp_analog`, GPIO
25/26/27 don't exist on either — change `PIN_R`/`PIN_G`/`PIN_B` to any three
free output pins. `esp32_udp_ws2812`'s GPIO 5 is fine on all of them.

### Toolchain versions

Install the **latest** of both; the sketches handle the API break:

- **Arduino-ESP32 core 3.x** (current). The LEDC/PWM API changed in 3.0 —
  `esp32_udp_analog` compiles on both 2.x and 3.x via `ESP_ARDUINO_VERSION_MAJOR`.
- **FastLED 3.7.0 or newer** for `esp32_udp_ws2812`. Older FastLED does not
  build against core 3.x.

## Bring-up, in the order that finds problems fastest

**1. Test the Python half with no hardware at all.**

```bash
python tools/led_monitor.py                                   # terminal A
python run.py --leds udp://127.0.0.1:4210 --led-count 16       # terminal B
```

Terminal A becomes a fake strip made of colored blocks. Press `1`–`9` to switch
scenes: `pulse` should be one solid color, `spectrum` a gradient that moves
with the music. If this works, every remaining problem is hardware or network.

**2. Flash the sketch.** Copy `wifi_secrets.example.h` to `wifi_secrets.h`
beside the sketch and fill in your 2.4GHz network (it's gitignored, so
credentials never reach git), set `LED_COUNT` at the top of the `.ino`, upload,
then open Serial Monitor at **115200**. It prints its IP and the
exact command to run:

```
audioviz LED receiver ready
  UDP port  : 4210
  LEDs      : 60

WiFi up
  name : audioviz.local
  IP   : 192.168.1.50  (DHCP -- may change; prefer the name)
```

Before Python is running you should already see the idle breathing animation.
**If you see that, the strip, power, and wiring are all good** — which cleanly
separates hardware problems from networking ones.

**3. Point Python at it.**

```bash
python run.py --source loopback --spotify --leds udp://audioviz.local:4210 --led-count 60
```

Press `h` for the HUD; the `leds` line shows the target and frames sent.

**3b. Once it's on a wall socket, there is no serial monitor.** That's what
`tools/find_leds.py` is for — it resolves the name, reports the address DHCP
handed out, and walks the strip through red/green/blue:

```bash
python tools/find_leds.py --led-count 1
```

**4. Check the fallback.** Quit `run.py`. After ~1 second the strip should
return to breathing, and pick straight back up when you restart.

## Addressing — why it's a name, not an IP

The board takes its address from **DHCP**, like everything else on your
network, and the router is free to hand it a different one each time it boots
— which is exactly what happens when you unplug it from the wall and plug it
back in. So nothing here refers to it by IP. Instead it registers a fixed
**mDNS name** and you point Python at that:

```bash
python run.py --leds udp://audioviz.local:4210 --led-count 1
```

`audioviz.local` resolves to whatever DHCP just gave it, so the command line
keeps working across reboots, lease changes and moving the board to another
room. The name is the `HOSTNAME` define at the top of each sketch; change it
only if you run two boards, and give the second one its own name.

The Python side resolves that name on a thread of its own and re-checks it
every 30 seconds, because a failed `.local` lookup on macOS blocks for a full
5 seconds and the sender thread can't afford that. Consequences worth knowing:

- You can start `run.py` **before** the board has joined; the strip picks up
  within ~5s of it appearing, with no restart.
- If the board's address changes while `run.py` is running, the strip
  resumes within ~30s on its own.
- The raw IP still works (`--leds udp://192.168.1.50:4210`) and skips
  resolution entirely — useful if mDNS is blocked on your network.

Connection is non-blocking on the firmware side too: the board runs its idle
animation while it joins, so plugging it into the wall before the router has
finished booting is fine, and it rejoins by itself if WiFi drops.

## Wiring

Both cases need the ESP32's ground tied to the power supply's ground, and
neither strip should be powered from the ESP32's onboard regulator.

**WS2812 (5V):** data on GPIO 5 through a 330Ω resistor placed near the strip,
1000µF across 5V/GND, and a 5V supply sized for ~60mA per LED at full white.
The ESP32's 3.3V data usually drives it fine; if the first LED flickers or
shows wrong colors, add a 74AHCT125 level shifter — that's the usual cause.

**Analog 12V:** one N-channel MOSFET per channel, low-side switched, gates on
GPIO 25/26/27 through ~150Ω with a 10k pulldown to GND. Use **logic-level**
MOSFETs — IRLZ44N or IRLB8721. A standard IRF540 wants ~10V on the gate and
will only partly turn on from 3.3V: dim output, hot transistor. A ready-made
3-channel MOSFET driver board handles all of this.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Never connects to WiFi (dots forever) | ESP32s are **2.4GHz only**. If your router presents one merged SSID, the Mac may be on 5GHz and the ESP32 can't join at all — enable the 2.4GHz band or use a separate SSID for it. Also check the password and that it's not a captive-portal/guest network. |
| Idle breathing never stops | Connected, but frames aren't arriving. The two devices are on different networks/VLANs, or macOS firewall is blocking outbound UDP. |
| `audioviz.local` never resolves | `ping audioviz.local` from the Mac. If that fails but the serial monitor shows an IP, mDNS is being blocked (guest networks and some mesh routers do this) — use the IP directly, or give the board a DHCP reservation in the router so the IP stops moving. |
| Strip stays dark, no idle either | Power or wiring. Confirm the sketch reached "ready" on serial. |
| Only part of the strip lights | `--led-count` is lower than `LED_COUNT` in the sketch. Make them match. |
| Full brightness when silent, dark when loud | Analog only: flip `INVERT_OUTPUT` — you have a common-cathode strip or an inverting driver. |
| First LED glitches, others fine | WS2812 level shifting — see above. |
| Colors are washed out / everything looks white | Press `l` in the window and lower **brightness**, or raise **gamma**. |
| Reacts but doesn't pulse on the beat | Beat detection isn't firing, not an LED problem: check the HUD's beat dot and tune `BEAT_SENSITIVITY` in `features.py`. (Check **beat gain** in the `l` panel isn't at 0 first.) |
| `tools/led_monitor.py` reports drops climbing fast | Weak WiFi. A few drops are normal and invisible on a real strip. |

## Changing the protocol

The frame format is defined in three places that must agree: the encoder in
`led.py`, and the **byte-identical copies** of `av_proto.h` in each sketch
folder. The duplication is forced by the Arduino IDE, which only compiles
headers sitting beside the `.ino` — if you edit one, copy it to the other:

```bash
cp firmware/esp32_udp_ws2812/av_proto.h firmware/esp32_udp_analog/av_proto.h
```

`av_net.h` — the WiFi/mDNS bring-up both sketches share — is duplicated for
the same reason and under the same rule.
