"""Generate PNG icons for the Chrome extension from SVG."""

import struct
import zlib

SIZES = [16, 48, 128]

BG = (15, 17, 23)
ACCENT = (108, 140, 255)


def create_png(size: int) -> bytes:
    rows = []
    cx, cy = size / 2, size / 2
    r_outer = size * 0.42
    r_inner = size * 0.22

    for y in range(size):
        row = bytearray([0])  # filter byte
        for x in range(size):
            dx, dy = x - cx + 0.5, y - cy + 0.5
            dist = (dx * dx + dy * dy) ** 0.5
            if r_inner <= dist <= r_outer:
                angle = __import__("math").atan2(dy, dx)
                t = (angle + 3.14159) / (2 * 3.14159)
                fac = 0.6 + 0.4 * abs(2 * t - 1)
                row.extend([
                    int(ACCENT[0] * fac),
                    int(ACCENT[1] * fac),
                    int(ACCENT[2] * fac),
                    255,
                ])
            elif dist < r_inner:
                row.extend([ACCENT[0], ACCENT[1], ACCENT[2], 220])
            else:
                row.extend([BG[0], BG[1], BG[2], 0])
        rows.append(bytes(row))

    raw = b"".join(rows)

    def chunk(ctype, data):
        c = ctype + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


if __name__ == "__main__":
    from pathlib import Path
    here = Path(__file__).parent
    for s in SIZES:
        (here / f"icon{s}.png").write_bytes(create_png(s))
        print(f"Generated icon{s}.png")
