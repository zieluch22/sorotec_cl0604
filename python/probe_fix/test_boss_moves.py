#!/usr/bin/env python3
# Dry test of probe_subprog_fixed.py: records the moves of "outside, four sides", no machine.
# usage: python3 python/probe_fix/test_boss_moves.py
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe_subprog_fixed as fixed
import qtvcp.widgets.probe_routines as routines

fails = 0


def run(edge, clearance, part_half):
    """Simulates the X and Y start positions relative to the starting point."""
    r = routines.ProbeRoutines.__new__(routines.ProbeRoutines)
    r.__dict__.update(data_rapid_vel=3000, data_side_edge_length=edge, data_xy_clearance=clearance,
                      data_latch_return_dist=1.0, data_z_clearance=10, data_extra_depth=5,
                      data_probe_diam=2, data_max_travel=60, data_probe_vel=30, data_search_vel=1000,
                      data_adj_x=0, data_adj_y=0, data_adj_z=0, timeout=30, status_xp=None,
                      status_yp=None, status_xm=None, status_ym=None, allow_auto_zero=False,
                      allow_auto_skew=False)
    pos = {"X": 0.0, "Y": 0.0}
    down_at = []

    def mdi(cmd, timeout=None):
        for ax, val in re.findall(r"G1 F\S+ ([XY])(-?[\d.]+)", cmd):
            pos[ax] = pos[ax] + float(val) if "G91" in cmd else float(val)
        if re.search(r"G1 F\S+ Z-", cmd):
            down_at.append((pos["X"], pos["Y"]))
            if abs(pos["X"]) <= part_half and abs(pos["Y"]) <= part_half:
                return "HIT the part"
        return 1

    r.CALL_MDI_WAIT = mdi
    r.probe = lambda name: 1
    r.add_history = lambda *a, **k: None
    r.set_zero = lambda s: None
    r.length_x = lambda: 0
    r.length_y = lambda: 0
    routines.STATUS.get_probed_position_with_offsets = lambda: (0, 0, 0)
    fixed.STATUS.get_probed_position_with_offsets = lambda: (0, 0, 0)
    return fixed.probe_outside_xy_boss(r), down_at


def check(name, got, want):
    global fails
    print(("PASS " if got == want else "FAIL ") + name + ("" if got == want else ": got %s, want %s" % (got, want)))
    fails += got != want


rtn, down = run(0.0, 30.0, 16.0)
print("edge 0, clearance 30:", down, "result", rtn)
check("first X side at -30", down[0], (-30.0, 0.0))
check("second X side at +30, not back at the centre", down[1], (30.0, 0.0))
check("Y sides at -30 and +30, centred in X", (down[2], down[3]), ((0.0, -30.0), (0.0, 30.0)))
check("never comes down on the part", rtn, 1)
rtn, down = run(25.0, 30.0, 25.0)
check("edge 25, clearance 30: sides at -55 and +55", (down[0][0], down[1][0]), (-55.0, 55.0))
print("\nOK: 0 failures" if not fails else "\nFAILED: %d" % fails)
sys.exit(1 if fails else 0)
