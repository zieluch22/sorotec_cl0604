#!/bin/bash
# Real machine, virtual part: builds qthd_virtual_probe.ini from the normal INI and starts it.
# The machine really moves; the camera picture and the probe touches come from virtual parts whose
# top is at machine Z VIRTUAL_TOP (default -10, spindle Z: a tool in the spindle reaches lower).
# Usage: ./start_virtual_probe.sh [top_z] [shift_x] [shift_y]
cd "$(dirname "$0")" || exit 1
TOP=${1:--10}
SX=${2:-0}
SY=${3:-0}
python3 - "$TOP" "$SX" "$SY" <<'PY'
import sys
top, sx, sy = (float(v) for v in sys.argv[1:4])
s = open("qthd_sorotec_cl0604.ini").read()
s = s.replace("POSTGUI_HALFILE = hallib/postgui_call_list.hal",
              "POSTGUI_HALFILE = hallib/postgui_call_list.hal\nPOSTGUI_HALFILE = hallib/virtual_probe.hal", 1)
s += "\n[TABLE_NAV]\nFAKE_CAMERA = 1\nVIRTUAL_PROBE = 1\nVIRTUAL_TOP = %g\nVIRTUAL_SHIFT_X = %g\nVIRTUAL_SHIFT_Y = %g\n" % (top, sx, sy)
open("qthd_virtual_probe.ini", "w").write(s)
PY
exec linuxcnc qthd_virtual_probe.ini
