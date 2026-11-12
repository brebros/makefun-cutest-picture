#!/usr/bin/env python3
"""make.fun cutest-picture-01 — "Baby sloth in a teacup".

Pure stdlib PNG writer (zlib + struct, raw RGB, filter 0).
All shapes are signed distance fields shaded via smoothstep antialiasing.
Deterministic: fixed constants only, no RNG, no time.
"""
import math
import os
import struct
import zlib

W = H = 1024

# ---------- palette ----------
BG_TOP = (255, 218, 192)      # peach
BG_BOT = (255, 183, 197)      # blush pink
DOT = (255, 255, 255)
BODY = (201, 232, 220)        # soft mint
BODY_DARK = (168, 208, 192)   # mint shade
CREAM = (255, 243, 224)       # face cream
PATCH = (86, 74, 96)          # dark sloth eye-patch (plum)
EYE = (58, 48, 70)
WHITE = (255, 255, 255)
NOSE = (120, 96, 110)
MOUTH = (150, 120, 128)
MANGO_Y = (255, 202, 88)
MANGO_O = (255, 152, 74)
MANGO_SEED = (214, 150, 96)
MANGO_RIND = (255, 178, 66)
FLOWER = (255, 226, 110)
FLOWER_CORE = (255, 176, 92)
LEAF = (140, 196, 140)
CUP = (255, 255, 255)
CUP_SHADE = (245, 224, 228)
CUP_RIM = (228, 194, 202)
SAUCER = (252, 238, 240)
STEAM = (255, 255, 255)
HEART = (255, 130, 150)
GLOW = (255, 236, 214)
FUR = (188, 220, 206)

# ---------- helpers ----------
def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))

def sstep(e0, e1, x):
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)

def aa(d, w=1.2):
    """coverage for sdf d, inside if d<0"""
    return 1.0 - sstep(-w, w, d)

def smin(a, b, k=12.0):
    h = max(0.0, min(1.0, 0.5 + 0.5 * (b - a) / k))
    return b * (1 - h) + a * h - k * h * (1 - h)

def smax(a, b, k=12.0):
    return -smin(-a, -b, k)

def sd_circle(px, py, cx, cy, r):
    return math.hypot(px - cx, py - cy) - r

def sd_ellipse(px, py, cx, cy, rx, ry):
    k0 = math.hypot((px - cx) / rx, (py - cy) / ry)
    k1 = math.hypot((px - cx) / (rx * rx), (py - cy) / (ry * ry))
    return k0 * (k0 - 1.0) / max(k1, 1e-6)

def sd_capsule(px, py, ax, ay, bx, by, r):
    pax, pay = px - ax, py - ay
    bax, bay = bx - ax, by - ay
    h = max(0.0, min(1.0, (pax * bax + pay * bay) / max(bax * bax + bay * bay, 1e-6)))
    return math.hypot(pax - bax * h, pay - bay * h) - r

def sd_box(px, py, cx, cy, hx, hy, rad=0.0):
    qx, qy = abs(px - cx) - hx + rad, abs(py - cy) - hy + rad
    return min(max(qx, qy), 0.0) + math.hypot(max(qx, 0), max(qy, 0)) - rad

# ---------- scene geometry ----------
CUP_CX, CUP_CY = 512.0, 760.0
CUP_HW, CUP_HH = 250.0, 150.0
CUP_RAD = 50.0
HANDLE_CX, HANDLE_CY = CUP_CX + CUP_HW + 40.0, CUP_CY - 40.0
HANDLE_R = 80.0
HANDLE_T = 28.0
SAUCER_CX, SAUCER_CY = CUP_CX, CUP_CY + CUP_HH + 22.0
SAUCER_HW, SAUCER_HH = 320.0, 28.0
SAUCER_RAD = 26.0
HEAD_CX, HEAD_CY = 490.0, 440.0
HEAD_R = 185.0
BODY_CX, BODY_CY = 510.0, 600.0
BODY_RX, BODY_RY = 105.0, 110.0
EAR_L = (HEAD_CX - 128.0, HEAD_CY - 150.0)
EAR_R = (HEAD_CX + 128.0, HEAD_CY - 150.0)
EAR_R2 = 44.0
PATCH_L_C = (HEAD_CX - 92.0, HEAD_CY - 30.0)
PATCH_R_C = (HEAD_CX + 92.0, HEAD_CY - 30.0)
PATCH_RX, PATCH_RY = 72.0, 86.0
EYE_L_C = (HEAD_CX - 82.0, HEAD_CY - 20.0)
EYE_R_C = (HEAD_CX + 82.0, HEAD_CY - 20.0)
EYE_R2 = 38.0
MANGO_CX, MANGO_CY = HEAD_CX + 138.0, HEAD_CY + 105.0
MANGO_RX, MANGO_RY = 100.0, 72.0
MANGO_SEED_CX, MANGO_SEED_CY = MANGO_CX - 30.0, MANGO_CY + 6.0
MANGO_SEED_RX, MANGO_SEED_RY = 32.0, 44.0
FLOWER_POS = (EAR_R[0] + 14.0, EAR_R[1] - 24.0)
FLOWER_R = 32.0
CHEST_FUR = [(HEAD_CX - 20, 540), (HEAD_CX, 565), (HEAD_CX + 20, 590)]
STEAM_X = [CUP_CX - 172, CUP_CX + 186]
HEARTS = [(150, 260, 26), (330, 160, 18), (860, 300, 30), (920, 130, 16)]
GLOW_CX, GLOW_CY, GLOW_R = CUP_CX, CUP_CY - 60.0, 440.0

