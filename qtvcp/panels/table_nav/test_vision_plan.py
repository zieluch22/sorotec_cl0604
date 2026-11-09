#!/usr/bin/env python3
# Detection and maths against the virtual camera, with deliberately rough drawings.
import math, os, random, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe_plan as PP
import sim_world as W
from vision import CameraModel, detect_circle, detect_rect, fake_frame, find_shape, fit_stroke

CAM = CameraModel()
POSE = (215.0, 150.0, -1.0)
TOP = W.BLOCK["top"]


class T(unittest.TestCase):
    def rough(self, pad=9.0):
        a = CAM.to_pixel(POSE, W.BLOCK["x"] - pad, W.BLOCK["y"] - pad, TOP)
        b = CAM.to_pixel(POSE, W.BLOCK["x"] + W.BLOCK["w"] + pad, W.BLOCK["y"] + W.BLOCK["h"] + pad, TOP)
        return [a, (b[0], a[1]), b, (a[0], b[1])]

    def test_rect_found_within_a_pixel(self):
        corners, found = detect_rect(fake_frame(CAM, POSE), self.rough())
        self.assertEqual(found, [True] * 4)
        want = [CAM.to_pixel(POSE, *W.block_point(u, v), TOP) for u, v in
                ((0, 0), (W.BLOCK["w"], 0), (W.BLOCK["w"], W.BLOCK["h"]), (0, W.BLOCK["h"]))]
        for c in corners:
            self.assertLess(min(math.hypot(c[0] - w[0], c[1] - w[1]) for w in want), 2.0)

    def test_empty_table_reports_not_found(self):
        pose = (560.0, 40.0, -1.0)
        a = CAM.to_pixel(pose, 560, 30, W.TABLE_Z)
        b = CAM.to_pixel(pose, 610, 50, W.TABLE_Z)
        _, found = detect_rect(fake_frame(CAM, pose), [a, (b[0], a[1]), b, (a[0], b[1])], max_angle=5)
        self.assertLess(sum(found), 4)

    def test_circle_found(self):
        pose = (W.BOSS["x"] - 60, W.BOSS["y"], -1.0)
        c = CAM.to_pixel(pose, W.BOSS["x"] + 4, W.BOSS["y"] - 3, W.BOSS["top"])
        e = CAM.to_pixel(pose, W.BOSS["x"] + W.BOSS["r"] + 12, W.BOSS["y"], W.BOSS["top"])
        center, radius, found = detect_circle(fake_frame(CAM, pose), c, abs(e[0] - c[0]))
        self.assertTrue(found)
        want = CAM.to_pixel(pose, W.BOSS["x"], W.BOSS["y"], W.BOSS["top"])
        self.assertLess(math.hypot(center[0] - want[0], center[1] - want[1]), 1.5)

    def test_pixel_round_trip_depends_on_height(self):
        px = CAM.to_pixel(POSE, 250, 120, -60)
        x, y = CAM.to_machine(POSE, px[0], px[1], -60)
        self.assertAlmostEqual(x, 250)
        self.assertAlmostEqual(y, 120)
        self.assertGreater(abs(CAM.to_machine(POSE, px[0], px[1], -90)[0] - 250), 1)

    def test_swap_moves_descent_to_other_side(self):
        s = PP.RectShape(self.rough())
        p = s.default_points(CAM, POSE, TOP, 1, 1, 10)[0]
        out_start = PP.probe_path(s, p, CAM, POSE, TOP, 5)
        p.inside = True
        in_start = PP.probe_path(s, p, CAM, POSE, TOP, 5)
        e = out_start[1]
        self.assertLess((out_start[0][0] - e[0]) * (in_start[0][0] - e[0]) + (out_start[0][1] - e[1]) * (in_start[0][1] - e[1]), 0)

    def touches(self, shape, points, ang=1.0, shift=(0.8, -0.6), r=1.0):
        """Stylus centres at touch on a true rectangle that differs from what the camera saw."""
        m = shape.machine(CAM, POSE, TOP)
        i = shape.origin_corner(CAM, POSE, TOP, 1, 1)
        o, a = m[i], math.radians(ang)
        tr = lambda q: (o[0] + shift[0] + (q[0] - o[0]) * math.cos(a) - (q[1] - o[1]) * math.sin(a),
                        o[1] + shift[1] + (q[0] - o[0]) * math.sin(a) + (q[1] - o[1]) * math.cos(a))
        out = []
        for p in points:
            s, e, t = PP.probe_path(shape, p, CAM, POSE, TOP, 5)
            _, n = shape.edge_geometry(p, CAM, POSE, TOP)
            nt = (n[0] * math.cos(a) - n[1] * math.sin(a), n[0] * math.sin(a) + n[1] * math.cos(a))
            q = tr(e)
            dv = (t[0] - s[0], t[1] - s[1])
            ln = math.hypot(*dv)
            dv = (dv[0] / ln, dv[1] / ln)
            sign = -1.0 if p.inside else 1.0
            lam = (r * sign + nt[0] * (q[0] - s[0]) + nt[1] * (q[1] - s[1])) / (nt[0] * dv[0] + nt[1] * dv[1])
            out.append((s[0] + dv[0] * lam, s[1] + dv[1] * lam, dv[0], dv[1]))
        m0 = tr(o)
        return out, m0

    def shape(self):
        return PP.RectShape([CAM.to_pixel(POSE, *W.block_point(u, v), TOP) for u, v in ((0, 0), (150, 0), (150, 100), (0, 100))], [True] * 4)

    def base_angle(self, shape):
        m = shape.machine(CAM, POSE, TOP)
        return math.degrees(math.atan2(m[1][1] - m[0][1], m[1][0] - m[0][0]))

    def check(self, points, determined=True):
        s = self.shape()
        c, corner = self.touches(s, points)
        x, y, ang, ok = PP.solve_rect(s, points, c, 1.0, CAM, POSE, TOP, 1, 1)
        self.assertEqual(ok, determined)
        if determined:
            self.assertAlmostEqual(x, corner[0], 3)
            self.assertAlmostEqual(y, corner[1], 3)
            self.assertAlmostEqual(ang, self.base_angle(s) + 1.0, 3)

    def test_solve_default_points(self):
        s = self.shape()
        self.check(s.default_points(CAM, POSE, TOP, 1, 1, 20))

    def test_solve_points_around_the_part(self):
        self.check([PP.Point(0, 0.9), PP.Point(1, 0.1), PP.Point(1, 0.5), PP.Point(2, 0.5)])

    def test_solve_mixed_inside_and_outside(self):
        pts = [PP.Point(0, 0.2), PP.Point(0, 0.8, inside=True), PP.Point(3, 0.5)]
        self.check(pts)

    def test_all_on_one_edge_warns(self):
        self.check([PP.Point(0, 0.2), PP.Point(0, 0.5), PP.Point(0, 0.8)], determined=False)

    def test_new_point_goes_to_free_space(self):
        s = self.shape()
        pts = [PP.Point(0, 0.2), PP.Point(0, 0.5), PP.Point(0, 0.8)]
        self.assertEqual(PP.next_free_slot(s, pts, CAM, POSE, TOP)[0], 2)

    def test_circle_spread(self):
        self.assertFalse(PP.circle_spread_ok([PP.Point(0, 0.1), PP.Point(0, 0.12), PP.Point(0, 0.14)]))
        self.assertTrue(PP.circle_spread_ok([PP.Point(0, 0.1), PP.Point(0, 0.4), PP.Point(0, 0.7)]))

    def test_solve_circle(self):
        pts = [(5 + 11 * math.cos(t), 7 + 11 * math.sin(t)) for t in (0.4, 2.0, 3.6, 5.1)]
        x, y, rad = PP.solve_circle(pts, 1.0, False)
        self.assertAlmostEqual(x, 5, 6)
        self.assertAlmostEqual(y, 7, 6)
        self.assertAlmostEqual(rad, 10, 6)
        self.assertAlmostEqual(PP.solve_circle(pts, 1.0, True)[2], 12, 6)

    def stroke(self, fn, seed, n=90, wobble=3.0):
        rng = random.Random(seed)
        return [(fn(i / float(n))[0] + rng.uniform(-wobble, wobble), fn(i / float(n))[1] + rng.uniform(-wobble, wobble)) for i in range(n + 1)]

    def test_freehand_circles_are_circles(self):
        fn = lambda t: (300 + 90 * math.cos(2 * math.pi * t), 240 + 90 * math.sin(2 * math.pi * t))
        for seed in range(20):
            self.assertEqual(fit_stroke(self.stroke(fn, seed))[0], "circle", seed)

    def test_freehand_rectangles_are_rectangles(self):
        for w, h in ((300, 180), (160, 160), (240, 100)):
            def fn(t):
                peri = 2.0 * (w + h)
                d = t * peri
                if d < w: return (100 + d, 100)
                if d < w + h: return (100 + w, 100 + d - w)
                if d < 2 * w + h: return (100 + w - (d - w - h), 100 + h)
                return (100, 100 + h - (d - 2 * w - h))
            for seed in range(20):
                self.assertEqual(fit_stroke(self.stroke(fn, seed))[0], "rect", (w, h, seed))

    def test_hole_descent_points_stay_apart(self):
        s = PP.CircleShape((300, 240), 40, True)
        pts = s.default_points(CAM, POSE, TOP, 1, 1, 20)
        for p in pts:
            p.inside = True
        starts = [PP.probe_path(s, p, CAM, POSE, TOP, 5)[0] for p in pts]
        self.assertGreater(min(math.hypot(a[0] - b[0], a[1] - b[1]) for i, a in enumerate(starts) for b in starts[i + 1:]), 2.0)

    def sloppy(self, center, half_w, half_h, circle=False, seed=1, n=70):
        rng = random.Random(seed)
        out = []
        for i in range(n):
            t = 2 * math.pi * i / n
            if circle:
                r = (half_w * math.cos(t), half_h * math.sin(t))
            else:
                c, s = math.cos(t), math.sin(t)
                k = 1.0 / max(abs(c) / half_w, abs(s) / half_h)
                r = (k * c, k * s)
            out.append((center[0] + r[0] + rng.uniform(-10, 10), center[1] + r[1] + rng.uniform(-10, 10)))
        return out

    def test_very_rough_sketch_of_block_is_found(self):
        frame = fake_frame(CAM, POSE)
        # about 45 px too big and 25 px off centre, and sketched as an oval
        for circle in (False, True):
            for seed in range(5):
                res = find_shape(frame, self.sloppy((345, 255), 215, 160, circle, seed))
                self.assertEqual(res[0], "rect")
                self.assertEqual(res[2], [True] * 4)
                want = [CAM.to_pixel(POSE, *W.block_point(u, v), TOP) for u, v in ((0, 0), (150, 0), (150, 100), (0, 100))]
                for c in res[1]:
                    self.assertLess(min(math.hypot(c[0] - w[0], c[1] - w[1]) for w in want), 2.0)

    def test_square_sketch_of_round_boss_is_a_circle(self):
        pose = (W.BOSS["x"] - 60, W.BOSS["y"], -1.0)
        frame = fake_frame(CAM, pose)
        res = find_shape(frame, self.sloppy((330, 232), 125, 125, False, 3))
        self.assertEqual(res[0], "circle")
        self.assertTrue(res[3])
        want = CAM.to_pixel(pose, W.BOSS["x"], W.BOSS["y"], W.BOSS["top"])
        self.assertLess(math.hypot(res[1][0] - want[0], res[1][1] - want[1]), 1.5)

    def test_sketch_around_hole_finds_the_hole(self):
        frame = fake_frame(CAM, POSE)
        c = CAM.to_pixel(POSE, *W.block_point(W.HOLE["u"], W.HOLE["v"]), TOP)
        res = find_shape(frame, self.sloppy((c[0] + 8, c[1] - 6), 65, 58, True, 2))
        self.assertEqual(res[0], "circle")
        self.assertTrue(res[3])
        self.assertLess(math.hypot(res[1][0] - c[0], res[1][1] - c[1]), 1.5)

    def test_empty_area_is_flagged(self):
        pose = (560.0, 40.0, -1.0)
        res = find_shape(fake_frame(CAM, pose), self.sloppy((320, 240), 40, 40, False, 4))
        self.assertFalse(all(res[2]) if res[0] == "rect" else res[3])

    def test_depth(self):
        self.assertAlmostEqual(PP.default_depth(1.98), 1.99)


unittest.main()
