#!/usr/bin/env python3
# Virtual table: a block with a hole and a round boss. Used by the virtual camera and the virtual probe,
# in the sim and in the real-machine virtual test (start_virtual_probe.sh).
import math

TABLE_Z = -100.0
BLOCK = dict(x=200.0, y=100.0, w=150.0, h=100.0, angle=3.0, top=-60.0)  # with a hole through it
HOLE = dict(u=110.0, v=50.0, r=20.0)
BOSS = dict(x=480.0, y=260.0, r=40.0, top=-50.0)
_c, _s = math.cos(math.radians(BLOCK["angle"])), math.sin(math.radians(BLOCK["angle"]))


def configure(top, shift_x=0.0, shift_y=0.0, floor=15.0):
    """Move the virtual parts: both tops at machine Z top, a virtual table floor below them."""
    global TABLE_Z
    BLOCK.update(top=top, x=200.0 + shift_x, y=100.0 + shift_y)
    BOSS.update(top=top, x=480.0 + shift_x, y=260.0 + shift_y)
    TABLE_Z = top - floor


def block_point(u, v):
    return BLOCK["x"] + u * _c - v * _s, BLOCK["y"] + u * _s + v * _c


def touching(x, y, z, r):
    """True when a stylus of radius r at (x, y, z) touches something."""
    if z <= TABLE_Z:
        return True
    if z <= BOSS["top"] and math.hypot(x - BOSS["x"], y - BOSS["y"]) <= BOSS["r"] + r:
        return True
    if z > BLOCK["top"]:
        return False
    dx, dy = x - BLOCK["x"], y - BLOCK["y"]
    u, v = dx * _c + dy * _s, -dx * _s + dy * _c
    if not (-r <= u <= BLOCK["w"] + r and -r <= v <= BLOCK["h"] + r):
        return False
    return math.hypot(u - HOLE["u"], v - HOLE["v"]) > HOLE["r"] - r
