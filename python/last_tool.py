#!/usr/bin/env python3
# Userspace HAL component "lasttool": remembers the tool in the spindle across
# restarts. LinuxCNC (nonrandom toolchanger) starts with tool 0 every time.
#
# Watches iocontrol.0.tool-number and writes it to the file given as argv[1]
# on every change (M6, M61, manual removal, ...). The value at startup is NOT
# written - it is always 0 and would wipe the stored tool.
# Atomic write (tmp + fsync + rename) so a power cut never leaves a broken file.
#
# Read by change_prolog (stdglue.py); rack_change.ngc uses it only when no tool
# is set but the spindle tool sensor sees one.

import os
import sys
import time

import hal

path = sys.argv[1] if len(sys.argv) > 1 else "last_tool.txt"

c = hal.component("lasttool")
c.newpin("tool-number", hal.HAL_S32, hal.HAL_IN)
c.ready()


def store(tool):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write("%d\n" % tool)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


last = c["tool-number"]
try:
    while True:
        tool = c["tool-number"]
        if tool != last:
            try:
                store(tool)
                last = tool
            except OSError as e:
                print("lasttool: cannot write %s: %s" % (path, e))
        time.sleep(0.2)
except KeyboardInterrupt:
    pass
