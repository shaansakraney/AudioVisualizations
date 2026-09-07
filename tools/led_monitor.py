"""
tools/led_monitor.py
--------------------
A fake LED strip in your terminal. Listens for the UDP frames run.py sends
and prints them as colored blocks, one block per LED.

    python tools/led_monitor.py                 # listen on 0.0.0.0:4210
    python tools/led_monitor.py --port 4300

    # in another terminal
    python run.py --leds udp://127.0.0.1:4210 --led-count 16

This exists so the entire Python half -- scene led() frames, resampling,
smoothing, the beat pulse, the wire protocol -- can be built and verified
before any hardware is on the desk. It decodes the same header the firmware
does (see led.py), so if the blocks look right here, the ESP32 is getting
well-formed frames too.

It also reports dropped frames, using the protocol's sequence byte. A few
drops over WiFi are normal and invisible on a real strip; a flood of them
means something is wrong with the network path.
"""

import argparse
import socket
import struct
import sys
import time

MAGIC = b"AVZ"
HEADER = struct.Struct(">3sBBH")


def main():
    p = argparse.ArgumentParser(description="render audioviz LED frames in the terminal")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=4210)
    p.add_argument("--fps", type=float, default=30.0,
                   help="redraw rate (frames arrive faster than a terminal can print)")
    args = p.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    sock.settimeout(1.0)
    print(f"listening on {args.host}:{args.port} -- ctrl-c to stop\n")

    last_seq = None
    frames = dropped = 0
    next_draw = 0.0
    period = 1.0 / args.fps

    try:
        while True:
            try:
                data, _ = sock.recvfrom(2048)
            except socket.timeout:
                sys.stdout.write("\r(no frames -- is run.py running with --leds?)   ")
                sys.stdout.flush()
                continue

            if len(data) < HEADER.size:
                continue
            magic, version, seq, count = HEADER.unpack_from(data)
            if magic != MAGIC:
                continue
            body = data[HEADER.size:HEADER.size + count * 3]
            if len(body) < count * 3:
                continue

            frames += 1
            if last_seq is not None:
                gap = (seq - last_seq - 1) & 0xFF
                dropped += gap
            last_seq = seq

            now = time.monotonic()
            if now < next_draw:
                continue
            next_draw = now + period

            blocks = "".join(
                f"\033[48;2;{body[i*3]};{body[i*3+1]};{body[i*3+2]}m  "
                for i in range(count)
            ) + "\033[0m"
            sys.stdout.write(f"\r{blocks}  v{version} n={count} "
                             f"frames={frames} dropped={dropped}   ")
            sys.stdout.flush()
    except KeyboardInterrupt:
        print("\033[0m\nbye")


if __name__ == "__main__":
    main()
