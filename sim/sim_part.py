#!/usr/bin/env python3
# Sim only: closes the probe input when the virtual stylus touches the virtual table.
import os, sys, time
import hal
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "qtvcp", "panels", "table_nav"))
from sim_world import touching
R = 0.99
c = hal.component("sim_part")
for n in "xyz":
    c.newpin(n, hal.HAL_FLOAT, hal.HAL_IN)
c.newpin("probe", hal.HAL_BIT, hal.HAL_OUT)
c.ready()
try:
    while True:
        c["probe"] = touching(c["x"], c["y"], c["z"], R)
        time.sleep(0.002)
except KeyboardInterrupt:
    pass
