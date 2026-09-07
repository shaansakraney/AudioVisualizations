// av_proto.h -- audioviz LED wire protocol, MCU side.
//
// Mirrors the encoder in led.py. One frame:
//
//   offset  size  field
//   0       3     magic "AVZ"
//   3       1     version (1)
//   4       1     sequence number, wraps at 256
//   5       2     pixel count, big-endian
//   7       3*N   RGB bytes
//
// NOTE: this file is duplicated in each sketch folder because the Arduino
// IDE only compiles headers that sit beside the .ino. The copies must stay
// byte-identical -- see firmware/README.md.

#pragma once
#include <stdint.h>
#include <stddef.h>

static const uint8_t AV_VERSION     = 1;
static const uint8_t AV_HEADER_SIZE = 7;

// How long to wait with no frames before falling back to the idle animation.
// Python sends at 60fps, so a full second of silence means it really is gone
// (app quit, WiFi dropped, laptop asleep) rather than a few lost packets.
static const uint32_t AV_IDLE_TIMEOUT_MS = 1000;

struct AvFrame {
  uint8_t        seq;
  uint16_t       count;
  const uint8_t *rgb;   // points into the caller's buffer, 3*count bytes
};

// Returns true and fills `out` if buf holds a well-formed frame.
static inline bool avParse(const uint8_t *buf, size_t len, AvFrame *out) {
  if (len < AV_HEADER_SIZE) return false;
  if (buf[0] != 'A' || buf[1] != 'V' || buf[2] != 'Z') return false;
  if (buf[3] != AV_VERSION) return false;
  uint16_t count = ((uint16_t)buf[5] << 8) | (uint16_t)buf[6];
  if (len < (size_t)AV_HEADER_SIZE + (size_t)count * 3) return false;
  out->seq   = buf[4];
  out->count = count;
  out->rgb   = buf + AV_HEADER_SIZE;
  return true;
}

// Idle fallback: a slow breathing brightness, so an unattended strip looks
// deliberate rather than broken. Returns 0..255.
static inline uint8_t avIdleBreath(uint32_t ms) {
  // ~6s period, triangle wave -- no floating point, no sin() table
  uint32_t phase = (ms % 6000u) * 2u;          // 0..11999
  uint32_t v = phase < 6000u ? phase : 12000u - phase;   // 0..6000..0
  return (uint8_t)(12 + (v * 90u) / 6000u);    // dim, 12..102
}
