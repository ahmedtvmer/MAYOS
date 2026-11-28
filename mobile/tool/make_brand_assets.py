"""Generate the #886 raster brand assets from the dumbbell-M geometry.

The geometry matches `assets/brand/mark-red.svg` at the repo root and
`MayosBrandMark` in `lib/src/core/ui/mayos_logo.dart`; no SVG renderer is
needed. Re-running rewrites the icons from the geometry.

Usage (from the repo root):
    python mobile/tool/make_brand_assets.py mobile
    python mobile/tool/make_brand_assets.py mobile --wallpaper   # one-off

`--wallpaper` converts the gym photos to black and white. It was run once on
2026-11-27 (see `mobile/assets/ATTRIBUTION.md`); running it again would boost
the contrast a second time, so it is off by default. Afterwards run
`dart run flutter_launcher_icons` in `mobile/` to refresh the Android mipmaps.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

MOBILE = Path(sys.argv[1])
CHARCOAL = (0x14, 0x14, 0x14)
ICON_RED = (0xE6, 0x39, 0x46)   # app-icon-charcoal.svg mark colour
LOGO_RED = (0xB3, 0x00, 0x1B)   # in-app mark
WORD = (0xF5, 0xF5, 0xF4)
SS = 4  # supersampling

V = [(144, 176), (256, 330), (368, 176)]
HALF = 17
BARS = [((108, 138, 180, 374), 36), ((332, 138, 404, 374), 36), ((60, 192, 100, 320), 20), ((412, 192, 452, 320), 20)]
BOUNDS = (56, 136, 456, 376)  # tight box, 400 x 240


def _offset_line(p, q, d):
    dx, dy = q[0] - p[0], q[1] - p[1]
    n = (dx * dx + dy * dy) ** 0.5
    nx, ny = -dy / n * d, dx / n * d
    return (p[0] + nx, p[1] + ny), (q[0] + nx, q[1] + ny)


def _intersect(a1, a2, b1, b2):
    x1, y1 = a1; x2, y2 = a2; x3, y3 = b1; x4, y4 = b2
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    return x1 + t * (x2 - x1), y1 + t * (y2 - y1)


def _v_polygon():
    p0, p1, p2 = V
    l0 = _offset_line(p0, p1, HALF); l1 = _offset_line(p1, p2, HALF)
    r0 = _offset_line(p0, p1, -HALF); r1 = _offset_line(p1, p2, -HALF)
    return [l0[0], _intersect(*l0, *l1), l1[1], r1[1], _intersect(*r0, *r1), r0[0]]


def draw_mark(img, colour, box):
    """Draw the mark scaled to fit `box` (x0, y0, x1, y1), centred, aspect kept."""
    x0, y0, x1, y1 = box
    bw, bh = BOUNDS[2] - BOUNDS[0], BOUNDS[3] - BOUNDS[1]
    s = min((x1 - x0) / bw, (y1 - y0) / bh)
    ox = x0 + ((x1 - x0) - bw * s) / 2 - BOUNDS[0] * s
    oy = y0 + ((y1 - y0) - bh * s) / 2 - BOUNDS[1] * s
    big = Image.new("L", (img.width * SS, img.height * SS), 0)
    d = ImageDraw.Draw(big)
    T = lambda x, y: ((ox + x * s) * SS, (oy + y * s) * SS)
    for (a, b, c, e), r in BARS:
        d.rounded_rectangle([T(a, b), T(c, e)], radius=r * s * SS, fill=255)
    d.polygon([T(*pt) for pt in _v_polygon()], fill=255)
    mask = big.resize(img.size, Image.LANCZOS)
    img.paste(Image.new("RGBA", img.size, colour + (255,)), (0, 0), mask)


def square(size, bg, frac, colour=ICON_RED):
    """Full-bleed square icon; mark width = frac of the side."""
    img = Image.new("RGBA", (size, size), bg + (255,) if bg else (0, 0, 0, 0))
    w = size * frac
    h = w * 240 / 400
    draw_mark(img, colour, ((size - w) / 2, (size - h) / 2, (size + w) / 2, (size + h) / 2))
    return img


def rounded_icon(size):
    """The app-icon-charcoal tile: rx 112/512, mark at the SVG's own scale (57%)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    big = Image.new("L", (size * SS, size * SS), 0)
    ImageDraw.Draw(big).rounded_rectangle([0, 0, size * SS - 1, size * SS - 1], radius=112 / 512 * size * SS, fill=255)
    img.paste(Image.new("RGBA", img.size, CHARCOAL + (255,)), (0, 0), big.resize(img.size, Image.LANCZOS))
    w = size * (392 * 0.742 / 512)
    h = w * 240 / 400
    draw_mark(img, ICON_RED, ((size - w) / 2, (size - h) / 2, (size + w) / 2, (size + h) / 2))
    return img


