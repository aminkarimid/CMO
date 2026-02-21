from __future__ import annotations

import sys
from pathlib import Path

def main() -> int:
    try:
        from PIL import Image, ImageOps, ImageDraw  # type: ignore
    except Exception:
        print("PIL_NOT_AVAILABLE", file=sys.stderr)
        return 2

    if len(sys.argv) < 3:
        print("Usage: round_iconify.py /path/in.png /path/out.png", file=sys.stderr)
        return 1

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    if not src.exists():
        print(f"NOT_FOUND:{src}", file=sys.stderr)
        return 3

    # Target canvas
    size = 1024

    im = Image.open(src).convert("RGBA")
    # Fit to square while keeping aspect
    im = ImageOps.contain(im, (size, size), method=Image.Resampling.LANCZOS)
    
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    # Center paste
    x = (size - im.width) // 2
    y = (size - im.height) // 2
    canvas.paste(im, (x, y), im)

    # Circular mask (full circle)
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)
    rounded = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rounded.paste(canvas, (0, 0), mask)

    dst.parent.mkdir(parents=True, exist_ok=True)
    rounded.save(dst, format="PNG")
    print(str(dst))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

