#!/usr/bin/env python3
# Camera geometry, the sim's virtual camera, and edge detection. No Qt or LinuxCNC here.
import math

import cv2
import numpy as np

import sim_world as W


class CameraModel:
    """Downward camera. The image matches the map: machine X+ is left, machine Y+ is down."""

    def __init__(self, width=640, height=480, focal=240.0, off_x=60.0, off_y=0.0, above=50.0):
        self.width, self.height, self.focal = width, height, focal
        self.off_x, self.off_y, self.above = off_x, off_y, above

    def to_pixel(self, pose, x, y, z):
        dist = pose[2] + self.above - z
        return (self.width / 2.0 - self.focal * (x - pose[0] - self.off_x) / dist,
                self.height / 2.0 + self.focal * (y - pose[1] - self.off_y) / dist)

    def to_machine(self, pose, px, py, z):
        dist = pose[2] + self.above - z
        return (pose[0] + self.off_x - (px - self.width / 2.0) * dist / self.focal,
                pose[1] + self.off_y + (py - self.height / 2.0) * dist / self.focal)


_texture = {}


def _table_texture(cam):
    key = (cam.width, cam.height)
    if key not in _texture:
        rng = np.random.default_rng(7)
        base = np.full((cam.height, cam.width, 3), 62, np.uint8)
        _texture[key] = cv2.add(base, rng.integers(0, 14, base.shape, dtype=np.uint8))
    return _texture[key]


def fake_frame(cam, pose):
    """Top-down picture of the virtual table as seen from the spindle pose."""
    img = _table_texture(cam).copy()
    pt = lambda x, y, z: tuple(int(round(v * 16)) for v in cam.to_pixel(pose, x, y, z))
    for y in range(20, 380, 60):  # T-slots
        cv2.line(img, pt(0, y, W.TABLE_Z), pt(615, y, W.TABLE_Z), (28, 28, 30), 3, cv2.LINE_AA, 4)
    poly = np.array([pt(*W.block_point(u, v), W.BLOCK["top"]) for u, v in
                     ((0, 0), (W.BLOCK["w"], 0), (W.BLOCK["w"], W.BLOCK["h"]), (0, W.BLOCK["h"]))], np.int32)
    cv2.fillPoly(img, [poly], (178, 182, 186), cv2.LINE_AA, 4)
    hx, hy = W.block_point(W.HOLE["u"], W.HOLE["v"])
    c = pt(hx, hy, W.BLOCK["top"])
    edge = pt(hx + W.HOLE["r"], hy, W.BLOCK["top"])
    cv2.circle(img, c, abs(edge[0] - c[0]), (30, 30, 32), -1, cv2.LINE_AA, 4)
    c = pt(W.BOSS["x"], W.BOSS["y"], W.BOSS["top"])
    edge = pt(W.BOSS["x"] + W.BOSS["r"], W.BOSS["y"], W.BOSS["top"])
    cv2.circle(img, c, abs(edge[0] - c[0]), (205, 200, 170), -1, cv2.LINE_AA, 4)
    return img


def _edges(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 40, 120)


