# SPDX-License-Identifier: MIT
"""make.fun cutest-picture-01 entry: pastel chibi companion.

Pure Python 3 stdlib. Renders a 1024x1024 PNG deterministically.
All shapes are built from analytic distance functions (circles, ellipses,
superellipses, heart polynomial, diamonds) with smoothstep coverage at the
edges for anti-aliasing. No PIL, no numpy.
"""
import math
import os
import struct
import sys
import zlib

W = H = 1024
SEED = 0xC0FFEE

# ---------------------------------------------------------------- palette ---
BG_TOP = (255, 232, 240)      # soft pink
BG_BOT = (255, 246, 224)      # warm cream
DOT_COL = (255, 255, 255)     # polka dots
HEART_BG = (255, 176, 189)    # floating hearts (background accents)
OUTLINE = (176, 122, 104)     # warm soft brown outline
FUR = (255, 250, 238)         # cream fur
EAR_IN = (255, 186, 199)      # inner ear pink
STRIPE = (255, 205, 158)      # peach head stripes
EYE_DARK = (72, 54, 58)       # big glossy eyes
IRIS_GLOW = (150, 116, 186)   # soft violet glow at eye bottom
HIGHLIGHT = (255, 255, 255)
BLUSH = (255, 168, 182)
NOSE_COL = (255, 148, 160)
MOUTH_COL = (150, 96, 88)
PAW_PAD = (255, 198, 208)
SHADOW = (240, 200, 208)
SPARKLE = (255, 255, 255)
WHISKER = (196, 156, 140)


