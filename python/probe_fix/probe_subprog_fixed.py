#!/usr/bin/env python3
# Starts the stock QtDragon probe subprogram with a fixed "outside, four sides" routine.
# Lives in the config so a LinuxCNC update does not overwrite it. qtdragon_hd_handler.py
# points VersaProbe here (init of the handler, SUBPROGRAM).
#
# Why: probe() returns to the start of the probe move, but the stock routine still moves
# across by 2 * edge + latch + clearance, which ends only (edge + latch) past the starting
# point: on top of the part with a small edge length. Fixed so that the second side starts
# at (edge + clearance) from the starting point, the same as the first side.
# The rest of this function is the stock 2.9.7 code. Compare it after a LinuxCNC update.

import os
import runpy

from qtvcp.core import Status
import qtvcp.widgets.probe_routines as routines

STATUS = Status()


def probe_outside_xy_boss(self):

    # probe_outside_length_x
    self.history_log = 'Probe outside_xy_boss did not finish'

    # move X- edge_length + xy_clearance
    s = """G91
    G1 F%s X-%f
    G90""" % (self.data_rapid_vel, self.data_side_edge_length + self.data_xy_clearance)
    rtn = self.CALL_MDI_WAIT(s, self.timeout) 
    if rtn != 1:
        return 'Probe outside_xy_boss: -X positioning failed: {}'.format(rtn)
    rtn = self.z_clearance_down()
    if rtn != 1:
        return 'Probe outside_xy_boss: Z clearance down failed: {}'.format(rtn)
    rtn = self.probe('xplus')
    if rtn != 1:
        return 'Probe outside_xy_boss: Probe +X failed: {}'.format(rtn)

    # show -X result
    a = STATUS.get_probed_position_with_offsets()
    xmres = float(a[0]) + 0.5 * self.data_probe_diam
    self.status_xm = xmres

    # move Z to start point up
    rtn = self.z_clearance_up()
    if rtn != 1:
        return 'Probe outside_xy_boss: Z clearance up failed: {}'.format(rtn)

    # move X+ 2 * (edge_length + xy_clearance)
    aa = 2 * (self.data_side_edge_length + self.data_xy_clearance)
    s = """G91
    G1 F%s X%f
    G90""" % (self.data_rapid_vel, aa)
    rtn = self.CALL_MDI_WAIT(s, self.timeout) 
    if rtn != 1:
        return 'Probe outside_xy_boss: X positioning failed: {}'.format(rtn)
    rtn = self.z_clearance_down()
    if rtn != 1:
        return 'Probe outside_xy_boss: Z clearance down failed: {}'.format(rtn)
    rtn = self.probe('xminus')
    if rtn != 1:
        return 'Probe outside_xy_boss: Probe -X failed: {}'.format(rtn)

    # show X result
    a = STATUS.get_probed_position_with_offsets()
    xpres = float(a[0]) - 0.5 * self.data_probe_diam
    self.status_xp = xpres

    len_x = self.length_x()
    xcres = 0.5 * (xpres + xmres)
    self.status_xc = xcres

    # move Z to start point up
    rtn = self.z_clearance_up()
    if rtn != 1:
        return 'Probe outside_xy_boss: Z clearance up failed: {}'.format(rtn)

    # go to the new center of X
    s = "G1 F%s X%f" % (self.data_rapid_vel, xcres)
    rtn = self.CALL_MDI_WAIT(s, self.timeout) 
    if rtn != 1:
        return 'Probe outside_xy_boss: X to center failed: {}'.format(rtn)

    ################################
    # X probing done
    # Now Y probe_outside_length_y
    ################################

    # move Y- edge_length + xy_clearance
    a = self.data_side_edge_length + self.data_xy_clearance
    s = """G91
    G1 F%s Y-%f
    G90""" % (self.data_rapid_vel, a)
    rtn = self.CALL_MDI_WAIT(s, self.timeout) 
    if rtn != 1:
        return 'Probe outside_xy_boss: -Y positioning failed: {}'.format(rtn)
    rtn = self.z_clearance_down()
    if rtn != 1:
        return 'Probe outside_xy_boss: Z clearance down failed: {}'.format(rtn)
    rtn = self.probe('yplus')
    if rtn != 1:
        return 'Probe outside_xy_boss: Probe +Y failed: {}'.format(rtn)

    # show +Y result
    a = STATUS.get_probed_position_with_offsets()
    ymres = float(a[1]) + 0.5 * self.data_probe_diam
    self.status_ym = ymres

    # move Z to start point up
    rtn = self.z_clearance_up()
    if rtn != 1:
        return 'Probe outside_xy_boss: Z clearance up failed: {}'.format(rtn)

    # move Y+ 2 * (edge_length + xy_clearance)
    aa = 2 * (self.data_side_edge_length + self.data_xy_clearance)
    s = """G91
    G1 F%s Y%f
    G90""" % (self.data_rapid_vel, aa)
    rtn = self.CALL_MDI_WAIT(s, self.timeout) 
    if rtn != 1:
        return 'Probe outside_xy_boss: +Y positioning failed: {}'.format(rtn)
    rtn = self.z_clearance_down()
    if rtn != 1:
        return 'Probe outside_xy_boss: Z clearance down failed: {}'.format(rtn)
    rtn = self.probe('yminus')
    if rtn != 1:
        return 'Probe outside_xy_boss: Probe -Y failed: {}'.format(rtn)

    # show -Y result
    a = STATUS.get_probed_position_with_offsets()
    ypres = float(a[1]) - 0.5 * self.data_probe_diam
    self.status_yp = ypres

    len_y = self.length_y()

    # find, show and move to found  point
    ycres = 0.5 * (ypres + ymres)
    self.status_yc = ycres

    # average of both lengths
    diam = 0.5 * (len_x +len_y)
    self.status_d = diam

    self.add_history('Outside Hole ', "XmXcXpLxYmYcYpLyD", xmres, xcres, xpres, len_x, ymres, ycres, ypres, len_y, 0, diam, 0)

    # move Z to start point up
    rtn = self.z_clearance_up()
    if rtn != 1:
        return 'Probe outside_xy_boss: Z clearance up failed: {}'.format(rtn)
    # move to found  point
    s = "G1 F%s Y%f" % (self.data_rapid_vel, ycres)
    rtn = self.CALL_MDI_WAIT(s, self.timeout) 
    if rtn != 1:
        return 'Probe outside_xy_boss: Y to center failed: {}'.format(rtn)
    self.set_zero("XY")
    return 1

# Left outside edge, right inside edge


routines.ProbeRoutines.probe_outside_xy_boss = probe_outside_xy_boss

if __name__ == "__main__":
    runpy.run_path(os.path.join(os.path.dirname(routines.__file__), "probe_subprog.py"),
                   run_name="__main__")
