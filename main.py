#!/usr/bin/env python3
"""make.fun cutest-picture-01 — 'baby axolotl floating'

Pure stdlib Python 3. SDF shapes + smoothstep AA, manual PNG encoder
(zlib + struct, raw RGB scanlines, filter 0). Deterministic: fixed seed.
1024x1024, target < 1 MiB, < 60 s.
"""
import math
import os
import random
import struct
import zlib

W = H = 1024
AA = 1.2  # anti-alias half-width in px

# ---------------- palette ----------------
BG_TOP = (150.0, 222.0, 220.0)
BG_BOT = (28.0, 94.0, 110.0)
RAY = (215.0, 242.0, 240.0)
BODY = (255.0, 217.0, 201.0)        # peach  #FFD9C9
BODY_EDGE = (243.0, 185.0, 158.0)   # shaded peach
GILL = (255.0, 143.0, 163.0)        # coral  #FF8FA3
GILL_TIP = (255.0, 182.0, 196.0)
EYE = (36.0, 30.0, 43.0)
EYE_RIM = (18.0, 14.0, 24.0)
WHITE = (255.0, 255.0, 255.0)
BLUSH = (255.0, 138.0, 150.0)
HEART = (255.0, 105.0, 130.0)
BUBBLE = (225.0, 248.0, 246.0)
GLOW = (255.0, 205.0, 212.0)

# ---------------- buffers ----------------
R = [0.0] * (W * H)
G = [0.0] * (W * H)
B = [0.0] * (W * H)


def blend(i, r, g, b, a):
    R[i] += (r - R[i]) * a
    G[i] += (g - G[i]) * a
    B[i] += (b - B[i]) * a


def add(i, r, g, b, k):
    R[i] += r * k
    G[i] += g * k
    B[i] += b * k


def aa_a(d):
    if d <= -AA:
        return 1.0
    if d >= AA:
        return 0.0
    t = 0.5 - d / (2.0 * AA)
    return t * t * (3.0 - 2.0 * t)


