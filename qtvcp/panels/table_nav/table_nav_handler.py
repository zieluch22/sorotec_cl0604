#!/usr/bin/env python3
# Handler for the "Table navigation" tab, two modes:
#   MOVE    tap or drag the camera picture to move X/Y at the travel height.
#   SKETCH  draw the part on the same picture, check the proposed points, probe.
# Both need a calibrated downward camera. So far only the sim's virtual camera provides one.

import math
import os
import sys
import time

import linuxcnc
from PyQt5 import QtCore, QtGui, QtWidgets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from table_nav_logic import CORNERS, TableMap, move_command, not_ready_reason, setup_reason
import probe_plan as PP

NAV_FEED = 3000.0  # mm/min for the X/Y part of a move
PROBE_LOG = "/tmp/table_nav_probe.log"  # also named in macros/setup_height.ngc and setup_touch.ngc
Z_CLEAR = 5.0     # above the measured top while moving between points
OVERTRAVEL = 5.0  # search this far past the expected edge
LOG_WAIT = 2.0    # seconds to wait for a measurement to appear in the log
WCS = ("", "G54", "G55", "G56", "G57", "G58", "G59", "G59.1", "G59.2", "G59.3")
PAD = 22
BTN = "min-height: 42px; font-size: 15px; font-weight: bold;"


class MapWidget(QtWidgets.QWidget):
    tapped = QtCore.pyqtSignal(float, float)

    def __init__(self, table, marks, parent=None):
        super().__init__(parent)
        self.table = table
        self.marks = marks
        self.pos_xy = None
        self.target = None
        self.setMinimumSize(420, 280)

    def mousePressEvent(self, event):
        self.tapped.emit(*self.table.to_machine(event.x(), event.y(), self.width(), self.height(), PAD))

    def _px(self, x, y):
        return QtCore.QPointF(*self.table.to_pixel(x, y, self.width(), self.height(), PAD))

    def paintEvent(self, event):
        t = self.table
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor(25, 28, 32))
        p.setPen(QtGui.QPen(QtGui.QColor(150, 160, 170), 2))
        p.setBrush(QtGui.QColor(55, 62, 70))
        p.drawRect(QtCore.QRectF(self._px(t.x_min, t.y_max), self._px(t.x_max, t.y_min)))
        p.setPen(QtGui.QColor(240, 180, 40))
        for name, x, y in self.marks:
            c = self._px(x, y)
            p.drawRect(QtCore.QRectF(c.x() - 4, c.y() - 4, 8, 8))
            p.drawText(c + QtCore.QPointF(8, 4), name)
        if self.target:
            c = self._px(*self.target)
            p.setPen(QtGui.QPen(QtGui.QColor(60, 200, 255), 2))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawEllipse(c, 11, 11)
            p.drawLine(c + QtCore.QPointF(-16, 0), c + QtCore.QPointF(16, 0))
            p.drawLine(c + QtCore.QPointF(0, -16), c + QtCore.QPointF(0, 16))
        if self.pos_xy:
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(70, 230, 90))
            p.drawEllipse(self._px(*self.pos_xy), 7, 7)
        p.end()


