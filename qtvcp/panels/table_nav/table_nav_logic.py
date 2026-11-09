#!/usr/bin/env python3
# Pure maths for the table navigation panel: no Qt, HAL or LinuxCNC, so it can be tested alone.

EDGE_MARGIN = 0.5  # mm kept away from the soft limits


class TableMap:
    """Top-down table map as seen at the machine: home (X min, Y min) is top right."""

    def __init__(self, x_min, x_max, y_min, y_max):
        self.x_min, self.x_max = float(x_min), float(x_max)
        self.y_min, self.y_max = float(y_min), float(y_max)

    def scale(self, width, height, pad):
        return min((width - 2 * pad) / (self.x_max - self.x_min),
                   (height - 2 * pad) / (self.y_max - self.y_min))

    def origin(self, width, height, pad):
        s = self.scale(width, height, pad)
        return ((width - s * (self.x_max - self.x_min)) / 2.0,
                (height - s * (self.y_max - self.y_min)) / 2.0)

    def to_pixel(self, x, y, width, height, pad):
        s = self.scale(width, height, pad)
        ox, oy = self.origin(width, height, pad)
        return ox + (self.x_max - x) * s, oy + (y - self.y_min) * s

    def to_machine(self, px, py, width, height, pad):
        s = self.scale(width, height, pad)
        ox, oy = self.origin(width, height, pad)
        return self.clamp(self.x_max - (px - ox) / s, self.y_min + (py - oy) / s)

    def clamp(self, x, y):
        return (max(self.x_min + EDGE_MARGIN, min(self.x_max - EDGE_MARGIN, x)),
                max(self.y_min + EDGE_MARGIN, min(self.y_max - EDGE_MARGIN, y)))


def move_command(x, y, feed, travel):
    """MDI line for macros/nav_move.ngc; travel is the machine Z for the X/Y move."""
    return "o<nav_move> call [%.3f] [%.3f] [%.1f] [%.3f]" % (x, y, feed, travel)


def not_ready_reason(machine_on, all_homed, interp_idle, auto_mode):
    """Why a move may not start, or "" when it may."""
    if not machine_on:
        return "Machine is off"
    if not all_homed:
        return "Home all axes first"
    if auto_mode:
        return "Switch out of AUTO"
    if not interp_idle:
        return "Machine is busy"
    return ""


# direction from the corner into the part (sx, sy); home is top right on the map
CORNERS = {"Top right": (1, 1), "Top left": (-1, 1), "Bottom right": (1, -1), "Bottom left": (-1, -1)}


def setup_command(corner, spacing, inset, depth, stylus_dia, out=10.0, slow=200.0, fast=1500.0,
                  zsearch=30.0, zclear=5.0):
    """MDI line for macros/setup_corner.ngc."""
    sx, sy = CORNERS[corner]
    values = (sx, sy, spacing, inset, out, depth, stylus_dia / 2.0, slow, fast, zsearch, zclear)
    return "o<setup_corner> call " + " ".join("[%.4f]" % v for v in values)


def setup_reason(move_reason, tool, probe_tool):
    """Why the guided setup may not start, or "" when it may."""
    if move_reason:
        return move_reason
    if probe_tool is not None and tool != probe_tool:
        return "Load the probe (T%d) first" % probe_tool
    return ""