def _gradient(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    return cv2.Sobel(blur, cv2.CV_32F, 1, 0), cv2.Sobel(blur, cv2.CV_32F, 0, 1)


def _intersect(a, b):
    (p, d), (q, e) = a, b
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-6:
        return None
    t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / den
    return (p[0] + t * d[0], p[1] + t * d[1])


def detect_rect(img, corners, band=36, max_angle=12.0):
    """Snap a rough four-corner shape to image edges.
    Returns (corners, found) where found[i] says side i (corners[i] to corners[i+1]) was detected.
    The strongest long edge wins, so weak lines such as T-slots lose to the part's own edge."""
    edges = _edges(img)
    gx, gy = _gradient(img)
    mag = cv2.magnitude(gx, gy)
    lines, found = [], []
    for i in range(4):
        a, b = np.array(corners[i], float), np.array(corners[(i + 1) % 4], float)
        side = b - a
        length = float(np.hypot(*side))
        direction = side / length
        mask = np.zeros(edges.shape, np.uint8)
        cv2.line(mask, tuple(int(v) for v in a), tuple(int(v) for v in b), 255, 2 * band)
        masked = cv2.bitwise_and(edges, mask)
        hits = cv2.HoughLinesP(masked, 1, np.pi / 720, 25, minLineLength=max(20, length * 0.3), maxLineGap=12)
        best = None
        for x1, y1, x2, y2 in ([] if hits is None else hits[:, 0]):
            v = np.array((x2 - x1, y2 - y1), float)
            size = float(np.hypot(*v))
            if abs(float(np.dot(v / size, direction))) < math.cos(math.radians(max_angle)):
                continue
            count = max(int(size), 2)
            lx = np.linspace(x1, x2, count).astype(int)
            ly = np.linspace(y1, y2, count).astype(int)
            score = size * float(mag[ly, lx].mean())
            if best is None or score > best[0]:
                best = (score, x1, y1, x2, y2)
        line = (tuple(a), tuple(direction))
        ok = False
        if best:
            _, x1, y1, x2, y2 = best
            ys, xs = np.nonzero(masked)
            pts = np.column_stack((xs, ys)).astype(float)
            p0 = np.array((x1, y1), float)
            d0 = np.array((x2 - x1, y2 - y1), float)
            d0 /= np.hypot(*d0)
            near = pts[np.abs((pts[:, 0] - p0[0]) * -d0[1] + (pts[:, 1] - p0[1]) * d0[0]) < 2.0]
            if len(near) >= 15:
                vx, vy, x0, y0 = cv2.fitLine(near.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
                line = ((float(x0), float(y0)), (float(vx), float(vy)))
                ok = True
        lines.append(line)
        found.append(ok)
    out = []
    for i in range(4):
        hit = _intersect(lines[i - 1], lines[i])
        out.append(hit if hit else tuple(corners[i]))
    return out, found


def _circle_from(p):
    """Circle through three points, or None when they are in a line."""
    (ax, ay), (bx, by), (cx, cy) = p
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-6:
        return None
    a2, b2, c2 = ax ** 2 + ay ** 2, bx ** 2 + by ** 2, cx ** 2 + cy ** 2
    x = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    y = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    return x, y, math.hypot(ax - x, ay - y)


def detect_circle(img, center, radius, band=36, min_cover=0.45, seed=3):
    """Snap a rough circle to image edges. Returns (center, radius, found).
    Random three-point trials, so straight lines crossing the band cannot pull the fit;
    the winner must be supported around at least min_cover of its circumference."""
    ys, xs = np.nonzero(_edges(img))
    pts = np.column_stack((xs, ys)).astype(float)
    dist = np.hypot(pts[:, 0] - center[0], pts[:, 1] - center[1])
    pts = pts[np.abs(dist - radius) < band]
    if len(pts) < 30:
        return tuple(center), float(radius), False
    rng = np.random.default_rng(seed)
    best, best_count = None, 0
    for _ in range(400):
        c = _circle_from(pts[rng.choice(len(pts), 3, replace=False)])
        if c is None or abs(c[2] - radius) > 0.35 * radius or math.hypot(c[0] - center[0], c[1] - center[1]) > band:
            continue
        count = int((np.abs(np.hypot(pts[:, 0] - c[0], pts[:, 1] - c[1]) - c[2]) < 1.5).sum())
        if count > best_count:
            best, best_count = c, count
    if best is None:
        return tuple(center), float(radius), False
    inl = pts[np.abs(np.hypot(pts[:, 0] - best[0], pts[:, 1] - best[1]) - best[2]) < 1.5]
    A = np.column_stack((2 * inl[:, 0], 2 * inl[:, 1], np.ones(len(inl))))
    sol = np.linalg.lstsq(A, (inl ** 2).sum(axis=1), rcond=None)[0]
    fit = (float(sol[0]), float(sol[1]), float(math.sqrt(max(sol[2] + sol[0] ** 2 + sol[1] ** 2, 0.0))))
    bins = np.floor((np.arctan2(inl[:, 1] - fit[1], inl[:, 0] - fit[0]) + math.pi) / (2 * math.pi) * 36).astype(int) % 36
    if len(set(bins.tolist())) / 36.0 < min_cover:
        return tuple(center), float(radius), False
    return (fit[0], fit[1]), fit[2], True


def _segment_distance(pts, a, b):
    ab = b - a
    t = np.clip(((pts - a) @ ab) / max(float(ab @ ab), 1e-9), 0.0, 1.0)
    return np.hypot(*(pts - (a + t[:, None] * ab)).T)


def fit_stroke(stroke):
    """Decide what a freehand stroke is. Returns ("rect", four corners) or ("circle", centre, radius).
    Whichever outline lies closest to the drawn line wins; circle needs a clear win over the box
    that encloses it."""
    pts = np.array(stroke, np.float32)
    box = cv2.boxPoints(cv2.minAreaRect(pts))
    p = pts.astype(float)
    b = box.astype(float)
    rect_err = float(np.min([_segment_distance(p, b[i], b[(i + 1) % 4]) for i in range(4)], axis=0).mean())
    A = np.column_stack((2 * p[:, 0], 2 * p[:, 1], np.ones(len(p))))
    sol = np.linalg.lstsq(A, (p ** 2).sum(axis=1), rcond=None)[0]
    cx, cy = float(sol[0]), float(sol[1])
    radius = float(math.sqrt(max(sol[2] + cx ** 2 + cy ** 2, 1.0)))
    circle_err = float(np.abs(np.hypot(p[:, 0] - cx, p[:, 1] - cy) - radius).mean())
    if circle_err < 0.85 * rect_err:
        return "circle", (cx, cy), radius
    return "rect", [tuple(float(v) for v in c) for c in box]


def _candidates(img):
    """Closed outlines in the image, from brightness and from edges, so one failing source is not fatal."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, bright = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    closed = cv2.morphologyEx(_edges(img), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    out = []
    for binary in (bright, cv2.bitwise_not(bright), closed):
        out.extend(cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)[0])
    return out


def find_shape(img, stroke, min_overlap=0.35):
    """Find what a freehand sketch means in the picture.
    Looks for the closed outline overlapping the sketch best; rectangle or circle is decided from
    that real outline. Falls back to the sketch itself, flagged not found, when nothing matches.
    Returns ("rect", corners, found list) or ("circle", centre, radius, found)."""
    sketch = np.zeros(img.shape[:2], np.uint8)
    poly = np.array([[int(x), int(y)] for x, y in stroke], np.int32)
    cv2.fillPoly(sketch, [poly], 255)
    area = float(cv2.countNonZero(sketch))
    best, best_score = None, min_overlap
    frame_area = img.shape[0] * img.shape[1]
    for c in _candidates(img) if area > 0 else []:
        a = cv2.contourArea(c)
        if a < 0.12 * area or a > 8.0 * area or a > 0.9 * frame_area:
            continue
        mask = np.zeros(img.shape[:2], np.uint8)
        cv2.drawContours(mask, [c], -1, 255, -1)
        both = cv2.countNonZero(cv2.bitwise_and(mask, sketch))
        hull = cv2.contourArea(cv2.convexHull(c))
        # a part outline is compact: this rejects outlines with T-slots or scratches stuck to them
        score = (both / float(cv2.countNonZero(cv2.bitwise_or(mask, sketch)))) * (a / max(hull, 1.0))
        if score > best_score:
            best, best_score = c, score
    fit = fit_stroke([tuple(p) for p in (best[:, 0] if best is not None else stroke)])
    band = 14 if best is not None else 36
    if fit[0] == "rect":
        corners, found = detect_rect(img, fit[1], band=band)
        return "rect", corners, found
    center, radius, found = detect_circle(img, fit[1], fit[2], band=band)
    return "circle", center, radius, found
