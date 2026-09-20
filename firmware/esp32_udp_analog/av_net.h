// av_net.h -- audioviz WiFi bring-up and keep-alive, MCU side.
//
// The problem this solves: the board is powered from a wall socket, so every
// time it is unplugged it reboots, and DHCP is free to hand it a *different*
// address than last time. An IP baked into a `--leds udp://...` command is
// therefore stale the moment the lease changes.
//
// The fix is not a static IP -- a hand-picked address outside the router's
// pool is one more thing to get wrong on a new network. Instead the board
// keeps taking its address from DHCP and *advertises* itself over mDNS under
// a fixed name, so `audioviz.local` resolves to whatever DHCP just gave it.
// Python resolves that name (and re-resolves it if sends start failing), so
// the command line never has to change again.
//
// The second half is reconnection. A board plugged into the wall routinely
// boots faster than the router it wants to join, and WiFi drops on its own
// besides, so connecting must never be a blocking wait in setup(): the idle
// animation should run the whole time, and the board should rejoin by itself
// whenever the network comes back.
//
// NOTE: duplicated in each sketch folder, like av_proto.h, because the
// Arduino IDE only compiles headers that sit beside the .ino. The copies must
// stay byte-identical -- see firmware/README.md.

#pragma once
#include <WiFi.h>
#include <ESPmDNS.h>
#include <stdint.h>

// How often to nudge a disconnected radio. Fast enough that plugging the
// board in before the router finishes booting costs a few seconds, slow
// enough that a genuinely absent network isn't a busy loop.
static const uint32_t AV_NET_RETRY_MS = 5000;

static const char *avNetHost = "audioviz";
static const char *avNetSsid = nullptr;
static const char *avNetPass = nullptr;
static bool        avNetUp   = false;
static uint32_t    avNetLastTryMs = 0;

// Advertise <host>.local -> this IP, plus a service record so the strip is
// discoverable rather than merely resolvable. Re-run on every reconnect: the
// responder is bound to the interface, and a new lease needs a new record.
static inline void avNetAdvertise() {
  MDNS.end();
  if (MDNS.begin(avNetHost)) {
    MDNS.addService("audioviz", "udp", 4210);
  } else {
    Serial.println("mDNS failed to start -- use the raw IP below");
  }
}

// Starts the radio. Does NOT wait for a connection -- callers run their idle
// animation while avNetLoop() gets there.
static inline void avNetBegin(const char *ssid, const char *pass,
                              const char *hostname) {
  avNetSsid = ssid;
  avNetPass = pass;
  avNetHost = hostname;

  WiFi.persistent(false);      // don't wear out flash rewriting creds
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);        // modem sleep adds 100ms+ of jitter to 60fps
  WiFi.setHostname(hostname);  // must precede begin(); names the DHCP lease
  WiFi.setAutoReconnect(true);
  WiFi.begin(ssid, pass);
  avNetLastTryMs = millis();

  Serial.printf("\nconnecting to %s as %s.local\n", ssid, hostname);
}

// Call every loop. Returns true on the frame the link comes up, so the sketch
// can (re)bind its UDP socket -- the old socket is bound to an address that
// no longer exists after a reconnect.
static inline bool avNetLoop() {
  bool connected = (WiFi.status() == WL_CONNECTED);

  if (connected && !avNetUp) {
    avNetUp = true;
    avNetAdvertise();
    Serial.printf("\nWiFi up\n");
    Serial.printf("  name : %s.local\n", avNetHost);
    Serial.printf("  IP   : %s  (DHCP -- may change; prefer the name)\n",
                  WiFi.localIP().toString().c_str());
    return true;
  }

  if (!connected) {
    if (avNetUp) {
      avNetUp = false;
      Serial.println("WiFi lost -- retrying");
    }
    uint32_t now = millis();
    if (now - avNetLastTryMs > AV_NET_RETRY_MS) {
      avNetLastTryMs = now;
      WiFi.disconnect();
      WiFi.begin(avNetSsid, avNetPass);
      Serial.print(".");
    }
  }
  return false;
}
