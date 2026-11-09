#!/usr/bin/env python3
# Probing plan and result maths for the Setup mode. No Qt or LinuxCNC here.
import math

import numpy as np


def _unit(v):
    n = math.hypot(*v)
    return (v[0] / n, v[1] / n)


class Point:
    """One edge probing point: position along an edge or circle, and where the probe descends."""

    def __init__(self, edge, t, inside=False, approach=10.0, role=""):
        self.edge, self.t, self.inside, self.approach, self.role = edge, t, inside, approach, role
        self.override = False  # True once this point's distance was set on its own


class RectShape:
    kind = "rect"

    def __init__(self, corners_px, found=None):
        self.corners = [tuple(c) for c in corners_px]
        self.found = found or [False] * 4

    def machine(self, cam, pose, z):
        return [cam.to_machine(pose, c[0], c[1], z) for c in self.corners]

    def center_px(self):
        return (sum(c[0] for c in self.corners) / 4.0, sum(c[1] for c in self.corners) / 4.0)

    def rebase(self, cam, old, new, z):
        self.corners = [cam.to_pixel(new, *cam.to_machine(old, c[0], c[1], z), z) for c in self.corners]

    def sample_slots(self):
        return [(e, (i + 0.5) / 12.0) for e in range(4) for i in range(12)]

    def origin_corner(self, cam, pose, z, sx, sy):
        m = self.machine(cam, pose, z)
        return min(range(4), key=lambda i: sx * m[i][0] + sy * m[i][1])

    def default_points(self, cam, pose, z, sx, sy, approach):
        """Two points on the X-running edge and one on the Y-running edge at the chosen corner."""
        m = self.machine(cam, pose, z)
        corner = min(range(4), key=lambda i: sx * m[i][0] + sy * m[i][1])
        a = (corner - 1) % 4  # edge ending at the corner
        b = corner            # edge starting at the corner
        along = lambda e: abs(_unit((m[(e + 1) % 4][0] - m[e][0], m[(e + 1) % 4][1] - m[e][1]))[0])
        if along(a) < along(b):
            a, b = b, a
        return [Point(a, 0.25, approach=approach, role="A"), Point(a, 0.75, approach=approach, role="A"),
                Point(b, 0.5, approach=approach, role="B")]

    def edge_geometry(self, point, cam, pose, z):
        m = self.machine(cam, pose, z)
        a, b = m[point.edge], m[(point.edge + 1) % 4]
        e = (a[0] + (b[0] - a[0]) * point.t, a[1] + (b[1] - a[1]) * point.t)
        d = _unit((b[0] - a[0], b[1] - a[1]))
        out = (-d[1], d[0])
        cx, cy = sum(c[0] for c in m) / 4.0, sum(c[1] for c in m) / 4.0
        if (e[0] - cx) * out[0] + (e[1] - cy) * out[1] < 0:
            out = (-out[0], -out[1])
        return e, out


class CircleShape:
    kind = "circle"

    def __init__(self, center_px, radius_px, found=False):
        self.center, self.radius, self.found = tuple(center_px), float(radius_px), found

    def center_px(self):
        return self.center

    def rebase(self, cam, old, new, z):
        m = cam.to_machine(old, self.center[0], self.center[1], z)
        self.radius *= (old[2] + cam.above - z) / (new[2] + cam.above - z)
        self.center = cam.to_pixel(new, m[0], m[1], z)

    def sample_slots(self):
        return [(0, i / 48.0) for i in range(48)]

    def default_points(self, cam, pose, z, sx, sy, approach):
        return [Point(0, i * 0.25 + 0.125, approach=approach, role="C") for i in range(4)]

    def radius_mm(self, cam, pose, z):
        c = cam.to_machine(pose, self.center[0], self.center[1], z)
        e = cam.to_machine(pose, self.center[0] + self.radius, self.center[1], z)
        return math.hypot(e[0] - c[0], e[1] - c[1])

    def edge_geometry(self, point, cam, pose, z):
        c = cam.to_machine(pose, self.center[0], self.center[1], z)
        r = self.radius_mm(cam, pose, z)
        ang = point.t * 2.0 * math.pi
        out = (math.cos(ang), math.sin(ang))
        return (c[0] + r * out[0], c[1] + r * out[1]), out


def probe_path(shape, point, cam, pose, z, over):
    """Machine XY of (descent point, edge point, end of search)."""
    edge, out = shape.edge_geometry(point, cam, pose, z)
    sign = -1.0 if point.inside else 1.0
    approach = point.approach
    if shape.kind == "circle" and point.inside:  # the descent points must stay apart inside a hole
        approach = min(approach, 0.7 * shape.radius_mm(cam, pose, z))
    start = (edge[0] + sign * out[0] * approach, edge[1] + sign * out[1] * approach)
    target = (edge[0] - sign * out[0] * over, edge[1] - sign * out[1] * over)
    return start, edge, target


def default_depth(stylus_dia, margin=1.0):
    """Edge check depth below the measured top: clear of chamfers and burrs, no deeper than needed."""
    return stylus_dia / 2.0 + margin


