#!/usr/bin/env python3
# Sim only: the virtual table, shared by the virtual camera and the virtual probe.
import math

TABLE_Z = -100.0
BLOCK = dict(x=200.0, y=100.0, w=150.0, h=100.0, angle=3.0, top=-60.0)  # with a hole through it
HOLE = dict(u=110.0, v=50.0, r=20.0)
BOSS = dict(x=480.0, y=260.0, r=40.0, top=-50.0)
_c, _s = math.cos(math.radians(BLOCK["angle"])), math.sin(math.radians(BLOCK["angle"]))


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