def greyscale_wallpaper(src, dst):
    im = Image.open(src).convert("L")
    im = ImageEnhance.Contrast(im).enhance(1.1)
    im.convert("RGB").save(dst, quality=80, optimize=True, progressive=True)


def lockup_png(dst, height=480, gap=20):
    """The splash lockup exactly as `MayosBrandLockup` lays it out, at 4x.

    The web loading screen shows this image at the splash's lockup height, so
    the hand-off to Flutter must not move anything: same mark height, fixed
    gap (5 at the splash's 120 high, so 20 at 4x), word size 0.36 of the mark,
    line height 1.2 and letter spacing 0.42em between letters, word centred.
    """
    mark_h = (height - gap) / (1 + 0.36 * 1.2)
    size = mark_h * 0.36
    font = ImageFont.truetype(str(MOBILE / "assets/fonts/MayosWordmark-SemiBold.ttf"), round(size))
    spacing = size * 0.42
    letters = "MAYOS"
    advances = [font.getlength(ch) for ch in letters]
    word_w = sum(advances) + spacing * (len(letters) - 1)
    mark_w = mark_h * 400 / 240
    W = int(round(max(mark_w, word_w))) + 2
    img = Image.new("RGBA", (W, int(round(height))), (0, 0, 0, 0))
    draw_mark(img, LOGO_RED, ((W - mark_w) / 2, 0, (W + mark_w) / 2, mark_h))
    d = ImageDraw.Draw(img)
    line_top = mark_h + gap
    baseline_mid = line_top + size * 1.2 / 2
    x = (W - word_w) / 2
    for ch, adv in zip(letters, advances):
        d.text((x, baseline_mid), ch, font=font, fill=WORD + (255,), anchor="lm")
        x += adv + spacing
    img.save(dst, optimize=True)


if __name__ == "__main__":
    web = MOBILE / "web"
    if "--wallpaper" in sys.argv[2:]:
        greyscale_wallpaper(MOBILE / "assets/images/gym-wallpaper.jpg", MOBILE / "assets/images/gym-wallpaper.jpg")
        greyscale_wallpaper(web / "mayos-loading-wallpaper.jpg", web / "mayos-loading-wallpaper.jpg")
    rounded_icon(192).save(web / "mayos-icon-192.png", optimize=True)
    rounded_icon(512).save(web / "mayos-icon-512.png", optimize=True)
    square(512, CHARCOAL, 0.50).convert("RGB").save(web / "mayos-icon-512-maskable.png", optimize=True)
    square(180, CHARCOAL, 0.62).convert("RGB").save(web / "apple-touch-icon.png", optimize=True)
    square(32, CHARCOAL, 0.80).convert("RGB").save(web / "favicon.png", optimize=True)
    lockup_png(web / "mayos-lockup-white.png")
    # Android launcher sources for flutter_launcher_icons.
    rounded_icon(1024).save(MOBILE / "assets/mayos-android-logo.png", optimize=True)
    # Adaptive foreground: 108dp canvas, mark inside the 66dp safe zone (~38% width).
    square(1024, None, 0.38).save(MOBILE / "assets/mayos-android-logo-foreground.png", optimize=True)
    print("done")
