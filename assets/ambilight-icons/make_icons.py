"""Ambilight icons for the Unfolded Circle Remote: white on transparent, 90x90 PNG.

Drawn at 4x (360 px) then downscaled for anti-aliasing. Artwork kept inside ~35 px, like the built-in Remote 3 icons.
Usage: python3 make_icons.py OUT_DIR
"""

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

S = 360  # working size (4x)
W = 22  # stroke width at 4x (~5.5 px final)
WHITE = (255, 255, 255, 255)


def canvas():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def line(d, pts, w=W):
    d.line(pts, fill=WHITE, width=w, joint="curve")
    r = w / 2
    for x, y in (pts[0], pts[-1]):
        d.ellipse((x - r, y - r, x + r, y + r), fill=WHITE)


def tv(d, box=(95, 115, 265, 225)):
    d.rounded_rectangle(box, radius=16, outline=WHITE, width=W)
    x0, _, x1, y1 = box
    cx = (x0 + x1) / 2
    line(d, [(cx - 35, y1 + 32), (cx + 35, y1 + 32)])


def rays(d):
    """Two light rays on each side of the TV and two above it."""
    for (ax, ay), (bx, by) in [((78, 148), (42, 132)), ((78, 196), (42, 212)), ((150, 96), (140, 58))]:
        line(d, [(ax, ay), (bx, by)], w=18)
        line(d, [(S - ax, ay), (S - bx, by)], w=18)


def star(d, cx, cy, r, inner):
    pts = []
    for i in range(8):
        ang = math.pi / 4 * i - math.pi / 2
        rr = r if i % 2 == 0 else inner
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    d.polygon(pts, fill=WHITE)


def ambi_on():
    img, d = canvas()
    tv(d)
    rays(d)
    return img


def centered(img):
    """Move the artwork so its bounding box is centred on the canvas."""
    x0, y0, x1, y1 = img.getchannel("A").getbbox()
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(img, (round((S - (x1 - x0)) / 2 - x0), round((S - (y1 - y0)) / 2 - y0)))
    return out


def slashed(img):
    """OFF version: a diagonal slash through the centre, with a transparent gap around it."""
    img = centered(img)
    gap = Image.new("L", (S, S), 0)
    ImageDraw.Draw(gap).line([(55, 55), (305, 305)], fill=255, width=W + 26)
    img.putalpha(Image.composite(Image.new("L", (S, S), 0), img.getchannel("A"), gap))
    line(ImageDraw.Draw(img), [(60, 60), (300, 300)])
    return img


def ambi_off():
    img, d = canvas()
    tv(d)
    rays(d)
    return slashed(img)


def ai():
    img, d = canvas()
    star(d, 180, 185, 135, 32)
    return img


def standard():
    img, d = canvas()
    tv(d)
    d.polygon([(160, 140), (160, 200), (212, 170)], fill=WHITE)
    return img


def cinema():
    """Clapperboard."""
    img, d = canvas()
    d.rounded_rectangle((70, 150, 290, 295), radius=16, outline=WHITE, width=W)
    # clapper stick, slightly open, with diagonal stripes
    stick = [(70, 128), (270, 72), (282, 112), (82, 168)]
    line(d, [*stick, stick[0]])
    for t in (0.3, 0.55, 0.8):
        x0, y0 = 70 + 200 * t, 128 - 56 * t
        line(d, [(x0, y0), (x0 + 30, y0 + 30)], w=14)
    return img


def game():
    img, d = canvas()
    d.rounded_rectangle((45, 115, 315, 255), radius=70, outline=WHITE, width=W)
    line(d, [(85, 185), (145, 185)], w=18)
    line(d, [(115, 155), (115, 215)], w=18)
    for x, y in ((238, 165), (272, 200)):
        d.ellipse((x - 16, y - 16, x + 16, y + 16), fill=WHITE)
    return img


def lumina():
    img, d = canvas()
    d.ellipse((85, 225, 175, 290), fill=WHITE)
    line(d, [(166, 255), (166, 75)])
    line(d, [(166, 75), (235, 115)])
    return img


def disco():
    img, d = canvas()
    cx, cy, r = 180, 210, 110
    line(d, [(cx, cy - r), (cx, 55)])
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=WHITE, width=W)
    d.ellipse((cx - r * 0.45, cy - r, cx + r * 0.45, cy + r), outline=WHITE, width=W)
    d.line([(cx - r, cy), (cx + r, cy)], fill=WHITE, width=W)
    return img


def rhythm():
    """Sound wave."""
    img, d = canvas()
    pts = [(x, 185 - 85 * math.sin((x - 80) / 200 * 3 * math.pi)) for x in range(80, 281, 2)]
    line(d, pts)
    return img


GLYPH_SCALE = 0.72  # mode glyph size inside the canvas, leaving room for the rays
GLYPH_SHIFT = 22  # glyph moved down so the top rays fit


def with_glow(fn):
    """Ambilight mode: the glyph with two light rays on each side and two above, like AMBI_ON."""

    def draw():
        glyph = fn()
        size = round(S * GLYPH_SCALE)
        small = glyph.resize((size, size), Image.LANCZOS)
        img, d = canvas()
        img.paste(small, ((S - size) // 2, (S - size) // 2 + GLYPH_SHIFT), small)
        d = ImageDraw.Draw(img)
        for a, b in [((48, 168), (12, 152)), ((48, 228), (12, 244)), ((150, 62), (140, 24))]:
            line(d, [a, b], w=18)
            line(d, [(S - a[0], a[1]), (S - b[0], b[1])], w=18)
        return img

    return draw


ICONS = {
    "ambilight_on": ambi_on,
    "ambilight_off": ambi_off,
    "ambi_ai": with_glow(ai),
    "ambi_standard": with_glow(standard),
    "ambi_cinema": with_glow(cinema),
    "ambi_game": with_glow(game),
    "ambi_lumina": with_glow(lumina),
    "ambi_disco": with_glow(disco),
    "ambi_rhythm": with_glow(rhythm),
}

# Share of the canvas used by the artwork, like the Remote 3 built-in icons (~35 px out of 90).
CONTENT_SCALE = 0.5


def shrink(img):
    size = round(S * CONTENT_SCALE)
    small = img.resize((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(small, ((S - size) // 2, (S - size) // 2), small)
    return out


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in ICONS.items():
        icon = shrink(centered(fn())).resize((90, 90), Image.LANCZOS)
        path = out / f"{name}.png"
        icon.save(path, optimize=True)
        print(f"{path.name}: {icon.size}, {path.stat().st_size} bytes")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
