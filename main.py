#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""make.fun cutest-picture-01 entry: pastel chibi cat companion.
Pure stdlib. Renders 1024x1024 PNG deterministically."""

import math
import os
import struct
import zlib

W = H = 1024

# ---------------- palette (warm pastel) ----------------
BG      = (255, 241, 236)   # cream pink
DOT     = (255, 205, 220)   # polka dot pink
BODY    = (255, 236, 214)   # soft cream
BODY_D  = (247, 214, 186)   # body shade
OUTLINE = (150, 110, 110)   # soft brown outline
EAR_IN  = (255, 192, 203)   # inner ear pink
EYE     = (72, 60, 88)      # deep plum eyes
WHITE   = (255, 255, 255)
BLUSH   = (255, 170, 185)
NOSE    = (255, 150, 165)
HEART   = (255, 190, 205)
SPARK   = (255, 224, 178)   # gold sparkle
PAW     = (255, 226, 198)
SHADOW  = (250, 214, 214)


def smoothstep(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


class Canvas:
    def __init__(self, w, h, color):
        self.w, self.h = w, h
        self.px = [color] * (w * h)

    def _put(self, x, y, c, cov):
        i = y * self.w + x
        self.px[i] = tuple(int(self.px[i][k] + (c[k] - self.px[i][k]) * cov)
                           for k in range(3))

    def fill(self, sdf, c, aa=1.5):
        """Fill shape; sdf.px_dist() gives pixel-space signed distance."""
        x0, y0, x1, y1 = sdf.bounds()
        x0 = max(0, x0); y0 = max(0, y0)
        x1 = min(self.w - 1, x1); y1 = min(self.h - 1, y1)
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                d = sdf.px_dist(x, y)
                if d < -aa:
                    self._put(x, y, c, 1.0)
                elif d < aa:
                    cov = 0.0
                    for sy in (-0.25, 0.25):
                        for sx in (-0.25, 0.25):
                            cov += smoothstep(0.5 - sdf.px_dist(x + sx, y + sy) / aa)
                    self._put(x, y, c, cov / 4.0)

    def stroke(self, sdf, r, w, c):
        """Stroke outline at sdf radius r with width w."""
        s = StrokeSDF(sdf, r, w)
        self.fill(s, c)

    def to_png(self, path):
        raw = bytearray()
        for y in range(self.h):
            raw.append(0)  # filter 0
            row = self.px[y * self.w:(y + 1) * self.w]
            for r, g, b in row:
                raw += struct.pack("BBB", r, g, b)
        comp = zlib.compress(bytes(raw), 9)
        def chunk(tag, data):
            c = struct.pack(">I", len(data)) + tag + data
            return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        png = b"\x89PNG\r\n\x1a\n"
        png += chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
        png += chunk(b"IDAT", comp)
        png += chunk(b"IEND", b"")
        with open(path, "wb") as f:
            f.write(png)


class StrokeSDF:
    """SDF of a band |dist - r| <= w/2 around another sdf (pixel-space)."""
    def __init__(self, inner, r, w):
        self.inner, self.r, self.w = inner, r, w / 2.0
    def px_dist(self, x, y):
        return abs(self.inner.px_dist(x, y) - self.r) - self.w
    def bounds(self):
        x0, y0, x1, y1 = self.inner.bounds()
        m = int(self.r + self.w) + 4
        return x0 - m, y0 - m, x1 + m, y1 + m


class Circle:
    def __init__(self, cx, cy, r, ry=None):
        self.cx, self.cy, self.rx = cx, cy, r
        self.ry = r if ry is None else ry
    def px_dist(self, x, y):
        k = math.sqrt(((x - self.cx) / self.rx) ** 2 +
                      ((y - self.cy) / self.ry) ** 2)
        return (k - 1.0) * min(self.rx, self.ry)
    def bounds(self):
        return (int(self.cx - self.rx - 4), int(self.cy - self.ry - 4),
                int(self.cx + self.rx + 4), int(self.cy + self.ry + 4))


class Super:
    def __init__(self, cx, cy, a, b, n=2.6):
        self.cx, self.cy, self.a, self.b, self.n = cx, cy, a, b, n
    def px_dist(self, x, y):
        dx = abs((x - self.cx) / self.a)
        dy = abs((y - self.cy) / self.b)
        v = dx ** self.n + dy ** self.n
        return (v ** (1.0 / self.n) - 1.0) * min(self.a, self.b)
    def bounds(self):
        return (int(self.cx - self.a - 4), int(self.cy - self.b - 4),
                int(self.cx + self.a + 4), int(self.cy + self.b + 4))


class Triangle:
    """Triangle with pixel-space signed distance (inside negative)."""
    def __init__(self, pts):
        self.pts = pts
        # ensure CCW in screen coords (y down): signed area < 0 => CCW visual
        x0, y0 = pts[0]; x1, y1 = pts[1]; x2, y2 = pts[2]
        area = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
        if area > 0:
            self.pts = [pts[0], pts[2], pts[1]]
    def px_dist(self, x, y):
        d = -1e9
        for i in range(3):
            ax, ay = self.pts[i]
            bx, by = self.pts[(i + 1) % 3]
            ex, ey = bx - ax, by - ay
            L = math.hypot(ex, ey)
            dist = -((x - ax) * ey - (y - ay) * ex) / L  # <0 inside (CCW y-down)
            d = max(d, dist)
        return d
    def bounds(self):
        xs = [p[0] for p in self.pts]; ys = [p[1] for p in self.pts]
        return (int(min(xs) - 4), int(min(ys) - 4),
                int(max(xs) + 4), int(max(ys) + 4))


class Arc:
    """Semi-circle stroke: pixel distance to arc path (center, radius, angle range)."""
    def __init__(self, cx, cy, r, a0, a1, w):
        self.cx, self.cy, self.r = cx, cy, r
        self.a0, self.a1, self.w = a0, a1, w / 2.0
        self._e0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
        self._e1 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
    def px_dist(self, x, y):
        dx, dy = x - self.cx, y - self.cy
        a = math.atan2(dy, dx)
        two_pi = 2 * math.pi
        while a < self.a0:
            a += two_pi
        if a <= self.a1:
            dd = math.hypot(dx, dy) - self.r
        else:
            dd = min(math.hypot(x - self._e0[0], y - self._e0[1]),
                     math.hypot(x - self._e1[0], y - self._e1[1]))
        return dd - self.w
    def bounds(self):
        m = self.r + self.w + 4
        return (int(self.cx - m), int(self.cy - m), int(self.cx + m), int(self.cy + m))


def render():
    cv = Canvas(W, H, BG)

    # ---- background polka dots + floating hearts ----
    for gy in range(9):
        for gx in range(9):
            off = (gy % 2) * 56
            cv.fill(Circle(gx * 128 + off, gy * 128 + 40, 16), DOT)

    # hearts (two overlapping circles + triangle)
    def heart(cx, cy, s, c):
        cv.fill(Circle(cx - s * 0.35, cy - s * 0.25, s * 0.52), c)
        cv.fill(Circle(cx + s * 0.35, cy - s * 0.25, s * 0.52), c)
        cv.fill(Triangle([(cx - s * 0.85, cy - s * 0.1),
                          (cx + s * 0.85, cy - s * 0.1),
                          (cx, cy + s * 0.95)]), c)
    for cx, cy, s in [(150, 700, 30), (880, 620, 26), (120, 330, 22),
                      (920, 300, 30), (500, 130, 24)]:
        heart(cx, cy, s, HEART)

    # ---- ground shadow ----
    cv.fill(Circle(512, 938, 285, 46), SHADOW)

    # ---- tail (stroke arc on body right) ----
    cv.fill(Arc(660, 800, 110, math.radians(-70), math.radians(40), 46), BODY)
    cv.stroke(Arc(660, 800, 110, math.radians(-70), math.radians(40), 46), 0, 7, OUTLINE)

    # ---- body (squishy superellipse) ----
    body = Super(512, 790, 215, 150, 2.8)
    cv.fill(body, BODY)
    cv.stroke(body, 0, 9, OUTLINE)
    # belly patch
    cv.fill(Circle(512, 830, 120, 88), PAW)

    # ---- raised hand paws (cute waving pose) ----
    for hx in (352, 672):
        paw = Circle(hx, 778, 48)
        cv.fill(paw, BODY)
        cv.stroke(paw, 0, 8, OUTLINE)
        cv.fill(Arc(hx, 778, 36, math.radians(120), math.radians(240), 5), OUTLINE)

    # ---- paws (front feet) ----
    for px in (408, 616):
        paw = Circle(px, 918, 58, 44)
        cv.fill(paw, BODY)
        cv.stroke(paw, 0, 7, OUTLINE)
        # toe lines
        cv.fill(Arc(px, 918, 46, math.radians(205), math.radians(335), 5), OUTLINE)

    # ---- ears ----
    for ex, flip in [(330, -1), (694, 1)]:
        ear = Triangle([(ex - 55 * (1 if flip > 0 else -1), 320),
                        (ex + 55 * (1 if flip > 0 else -1), 320),
                        (ex, 140)])
        cv.fill(ear, BODY)
        cv.stroke(ear, 0, 7, OUTLINE)
        inner = Triangle([(ex - 30 * (1 if flip > 0 else -1), 315),
                          (ex + 30 * (1 if flip > 0 else -1), 315),
                          (ex, 185)])
        cv.fill(inner, EAR_IN)

    # ---- head (big circle, chibi ratio) ----
    head = Circle(512, 440, 265)
    cv.fill(head, BODY)
    cv.stroke(head, 0, 9, OUTLINE)
    # soft top shade (kept inside the head so it never touches the ears)
    cv.fill(Circle(512, 245, 170, 85), BODY_D)
    # tabby stripes on the forehead
    for sx, sw in ((452, 26), (512, 34), (572, 26)):
        cv.fill(Triangle([(sx - sw, 210), (sx + sw, 210), (sx, 292)]), BODY_D)

    # ---- eyes (big, glossy, sparkly) ----
    for ex in (405, 619):
        eye = Circle(ex, 465, 70, 80)
        cv.fill(eye, EYE)
        # glossy highlights
        cv.fill(Circle(ex - 26, 432, 28), WHITE)
        cv.fill(Circle(ex + 22, 498, 13), WHITE)
        # 4-point sparkle
        for ang in (0, 90, 180, 270):
            a = math.radians(ang)
            cv.fill(Circle(ex + 30 + 18 * math.cos(a), 448 + 18 * math.sin(a),
                           6), WHITE)
        cv.fill(Circle(ex + 30, 448, 8), WHITE)

    # ---- blush (with tiny shine dashes) ----
    cv.fill(Circle(300, 560, 52, 34), BLUSH)
    cv.fill(Circle(724, 560, 52, 34), BLUSH)
    cv.fill(Circle(286, 548, 8), WHITE)
    cv.fill(Circle(738, 548, 8), WHITE)

    # ---- nose + mouth ----
    nose = Triangle([(487, 545), (537, 545), (512, 578)])
    cv.fill(nose, NOSE)
    cv.fill(Arc(512, 590, 26, math.radians(0), math.radians(180), 5), OUTLINE)
    cv.fill(Arc(472, 578, 20, math.radians(0), math.radians(180), 5), OUTLINE)
    cv.fill(Arc(552, 578, 20, math.radians(0), math.radians(180), 5), OUTLINE)

    # ---- whiskers (3 per side, fanning out) ----
    for r0 in (235, 272, 309):
        cv.fill(Arc(512, 555, r0, math.radians(-8), math.radians(8), 5), OUTLINE)
        cv.fill(Arc(512, 555, r0, math.radians(math.pi - 8),
                    math.radians(math.pi + 8), 5), OUTLINE)

    # ---- sparkles ----
    def star(cx, cy, r, c):
        for ang in range(0, 360, 90):
            a = math.radians(ang)
            cv.fill(Circle(cx + r * math.cos(a) * 0.5, cy + r * math.sin(a) * 0.5,
                           r * 0.22), c)
        cv.fill(Circle(cx, cy, r * 0.3), c)
    for cx, cy, r in [(830, 430, 34), (195, 500, 28), (560, 250, 22)]:
        star(cx, cy, r, SPARK)
    heart(430, 640, 20, HEART)

    return cv


def main():
    out = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out, exist_ok=True)
    t0 = __import__("time").time()
    cv = render()
    path = os.path.join(out, "entry.png")
    cv.to_png(path)
    print(f"wrote {path} in {__import__('time').time() - t0:.2f}s")


if __name__ == "__main__":
    main()
