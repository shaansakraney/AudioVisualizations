// esp32_udp_analog.ino
// ---------------------------------------------------------------------------
// audioviz LED receiver for an ANALOG 12V RGB strip -- the 4-pin kind labeled
// +12V / R / G / B (common anode). The whole strip is ONE color at a time, so
// this sketch only uses pixel 0 of each frame. Run Python with --led-count 1
// and LedSink averages the scene's colors down for you.
//
// SETUP
//   1. Arduino IDE -> Boards Manager -> install "esp32" by Espressif.
//   2. cp wifi_secrets.example.h wifi_secrets.h and fill in your network.
//      (No FastLED needed here.)
//   3. Upload, open Serial Monitor at 115200 -- it prints its name and IP.
//   4. On the Mac (the NAME, not the IP -- see HOSTNAME below):
//        python run.py --source mic --leds udp://audioviz.local:4210 --led-count 1
//   Step by step, including moving the board to a wall socket:
//   firmware/QUICKSTART.md
//
// WIRING -- read this before buying parts
//   An ESP32 pin sources ~20mA at 3.3V; a 12V strip draws amps. You need one
//   N-channel MOSFET per channel, low-side switched:
//
//     12V PSU (+) ---> strip +12V pin
//     strip R -------> MOSFET#1 drain
//     strip G -------> MOSFET#2 drain
//     strip B -------> MOSFET#3 drain
//     each MOSFET source ---> GND (shared with ESP32 GND and PSU GND)
//     each MOSFET gate   ---> its GPIO below, through ~150 ohm
//     plus a 10k resistor from each gate to GND (holds it off during boot)
//
//   Use LOGIC-LEVEL MOSFETs -- IRLZ44N or IRLB8721. A plain IRF540 needs ~10V
//   on the gate and will only partly turn on from 3.3V: dim output and a very
//   hot transistor. This is the #1 mistake with these strips.
//
//   Common ground between the 12V supply and the ESP32 is mandatory.
//   An off-the-shelf 3-channel MOSFET driver board does all of the above.
// ---------------------------------------------------------------------------

#include <WiFi.h>
#include <WiFiUdp.h>
#include "av_proto.h"
#include "av_net.h"

// ---- configure me ---------------------------------------------------------
// Credentials live in wifi_secrets.h beside this file (gitignored) so they
// never reach git: copy wifi_secrets.example.h to wifi_secrets.h and fill it in.
#if __has_include("wifi_secrets.h")
  #include "wifi_secrets.h"
#else
  #define WIFI_SSID_VALUE "YOUR_WIFI_NAME"
  #define WIFI_PASS_VALUE "YOUR_WIFI_PASSWORD"
#endif
static const char *WIFI_SSID = WIFI_SSID_VALUE;
static const char *WIFI_PASS = WIFI_PASS_VALUE;

#define PIN_R     25
#define PIN_G     26
#define PIN_B     27
#define UDP_PORT  4210

// The board's name on the network. It takes its ADDRESS from DHCP as usual,
// but answers to <HOSTNAME>.local over mDNS, so unplugging it from the wall
// and plugging it back in can't invalidate your command line even if the
// router hands out a different IP. Change it only if you run two of these.
#define HOSTNAME  "audioviz"

// Set true if your strip is COMMON CATHODE (pins are GND/R/G/B) or your
// driver board inverts. Symptom of getting this wrong: the strip is at full
// brightness when silent and goes dark when the music is loud.
#define INVERT_OUTPUT false

#define PWM_FREQ  5000
#define PWM_BITS  8
// ---------------------------------------------------------------------------

// PIN NOTE: GPIO 25/26/27 exist on the classic ESP32 (WROOM-32). On an
// ESP32-S3 or -C3 they don't -- pick any three free output pins there.

// The LEDC (PWM) API changed in Arduino-ESP32 core 3.0: ledcSetup/
// ledcAttachPin were replaced by ledcAttach, and ledcWrite now takes the PIN
// rather than a channel number. Passing a channel to the 3.x ledcWrite would
// silently drive GPIO 0/1/2 instead, so this picks the right one at compile
// time and works on either core.
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  #define AV_LEDC_ATTACH(pin, ch)      ledcAttach((pin), PWM_FREQ, PWM_BITS)
  #define AV_LEDC_WRITE(pin, ch, val)  ledcWrite((pin), (val))
#else
  #define AV_LEDC_ATTACH(pin, ch)      do { ledcSetup((ch), PWM_FREQ, PWM_BITS); \
                                            ledcAttachPin((pin), (ch)); } while (0)
  #define AV_LEDC_WRITE(pin, ch, val)  ledcWrite((ch), (val))
#endif

WiFiUDP udp;
static uint8_t  packet[256];
static uint32_t lastFrameMs = 0;
static uint32_t framesRx = 0;

// ESP32 cores use the LEDC peripheral rather than analogWrite().
static void writeRGB(uint8_t r, uint8_t g, uint8_t b) {
  if (INVERT_OUTPUT) { r = 255 - r; g = 255 - g; b = 255 - b; }
  AV_LEDC_WRITE(PIN_R, 0, r);
  AV_LEDC_WRITE(PIN_G, 1, g);
  AV_LEDC_WRITE(PIN_B, 2, b);
}

void setup() {
  Serial.begin(115200);
  delay(200);

  AV_LEDC_ATTACH(PIN_R, 0);
  AV_LEDC_ATTACH(PIN_G, 1);
  AV_LEDC_ATTACH(PIN_B, 2);
  writeRGB(0, 0, 0);

  // Non-blocking: the idle breath below runs while this connects, so a board
  // that boots faster than the router still lights up and joins when it can.
  avNetBegin(WIFI_SSID, WIFI_PASS, HOSTNAME);

  Serial.printf("audioviz LED receiver (analog RGB) ready\n");
  Serial.printf("  UDP port : %d\n", UDP_PORT);
  Serial.printf("\n  run: python run.py --leds udp://%s.local:%d --led-count 1\n\n",
                HOSTNAME, UDP_PORT);
}

void loop() {
  // Rebind the socket whenever the link comes back: the old one is bound to
  // an address the interface no longer holds.
  if (avNetLoop()) udp.begin(UDP_PORT);

  int size = udp.parsePacket();
  if (size > 0) {
    int len = udp.read(packet, sizeof(packet));
    AvFrame frame;
    if (len > 0 && avParse(packet, (size_t)len, &frame) && frame.count > 0) {
      // one color for the whole strip: pixel 0 is all we can show
      writeRGB(frame.rgb[0], frame.rgb[1], frame.rgb[2]);
      lastFrameMs = millis();
      if ((++framesRx % 600) == 0) Serial.printf("frames=%lu\n", framesRx);
    }
    return;
  }

  // ---- fallback: nobody is driving us, so drive ourselves -----------------
  if (millis() - lastFrameMs > AV_IDLE_TIMEOUT_MS) {
    uint8_t v = avIdleBreath(millis());
    writeRGB(v / 3, v / 6, v);   // a slow blue breath
    delay(16);
  }
}
