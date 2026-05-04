#!/usr/bin/env python3
"""Convert a flat binary (RV32 firmware) to a $readmemh-friendly hex file.

Each 32-bit word in the input is emitted as one line of 8 hex digits in
little-endian order. The output matches what iverilog's $readmemh expects
when reading into an array declared as `reg [31:0] mem [0:N-1]`.

If --pad-words=N is given, the file is zero-padded out to N words so the
$readmemh fill is exact and iverilog stays silent about partial fills.

Usage:  bin2hex.py <input.bin> <output.hex> [--pad-words=N]
"""
from __future__ import annotations
import struct
import sys


def main(argv: list[str]) -> int:
    pad_words = 0
    args = []
    for a in argv[1:]:
        if a.startswith("--pad-words="):
            pad_words = int(a.split("=", 1)[1])
        else:
            args.append(a)
    if len(args) != 2:
        print(
            "usage: bin2hex.py <input.bin> <output.hex> [--pad-words=N]",
            file=sys.stderr,
        )
        return 2
    src, dst = args
    with open(src, "rb") as f:
        data = f.read()
    pad = (-len(data)) % 4
    if pad:
        data += b"\x00" * pad
    n_words = len(data) // 4
    words = list(struct.unpack("<" + "I" * n_words, data))
    if pad_words and len(words) < pad_words:
        words.extend([0] * (pad_words - len(words)))
    with open(dst, "w") as f:
        for w in words:
            f.write(f"{w:08x}\n")
    print(
        f"bin2hex: wrote {len(words)} words "
        f"({n_words} from input, {len(words) - n_words} zero-padded) to {dst}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
