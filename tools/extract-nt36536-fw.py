#!/usr/bin/env python3
"""Extract the NT36536 touch firmware blob embedded in the vendor dtsi
(firmware-data-0 = /bits/ 8 <0xNN ...>) into a flat binary for the
mainline driver's request_firmware() path."""
import argparse
import re
import sys

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    text = open(args.input).read()
    m = re.search(r"firmware-data-0\s*=\s*/bits/\s*8\s*<(.*?)>;", text, re.S)
    if not m:
        sys.exit("firmware-data-0 property not found")
    data = bytes(int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))
    with open(args.output, "wb") as f:
        f.write(data)
    print(f"wrote {len(data)} bytes to {args.output}")
    print("first 64 bytes:", data[:64].hex(" "))

if __name__ == "__main__":
    main()
