#!/usr/bin/env python3
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from table_nav_logic import TableMap, move_command, not_ready_reason, setup_command, setup_reason


class T(unittest.TestCase):
    def setUp(self):
        self.m = TableMap(0, 615, 0, 380)

    def test_round_trip(self):
        px = self.m.to_pixel(200, 100, 800, 500, 20)
        x, y = self.m.to_machine(px[0], px[1], 800, 500, 20)
        self.assertAlmostEqual(x, 200)
        self.assertAlmostEqual(y, 100)

    def test_home_is_top_right(self):
        hx, hy = self.m.to_pixel(0, 0, 800, 500, 20)
        fx, fy = self.m.to_pixel(615, 380, 800, 500, 20)
        self.assertGreater(hx, fx)
        self.assertLess(hy, fy)

    def test_outside_is_clamped_inside_limits(self):
        self.assertEqual(self.m.to_machine(-999, 9999, 800, 500, 20), (614.5, 379.5))
        self.assertEqual(self.m.to_machine(9999, -999, 800, 500, 20), (0.5, 0.5))

    def test_command(self):
        self.assertEqual(move_command(1, 2.5, 3000, -1), "o<nav_move> call [1.000] [2.500] [3000.0] [-1.000]")

    def test_setup_command(self):
        self.assertEqual(setup_command("Bottom left", 60, 20, 5, 1.98),
                         "o<setup_corner> call [-1.0000] [-1.0000] [60.0000] [20.0000] [10.0000] [5.0000] "
                         "[0.9900] [200.0000] [1500.0000] [30.0000] [5.0000]")

    def test_setup_needs_probe(self):
        self.assertEqual(setup_reason("", 99, 99), "")
        self.assertEqual(setup_reason("", 0, None), "")
        self.assertTrue(setup_reason("", 5, 99))
        self.assertEqual(setup_reason("Machine is off", 99, 99), "Machine is off")

    def test_gating(self):
        self.assertEqual(not_ready_reason(True, True, True, False), "")
        self.assertTrue(not_ready_reason(False, True, True, False))
        self.assertTrue(not_ready_reason(True, False, True, False))
        self.assertTrue(not_ready_reason(True, True, False, False))
        self.assertTrue(not_ready_reason(True, True, True, True))


unittest.main()
