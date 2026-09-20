"""
tools/find_leds.py
------------------
Find the LED board on the network and prove it is listening -- the check that
replaces the serial monitor once the ESP32 is powered from a wall socket
instead of USB.

The board stays on DHCP (its address is the router's business and changes
freely across reboots) and answers to a fixed mDNS name instead, so this tool
asks for the *name* and reports whatever address is behind it today:

    python tools/find_leds.py                 # wait for audioviz.local, then test
    python tools/find_leds.py --name mystrip  # a board flashed with another HOSTNAME
    python tools/find_leds.py --no-test       # just resolve, don't light anything

With the test enabled (the default) it sends a few seconds of solid red, green
and blue through the real `LedSink`, so a strip that lights in that order is
end-to-end good: network, firmware, wiring and channel order all at once. On an
analog RGB strip a wrong color here means the R/G/B gate wires are swapped.
"""

import argparse
import os
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from led import build_sink
from features import Features


def resolve(name, timeout):
    """Wait up to `timeout` seconds for the name to resolve. A failed .local
    lookup on macOS takes ~5s to come back, so this is slow by nature -- the
    dots are there to show it is still trying rather than hung."""
    deadline = time.monotonic() + timeout
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            return socket.getaddrinfo(name, None, socket.AF_INET)[0][4][0]
        except OSError:
            print(f"  ...not on the network yet (try {attempt})", flush=True)
            time.sleep(1.0)
    return None


def ping(ip):
    """ICMP is the one round trip available -- the LED protocol is fire and
    forget, so a UDP send can never tell us anything came back."""
    try:
        r = subprocess.run(["ping", "-c", "2", "-t", "3", ip],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def test_colors(target, count, seconds):
    """Drive the strip through R, G, B with the real sink, so what is proven
    is the actual path run.py uses."""
    sink = build_sink(target, count)
    sink.start()
    f = Features()
    try:
        for name, rgb in (("red", (1.0, 0.0, 0.0)),
                          ("green", (0.0, 1.0, 0.0)),
                          ("blue", (0.0, 0.0, 1.0))):
            print(f"  {name} ...", flush=True)
            px = np.tile(np.array(rgb, dtype=np.float32), (count, 1))
            t0 = time.monotonic()
            while time.monotonic() - t0 < seconds:
                sink.submit(px, f)      # 60fps, as the render loop would
                time.sleep(1 / 60.)
    finally:
        sink.stop()


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", default="audioviz",
                   help="the board's HOSTNAME, as set in the sketch "
                        "(default: audioviz)")
    p.add_argument("--port", type=int, default=4210)
    p.add_argument("--led-count", type=int, default=1,
                   help="1 for an analog RGB strip, your LED count otherwise")
    p.add_argument("--timeout", type=float, default=60.0,
                   help="how long to wait for the board to appear")
    p.add_argument("--no-test", action="store_true",
                   help="only resolve the name; don't light the strip")
    p.add_argument("--seconds", type=float, default=2.0,
                   help="how long to hold each test color")
    args = p.parse_args()

    host = f"{args.name}.local"
    print(f"looking for {host} (up to {args.timeout:.0f}s)")
    print("a board that just got power needs a few seconds to join WiFi\n")

    ip = resolve(host, args.timeout)
    if ip is None:
        print(f"\n{host} did not resolve.\n")
        print("  - Is it powered? The strip should be doing a slow blue breath")
        print("    within ~2s of power, before it even joins WiFi. No breath")
        print("    means power or wiring, not network.")
        print("  - Same WiFi as this Mac, and 2.4GHz? The ESP32 cannot see a")
        print("    5GHz-only band.")
        print("  - Some routers block mDNS on guest networks. Check the router's")
        print("    client list for a device named 'audioviz' and use its IP:")
        print(f"      python run.py --leds udp://<ip>:{args.port} "
              f"--led-count {args.led_count}")
        return 1

    print(f"\nfound: {host} -> {ip}")
    print(f"  ping: {'ok' if ping(ip) else 'no reply (mDNS worked, so this is usually fine)'}")

    target = f"udp://{host}:{args.port}"
    if not args.no_test:
        print(f"\nsending test colors to {target}")
        test_colors(target, args.led_count, args.seconds)
        print("  done -- the strip should have gone red, green, blue in that order")

    print("\nready:")
    print(f"  python run.py --source loopback --spotify --leds {target} "
          f"--led-count {args.led_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
