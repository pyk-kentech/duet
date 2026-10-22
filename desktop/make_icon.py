"""앱 아이콘 원본(1024×1024 PNG)을 그린다: 화면의 브랜드 표시와 같은 어두운 둥근 사각형 안의 't'.

    python desktop/make_icon.py && (cd app && npx tauri icon src-tauri/icons/source.png)

외부 이미지·라이브러리 없이 표준 라이브러리(zlib)로만 쓴다.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIZE = 1024
BG = (27, 31, 42, 255)        # --text (밝은 테마)
FG = (255, 255, 255, 255)
RADIUS = 220
# 't' 를 사각형 몇 개로: 세로 막대, 가로 막대, 아래 오른쪽 꼬리
RECTS = [(452, 210, 572, 760), (330, 370, 694, 470), (452, 680, 720, 780)]


def inside_rounded(x: int, y: int) -> bool:
    r = RADIUS
    cx = min(max(x, r), SIZE - 1 - r)
    cy = min(max(y, r), SIZE - 1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def pixel(x: int, y: int) -> tuple[int, int, int, int]:
    if not inside_rounded(x, y):
        return (0, 0, 0, 0)
    for x0, y0, x1, y1 in RECTS:
        if x0 <= x < x1 and y0 <= y < y1:
            return FG
    return BG


def png(path: Path) -> None:
    rows = bytearray()
    for y in range(SIZE):
        rows.append(0)
        for x in range(SIZE):
            rows.extend(pixel(x, y))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "app" / "src-tauri" / "icons" / "source.png"
    png(out)
    print(out)
