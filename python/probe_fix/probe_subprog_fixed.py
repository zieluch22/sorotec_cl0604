#!/usr/bin/env python3
# Starts the stock QtDragon probe subprogram with fixed routines:
#   - outside, four sides and hole (round pocket): see below
#   - inside corners / length / valley / rectangular pocket: stop with a clear message
#     when Side Edge < XY Clearance (stock: invalid move "X--30")
#   - angle routines: stop with a clear message when Side Edge is 0 (needs two touches apart)
# Lives in the config so a LinuxCNC update does not overwrite it. qtdragon_hd_handler.py
# points VersaProbe here (init of the handler, SUBPROGRAM).
#
# Why: probe() returns to the start of the probe move, but the stock routine still moves
# across by 2 * edge + latch + clearance, which ends only (edge + latch) past the starting
# point: on top of the part with a small edge length. Fixed so that the second side starts
# at (edge + clearance) from the starting point, the same as the first side.
# Hole: same problem. The stock move ends about 1 mm from where the far wall is expected, at
# depth and at rapid speed. Now it stops (edge - clearance) from the starting point, the same
# as the first side.
# The rest of these functions is the stock 2.9.7 code. Compare it after a LinuxCNC update.

import functools
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


def probe_xy_hole(self):
    self.history_log = 'Probe_xy_hole did not finish'

    rtn = self.z_clearance_down()
    if rtn != 1:
        return 'Probe_xy_hole failed: clearance up: {}'.format(rtn)
    # move X- edge_length - xy_clearance if needed
    tmpx = self.data_side_edge_length - self.data_xy_clearance
    if tmpx > 0:
        s = """G91
        G1 F%s X-%f
        G90""" % (self.data_rapid_vel, tmpx)        
        rtn = self.CALL_MDI_WAIT(s, self.timeout) 
        if rtn != 1:
            return 'Probe_xy_hole failed: X minus rapid positioning {}'.format(rtn)
    elif self.data_max_travel < self.data_side_edge_length:
            return 'Probe_xy_hole failed: Max travel is less then hole radius while xy_clearance is too large for rapid  positioning'
    elif self.data_max_travel < (2 * self.data_side_edge_length - self.data_latch_return_dist):
            return 'Probe_xy_hole failed: Max travel is less then hole diameter while xy_clearance is too large for rapid  positioning'
    # rough probe
    rtn = self.probe('xminus')
    if rtn != 1:
        return 'Probe_xy_hole failed: X minus probe: {}'.format(rtn)

    # show -X result
    a = STATUS.get_probed_position_with_offsets()
    xmres = float(a[0])-0.5*self.data_probe_diam
    self.status_xm =  xmres

    # move X+ 2 * (edge_length - xy_clearance)
    tmpx = 2 * (self.data_side_edge_length - self.data_xy_clearance)
    if tmpx > 0:
        s = """G91
        G1 F%s X%f
        G90""" % (self.data_rapid_vel, tmpx)        
        rtn = self.CALL_MDI_WAIT(s, self.timeout) 
        if rtn != 1:
            return 'Probe_xy_hole failed: X plus rapid positioning: {}'.format(rtn)
 
    # probe
    rtn = self.probe('xplus')
    if rtn != 1:
        return 'Probe_xy_hole failed: X plus probe: {}'.format(rtn)

    # show X result
    a = STATUS.get_probed_position_with_offsets()
    xpres = float(a[0]) + 0.5 * self.data_probe_diam
    self.status_xp = xpres
    len_x = self.length_x()
    xcres = 0.5 * (xmres + xpres)
    self.status_xc = xcres
    # move X to new center
    s = """G90
    G1 F%s X%f""" % (self.data_rapid_vel, xcres)        
    rtn = self.CALL_MDI_WAIT(s, self.timeout) 
    if rtn != 1:
        return 'Probe_xy_hole failed: X return to center: {}'.format(rtn)

    # move Y- edge_length + xy_clearance
    tmpy = self.data_side_edge_length - self.data_xy_clearance
    if tmpy > 0:
        s = """G91
        G1 F%s Y-%f
        G90""" % (self.data_rapid_vel, tmpy)        
        rtn = self.CALL_MDI_WAIT(s, self.timeout) 
        if rtn != 1:
            return 'Probe_xy_hole failed: Y minus rapid positioning: {}'.format(rtn)

    rtn = self.probe('yminus') 
    if rtn == -1: return 'Probe_xy_hole failed: Y minus probe: {}'.format(rtn)
    # show Y result
    a = STATUS.get_probed_position_with_offsets()
    ymres = float(a[1]) - 0.5 * self.data_probe_diam
    self.status_ym = ymres

    # move Y+ 2 * (edge_length - xy_clearance)
    tmpy = 2 * (self.data_side_edge_length - self.data_xy_clearance)
    if tmpy > 0:
        s = """G91
        G1 F%s Y%f
        G90""" % (self.data_rapid_vel, tmpy)        
        rtn = self.CALL_MDI_WAIT(s, self.timeout) 
        if rtn != 1:
            return 'Probe_xy_hole failed: Y minus rapid positioning {}'.format(rtn)

    rtn = self.probe('yplus')
    if rtn != 1:
        return 'Probe_xy_hole failed: Y plus probe: {}'.format(rtn)
    # show Y result
    a = STATUS.get_probed_position_with_offsets()
    ypres = float(a[1]) + 0.5 * self.data_probe_diam
    self.status_yp = ypres
    len_y = self.length_y()
    # find, show and move to found  point
    ycres = 0.5 * (ymres + ypres)
    self.status_yc = ycres
    diam = 0.5 * ((xpres - xmres) + (ypres - ymres))
    self.status_d = diam

    self.add_history('Inside Hole ', "XmXcXpLxYmYcYpLyD", xmres, xcres, xpres, len_x, ymres, ycres, ypres, len_y, 0, diam, 0)
    rtn = self.z_clearance_up()
    if rtn != 1:
        return 'Probe_xy_hole failed: clearance up: {}'.format(rtn)
    # move to center
    s = "G1 F%s Y%f" % (self.data_rapid_vel, ycres)
    rtn = self.CALL_MDI_WAIT(s, self.timeout) 
    if rtn != 1:
        return 'Probe_xy_hole failed: Y return to center: {}'.format(rtn)
    self.set_zero("XY")
    return 1
    
