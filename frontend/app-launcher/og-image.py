#!/usr/bin/env python3
"""BUILD-29: generate the Atlas launcher og:image (1200x630 glass card).

Hive glass standard: #090d17 base, indigo accent (#aa9bf7 family), mono
kicker, ambient radial glows and the dotted map-grid texture — matching
atlas.css tokens. Deterministic output; requires Pillow + Liberation fonts.
Run from the repository root:  python3 frontend/app-launcher/og-image.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1200, 630
S = 2  # supersample factor for crisp edges
ROOT = Path(__file__).resolve().parent
FONT_DIR = Path('/usr/share/fonts/truetype/liberation')

BG = (9, 13, 23)            # #090d17
TEXT = (237, 240, 255)      # .brand-name #edf0ff
MUTED = (143, 155, 177)     # .hero-description #8f9bb1
KICKER = (159, 150, 201)    # .eyebrow #9f96c9
ACCENT = (170, 155, 247)    # .brand-mark #aa9bf7
ACCENT_SOFT = (156, 139, 234)  # .eyebrow dot #9c8bea
LABEL = (113, 127, 150)     # .map-label #717f96
GRID = (132, 146, 191, 24)  # .map-preview dots #8492bf1c
BORDER = (37, 48, 68)       # .app-header border #253044
GLOW_INDIGO = (53, 41, 93)  # ambient #35295d
GLOW_TEAL = (23, 67, 84)    # ambient #174354

KICKER_TEXT = 'SHIZUHA · HOSTED APP'
TITLE = 'Shizuha Atlas'
DESCRIPTION = ('Explore your architecture, design the next layer, '
               'and navigate with an agent guide.')
FOOTER = 'shizuha.com/apps/shizuha/atlas/'


def font(name, size):
    return ImageFont.truetype(str(FONT_DIR / name), size * S)


def tracked(draw, xy, text, fnt, fill, tracking):
    """Draw text with letter-spacing; returns end x."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += draw.textlength(ch, font=fnt) + tracking * S
    return x


def hexagon(draw, cx, cy, r, color, width):
    """Flat-top hexagon matching the .brand-mark geometry (pointy-top)."""
    import math
    pts = []
    for i in range(6):
        ang = math.pi / 180 * (60 * i - 90)
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    draw.line(pts + [pts[0]], fill=color, width=width, joint='curve')


def main():
    img = Image.new('RGB', (W * S, H * S), BG)

    # Ambient radial glows (atlas.css .ambient).
    glow = Image.new('RGB', (W * S, H * S), BG)
    gd = ImageDraw.Draw(glow)
    gd.ellipse([int(W * S * 0.52), int(-H * S * 0.28), int(W * S * 1.28), int(H * S * 0.62)],
               fill=GLOW_INDIGO)
    gd.ellipse([int(-W * S * 0.22), int(H * S * 0.34), int(W * S * 0.42), int(H * S * 1.1)],
               fill=GLOW_TEAL)
    glow = glow.filter(ImageFilter.GaussianBlur(90 * S))
    img = Image.blend(img, glow, 0.42)
    draw = ImageDraw.Draw(img)

    # Dotted grid texture (.map-preview:before).
    step = 17 * S
    for gy in range(step, H * S, step):
        for gx in range(step, W * S, step):
            draw.point((gx, gy), fill=GRID[:3])

    f_mono = font('LiberationMono-Regular.ttf', 22)
    f_title = font('LiberationSans-Bold.ttf', 86)
    f_desc = font('LiberationSans-Regular.ttf', 29)
    f_brand = font('LiberationSans-Bold.ttf', 24)
    f_foot = font('LiberationMono-Regular.ttf', 16)

    # Brand row: hexagon mark + wordmark.
    mark_cx, mark_cy, mark_r = 78 * S, 76 * S, 30 * S
    hexagon(draw, mark_cx, mark_cy, mark_r, ACCENT, 4 * S)
    tri = [(mark_cx, mark_cy - mark_r * 0.45),
           (mark_cx + mark_r * 0.52, mark_cy + mark_r * 0.42),
           (mark_cx - mark_r * 0.52, mark_cy + mark_r * 0.42)]
    draw.polygon(tri, fill=ACCENT)
    tracked(draw, (124 * S, 62 * S), 'SHIZUHA', f_brand, TEXT, 2.2)

    # Kicker: accent dot + mono letterspaced label.
    ky = 236 * S
    draw.ellipse([78 * S, ky + 6 * S, 86 * S, ky + 14 * S], fill=ACCENT_SOFT)
    tracked(draw, (104 * S, ky - 2 * S), KICKER_TEXT, f_mono, KICKER, 3.4)

    # Title + description.
    draw.text((74 * S, 286 * S), TITLE, font=f_title, fill=TEXT)
    draw.text((78 * S, 428 * S), DESCRIPTION, font=f_desc, fill=MUTED)

    # Accent rule + footer hairline.
    draw.line([(78 * S, 496 * S), (206 * S, 496 * S)], fill=ACCENT, width=3 * S)
    draw.line([(0, (H - 72) * S), (W * S, (H - 72) * S)], fill=BORDER, width=S)
    tracked(draw, (78 * S, (H - 48) * S), FOOTER, f_foot, LABEL, 1.2)

    img = img.resize((W, H), Image.LANCZOS)
    out = ROOT / 'og-image.png'
    img.save(out, 'PNG', optimize=True)
    print(f'og-image: {out} ({out.stat().st_size} bytes, {W}x{H})')


if __name__ == '__main__':
    main()