# ---------- layer sdfs (d<0 inside) ----------
def d_glow(px, py):
    return sd_circle(px, py, GLOW_CX, GLOW_CY, GLOW_R)

def d_saucer(px, py):
    return sd_box(px, py, SAUCER_CX, SAUCER_CY, SAUCER_HW, SAUCER_HH, SAUCER_RAD)

def d_cup(px, py):
    return sd_box(px, py, CUP_CX, CUP_CY, CUP_HW, CUP_HH, CUP_RAD)

def d_handle(px, py):
    d = sd_circle(px, py, HANDLE_CX, HANDLE_CY, HANDLE_R)
    di = sd_circle(px, py, HANDLE_CX, HANDLE_CY, HANDLE_R - HANDLE_T)
    return smax(d, -di, 6.0)

def d_body(px, py):
    return sd_ellipse(px, py, BODY_CX, BODY_CY, BODY_RX, BODY_RY)

def d_head(px, py):
    d = sd_circle(px, py, HEAD_CX, HEAD_CY, HEAD_R)
    for ex, ey in (EAR_L, EAR_R):
        d = smin(d, sd_circle(px, py, ex, ey, EAR_R2), 10.0)
    return d

def d_patch(px, py, c):
    d = sd_ellipse(px, py, c[0], c[1], PATCH_RX, PATCH_RY)
    cut = sd_circle(px, py, c[0], c[1] + 140.0, 110.0)
    return smax(d, cut, 10.0)

def d_eye(px, py, c):
    return sd_circle(px, py, c[0], c[1], EYE_R2)

def d_mango(px, py):
    return sd_ellipse(px, py, MANGO_CX, MANGO_CY, MANGO_RX, MANGO_RY)

def d_mango_seed(px, py):
    return sd_ellipse(px, py, MANGO_SEED_CX, MANGO_SEED_CY, MANGO_SEED_RX, MANGO_SEED_RY)

def d_flower(px, py):
    d = 1e9
    for i in range(6):
        a = i * math.pi / 3.0 + 0.3
        fx = FLOWER_POS[0] + math.cos(a) * FLOWER_R * 0.7
        fy = FLOWER_POS[1] + math.sin(a) * FLOWER_R * 0.7
        d = smin(d, sd_circle(px, py, fx, fy, 16.0), 8.0)
    return d

def d_flower_core(px, py):
    return sd_circle(px, py, FLOWER_POS[0], FLOWER_POS[1], 13.0)

def d_leaf(px, py):
    return sd_ellipse(px, py, FLOWER_POS[0] + 34.0, FLOWER_POS[1] + 30.0, 26.0, 12.0)

def d_steam(px, py, sx):
    t = (py - 500.0) / 180.0
    cx = sx + math.sin(t * 4.0 + sx * 0.01) * 30.0
    return sd_capsule(px, py, cx, py - 10, cx, py + 10, 11.0)

def d_heart(px, py, hx, hy, s):
    d1 = sd_circle(px, py, hx - s * 0.5, hy - s * 0.3, s * 0.55)
    d2 = sd_circle(px, py, hx + s * 0.5, hy - s * 0.3, s * 0.55)
    d3 = sd_ellipse(px, py, hx, hy + s * 0.35, s * 0.78, s * 0.62)
    return smin(smin(d1, d2, 6.0), d3, 6.0)

