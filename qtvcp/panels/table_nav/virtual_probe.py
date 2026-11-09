#!/usr/bin/env python3
# Real-machine virtual test only: a probe signal from the virtual parts, following the real machine
# position. hallib/virtual_probe.hal ORs it with the real probe, so a real touch still counts.
import os
import sys
import time

import hal
import linuxcnc

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim_world

R = 0.99  # stylus radius
ini = linuxcnc.ini(os.environ["INI_FILE_NAME"])
get = lambda name, default: float(ini.find("TABLE_NAV", name) or default)
sim_world.configure(get("VIRTUAL_TOP", -10), get("VIRTUAL_SHIFT_X", 0), get("VIRTUAL_SHIFT_Y", 0))
c = hal.component("vprobe")
c.newpin("touch", hal.HAL_BIT, hal.HAL_OUT)
c.ready()
stat = linuxcnc.stat()
try:
    while True:
        try:
            stat.poll()
            x, y, z = stat.actual_position[:3]
            c["touch"] = sim_world.touching(x, y, z, R)
        except linuxcnc.error:
            c["touch"] = False
        time.sleep(0.002)
except KeyboardInterrupt:
    pass
