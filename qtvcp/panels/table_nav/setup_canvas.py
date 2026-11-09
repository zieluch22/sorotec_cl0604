#!/usr/bin/env python3
# Picture area of the Table page. MOVE: tap or drag the picture to move the machine. SKETCH: freehand shape and probing points.
# The first point is the master: it holds the inside/outside swap and sets the distance for all points.
# Tap another small circle to mark it; only a marked one can be dragged on its own.
import math

from PyQt5 import QtCore, QtGui, QtWidgets

from probe_plan import probe_path

GREEN, RED, BLUE, AMBER, WHITE = (QtGui.QColor(70, 230, 90), QtGui.QColor(255, 80, 70), QtGui.QColor(60, 200, 255),
                                  QtGui.QColor(240, 180, 40), QtGui.QColor(245, 245, 245))
GRAB = 24  # px on the widget, finger sized
SWAP_GAP = 36
MIN_APPROACH, MAX_APPROACH = 3.0, 60.0


class Canvas(QtWidgets.QWidget):
    drawn = QtCore.pyqtSignal(object)            # list of image points of the stroke
    changed = QtCore.pyqtSignal()
    go_to = QtCore.pyqtSignal(float, float)      # machine X/Y the spindle should go to
    master_distance = QtCore.pyqtSignal(float)

    def __init__(self, cam, parent=None):
        super().__init__(parent)
        self.cam = cam
        self.frame = None
        self.mode = "move"
        self.pan_from = self.pan_to = None
        self._pix = None
        self._pix_key = None
        self.shape = None
        self.points = []
        self.height_px = None
        self.pose = (0.0, 0.0, 0.0)
        self.z = -100.0
        self.over = 5.0
        self.stroke = None
        self.drag = None
        self.moved = False
        self.marked = None
        self.setMinimumSize(480, 360)

    # ---- image <-> widget
    def _fit(self):
        s = min(self.width() / float(self.cam.width), self.height() / float(self.cam.height))
        return s, (self.width() - s * self.cam.width) / 2.0, (self.height() - s * self.cam.height) / 2.0

    def to_widget(self, p):
        s, ox, oy = self._fit()
        return QtCore.QPointF(ox + p[0] * s, oy + p[1] * s)

    def to_image(self, event):
        s, ox, oy = self._fit()
        return ((event.x() - ox) / s, (event.y() - oy) / s)

    def mm_px(self, xy):
        return self.cam.to_pixel(self.pose, xy[0], xy[1], self.z)

    # ---- points
    def set_points(self, points):
        self.points = points
        self.marked = None

    def layout_point(self, point):
        start, edge, _ = probe_path(self.shape, point, self.cam, self.pose, self.z, self.over)
        return self.to_widget(self.mm_px(start)), self.to_widget(self.mm_px(edge))

    def swap_pos(self):
        s, e = self.layout_point(self.points[0])
        v = (s.x() - e.x(), s.y() - e.y())
        n = math.hypot(*v) or 1.0
        return QtCore.QPointF(e.x() - v[1] / n * SWAP_GAP, e.y() + v[0] / n * SWAP_GAP)

    def add_point(self, point):
        self.points.append(point)
        self.marked = len(self.points) - 1
        self.update()

    def remove_marked(self):
        if self.marked is not None and self.marked != 0 and len(self.points) > 3:
            del self.points[self.marked]
            self.marked = None
            self.update()
            return True
        return False

    def set_all_distances(self, value):
        """Every point that is not individually adjusted follows the master."""
        for p in self.points:
            if not p.override:
                p.approach = value
        self.update()

    def swap_all(self):
        inside = not self.points[0].inside
        for p in self.points:
            p.inside = inside

    def hit(self, pos):
        near = lambda q: math.hypot(pos.x() - q.x(), pos.y() - q.y()) <= GRAB
        if self.height_px and near(self.to_widget(self.height_px)):
            return "height", 0
        if self.points and near(self.swap_pos()):
            return "swap", 0
        for i, point in enumerate(self.points):
            s, e = self.layout_point(point)
            if near(s):
                return "start", i
            if near(e):
                return "edge", i
        return None

    # ---- input
    def set_pose(self, pose, frame, follow=True):
        """New picture. Sketches stay on the part while the machine moves under them."""
        if follow and self.shape is not None:
            self.shape.rebase(self.cam, self.pose, pose, self.z)
            if self.height_px:
                self.height_px = self.cam.to_pixel(pose, *self.cam.to_machine(self.pose, self.height_px[0], self.height_px[1], self.z), self.z)
        self.pose, self.frame = pose, frame
        self.update()

    def mousePressEvent(self, event):
        if self.frame is None or self.mode is None:  # view switched off: touches do nothing
            return
        if self.mode == "move":
            self.pan_from = self.pan_to = self.to_image(event)
            return
        hit = self.hit(event.pos()) if self.shape else None
        self.moved = False
        if hit and hit[0] == "swap":
            self.swap_all()
            self.changed.emit()
            self.update()
        elif hit:
            self.drag = hit
        else:
            self.stroke = [self.to_image(event)]

    def mouseMoveEvent(self, event):
        if self.pan_from is not None:
            self.pan_to = self.to_image(event)
            self.update()
        elif self.drag:
            self.moved = True
            self.drag_to(self.to_image(event))
            self.update()
        elif self.stroke is not None:
            self.stroke.append(self.to_image(event))
            self.update()

    def mouseReleaseEvent(self, event):
        if self.pan_from is not None:
            a, b = self.pan_from, self.to_image(event)
            self.pan_from = self.pan_to = None
            self.finish_pan(a, b)
            self.update()
        elif self.drag:
            name, i = self.drag
            if name == "start" and i != 0 and not self.moved:
                self.tap_small(i)
            self.drag = None
            self.changed.emit()
            self.update()
        elif self.stroke is not None:
            stroke, self.stroke = self.stroke, None
            xs = [p[0] for p in stroke]
            ys = [p[1] for p in stroke]
            if max(max(xs) - min(xs), max(ys) - min(ys)) >= 20:
                self.drawn.emit(stroke)
            self.update()

    def finish_pan(self, a, b):
        """Tap: bring that spot to the centre. Drag: the picture follows the finger."""
        to_m = lambda p: self.cam.to_machine(self.pose, p[0], p[1], self.z)
        if math.hypot(b[0] - a[0], b[1] - a[1]) < 10:
            m, c = to_m(a), to_m((self.cam.width / 2.0, self.cam.height / 2.0))
            self.go_to.emit(self.pose[0] + m[0] - c[0], self.pose[1] + m[1] - c[1])
        else:
            m, n = to_m(a), to_m(b)
            self.go_to.emit(self.pose[0] + m[0] - n[0], self.pose[1] + m[1] - n[1])

    def tap_small(self, i):
        """First tap marks a point; a tap on the marked point releases it back to the master."""
        if self.marked == i:
            self.marked = None
            self.points[i].override = False
            self.points[i].approach = self.points[0].approach
        else:
            self.marked = i

    def drag_to(self, px):
        name, i = self.drag
        if name == "height":
            self.height_px = px
            return
        point = self.points[i]
        if name == "start":
            if i != 0 and self.marked != i:
                return
            m = self.cam.to_machine(self.pose, px[0], px[1], self.z)
            edge, out = self.shape.edge_geometry(point, self.cam, self.pose, self.z)
            dist = (m[0] - edge[0]) * out[0] + (m[1] - edge[1]) * out[1]
            value = max(MIN_APPROACH, min(MAX_APPROACH, -dist if point.inside else dist))
            if i == 0:
                point.approach = value
                self.set_all_distances(value)
                self.master_distance.emit(value)
            else:
                point.approach = value
                point.override = True
        elif self.shape.kind == "rect":
            best = None
            for e in range(4):  # the nearest side wins, so a point can go round the corners
                a, b = self.shape.corners[e], self.shape.corners[(e + 1) % 4]
                d = (b[0] - a[0], b[1] - a[1])
                t = max(0.03, min(0.97, ((px[0] - a[0]) * d[0] + (px[1] - a[1]) * d[1]) / (d[0] ** 2 + d[1] ** 2)))
                dist = math.hypot(a[0] + d[0] * t - px[0], a[1] + d[1] * t - px[1])
                if best is None or dist < best[0]:
                    best = (dist, e, t)
            point.edge, point.t = best[1], best[2]
        else:
            c = self.shape.center
            m = self.cam.to_machine(self.pose, px[0], px[1], self.z)
            mc = self.cam.to_machine(self.pose, c[0], c[1], self.z)
            point.t = (math.atan2(m[1] - mc[1], m[0] - mc[0]) / (2 * math.pi)) % 1.0

    # ---- drawing
    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor(15, 16, 18))
        if self.frame is not None:
            h, w = self.frame.shape[:2]
            s, ox, oy = self._fit()
            key = (id(self.frame), self.width(), self.height())
            if key != self._pix_key:  # scaling is the slow part, so it is done once per picture
                img = QtGui.QImage(self.frame.data, w, h, 3 * w, QtGui.QImage.Format_BGR888)
                self._pix = QtGui.QPixmap.fromImage(img).scaled(int(w * s), int(h * s))
                self._pix_key = key
            p.drawPixmap(int(ox), int(oy), self._pix)
        self.paint_setup(p)
        p.end()

    def paint_setup(self, p):
        if self.shape is not None:
            p.setBrush(QtCore.Qt.NoBrush)
            if self.shape.kind == "rect":
                for i in range(4):
                    p.setPen(QtGui.QPen(GREEN if self.shape.found[i] else RED, 2))
                    p.drawLine(self.to_widget(self.shape.corners[i]), self.to_widget(self.shape.corners[(i + 1) % 4]))
            else:
                s = self._fit()[0] * self.shape.radius
                p.setPen(QtGui.QPen(GREEN if self.shape.found else RED, 2))
                p.drawEllipse(self.to_widget(self.shape.center), s, s)
            for i, point in enumerate(self.points):
                self.paint_point(p, i, point)
            self.paint_swap(p)
        if self.height_px:
            c = self.to_widget(self.height_px)
            p.setPen(QtGui.QPen(AMBER, 3))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawEllipse(c, 11, 11)
            p.drawText(c + QtCore.QPointF(15, 6), "Z first")
        if self.stroke and len(self.stroke) > 1:
            p.setPen(QtGui.QPen(BLUE, 2))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawPolyline(QtGui.QPolygonF([self.to_widget(q) for q in self.stroke]))

    def paint_point(self, p, i, point):
        s, e = self.layout_point(point)
        master = i == 0
        marked = self.marked == i
        color = AMBER if master else BLUE
        p.setPen(QtGui.QPen(color, 2))
        p.drawLine(s, e)
        p.setBrush(color)
        p.drawEllipse(e, 10 if master else 8, 10 if master else 8)
        if marked:
            p.setPen(QtGui.QPen(WHITE, 3))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawEllipse(s, 13, 13)
        p.setPen(QtGui.QPen(color, 2))
        p.setBrush(WHITE if marked else QtGui.QColor(20, 24, 28))
        p.drawEllipse(s, 7 if master else 6, 7 if master else 6)
        if master:
            p.setPen(WHITE)
            p.drawText(e + QtCore.QPointF(-22, -13), "1st")

    def paint_swap(self, p):
        sw = self.swap_pos()
        p.setBrush(QtGui.QColor(30, 34, 40))
        p.setPen(QtGui.QPen(AMBER, 2))
        p.drawEllipse(sw, 17, 17)
        rect = QtCore.QRectF(sw.x() - 9, sw.y() - 9, 18, 18)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawArc(rect, 30 * 16, 130 * 16)
        p.drawArc(rect, 210 * 16, 130 * 16)
        for ang in (30, 210):
            r = math.radians(ang)
            tip = QtCore.QPointF(sw.x() + 9 * math.cos(r), sw.y() - 9 * math.sin(r))
            p.drawLine(tip, tip + QtCore.QPointF(4.5 * math.cos(r + 2.4), -4.5 * math.sin(r + 2.4)))
            p.drawLine(tip, tip + QtCore.QPointF(4.5 * math.cos(r + 0.9), -4.5 * math.sin(r + 0.9)))