# ---------- painter ----------
def render():
    """Bbox-driven painter: each shape evaluates its SDF only inside its
    bounding box, blended in order into float accumulation buffers."""
    r_buf = [0.0] * (W * H)
    g_buf = [0.0] * (W * H)
    b_buf = [0.0] * (W * H)

    def paint(fn, color, alpha_scale, x0, y0, x1, y1, w=1.2):
        x0 = max(0, int(x0)); y0 = max(0, int(y0))
        x1 = min(W, int(x1) + 1); y1 = min(H, int(y1) + 1)
        cr, cg, cb = color
        for y in range(y0, y1):
            base = y * W
            for x in range(x0, x1):
                a = fn(x, y)
                if a <= 0.004:
                    continue
                a *= alpha_scale
                if a <= 0.004:
                    continue
                if a > 1.0:
                    a = 1.0
                i = base + x
                r_buf[i] += (cr - r_buf[i]) * a
                g_buf[i] += (cg - g_buf[i]) * a
                b_buf[i] += (cb - b_buf[i]) * a

    # background gradient (per row, one blend then fill row)
    for y in range(H):
        t = y / H
        cr = BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t
        cg = BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t
        cb = BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t
        base = y * W
        for x in range(W):
            i = base + x
            r_buf[i] = cr
            g_buf[i] = cg
            b_buf[i] = cb

    # polka dots (faint white)
    for dx, dy, dr in dots:
        paint(lambda x, y, dx=dx, dy=dy, dr=dr: aa(sd_circle(x, y, dx, dy, dr)) * 0.35,
              DOT, 1.0, dx - dr - 3, dy - dr - 3, dx + dr + 3, dy + dr + 3)

    # soft glow behind cup (radial falloff) — before hearts so hearts stay vivid
    paint(lambda x, y: (1.0 - sstep(0.0, GLOW_R, d_glow(x, y))),
          GLOW, 0.30, GLOW_CX - GLOW_R - 4, GLOW_CY - GLOW_R - 4,
          GLOW_CX + GLOW_R + 4, GLOW_CY + GLOW_R + 4)

    # mini hearts
    for hx, hy, hs in HEARTS:
        pad = hs + 4
        paint(lambda x, y, hx=hx, hy=hy, hs=hs: aa(d_heart(x, y, hx, hy, hs)) * 0.9,
              HEART, 1.0, hx - pad, hy - pad, hx + pad, hy + pad)

    # saucer
    paint(lambda x, y: aa(d_saucer(x, y)), SAUCER, 1.0,
          SAUCER_CX - SAUCER_HW - SAUCER_RAD - 4, SAUCER_CY - SAUCER_HH - SAUCER_RAD - 4,
          SAUCER_CX + SAUCER_HW + SAUCER_RAD + 4, SAUCER_CY + SAUCER_HH + SAUCER_RAD + 4)

    # steam curls (soft white, rising beside the head)
    for sx in STEAM_X:
        paint(lambda x, y, sx=sx: aa(d_steam(x, y, sx), 2.0),
              STEAM, 0.28, sx - 90, 430, sx + 90, 650)

    # ---- sloth body & head ----
    paint(lambda x, y: aa(d_body(x, y)), BODY, 1.0,
          BODY_CX - BODY_RX - 4, BODY_CY - BODY_RY - 4,
          BODY_CX + BODY_RX + 4, BODY_CY + BODY_RY + 4)
    # chest feather-fur arcs (3)
    for fx, fy in CHEST_FUR:
        paint(lambda x, y, fx=fx, fy=fy: aa(sd_capsule(x, y, fx - 26, fy, fx + 26, fy, 5.0)) * 0.8,
              FUR, 1.0, fx - 34, fy - 8, fx + 34, fy + 8)
    # body bottom shade
    paint(lambda x, y: aa(sd_ellipse(x, y, BODY_CX, BODY_CY + 60, BODY_RX - 18, 60)) * 0.4,
          BODY_DARK, 1.0, BODY_CX - BODY_RX, BODY_CY, BODY_CX + BODY_RX, BODY_CY + BODY_RY + 64)

    # paws resting on the cup rim (claws draped over the front wall)
    for bx, by in ((BODY_CX - 118, BODY_CY - 4), (BODY_CX + 118, BODY_CY - 2)):
        paint(lambda x, y, bx=bx, by=by: aa(sd_circle(x, y, bx, by, 44)), BODY_DARK, 1.0,
              bx - 48, by - 48, bx + 48, by + 48)

    # head (with ears smooth-unioned)
    paint(lambda x, y: aa(d_head(x, y)), BODY, 1.0,
          HEAD_CX - HEAD_R - 8, HEAD_CY - HEAD_R - 60,
          HEAD_CX + HEAD_R + 8, HEAD_CY + HEAD_R + 8)
    # cream face
    paint(lambda x, y: aa(sd_ellipse(x, y, HEAD_CX, HEAD_CY + 24, 128, 106)), CREAM, 1.0,
          HEAD_CX - 132, HEAD_CY - 86, HEAD_CX + 132, HEAD_CY + 134)
    # dark sloth eye-patches (2, symmetric, curved)
    for c in (PATCH_L_C, PATCH_R_C):
        paint(lambda x, y, c=c: aa(d_patch(x, y, c)), PATCH, 1.0,
              c[0] - PATCH_RX - 6, c[1] - PATCH_RY - 6, c[0] + PATCH_RX + 6, c[1] + 60)
    # glossy eyes + highlights
    for c in (EYE_L_C, EYE_R_C):
        paint(lambda x, y, c=c: aa(d_eye(x, y, c)), EYE, 1.0,
              c[0] - EYE_R2 - 4, c[1] - EYE_R2 - 4, c[0] + EYE_R2 + 4, c[1] + EYE_R2 + 4)
        paint(lambda x, y, c=c: aa(sd_circle(x, y, c[0] + 12, c[1] - 14, 12)), WHITE, 1.0,
              c[0] - 4, c[1] - 30, c[0] + 28, c[1] + 2)
        paint(lambda x, y, c=c: aa(sd_circle(x, y, c[0] - 10, c[1] + 12, 6)), WHITE, 0.8,
              c[0] - 20, c[1] + 2, c[0] - 4, c[1] + 22)
    # nose
    paint(lambda x, y: aa(sd_ellipse(x, y, HEAD_CX, HEAD_CY + 44, 22, 15)), NOSE, 1.0,
          HEAD_CX - 26, HEAD_CY + 24, HEAD_CX + 26, HEAD_CY + 64)
    # smile
    def smile(x, y):
        sm = sd_capsule(x, y, HEAD_CX - 24, HEAD_CY + 78, HEAD_CX, HEAD_CY + 88, 6)
        sm = smin(sm, sd_capsule(x, y, HEAD_CX, HEAD_CY + 88, HEAD_CX + 24, HEAD_CY + 78, 6), 8)
        return aa(sm)
    paint(smile, MOUTH, 1.0, HEAD_CX - 34, HEAD_CY + 68, HEAD_CX + 34, HEAD_CY + 98)
    # ear shading + inner cream
    for ex, ey in (EAR_L, EAR_R):
        paint(lambda x, y, ex=ex, ey=ey: aa(sd_circle(x, y, ex, ey, EAR_R2)) * 0.55,
              BODY_DARK, 1.0, ex - EAR_R2 - 4, ey - EAR_R2 - 4, ex + EAR_R2 + 4, ey + EAR_R2 + 4)
        paint(lambda x, y, ex=ex, ey=ey: aa(sd_circle(x, y, ex, ey, EAR_R2 * 0.55)),
              CREAM, 1.0, ex - 30, ey - 30, ex + 30, ey + 30)

    # green leaf tucked under flower
    paint(lambda x, y: aa(d_leaf(x, y)), LEAF, 1.0,
          FLOWER_POS[0] + 2, FLOWER_POS[1] + 12, FLOWER_POS[0] + 66, FLOWER_POS[1] + 48)
    # yellow flower on right ear
    paint(lambda x, y: aa(d_flower(x, y)), FLOWER, 1.0,
          FLOWER_POS[0] - 44, FLOWER_POS[1] - 44, FLOWER_POS[0] + 44, FLOWER_POS[1] + 44)
    paint(lambda x, y: aa(d_flower_core(x, y)), FLOWER_CORE, 1.0,
          FLOWER_POS[0] - 17, FLOWER_POS[1] - 17, FLOWER_POS[0] + 17, FLOWER_POS[1] + 17)

    # mango slice (held by right paw, below mouth level)
    paint(lambda x, y: aa(d_mango(x, y)), MANGO_RIND, 1.0,
          MANGO_CX - MANGO_RX - 4, MANGO_CY - MANGO_RY - 4,
          MANGO_CX + MANGO_RX + 4, MANGO_CY + MANGO_RY + 4)
    paint(lambda x, y: aa(sd_ellipse(x, y, MANGO_CX, MANGO_CY, MANGO_RX - 12, MANGO_RY - 12)),
          MANGO_Y, 1.0, MANGO_CX - MANGO_RX, MANGO_CY - MANGO_RY,
          MANGO_CX + MANGO_RX, MANGO_CY + MANGO_RY)
    paint(lambda x, y: aa(sd_ellipse(x, y, MANGO_CX + 40, MANGO_CY - 18, 52, 34)) * 0.7,
          MANGO_O, 1.0, MANGO_CX - 20, MANGO_CY - 60, MANGO_CX + 100, MANGO_CY + 24)
    paint(lambda x, y: aa(d_mango_seed(x, y)), MANGO_SEED, 1.0,
          MANGO_SEED_CX - MANGO_SEED_RX - 4, MANGO_SEED_CY - MANGO_SEED_RY - 4,
          MANGO_SEED_CX + MANGO_SEED_RX + 4, MANGO_SEED_CY + MANGO_SEED_RY + 4)

    # cup (front wall overlaps sloth bottom — sloth sits IN the cup)
    paint(lambda x, y: aa(d_cup(x, y)), CUP, 1.0,
          CUP_CX - CUP_HW - CUP_RAD - 4, CUP_CY - CUP_HH - CUP_RAD - 4,
          CUP_CX + CUP_HW + CUP_RAD + 4, CUP_CY + CUP_HH + CUP_RAD + 4)
    paint(lambda x, y: aa(sd_box(x, y, CUP_CX, CUP_CY + CUP_HH - 40, CUP_HW - 16, 40, CUP_RAD - 16)) * 0.55,
          CUP_SHADE, 1.0, CUP_CX - CUP_HW, CUP_CY + 60, CUP_CX + CUP_HW, CUP_CY + CUP_HH + 4)
    paint(lambda x, y: aa(sd_box(x, y, CUP_CX, CUP_CY - CUP_HH + 16, CUP_HW - 12, 18, 14)),
          CUP_RIM, 1.0, CUP_CX - CUP_HW, CUP_CY - CUP_HH - 6, CUP_CX + CUP_HW, CUP_CY - CUP_HH + 40)
    # cup handle (right side, clear ring)
    paint(lambda x, y: aa(d_handle(x, y)), CUP, 1.0,
          HANDLE_CX - HANDLE_R - 4, HANDLE_CY - HANDLE_R - 4,
          HANDLE_CX + HANDLE_R + 4, HANDLE_CY + HANDLE_R + 4)
    paint(lambda x, y: aa(sd_circle(x, y, HANDLE_CX, HANDLE_CY, HANDLE_R))
                       * (1.0 - aa(sd_circle(x, y, HANDLE_CX, HANDLE_CY, HANDLE_R - 10))),
          CUP_SHADE, 0.6, HANDLE_CX - HANDLE_R, HANDLE_CY - HANDLE_R,
          HANDLE_CX + HANDLE_R, HANDLE_CY + HANDLE_R)

    # sloth claws draped over the cup front wall (3 per paw)
    for bx, by in ((BODY_CX - 118, BODY_CY - 4), (BODY_CX + 118, BODY_CY - 2)):
        for k in range(3):
            kx = bx - 26 + k * 26
            paint(lambda x, y, kx=kx, by=by: aa(sd_capsule(x, y, kx, by + 30, kx, by + 52, 5.0)),
                  CREAM, 1.0, kx - 8, by + 22, kx + 8, by + 58)

    img = bytearray(W * H * 3)
    idx = 0
    for i in range(W * H):
        img[idx] = int(r_buf[i] + 0.5)
        img[idx + 1] = int(g_buf[i] + 0.5)
        img[idx + 2] = int(b_buf[i] + 0.5)
        idx += 3
    return bytes(img)


def write_png(path, raw):
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    stride = W * 3
    rows = bytearray()
    for y in range(H):
        rows.append(0)
        rows += raw[y * stride:(y + 1) * stride]
    idat = zlib.compress(bytes(rows), 6)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return len(png)


if __name__ == "__main__":
    outdir = os.environ.get("MAKEFUN_OUTPUT_DIR", "out")
    os.makedirs(outdir, exist_ok=True)
    dots = []
    for gy in range(7):
        for gx in range(7):
            dots.append((60 + gx * 152 + (76 if gy % 2 else 0),
                         90 + gy * 148, 17))
    raw = render()
    path = os.path.join(outdir, "entry.png")
    n = write_png(path, raw)
    print(f"wrote {path} ({n} bytes)")