# ------------------------------------------------------------------ math ---
def clamp01(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def smoothstep(t):
    t = clamp01(t)
    return t * t * (3.0 - 2.0 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, a):
    return (lerp(c1[0], c2[0], a), lerp(c1[1], c2[1], a),
            lerp(c1[2], c2[2], a))


# ------------------------------------------------------- coverage shapes ---
# Each returns coverage in [0,1]; ~1px soft transition = built-in AA.

def circle(x, y, cx, cy, r):
    return clamp01(0.5 - (math.hypot(x - cx, y - cy) - r))


def ellipse(x, y, cx, cy, a, b):
    """Axis-aligned ellipse with semi-axes a (x) and b (y)."""
    d = math.hypot((x - cx) / a, (y - cy) / b) - 1.0
    return clamp01(0.5 - d * min(a, b))


def superellipse(x, y, cx, cy, a, b, n):
    """Squircle body: |dx/a|^n + |dy/b|^n <= 1."""
    dx = abs((x - cx) / a)
    dy = abs((y - cy) / b)
    q = dx ** n + dy ** n
    d = (q ** (1.0 / n) - 1.0) * min(a, b)
    return clamp01(0.5 - d)


def rotEllipse(x, y, cx, cy, a, b, ang):
    """Rotated ellipse; ang in radians."""
    s = math.sin(ang)
    c = math.cos(ang)
    dx = x - cx
    dy = y - cy
    u = dx * c + dy * s
    v = -dx * s + dy * c
    d = math.hypot(u / a, v / b) - 1.0
    return clamp01(0.5 - d * min(a, b))


def diamond(x, y, cx, cy, a, b):
    d = abs(x - cx) / a + abs(y - cy) / b - 1.0
    return clamp01(0.5 - d * min(a, b))


def heart(x, y, cx, cy, s):
    """Classic heart implicit curve; s = half-width scale."""
    fx = (x - cx) / s
    fy = -(y - cy) / s  # flip y so the point aims down
    h = (fx * fx + fy * fy - 1.0) ** 3 - fx * fx * fy * fy * fy
    return clamp01(-h * 0.35 * s)


def ring(x, y, cx, cy, a, b):
    """Crescent ring band: ellipse annulus (for mouth arcs)."""
    d = math.hypot((x - cx) / a, (y - cy) / b)
    band = 1.0 - clamp01(abs(d - 0.82) * min(a, b) * 1.4)
    return clamp01(band) * clamp01(0.5 + (y - cy) / b)


def heart_only_bottom(x, y, cx, cy, s):
    """Heart mouth: keep only lower half of a small heart."""
    if y < cy:
        return 0.0
    return heart(x, y, cx, cy, s)


def arcband(x, y, cx, cy, a, b):
    """Thin arc hugging the top of an ellipse (eyelash)."""
    d = math.hypot((x - cx) / a, (y - cy) / b)
    if y > cy:
        return 0.0
    band = 1.0 - clamp01(abs(d - 0.94) * min(a, b) * 1.8)
    return clamp01(band)


# ------------------------------------------------------- PNG (stdlib) ------
def write_png(path, pixels):
    raw = bytearray()
    stride = W * 3
    for row in range(H):
        raw.append(0)  # filter 0
        off = row * stride
        raw += pixels[off:off + stride]
    comp = zlib.compress(bytes(raw), 9)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", comp))
        f.write(chunk(b"IEND", b""))


# ------------------------------------------------------------- scene -------
class Layer:
    __slots__ = ("x0", "x1", "y0", "y1", "fn")

    def __init__(self, x0, y0, x1, y1, fn):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.fn = fn  # fn(x, y) -> (color, alpha) or None


def build_layers():
    L = []
    add = L.append

    # --- background polka dots (deterministic LCG grid with jitter) ---
    rng = SEED
    for gy in range(9):
        for gx in range(9):
            rng = (rng * 1103515245 + 12345) & 0x7FFFFFFF
            jx = (rng >> 7) % 40 - 20
            rng = (rng * 1103515245 + 12345) & 0x7FFFFFFF
            jy = (rng >> 9) % 40 - 20
            rng = (rng * 1103515245 + 12345) & 0x7FFFFFFF
            r = 7 + (rng >> 12) % 9
            cx = 60 + gx * 112 + jx
            cy = 60 + gy * 112 + jy
            if 120 < cx < 904 and cy > 300:
                continue  # keep character area cleaner
            add(Layer(cx - r - 4, cy - r - 4, cx + r + 4, cy + r + 4,
                      (lambda cx=cx, cy=cy, r=r:
                       (lambda x, y: (DOT_COL, 0.55 * circle(x, y, cx, cy, r))))()))

    # --- floating hearts + sparkles around the character ---
    accents = [
        (150, 210, 26, 0.8), (860, 260, 30, 0.9), (770, 130, 20, 0.7),
        (230, 120, 18, 0.6), (900, 470, 18, 0.6), (110, 480, 16, 0.5),
        (820, 620, 14, 0.5), (170, 660, 15, 0.5),
    ]
    for cx, cy, s, al in accents:
        add(Layer(cx - s * 2, cy - s * 2, cx + s * 2, cy + s * 2,
                  (lambda cx=cx, cy=cy, s=s, al=al:
                   (lambda x, y: (HEART_BG, al * heart(x, y, cx, cy, s))))()))
    sparkles = [(310, 160, 12), (700, 90, 14), (940, 330, 11),
                (90, 330, 10), (620, 700, 9)]
    for cx, cy, s in sparkles:
        def make_spark(cx=cx, cy=cy, s=s):
            def f(x, y):
                a = max(diamond(x, y, cx, cy, s, s * 2.6),
                        diamond(x, y, cx, cy, s * 0.55, s * 0.55))
                return (SPARKLE, 0.9 * a)
            return f
        add(Layer(cx - s * 2, cy - s * 2, cx + s * 2, cy + s * 2,
                  make_spark()))

    # --- soft ground shadow ---
    add(Layer(240, 880, 820, 970,
              lambda x, y: (SHADOW, 0.45 * ellipse(x, y, 530, 925, 280, 42))))

    # --- soft white glow behind the character for contrast ---
    add(Layer(60, 100, 960, 900,
              lambda x, y: (HIGHLIGHT, 0.35 * ellipse(x, y, 512, 520, 450, 400))))

    # --- tail: chain of circles along a curve ---
    for i in range(9):
        t = i / 8.0
        cx = 760 + 70 * math.sin(t * math.pi)
        cy = 780 - 150 * t + 40 * t * t
        r = 34 - 12 * t
        add(Layer(cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3,
                  (lambda cx=cx, cy=cy, r=r:
                   (lambda x, y: (OUTLINE, 1.0 * circle(x, y, cx, cy, r))))()))
        r2 = r - 7
        add(Layer(cx - r2 - 3, cy - r2 - 3, cx + r2 + 3, cy + r2 + 3,
                  (lambda cx=cx, cy=cy, r=r2:
                   (lambda x, y: (FUR, 1.0 * circle(x, y, cx, cy, r2))))()))

    # --- body: squircle ---
    bx, by, ba, bb = 512, 800, 190, 150
    add(Layer(bx - ba - 6, by - bb - 6, bx + ba + 6, by + bb + 6,
              lambda x, y: (OUTLINE, 1.0 * superellipse(x, y, bx, by, ba + 6, bb + 6, 3.2))))
    add(Layer(bx - ba - 6, by - bb - 6, bx + ba + 6, by + bb + 6,
              lambda x, y: (FUR, 1.0 * superellipse(x, y, bx, by, ba, bb, 3.2))))
    # belly patch
    add(Layer(bx - 140, by - 60, bx + 140, by + 130,
              lambda x, y: (HIGHLIGHT, 0.85 * superellipse(x, y, bx, by + 35, 130, 88, 3.0))))

    # --- paws ---
    for px in (415, 609):
        add(Layer(px - 62, 855, px + 62, 945,
                  (lambda px=px:
                   (lambda x, y: (OUTLINE, 1.0 * ellipse(x, y, px, 898, 56, 40))))()
                  ))
        add(Layer(px - 62, 855, px + 62, 945,
                  (lambda px=px:
                   (lambda x, y: (FUR, 1.0 * ellipse(x, y, px, 898, 50, 34))))()
                  ))
        # toe lines
        for dx in (-16, 16):
            add(Layer(px + dx - 6, 880, px + dx + 6, 928,
                      (lambda px=px, dx=dx:
                       (lambda x, y: (OUTLINE, 0.5 * diamond(x, y, px + dx, 903, 2.6, 26))))()
                      ))

    # --- head: big superellipse ---
    hx, hy, ha, hb = 512, 470, 340, 290
    add(Layer(hx - ha - 8, hy - hb - 8, hx + ha + 8, hy + hb + 8,
              lambda x, y: (OUTLINE, 1.0 * superellipse(x, y, hx, hy, ha + 11, hb + 11, 3.0))))
    add(Layer(hx - ha - 8, hy - hb - 8, hx + ha + 8, hy + hb + 8,
              lambda x, y: (FUR, 1.0 * superellipse(x, y, hx, hy, ha, hb, 3.0))))
    # soft sheen on upper-left of head
    add(Layer(hx - 300, hy - 280, hx - 60, hy - 60,
              (lambda: (lambda x, y: (HIGHLIGHT, 0.22 * ellipse(x, y, hx - 190, hy - 175, 110, 82))))()
              ))

    # --- ears (rounded triangles via rotated squished squircles) ---
    # two-pass: all outlines first, then all fur, so scalloped ring
    # artifacts from the chain get covered by neighbouring fur
    for sx, ex in ((-1, hx - 218), (1, hx + 218)):
        base_y = hy - 200
        tip_y = hy - 380
        segs = []
        for t_i in range(10):
            t = t_i / 9.0
            cx = ex + sx * 24 * (1 - t)
            cy = base_y + (tip_y - base_y) * t
            a = 58 - 32 * t
            segs.append((cx, cy, a))
        for cx, cy, a in segs:
            add(Layer(cx - a - 8, cy - 40, cx + a + 8, cy + 40,
                      (lambda cx=cx, cy=cy, a=a, sx=sx:
                       (lambda x, y: (OUTLINE, 1.0 * rotEllipse(x, y, cx, cy, a + 6, 39, 0.35 * sx))))()
                      ))
        for cx, cy, a in segs:
            add(Layer(cx - a - 4, cy - 38, cx + a + 4, cy + 38,
                      (lambda cx=cx, cy=cy, a=a, sx=sx:
                       (lambda x, y: (FUR, 1.0 * rotEllipse(x, y, cx, cy, a, 34, 0.35 * sx))))()
                      ))
        # extra fur pass to fully smooth the ear silhouette
        for cx, cy, a in segs:
            add(Layer(cx - a - 4, cy - 38, cx + a + 4, cy + 38,
                      (lambda cx=cx, cy=cy, a=a, sx=sx:
                       (lambda x, y: (FUR, 1.0 * rotEllipse(x, y, cx, cy, a - 2, 32, 0.35 * sx))))()
                      ))
    # inner ears
    for sx, ex in ((-1, hx - 214), (1, hx + 214)):
        add(Layer(ex - 34, hy - 360, ex + 34, hy - 232,
                  (lambda sx=sx, ex=ex:
                   (lambda x, y: (EAR_IN, 0.95 * rotEllipse(x, y, ex, hy - 300, 26, 62, 0.35 * sx))))()
                  ))

    # --- head stripes ---
    for dx in (-70, 0, 70):
        add(Layer(hx + dx - 40, hy - 290, hx + dx + 40, hy - 190,
                  (lambda dx=dx:
                   (lambda x, y: (STRIPE, 0.9 * ellipse(x, y, hx + dx, hy - 240, 30, 46))))()
                  ))

    # --- eyes: big, glossy ---
    for sx, ex in ((-1, hx - 138), (1, hx + 138)):
        ey = hy + 10
        add(Layer(ex - 84, ey - 96, ex + 84, ey + 96,
                  (lambda ex=ex, ey=ey:
                   (lambda x, y: (EYE_DARK, 1.0 * ellipse(x, y, ex, ey, 70, 86))))()
                  ))
        # violet glow at bottom of iris
        add(Layer(ex - 60, ey + 10, ex + 60, ey + 90,
                  (lambda ex=ex, ey=ey:
                   (lambda x, y: (IRIS_GLOW, 0.6 * ellipse(x, y, ex, ey + 32, 50, 38))))()
                  ))
        # big highlight upper-left + small one lower-right
        add(Layer(ex - 50, ey - 80, ex + 10, ey - 8,
                  (lambda ex=ex, ey=ey:
                   (lambda x, y: (HIGHLIGHT, 0.97 * ellipse(x, y, ex - 24, ey - 42, 27, 32))))()
                  ))
        add(Layer(ex + 10, ey + 14, ex + 50, ey + 54,
                  (lambda ex=ex, ey=ey:
                   (lambda x, y: (HIGHLIGHT, 0.9 * circle(x, y, ex + 30, ey + 34, 12))))()
                  ))
        # tiny sparkle cross inside the eye
        def make_cross(ex=ex, ey=ey):
            def f(x, y):
                a = max(diamond(x, y, ex + 16, ey + 6, 3.5, 11),
                        diamond(x, y, ex + 16, ey + 6, 11, 3.5))
                return (HIGHLIGHT, 0.9 * a)
            return f
        add(Layer(ex - 6, ey - 8, ex + 42, ey + 28, make_cross()))
        # soft eyelash arc on top
        add(Layer(ex - 84, ey - 96, ex + 84, ey,
                  (lambda ex=ex, ey=ey:
                   (lambda x, y: (EYE_DARK, 0.9 * arcband(x, y, ex, ey, 70, 86))))()
                  ))

    # --- nose (tiny heart) ---
    add(Layer(hx - 22, hy + 118, hx + 22, hy + 160,
              (lambda hx=hx: (lambda x, y: (NOSE_COL, 1.0 * heart_only_bottom(
                  x, y, hx, hy + 136, 20))))()))

    # --- mouth: two soft arcs (omega shape) ---
    for dx in (-24, 24):
        add(Layer(hx + dx - 26, hy + 150, hx + dx + 26, hy + 186,
                  (lambda dx=dx, hx=hx:
                   (lambda x, y: (MOUTH_COL, 0.85 * ring(x, y, hx + dx, hy + 152, 22, 24))))()
                  ))

    # --- blush ---
    for sx, ex in ((-1, hx - 218), (1, hx + 218)):
        add(Layer(ex - 62, hy + 66, ex + 62, hy + 140,
                  (lambda ex=ex:
                   (lambda x, y: (BLUSH, 0.62 * ellipse(x, y, ex, hy + 104, 56, 34))))()
                  ))

    # --- whiskers ---
    for sx in (-1, 1):
        for i, (dy, ang) in enumerate(((-18, 0.22), (0, 0.0), (18, -0.22))):
            wcx = hx + sx * 290
            wcy = hy + 90 + dy
            ln = 92
            add(Layer(min(wcx, wcx + sx * ln * math.cos(ang)) - 8,
                      wcy - 22, max(wcx, wcx + sx * ln * math.cos(ang)) + 8,
                      wcy + 22,
                      (lambda wcx=wcx, wcy=wcy, sx=sx, ang=ang, ln=ln:
                       (lambda x, y: (WHISKER, 0.5 * rotEllipse(
                           x, y, wcx + sx * ln * 0.5 * math.cos(ang),
                           wcy + sx * ln * 0.5 * math.sin(ang),
                           ln * 0.5, 2.0, ang))))()
                      ))

    # --- small hearts floating in front, near the paws ---
    for cx, cy, s, al in ((350, 788, 16, 0.75), (676, 800, 13, 0.7)):
        add(Layer(cx - s * 2, cy - s * 2, cx + s * 2, cy + s * 2,
                  (lambda cx=cx, cy=cy, s=s, al=al:
                   (lambda x, y: ((255, 150, 165), al * heart(x, y, cx, cy, s))))()
                  ))

    return L


def render():
    layers = build_layers()
    buf = bytearray(W * H * 3)
    # background: vertical gradient
    for y in range(H):
        t = smoothstep(y / (H - 1))
        r = int(lerp(BG_TOP[0], BG_BOT[0], t))
        g = int(lerp(BG_TOP[1], BG_BOT[1], t))
        b = int(lerp(BG_TOP[2], BG_BOT[2], t))
        off = y * W * 3
        for x in range(W):
            o = off + x * 3
            buf[o] = r
            buf[o + 1] = g
            buf[o + 2] = b

    active_rows = {}
    for idx, L in enumerate(layers):
        y0 = max(0, int(L.y0))
        y1 = min(H - 1, int(L.y1))
        for yy in range(y0, y1 + 1):
            active_rows.setdefault(yy, []).append(idx)

    for y in range(H):
        idxs = active_rows.get(y)
        if not idxs:
            continue
        act = [layers[i] for i in idxs
               if layers[i].x0 <= W and layers[i].x1 >= 0]
        off = y * W * 3
        for x in range(W):
            o = off + x * 3
            col = (buf[o], buf[o + 1], buf[o + 2])
            for L in act:
                if x < L.x0 or x > L.x1:
                    continue
                res = L.fn(x, y)
                if res is None:
                    continue
                c, a = res
                if a <= 0.0:
                    continue
                col = mix(col, c, a)
            buf[o] = int(col[0])
            buf[o + 1] = int(col[1])
            buf[o + 2] = int(col[2])
    return buf


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "entry.png")
    buf = render()
    write_png(path, buf)
    print("wrote", path, os.path.getsize(path), "bytes")


if __name__ == "__main__":
    sys.exit(main())