def clamp01(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def sstep(e0, e1, x):
    t = clamp01((x - e0) / (e1 - e0))
    return t * t * (3.0 - 2.0 * t)


# ---------------- SDF primitives ----------------
def sd_circle(dx, dy, r):
    return math.sqrt(dx * dx + dy * dy) - r


def sd_ellipse(dx, dy, rx, ry):
    q = math.sqrt(dx * dx / (rx * rx) + dy * dy / (ry * ry))
    return (q - 1.0) * (rx if rx < ry else ry)


def sd_cap(px, py, ax, ay, bx, by, r):
    pax = px - ax
    pay = py - ay
    bax = bx - ax
    bay = by - ay
    bb = bax * bax + bay * bay
    h = 0.0 if bb == 0.0 else (pax * bax + pay * bay) / bb
    if h < 0.0:
        h = 0.0
    elif h > 1.0:
        h = 1.0
    dx = pax - bax * h
    dy = pay - bay * h
    return math.sqrt(dx * dx + dy * dy) - r


def sd_arc(px, py, cx, cy, r, a0, a1, th):
    dx = px - cx
    dy = py - cy
    l = math.sqrt(dx * dx + dy * dy)
    ang = math.atan2(dy, dx)
    mid = 0.5 * (a0 + a1)
    half = 0.5 * (a1 - a0)
    da = ang - mid
    da = (da + math.pi) % (2.0 * math.pi) - math.pi
    if abs(da) <= half:
        return abs(l - r) - th * 0.5
    ea = a0 if da < 0.0 else a1
    ex = cx + r * math.cos(ea)
    ey = cy + r * math.sin(ea)
    ddx = px - ex
    ddy = py - ey
    return math.sqrt(ddx * ddx + ddy * ddy) - th * 0.5


# ---------------- creature group transform ----------------
GCX, GCY = 512.0, 524.0
TH = 0.11  # floating tilt (radians)
CA = math.cos(TH)
SA = math.sin(TH)

# local layout
HX, HY = -30.0, -70.0      # head center
HR = 215.0                 # head radius
BX, BY = 115.0, 95.0       # body center
BRX, BRY = 130.0, 100.0    # body ellipse
EYE1 = (HX - 100.0, HY - 40.0)
EYE2 = (HX + 58.0, HY - 40.0)
EYE_R = 36.0
MOUTH = (HX - 20.0, HY + 44.0)


def to_local(px, py):
    dx = px - GCX
    dy = py - GCY
    return dx * CA + dy * SA, -dx * SA + dy * CA


def head_sd(lx, ly):
    return sd_circle(lx - HX, ly - HY, HR)


def body_sd(lx, ly):
    return sd_ellipse(lx - BX, ly - BY, BRX, BRY)


def tail_sd(lx, ly):
    d1 = sd_cap(lx, ly, BX + 100.0, BY + 45.0, BX + 175.0, BY + 80.0, 17.0)
    d2 = sd_cap(lx, ly, BX + 175.0, BY + 80.0, BX + 225.0, BY + 102.0, 7.0)
    return d1 if d1 < d2 else d2


def creature_sd(lx, ly):
    d = head_sd(lx, ly)
    b = body_sd(lx, ly)
    if b < d:
        d = b
    t = tail_sd(lx, ly)
    if t < d:
        d = t
    return d


# ---------------- pass 1: background ----------------
def draw_bg():
    beams = ((250.0, 0.32, 95.0), (510.0, 0.02, 120.0), (760.0, -0.28, 90.0))
    for y in range(H):
        ty = y / (H - 1)
        br = BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * ty
        bgg = BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * ty
        bb = BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * ty
        strength = 0.11 * math.exp(-y / 620.0)
        b1x = beams[0][0] + beams[0][1] * y
        b1s2 = 2.0 * beams[0][2] * beams[0][2]
        b2x = beams[1][0] + beams[1][1] * y
        b2s2 = 2.0 * beams[1][2] * beams[1][2]
        b3x = beams[2][0] + beams[2][1] * y
        b3s2 = 2.0 * beams[2][2] * beams[2][2]
        row = y * W
        for x in range(W):
            v = strength * (
                math.exp(-((x - b1x) * (x - b1x)) / b1s2)
                + math.exp(-((x - b2x) * (x - b2x)) / b2s2)
                + math.exp(-((x - b3x) * (x - b3x)) / b3s2)
            )
            i = row + x
            R[i] = br + RAY[0] * v
            G[i] = bgg + RAY[1] * v
            B[i] = bb + RAY[2] * v


# ---------------- pass 2: soft glow around creature ----------------
def draw_glow():
    x0, x1, y0, y1 = 60, 970, 60, 990
    for y in range(y0, y1):
        row = y * W
        for x in range(x0, x1):
            lx, ly = to_local(x, y)
            d = creature_sd(lx, ly)
            if d > 0.0:
                g = 0.22 * math.exp(-d / 34.0)
                if g > 0.002:
                    i = row + x
                    add(i, GLOW[0], GLOW[1], GLOW[2], g)


# ---------------- pass 3: gills (feathery ektorel) ----------------
def gill_segments():
    """Build 6 gills: main capsule + 3 feather branches + tip, per side."""
    segs = []
    fan = (-60.0, -25.0, 5.0)
    for side in (1.0, -1.0):
        for deg in fan:
            a = math.radians(deg)
            dx = side * math.cos(a)
            dy = math.sin(a)
            L = 100.0 - abs(deg) * 0.45
            bx = HX + dx * (HR - 30.0)
            by = HY + dy * (HR - 30.0)
            ex = bx + dx * L
            ey = by + dy * L
            segs.append(((bx, by, ex, ey, 7.5), GILL))
            for fi, t in enumerate((0.26, 0.44, 0.62, 0.79)):
                px = bx + dx * L * t
                py = by + dy * L * t
                fa = math.radians(40.0 + t * 16.0)
                if fi % 2 == 0:
                    fdx = dx * math.cos(fa) - dy * math.sin(fa)
                    fdy = dx * math.sin(fa) + dy * math.cos(fa)
                else:
                    fdx = dx * math.cos(fa) + dy * math.sin(fa)
                    fdy = -dx * math.sin(fa) + dy * math.cos(fa)
                flen = 30.0 * (1.0 - 0.45 * t)
                fr = 3.4 * (1.0 - 0.45 * t)
                segs.append((
                    (px - fdx * 3.0, py - fdy * 3.0,
                     px + fdx * flen, py + fdy * flen, fr),
                    GILL,
                ))
            segs.append(((ex, ey, ex, ey, 5.5), GILL_TIP))
    return segs


GILL_SEGS = gill_segments()


def draw_gills():
    for side in (0, 1):  # 0: right gills, 1: left gills
        x0, x1 = (500, 980) if side == 0 else (50, 530)
        for y in range(140, 620):
            row = y * W
            for x in range(x0, x1):
                lx, ly = to_local(x, y)
                best = 1e9
                bc = GILL
                for (ax, ay, bx, by, rr), col in GILL_SEGS:
                    d = sd_cap(lx, ly, ax, ay, bx, by, rr)
                    if d < best:
                        best = d
                        bc = col
                if best < AA:
                    i = row + x
                    a = aa_a(best)
                    if a > 0.0:
                        blend(i, bc[0], bc[1], bc[2], a)


# ---------------- pass 4: tail + body + head ----------------
def draw_body_head():
    x0, x1, y0, y1 = 240, 980, 180, 990
    for y in range(y0, y1):
        row = y * W
        for x in range(x0, x1):
            lx, ly = to_local(x, y)
            d = creature_sd(lx, ly)
            if d >= AA:
                continue
            i = row + x
            a = aa_a(d)
            if a <= 0.0:
                continue
            hd = head_sd(lx, ly)
            if hd < 0.0:
                dxh = (lx - HX) / HR
                dyh = (ly - HY) / HR
                shade = sstep(-0.35, 0.85, dyh * 0.8 + abs(dxh) * 0.35)
                r = BODY[0] + (BODY_EDGE[0] - BODY[0]) * shade
                g = BODY[1] + (BODY_EDGE[1] - BODY[1]) * shade
                b = BODY[2] + (BODY_EDGE[2] - BODY[2]) * shade
            elif body_sd(lx, ly) < 0.0:
                bdx = (lx - BX) / BRX
                bdy = (ly - BY) / BRY
                shade = sstep(-0.6, 0.9, bdy * 0.7 + abs(bdx) * 0.4)
                r = BODY[0] + (BODY_EDGE[0] - BODY[0]) * shade
                g = BODY[1] + (BODY_EDGE[1] - BODY[1]) * shade
                b = BODY[2] + (BODY_EDGE[2] - BODY[2]) * shade
            else:
                r, g, b = BODY_EDGE
            blend(i, r, g, b, a)


# ---------------- pass 5: shimmer + top highlight ----------------
def draw_shimmer():
    cx, cy, rx, ry = HX - 70.0, HY - 150.0, 95.0, 45.0
    for y in range(200, 480):
        row = y * W
        for x in range(260, 760):
            lx, ly = to_local(x, y)
            d = sd_ellipse(lx - cx, ly - cy, rx, ry)
            if d < 10.0:
                a = sstep(10.0, -25.0, d) * 0.22
                i = row + x
                add(i, WHITE[0], WHITE[1], WHITE[2], a)
    for y in range(180, 900):
        row = y * W
        for x in range(240, 990):
            lx, ly = to_local(x, y)
            d = head_sd(lx, ly)
            if -6.0 < d < -0.5 and ly < -30.0:
                i = row + x
                add(i, WHITE[0], WHITE[1], WHITE[2], 0.45 * sstep(-0.5, -6.0, d))
            else:
                d2 = body_sd(lx, ly)
                if -6.0 < d2 < -0.5 and ly - BY < -20.0:
                    i = row + x
                    add(i, WHITE[0], WHITE[1], WHITE[2], 0.40 * sstep(-0.5, -6.0, d2))


# ---------------- pass 6: paw over head ----------------
def draw_paw():
    arm = (HX - 20.0, HY - 120.0, HX - 88.0, HY - 208.0, 14.0)
    px, py, prx, pry = HX - 96.0, HY - 226.0, 37.0, 28.0
    x0, x1, y0, y1 = 150, 560, 80, 460
    for y in range(y0, y1):
        row = y * W
        for x in range(x0, x1):
            lx, ly = to_local(x, y)
            da = sd_cap(lx, ly, arm[0], arm[1], arm[2], arm[3], arm[4])
            de = sd_ellipse(lx - px, ly - py, prx, pry)
            d = da if da < de else de
            if d >= AA:
                continue
            i = row + x
            a = aa_a(d)
            if a <= 0.0:
                continue
            rimb = sstep(-10.0, -1.0, d)
            r = 255.0 - 14.0 * (1.0 - rimb)
            g = 224.0 - 30.0 * (1.0 - rimb)
            b = 210.0 - 32.0 * (1.0 - rimb)
            blend(i, r, g, b, a)
            if de < 0.0:
                for ti in (-1, 0, 1):
                    tx = px + ti * 16.0
                    dt = sd_cap(lx, ly, tx, py - 18.0, tx + ti * 4.0, py - 2.0, 1.8)
                    if dt < 1.8:
                        ta = aa_a(dt) * 0.35
                        blend(i, 210.0, 160.0, 145.0, ta)


# ---------------- pass 7: eyes, mouth, blush ----------------
def draw_face():
    x0, x1, y0, y1 = 150, 900, 220, 700
    for y in range(y0, y1):
        row = y * W
        for x in range(x0, x1):
            lx, ly = to_local(x, y)
            i = row + x
            for ecx, ecy in (EYE1, EYE2):
                d = sd_circle(lx - ecx, ly - ecy, EYE_R)
                if d < AA:
                    a = aa_a(d)
                    if a > 0.0:
                        if d > -3.0:
                            blend(i, EYE_RIM[0], EYE_RIM[1], EYE_RIM[2], a)
                        else:
                            blend(i, EYE[0], EYE[1], EYE[2], a)
                dsh = sd_ellipse(lx - ecx, ly - (ecy + 20.0), 17.0, 7.0)
                if dsh < 0.0:
                    add(i, WHITE[0], WHITE[1], WHITE[2], 0.30 * sstep(0.0, -10.0, dsh))
                dh = sd_circle(lx - (ecx - 13.0), ly - (ecy - 14.0), 12.0)
                if dh < AA:
                    a = aa_a(dh)
                    if a > 0.0:
                        blend(i, WHITE[0], WHITE[1], WHITE[2], a * 0.97)
                ds = sd_circle(lx - (ecx + 10.0), ly - (ecy + 7.0), 5.5)
                if ds < AA:
                    a = aa_a(ds)
                    if a > 0.0:
                        blend(i, WHITE[0], WHITE[1], WHITE[2], a * 0.9)
            dm = sd_arc(lx, ly, MOUTH[0], MOUTH[1], 17.0, 0.35, 2.79, 7.0)
            if dm < AA:
                a = aa_a(dm)
                if a > 0.0:
                    blend(i, 130.0, 82.0, 82.0, a)
            for bcx, bcy in ((HX - 158.0, HY + 32.0), (HX + 116.0, HY + 32.0)):
                db = sd_ellipse(lx - bcx, ly - bcy, 32.0, 19.0)
                if db < 14.0:
                    a = sstep(14.0, -8.0, db) * 0.50
                    if a > 0.0:
                        blend(i, BLUSH[0], BLUSH[1], BLUSH[2], a)


# ---------------- pass 8: bubbles + specks ----------------
def draw_bubbles():
    rng = random.Random(20261112)
    for _ in range(18):
        bx = rng.uniform(40.0, 984.0)
        by = rng.uniform(60.0, 880.0)
        br = rng.uniform(6.0, 24.0)
        x0 = max(0, int(bx - br - 3))
        x1 = min(W - 1, int(bx + br + 3))
        y0 = max(0, int(by - br - 3))
        y1 = min(H - 1, int(by + br + 3))
        for y in range(y0, y1 + 1):
            row = y * W
            for x in range(x0, x1 + 1):
                d = sd_circle(x - bx, y - by, br)
                i = row + x
                ring = sstep(2.6, 0.6, abs(d))
                if ring > 0.0:
                    blend(i, BUBBLE[0], BUBBLE[1], BUBBLE[2], ring * 0.55)
                inner = sstep(0.0, -br * 0.8, d)
                if inner > 0.0:
                    add(i, BUBBLE[0], BUBBLE[1], BUBBLE[2], inner * 0.10)
                dspec = sd_circle(x - (bx - br * 0.35), y - (by - br * 0.35), br * 0.18)
                if dspec < 0.0:
                    add(i, WHITE[0], WHITE[1], WHITE[2], 0.35)
    for _ in range(46):
        sx = rng.uniform(10.0, 1010.0)
        sy = rng.uniform(10.0, 1010.0)
        sr = rng.uniform(1.0, 2.6)
        i = int(sy) * W + int(sx)
        add(i, WHITE[0], WHITE[1], WHITE[2], 0.16)
    # a few larger foreground bubbles drifting up
    for _ in range(6):
        bx = rng.uniform(120.0, 900.0)
        by = rng.uniform(300.0, 950.0)
        br = rng.uniform(26.0, 38.0)
        for y in range(max(0, int(by - br - 3)), min(H - 1, int(by + br + 3)) + 1):
            row = y * W
            for x in range(max(0, int(bx - br - 3)), min(W - 1, int(bx + br + 3)) + 1):
                d = sd_circle(x - bx, y - by, br)
                i = row + x
                ring = sstep(3.2, 1.0, abs(d))
                if ring > 0.0:
                    blend(i, BUBBLE[0], BUBBLE[1], BUBBLE[2], ring * 0.45)
                inner = sstep(0.0, -br * 0.85, d)
                if inner > 0.0:
                    add(i, BUBBLE[0], BUBBLE[1], BUBBLE[2], inner * 0.07)
                dspec = sd_circle(x - (bx - br * 0.35), y - (by - br * 0.35), br * 0.16)
                if dspec < 0.0:
                    add(i, WHITE[0], WHITE[1], WHITE[2], 0.3)


# ---------------- pass 8b: sparkles ----------------
def draw_sparkles():
    spots = ((680.0, 160.0, 9.0), (180.0, 560.0, 7.0), (860.0, 520.0, 8.0))
    for (sx, sy, s) in spots:
        for y in range(max(0, int(sy - s - 2)), min(H - 1, int(sy + s + 2)) + 1):
            row = y * W
            for x in range(max(0, int(sx - s - 2)), min(W - 1, int(sx + s + 2)) + 1):
                dx = abs(x - sx)
                dy = abs(y - sy)
                star = max(0.0, 1.0 - (dx + dy) / s)
                star = star * star
                if star > 0.01:
                    add(row + x, WHITE[0], WHITE[1], WHITE[2], star * 0.9)


# ---------------- pass 9: hearts ----------------
def draw_hearts():
    spots = ((300.0, 200.0, 15.0), (760.0, 300.0, 12.0), (250.0, 420.0, 10.0))
    for (hx, hy, s) in spots:
        x0 = max(0, int(hx - s * 1.6))
        x1 = min(W - 1, int(hx + s * 1.6))
        y0 = max(0, int(hy - s * 1.6))
        y1 = min(H - 1, int(hy + s * 1.6))
        for y in range(y0, y1 + 1):
            row = y * W
            for x in range(x0, x1 + 1):
                ux = (x - hx) / s
                uy = (hy - y) / s
                f = (ux * ux + uy * uy - 1.0) ** 3 - ux * ux * uy * uy * uy
                a = sstep(0.9, -0.9, f * 2.2)
                if a > 0.0:
                    i = row + x
                    blend(i, HEART[0], HEART[1], HEART[2], a * 0.9)


# ---------------- PNG encode ----------------
def write_png(path):
    raw = bytearray()
    for y in range(H):
        raw.append(0)  # filter 0
        row = y * W
        for x in range(W):
            i = row + x
            r = R[i]
            g = G[i]
            b = B[i]
            raw.append(255 if r > 255.0 else (0 if r < 0.0 else int(r)))
            raw.append(255 if g > 255.0 else (0 if g < 0.0 else int(g)))
            raw.append(255 if b > 255.0 else (0 if b < 0.0 else int(b)))
    comp = zlib.compress(bytes(raw), 6)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", comp)
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def main():
    outdir = os.environ.get("MAKEFUN_OUTPUT_DIR", ".")
    os.makedirs(outdir, exist_ok=True)
    draw_bg()
    draw_glow()
    draw_gills()
    draw_body_head()
    draw_shimmer()
    draw_paw()
    draw_face()
    draw_bubbles()
    draw_sparkles()
    draw_hearts()
    path = os.path.join(outdir, "entry.png")
    write_png(path)
    print("wrote", path, os.path.getsize(path), "bytes")


if __name__ == "__main__":
    main()
