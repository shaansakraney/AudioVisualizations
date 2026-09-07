# Firmware — driving an LED strip from the visuals

The Mac decides every color and streams finished RGB frames over WiFi; the
ESP32 is a dumb driver that writes what it's told. Color schemes are therefore
tuned in Python, with no reflashing — and if frames stop arriving for a second,
the sketch falls back to its own breathing animation so the strip never just
goes dead.

```
run.py ──UDP:4210──> ESP32 ──> strip
```

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

**2. Flash the sketch.** Fill in `WIFI_SSID` / `WIFI_PASS` / `LED_COUNT` at the
top, upload, then open Serial Monitor at **115200**. It prints its IP and the
exact command to run:

```
audioviz LED receiver ready
  IP        : 192.168.1.50
  run: python run.py --leds udp://192.168.1.50:4210 --led-count 60
```

Before Python is running you should already see the idle breathing animation.
**If you see that, the strip, power, and wiring are all good** — which cleanly
separates hardware problems from networking ones.

**3. Point Python at it.**

```bash
python run.py --source loopback --spotify --leds udp://192.168.1.50:4210 --led-count 60
```

Press `h` for the HUD; the `leds` line shows the target and frames sent.

**4. Check the fallback.** Quit `run.py`. After ~1 second the strip should
return to breathing, and pick straight back up when you restart.

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
| Idle breathing never stops | Connected, but frames aren't arriving. Wrong IP, the two devices are on different networks/VLANs, or macOS firewall is blocking outbound UDP. |
| Strip stays dark, no idle either | Power or wiring. Confirm the sketch reached "ready" on serial. |
| Only part of the strip lights | `--led-count` is lower than `LED_COUNT` in the sketch. Make them match. |
| Full brightness when silent, dark when loud | Analog only: flip `INVERT_OUTPUT` — you have a common-cathode strip or an inverting driver. |
| First LED glitches, others fine | WS2812 level shifting — see above. |
| Colors are washed out / everything looks white | Lower `--led-brightness`, or raise `GAMMA` in `led.py`. |
| Reacts but doesn't pulse on the beat | Beat detection isn't firing, not an LED problem: check the HUD's beat dot and tune `BEAT_SENSITIVITY` in `features.py`. |
| HUD `dropped` climbing fast | Weak WiFi. A few drops are normal and invisible. |

## Changing the protocol

The frame format is defined in three places that must agree: the encoder in
`led.py`, and the **byte-identical copies** of `av_proto.h` in each sketch
folder. The duplication is forced by the Arduino IDE, which only compiles
headers sitting beside the `.ino` — if you edit one, copy it to the other:

```bash
cp firmware/esp32_udp_ws2812/av_proto.h firmware/esp32_udp_analog/av_proto.h
```