def _rotate(v, a):
    c, s = math.cos(a), math.sin(a)
    return (c * v[0] - s * v[1], s * v[0] + c * v[1])


def solve_rect(shape, points, contacts, r, cam, pose, z, sx, sy):
    """Correct the camera's rectangle with the touches, for any arrangement of points.
    contacts: [(cx, cy, dx, dy)] stylus centre at touch and probing direction, one per point.
    Returns (corner x, corner y, rotation degrees, determined): determined is False when the points
    cannot fix X, Y and rotation together, and the camera's value was kept for what is missing."""
    m = shape.machine(cam, pose, z)
    i = shape.origin_corner(cam, pose, z, sx, sy)
    o = m[i]
    neighbours = (m[(i + 1) % 4], m[(i - 1) % 4])
    far = max(neighbours, key=lambda q: abs(q[0] - o[0]))
    base = math.atan2(sx * (far[1] - o[1]), sx * (far[0] - o[0]))
    edges = [shape.edge_geometry(p, cam, pose, z) for p in points]
    dx, dy, th, scale = 0.0, 0.0, 0.0, 100.0
    A = None
    for _ in range(6):
        rows, res = [], []
        for (e, n), (cx, cy, px, py) in zip(edges, contacts):
            v = _rotate((e[0] - o[0], e[1] - o[1]), th)
            ex, ey = o[0] + dx + v[0], o[1] + dy + v[1]
            nx, ny = _rotate(n, th)
            sign = 1.0 if nx * px + ny * py > 0 else -1.0
            sx_p, sy_p = cx + r * sign * nx, cy + r * sign * ny
            rows.append((nx, ny, (nx * -v[1] + ny * v[0]) / scale))
            res.append(nx * (sx_p - ex) + ny * (sy_p - ey))
        A = np.array(rows, float)
        step = np.linalg.lstsq(A, np.array(res, float), rcond=1e-6)[0]
        dx, dy, th = dx + float(step[0]), dy + float(step[1]), th + float(step[2]) / scale
    determined = int(np.linalg.matrix_rank(A, tol=1e-3)) == 3
    return o[0] + dx, o[1] + dy, math.degrees(base + th), determined


def circle_spread_ok(points):
    """False when the points cover too little of the circle for a reliable centre."""
    ts = sorted(p.t % 1.0 for p in points)
    gaps = [(ts[(i + 1) % len(ts)] - ts[i]) % 1.0 for i in range(len(ts))]
    return len(ts) >= 3 and 1.0 - max(gaps) >= 0.25


def next_free_slot(shape, points, cam, pose, z):
    """Where a new point fits best: the free spot farthest from every existing point."""
    used = [shape.edge_geometry(p, cam, pose, z)[0] for p in points]
    def score(slot):
        probe = Point(slot[0], slot[1])
        e = shape.edge_geometry(probe, cam, pose, z)[0]
        return min(math.hypot(e[0] - u[0], e[1] - u[1]) for u in used)
    return max(shape.sample_slots(), key=score)


def solve_circle(contacts, r, inside):
    """Fit the stylus centres at touch. Returns (centre x, centre y, surface radius)."""
    n = len(contacts)
    sx = sum(c[0] for c in contacts) / n
    sy = sum(c[1] for c in contacts) / n
    uu = sum((c[0] - sx) ** 2 for c in contacts)
    vv = sum((c[1] - sy) ** 2 for c in contacts)
    uv = sum((c[0] - sx) * (c[1] - sy) for c in contacts)
    bu = sum((c[0] - sx) * ((c[0] - sx) ** 2 + (c[1] - sy) ** 2) for c in contacts) / 2.0
    bv = sum((c[1] - sy) * ((c[0] - sx) ** 2 + (c[1] - sy) ** 2) for c in contacts) / 2.0
    det = uu * vv - uv * uv
    cu = (bu * vv - bv * uv) / det
    cv = (bv * uu - bu * uv) / det
    rad = math.sqrt(cu ** 2 + cv ** 2 + (uu + vv) / n)
    return sx + cu, sy + cv, rad + r if inside else rad - r


def height_command(x, y, travel, floor, select=-1, fast=1000.0, slow=200.0, feed=3000.0):
    """floor: lowest machine Z the height search may reach. select: probe-select output or -1."""
    return "o<setup_height> call [%.3f] [%.3f] [%.3f] [%.3f] [%.1f] [%.1f] [%.1f] [%d]" % (
        x, y, travel, floor, fast, slow, feed, select)


def touch_command(start, target, zsafe, zlow, select=-1, fast=1500.0, slow=200.0):
    return "o<setup_touch> call [%.3f] [%.3f] [%.3f] [%.3f] [%.3f] [%.3f] [%.1f] [%.1f] [%d]" % (
        start[0], start[1], target[0], target[1], zsafe, zlow, fast, slow, select)


def parse_log(text):
    """Records from the probing macros: ('H', top in offset, top in machine) or ('T', x, y)."""
    out = []
    for line in text.splitlines():
        w = line.split()
        if len(w) == 3 and w[0] in ("H", "T"):
            out.append((w[0], float(w[1]), float(w[2])))
    return out