class HandlerClass:
    def __init__(self, halcomp, widgets, paths):
        self.w = widgets
        self.stat = linuxcnc.stat()
        self.cmd = linuxcnc.command()
        self.xy = None
        self.reason = "Starting"
        self.run_block = "Starting"
        self.canvas = None
        self.cam = None
        self.stage = None
        self.sent_at = 0.0
        self.idle_at = None
        self.frame_tick = 0
        self.result = None
        self.result_text = ""
        self.orig_rotation = 0.0
        self.final_xy = None
        self.run_pose = None
        self.view_ready = False
        self.restore_pending = False
        self.drawn_xy = None

    def _ini(self, section, name, default):
        try:
            value = self.ini.find(section, name)
            return float(value) if value is not None else default
        except ValueError:
            return default

    def initialized__(self):
        self.ini = linuxcnc.ini(os.environ["INI_FILE_NAME"])
        table = TableMap(self._ini("AXIS_X", "MIN_LIMIT", 0), self._ini("AXIS_X", "MAX_LIMIT", 100),
                         self._ini("AXIS_Y", "MIN_LIMIT", 0), self._ini("AXIS_Y", "MAX_LIMIT", 100))
        self.table = table
        self.z_max = self._ini("AXIS_Z", "MAX_LIMIT", 0)
        self.z_min = self._ini("AXIS_Z", "MIN_LIMIT", -100)
        marks = []
        if self.ini.find("ATC", "CHANGEX") and self.ini.find("ATC", "CHANGEY"):
            marks.append(("Setter", self._ini("ATC", "CHANGEX", 0), self._ini("ATC", "CHANGEY", 0)))
        if self.ini.find("ATC", "FIRSTPOCKET_X") and self.ini.find("ATC", "FIRSTPOCKET_Y"):
            marks.append(("Rack 1", self._ini("ATC", "FIRSTPOCKET_X", 0), self._ini("ATC", "FIRSTPOCKET_Y", 0)))
        tool = self.ini.find("VERSA_PROBE_OPTIONS", "PS_PROBE_TOOL")
        self.probe_tool = int(float(tool)) if tool else None
        self.map = MapWidget(table, marks)
        self.map.tapped.connect(self.view_go)
        self.build_controls()
        if self._ini("TABLE_NAV", "FAKE_CAMERA", 0):
            self.build_canvas()
        else:  # no sketching: the map is the way to move, so it gets the room
            self.w.nav_holder.setFixedWidth(560)
            self.map.setMaximumHeight(16777215)
            self.map.setMinimumSize(520, 330)
        self.set_target(*table.clamp((table.x_min + table.x_max) / 2, (table.y_min + table.y_max) / 2))
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.poll)
        self.timer.start(100)

    def button(self, text, slot, style=BTN):
        b = QtWidgets.QPushButton(text)
        b.setStyleSheet(style)
        b.clicked.connect(slot)
        return b

    def spin(self, value, low, high):
        box = QtWidgets.QDoubleSpinBox()
        box.setRange(low, high)
        box.setDecimals(2)
        box.setValue(value)
        box.setStyleSheet("min-height: 34px; font-size: 15px;")
        return box

    def build_controls(self):
        self.w.nav_holder.setFixedWidth(270)
        side = QtWidgets.QVBoxLayout(self.w.nav_holder)
        side.setContentsMargins(0, 0, 0, 0)
        self.map.setMinimumSize(200, 105)
        self.map.setMaximumHeight(125)
        side.addWidget(self.map)
        self.lbl_pos = QtWidgets.QLabel()
        self.lbl_status = QtWidgets.QLabel()
        self.lbl_status.setWordWrap(True)
        for lbl in (self.lbl_pos, self.lbl_status):
            lbl.setStyleSheet("font-size: 14px;")
            side.addWidget(lbl)
        side.addWidget(self.button("STOP", self.stop, BTN + "color: #ff5050;"))
        side.addStretch(1)
        box = QtWidgets.QGroupBox("Configuration")
        self.cfg = QtWidgets.QGridLayout(box)
        side.addWidget(box)
        self.sp_travel = self.spin(self.z_max - 1.0, self.z_min, self.z_max)
        self.cfg_row("Travel Z", self.sp_travel)

    def cfg_row(self, text, widget):
        row = self.cfg.rowCount()
        self.cfg.addWidget(QtWidgets.QLabel(text), row, 0)
        self.cfg.addWidget(widget, row, 1)

    def build_canvas(self):
        from setup_canvas import Canvas
        from vision import CameraModel, fake_frame, find_shape
        self.fake_frame, self.find_shape = fake_frame, find_shape
        self.cam = CameraModel()
        self.w.camview.hide()
        box = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(box)
        self.canvas = Canvas(self.cam)
        self.canvas.drawn.connect(self.shape_drawn)
        self.canvas.changed.connect(self.update_setup_text)
        self.canvas.master_distance.connect(self.master_dragged)
        col.addWidget(self.canvas, 1)
        top = QtWidgets.QHBoxLayout()
        self.view_btns = []
        for key, text in (("move", "MOVE"), ("sketch", "SKETCH")):
            b = self.button(text, lambda _=False, v=key: self.set_view_mode(v))
            b.setProperty("label", text)
            self.view_btns.append((key, b))
            top.addWidget(b)
        col.insertLayout(0, top)
        actions = QtWidgets.QHBoxLayout()
        actions.addWidget(self.button("ADD POINT", self.add_point))
        actions.addWidget(self.button("REMOVE POINT", self.remove_point))
        self.btn_run = self.button("PROBE", self.run_setup, BTN + "color: #60c8ff;")
        actions.addWidget(self.btn_run)
        self.btn_apply = self.button("APPLY", self.apply_result, BTN + "color: #30ff60;")
        actions.addWidget(self.btn_apply)
        actions.addWidget(self.button("CLEAR", self.clear_shape))
        col.addLayout(actions)
        self.lbl_setup = QtWidgets.QLabel()
        self.lbl_setup.setStyleSheet("font-size: 15px;")
        self.lbl_setup.setWordWrap(True)
        col.addWidget(self.lbl_setup)
        self.cmb_corner = QtWidgets.QComboBox()
        self.cmb_corner.addItems(list(CORNERS))
        self.cmb_corner.setStyleSheet("min-height: 34px; font-size: 15px;")
        self.cmb_corner.currentIndexChanged.connect(lambda _: self.propose_points())
        self.sp_approach = self.spin(20.0, 3.0, 60.0)
        self.sp_dia = self.spin(1.98, 0.1, 20.0)
        self.sp_depth = self.spin(PP.default_depth(1.98), 0.2, 60.0)
        self.sp_z = self.spin(-70.0, self.z_min, self.z_max)
        for text, widget in (("Origin corner", self.cmb_corner), ("Approach mm", self.sp_approach), ("Stylus dia", self.sp_dia),
                             ("Edge depth", self.sp_depth), ("Rough top Z", self.sp_z)):
            self.cfg_row(text, widget)
        self.chk_auto = QtWidgets.QCheckBox("Apply automatically")
        self.chk_auto.setStyleSheet("font-size: 15px;")
        self.cfg.addWidget(self.chk_auto, self.cfg.rowCount(), 0, 1, 2)
        self.sp_approach.valueChanged.connect(self.approach_changed)
        self.sp_dia.valueChanged.connect(lambda v: self.sp_depth.setValue(PP.default_depth(v)))
        self.sp_z.valueChanged.connect(self.rough_z_changed)
        self.set_view_mode("move")
        self.w.main_l.insertWidget(0, box, 1)
        self.canvas.go_to.connect(self.view_go)
        self.canvas.z = self.sp_z.value()

    # ---- camera view: MOVE and SKETCH share it
    def set_view_mode(self, key):
        if key == self.canvas.mode and self.view_ready:
            key = None  # tapping the active mode switches the view off
        self.view_ready = True
        self.canvas.mode = key
        for k, b in self.view_btns:
            active = k == key
            b.setText(("\u25cf " if active else "\u25cb ") + b.property("label"))
            b.setStyleSheet(BTN + ("color: #30ff60;" if active else "color: #909090;"))

    def view_go(self, x, y):
        self.set_target(*self.table.clamp(x, y))
        self.go()

    def add_point(self):
        c = self.canvas
        if c.shape is None or not c.points:
            return
        slot = PP.next_free_slot(c.shape, c.points, self.cam, c.pose, c.z)
        p = PP.Point(slot[0], slot[1], c.points[0].inside, c.points[0].approach)
        c.add_point(p)
        self.update_setup_text()

    def remove_point(self):
        if not self.canvas.remove_marked():
            self.lbl_setup.setText("Tap a small circle to mark a point first. The first point and the last three stay.")
        else:
            self.update_setup_text()

    def clear_shape(self):
        self.result = None
        self.canvas.shape = None
        self.canvas.points = []
        self.canvas.height_px = None
        self.lbl_setup.setText("")
        self.canvas.update()

    def rough_z_changed(self, value):
        self.canvas.z = value
        self.canvas.update()

    def approach_changed(self, value):
        if self.canvas.points:
            self.canvas.points[0].approach = value
            self.canvas.set_all_distances(value)

    def master_dragged(self, value):
        self.sp_approach.blockSignals(True)
        self.sp_approach.setValue(value)
        self.sp_approach.blockSignals(False)

    def shape_drawn(self, stroke):
        self.result = None
        found = self.find_shape(self.canvas.frame, stroke)
        if found[0] == "rect":
            self.canvas.shape = PP.RectShape(found[1], found[2])
        else:
            self.canvas.shape = PP.CircleShape(found[1], found[2], found[3])
        self.canvas.height_px = self.canvas.shape.center_px()
        self.propose_points()

    def propose_points(self):
        c = self.canvas
        if c is None or c.shape is None:
            return
        sx, sy = CORNERS[self.cmb_corner.currentText()]
        c.set_points(c.shape.default_points(self.cam, c.pose, c.z, sx, sy, self.sp_approach.value()))
        self.update_setup_text()
        c.update()

    def update_setup_text(self):
        c = self.canvas
        if c.shape is None:
            return
        found = all(c.shape.found) if c.shape.kind == "rect" else c.shape.found
        text = "Edges found: check the points." if found else "RED edges were not found: they follow your drawing, check them carefully."
        if c.shape.kind == "circle" and c.points[0].inside:
            text += "  Inside (hole): put the Z point on the surface, outside the circle."
        self.lbl_setup.setText(text)

    # ---- moving
    def set_target(self, x, y):
        self.map.target = (x, y)
        self.map.update()

    def go(self):
        # state is read again here: the last poll can be 100 ms old
        self.poll()
        if self.reason or not self.map.target:
            return
        self.send(move_command(self.map.target[0], self.map.target[1], NAV_FEED, self.sp_travel.value()))

    def send(self, line):
        self.cmd.mode(linuxcnc.MODE_MDI)
        self.cmd.wait_complete()
        self.cmd.mdi(line)
        self.sent_at = time.time()
        self.idle_at = None

    def stop(self):
        if self.stage:
            self.restore_pending = True
        self.stage = None
        self.cmd.abort()

    # ---- probing sequence: height first, then the edge points, then write the offset
    def run_setup(self):
        c = self.canvas
        self.poll()
        if self.run_block or c.shape is None or c.height_px is None:
            return
        answer = QtWidgets.QMessageBox.question(self.w.nav_holder, "Probe",
                 "Measures the height first, then %d edge points, then overwrites the active work offset.\n\n"
                 "The probe will go down at the small dots: are those spaces free?" % len(c.points))
        if answer != QtWidgets.QMessageBox.Yes:
            return
        self.poll()
        if self.run_block:
            return
        self.result = None
        self.orig_rotation = self.stat.rotation_xy
        try:
            os.remove(PROBE_LOG)
        except OSError:
            pass
        self.run_pose = c.pose  # the picture the plan was drawn on; the machine moves away from it
        x, y = self.cam.to_machine(c.pose, c.height_px[0], c.height_px[1], c.z)
        descent = self.sp_travel.value() - self.z_min - 1.0
        self.stage = ("height", 0)
        self.send(PP.height_command(x, y, self.sp_travel.value(), descent))
        self.lbl_setup.setText("Measuring height...")

    def records(self):
        try:
            with open(PROBE_LOG) as f:
                return PP.parse_log(f.read())
        except OSError:
            return []

    def fail(self, text):
        self.stage = None
        self.restore_pending = True
        self.lbl_setup.setText("Stopped: " + text + " The work offset was not changed.")

    def advance(self):
        c = self.canvas
        name, i = self.stage
        rec = self.records()
        # LinuxCNC can report idle just before the macro's log line reaches the file
        if len(rec) < {"height": 1, "touch": i + 2}.get(name, 0) and time.time() - self.idle_at < LOG_WAIT:
            return
        if name == "height":
            if len(rec) != 1:
                return self.fail("height not measured.")
            self.top_f, top_m = rec[0][1], rec[0][2]
            c.z = top_m
            c.update()
            self.paths = [PP.probe_path(c.shape, p, self.cam, self.run_pose, top_m, OVERTRAVEL) for p in c.points]
            self.stage = ("touch", 0)
            return self.send_touch(0)
        if name == "touch":
            if len(rec) != i + 2:
                return self.fail("edge point %d not measured." % (i + 1))
            if i + 1 < len(self.paths):
                self.stage = ("touch", i + 1)
                return self.send_touch(i + 1)
            return self.apply(rec[1:])
        if name == "apply":
            # finish over the result (corner or centre) at the travel height
            self.stage = ("finish", 0)
            x, y = self.table.clamp(self.final_xy[0], self.final_xy[1])
            return self.send(move_command(x, y, NAV_FEED, self.sp_travel.value()))
        self.stage = None

    def send_touch(self, i):
        start, _, target = self.paths[i]
        zsafe = self.top_f + Z_CLEAR
        self.send(PP.touch_command(start, target, zsafe, self.top_f - self.sp_depth.value()))
        self.lbl_setup.setText("Edge point %d of %d..." % (i + 1, len(self.paths)))

    def apply(self, touches):
        c = self.canvas
        r = self.sp_dia.value() / 2.0
        contacts = []
        for t, (start, _, target) in zip(touches, self.paths):
            d = (target[0] - start[0], target[1] - start[1])
            n = math.hypot(*d)
            contacts.append((t[1], t[2], d[0] / n, d[1] / n))
        self.stat.poll()
        z_offset = self.top_f + self.stat.g5x_offset[2]
        if c.shape.kind == "rect":
            sx, sy = CORNERS[self.cmb_corner.currentText()]
            x, y, angle, determined = PP.solve_rect(c.shape, c.points, contacts, r, self.cam, self.run_pose, c.z, sx, sy)
            if abs(angle) > 15:
                return self.fail("part looks more than 15 degrees crooked.")
            text = "Set: corner X %.3f  Y %.3f  Z %.3f  rotation %.3f deg" % (x, y, z_offset, angle)
            if not determined:
                text += "  WARNING: points do not fix X, Y and rotation; the camera value was used for the rest."
        else:
            x, y, rad = PP.solve_circle(contacts, r, c.points[0].inside)
            angle = 0.0
            text = "Set: centre X %.3f  Y %.3f  Z %.3f  diameter %.3f" % (x, y, z_offset, 2 * rad)
            if not PP.circle_spread_ok(c.points):
                text += "  WARNING: points are bunched up, the centre is unreliable."
        self.result = (x, y, z_offset, angle)
        self.final_xy = (x, y)
        self.result_text = text
        self.stage = ("apply", 0)
        if self.chk_auto.isChecked():
            self.send(self.result_line())
            self.lbl_setup.setText(text + "  Applied to %s." % self.wcs_name())
            self.result = None
        else:
            self.send("G10 L2 P0 R%.4f" % self.orig_rotation)  # measuring alone leaves the offset as it was
            self.lbl_setup.setText(text.replace("Set:", "Measured:", 1) + "  Press APPLY to write it.")

    def result_line(self):
        return "G10 L2 P0 X%.4f Y%.4f Z%.4f R%.4f" % self.result

    def wcs_name(self):
        return WCS[self.stat.g5x_index]

    def apply_result(self):
        """Write the last measurement to the coordinate system active right now."""
        self.poll()
        if self.reason or not self.result:
            return
        self.send(self.result_line())
        self.lbl_setup.setText(self.result_text + "  Applied to %s." % self.wcs_name())
        self.result = None

    def poll(self):
        try:
            self.stat.poll()
        except linuxcnc.error:
            self.reason = "No connection to LinuxCNC"
            self.run_block = self.reason
        else:
            s = self.stat
            self.xy = (s.actual_position[0], s.actual_position[1])
            self.map.pos_xy = self.xy
            self.lbl_pos.setText("Machine  X %.1f  Y %.1f  Z %.1f" % (s.actual_position[0], s.actual_position[1], s.actual_position[2]))
            idle = s.interp_state == linuxcnc.INTERP_IDLE
            if self.restore_pending and idle:
                self.restore_pending = False
                self.send("G10 L2 P0 R%.4f" % self.orig_rotation)
            base = not_ready_reason(s.task_state == linuxcnc.STATE_ON, all(s.homed[i] for i in range(s.joints)),
                                    idle, s.task_mode == linuxcnc.MODE_AUTO)
            self.run_block = setup_reason(base, s.tool_in_spindle, self.probe_tool) or ("Probing" if self.stage else "")
            self.reason = base or ("Probing" if self.stage else "")
            if self.stage and idle and time.time() - self.sent_at > 0.4:
                if self.idle_at is None:
                    self.idle_at = time.time()
                self.advance()
            elif not idle:
                self.idle_at = None  # busy again: the wait for its log line starts when it ends
            moved = self.xy != self.drawn_xy
            if moved:
                self.drawn_xy = self.xy
                self.map.update()
            if self.canvas and not self.stage and (moved or self.canvas.frame is None):
                self.frame_tick += 1
                if self.frame_tick % 2 == 0 or self.canvas.frame is None:
                    pose = tuple(s.actual_position[:3])
                    self.canvas.set_pose(pose, self.fake_frame(self.cam, pose))
        if self.canvas:
            self.btn_run.setEnabled(not self.run_block)
            self.btn_apply.setEnabled(bool(self.result) and not self.reason)
            self.btn_apply.setText("APPLY TO " + WCS[self.stat.g5x_index])
        view_off = self.canvas is not None and self.canvas.mode is None
        self.lbl_status.setText(self.reason or ("Ready - camera view switched off" if view_off else "Ready"))


def get_handlers(halcomp, widgets, paths):
    return [HandlerClass(halcomp, widgets, paths)]
