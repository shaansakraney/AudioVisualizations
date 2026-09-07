// esp32_udp_ws2812.ino
// ---------------------------------------------------------------------------
// audioviz LED receiver for an ADDRESSABLE strip (WS2812 / WS2812B / SK6812 --
// the 4-wire kind whose pins are 5V, GND, DIN, DOUT).
//
// The Mac decides every color; this sketch is a dumb driver. If frames stop
// arriving for AV_IDLE_TIMEOUT_MS it falls back to its own breathing
// animation, so the strip never just goes dead when you quit run.py.
//
// SETUP
//   1. Arduino IDE -> Boards Manager -> install "esp32" by Espressif.
//   2. Library Manager -> install "FastLED".
//   3. Fill in WIFI_SSID / WIFI_PASS / LED_COUNT below.
//   4. Upload, then open Serial Monitor at 115200 -- it prints its IP address.
//   5. On the Mac:
//        python run.py --source mic --leds udp://<that-ip>:4210 --led-count <LED_COUNT>
//
// WIRING
//   DIN  <- GPIO 5 (through a 330 ohm resistor, close to the strip)
//   GND  <- ESP32 GND *and* the power supply ground (common ground is required)
//   5V   <- 5V supply rated for ~60mA per LED at full white. Do NOT power a
//           full strip from the ESP32's onboard regulator.
//   Add a 1000uF capacitor across the strip's 5V/GND to absorb inrush.
//
//   The ESP32's data pin is 3.3V and WS2812 wants ~0.7*5V = 3.5V. It usually
//   works anyway; if the first LED flickers or shows wrong colors, add a
//   74AHCT125 level shifter on the data line. That is the single most common
//   cause of "it mostly works but glitches".
// ---------------------------------------------------------------------------

#include <WiFi.h>
#include <WiFiUdp.h>
#include <FastLED.h>
#include "av_proto.h"

// ---- configure me ---------------------------------------------------------
static const char *WIFI_SSID = "YOUR_WIFI_NAME";
static const char *WIFI_PASS = "YOUR_WIFI_PASSWORD";

#define LED_PIN     5
#define LED_COUNT   60      // must match --led-count on the Python side
#define UDP_PORT    4210
#define MAX_MILLIAMPS 2000  // FastLED brownout guard; match your PSU
// ---------------------------------------------------------------------------

CRGB leds[LED_COUNT];
WiFiUDP udp;

static uint8_t  packet[AV_HEADER_SIZE + LED_COUNT * 3 + 16];
static uint32_t lastFrameMs = 0;
static uint8_t  lastSeq     = 0;
static bool     haveSeq     = false;
static uint32_t framesRx = 0, framesDropped = 0;

void setup() {
  Serial.begin(115200);
  delay(200);

  FastLED.addLeds<WS2812B, LED_PIN, GRB>(leds, LED_COUNT);
  FastLED.setMaxPowerInVoltsAndMilliamps(5, MAX_MILLIAMPS);
  FastLED.clear(true);

  Serial.printf("\nconnecting to %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  udp.begin(UDP_PORT);

  Serial.printf("\n\naudioviz LED receiver ready\n");
  Serial.printf("  IP        : %s\n", WiFi.localIP().toString().c_str());
  Serial.printf("  UDP port  : %d\n", UDP_PORT);
  Serial.printf("  LEDs      : %d\n", LED_COUNT);
  Serial.printf("\n  run: python run.py --leds udp://%s:%d --led-count %d\n\n",
                WiFi.localIP().toString().c_str(), UDP_PORT, LED_COUNT);
}

void loop() {
  int size = udp.parsePacket();
  if (size > 0) {
    int len = udp.read(packet, sizeof(packet));
    AvFrame frame;
    if (len > 0 && avParse(packet, (size_t)len, &frame)) {
      // sequence gap = packets lost in flight. A trickle is normal on WiFi
      // and invisible on the strip; a flood means a bad network path.
      if (haveSeq) framesDropped += (uint8_t)(frame.seq - lastSeq - 1);
      lastSeq = frame.seq;
      haveSeq = true;
      framesRx++;

      // The strip is the authority on length: honor whichever is smaller so a
      // --led-count mismatch dims part of the strip instead of overrunning.
      uint16_t n = frame.count < LED_COUNT ? frame.count : LED_COUNT;
      for (uint16_t i = 0; i < n; i++) {
        leds[i] = CRGB(frame.rgb[i * 3], frame.rgb[i * 3 + 1], frame.rgb[i * 3 + 2]);
      }
      for (uint16_t i = n; i < LED_COUNT; i++) leds[i] = CRGB::Black;

      FastLED.show();
      lastFrameMs = millis();

      if ((framesRx % 600) == 0) {   // ~every 10s at 60fps
        Serial.printf("frames=%lu dropped=%lu\n", framesRx, framesDropped);
      }
    }
    return;
  }

  // ---- fallback: nobody is driving us, so drive ourselves -----------------
  if (millis() - lastFrameMs > AV_IDLE_TIMEOUT_MS) {
    uint8_t v   = avIdleBreath(millis());
    uint8_t hue = (uint8_t)((millis() / 60) & 0xFF);   // slow hue drift
    for (uint16_t i = 0; i < LED_COUNT; i++) {
      leds[i] = CHSV(hue + (uint8_t)(i * 2), 200, v);
    }
    FastLED.show();
    delay(16);
    haveSeq = false;   // don't count the gap as drops when Python returns
  }
}