# Corners
# Move Probe manual under corner 2-3 mm
# Back left inside corner


def _check(method, problem):
    @functools.wraps(method)
    def checked(self):
        message = problem(self)
        return message if message else method(self)
    return checked


def _edge_too_small(self):
    if self.data_side_edge_length < self.data_xy_clearance:
        return 'Side Edge Length (%.3f) must not be smaller than XY Clearance (%.3f) for this routine' % (
            self.data_side_edge_length, self.data_xy_clearance)
    return None


def _no_edge(self):
    if self.data_side_edge_length <= 0:
        return 'Side Edge Length must be larger than 0: it is the distance between the two touches'
    return None


routines.ProbeRoutines.probe_outside_xy_boss = probe_outside_xy_boss
routines.ProbeRoutines.probe_xy_hole = probe_xy_hole
for name in ('probe_inside_xpyp', 'probe_inside_xpym', 'probe_inside_xmyp', 'probe_inside_xmym',
             'probe_inside_length_x', 'probe_inside_length_y'):
    setattr(routines.ProbeRoutines, name, _check(getattr(routines.ProbeRoutines, name), _edge_too_small))
for name in ('probe_angle_xp', 'probe_angle_xm', 'probe_angle_yp', 'probe_angle_ym',
             'probe_angle_front', 'probe_angle_back', 'probe_angle_left', 'probe_angle_right'):
    setattr(routines.ProbeRoutines, name, _check(getattr(routines.ProbeRoutines, name), _no_edge))

if __name__ == "__main__":
    runpy.run_path(os.path.join(os.path.dirname(routines.__file__), "probe_subprog.py"),
                   run_name="__main__")
