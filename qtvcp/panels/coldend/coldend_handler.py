#!/usr/bin/env python3
# Handler for the embedded QtDragon "ColdEnd" tab (qtvcp/panels/coldend/coldend.ui).
# Remembers the spit on/off button in the QtDragon
# preference file, section [COLDEND]. All HAL wiring is in hallib/coldend_postgui.hal.

import os

from PyQt5 import QtCore, QtGui
from qtvcp import logger

LOG = logger.getLogger(__name__)
SECTION = "COLDEND"

CHECKS = ("btn_spit_on",)

GREEN = QtGui.QColor(0, 220, 0)
RED = QtGui.QColor(230, 0, 0)
GREY = QtGui.QColor(70, 70, 70)
# health: green = OK, red = problem
HEALTH_LEDS = ("led_link", "led_fw", "led_main_link")
# activity: green = running / switch on, grey = off (off is not a fault)
ACTIVITY_LEDS = ("led_mist", "led_air", "led_prime", "led_sw_mist", "led_sw_fast",
                 "led_sw_air", "led_main_mist")
BOARD_IMAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "coldend_board.png")


class HandlerClass:
    def __init__(self, halcomp, widgets, paths):
        self.hal = halcomp
        self.w = widgets
        self.PATHS = paths
        self.prefs = None

    def initialized__(self):
        self.init_look()
        self.init_slider()
        try:
            self.prefs = self.w.MAIN.PREFS_
        except AttributeError:
            self.prefs = None
        if not self.prefs:
            LOG.warning("ColdEnd tab: no preference file - screen settings will not be remembered")
            return
        for name in CHECKS:
            wid = getattr(self.w, name)
            wid.setChecked(self.prefs.getpref(name, wid.isChecked(), bool, SECTION))
            wid.toggled.connect(lambda v, n=name: self.save(n, bool(v), bool))

    def init_look(self):
        for names, on, off in ((HEALTH_LEDS, GREEN, RED), (ACTIVITY_LEDS, GREEN, GREY)):
            for name in names:
                led = getattr(self.w, name, None)
                if led is not None:
                    led.setColor(on)
                    led.setOffColor(off)
        # ColdEnd board picture (from the TallaMod AXIS panel)
        pix = QtGui.QPixmap(BOARD_IMAGE)
        if not pix.isNull():
            self.w.img_board.setPixmap(pix.scaled(300, 300, QtCore.Qt.KeepAspectRatio,
                                                  QtCore.Qt.SmoothTransformation))

    def init_slider(self):
        # A slider follows the value in use, so it shows the knob's value after the knob
        # takes over (held at its end above its range). A real touch is reported by the
        # hidden counters sl_mist_touch / sl_spit_touch: python/coldend.py cannot tell it
        # from the slider's value, a button may set the value the pin already has.
        w = self.w
        w.sl_mist_touch.hide()
        w.sl_spit_touch.hide()
        w.sl_mist.actionTriggered.connect(lambda a: self.touched(w.sl_mist_touch))
        w.sl_spit_time.actionTriggered.connect(lambda a: self.touched(w.sl_spit_touch))
        for btn, slider, value, counter in (
                (w.btn_mist_40, w.sl_mist, 40, w.sl_mist_touch),
                (w.btn_mist2_0, w.sl_mist, 0, w.sl_mist_touch),
                (w.btn_mist2_40, w.sl_mist, 40, w.sl_mist_touch),
                (w.btn_spit_0, w.sl_spit_time, 0, w.sl_spit_touch),
                (w.btn_spit_4, w.sl_spit_time, 40, w.sl_spit_touch),
                (w.btn_flow_100, w.sl_spit_flow, 100, None),
                (w.btn_flow_1562, w.sl_spit_flow, 1562, None)):
            btn.clicked.connect(lambda c, s=slider, v=value, t=counter: self.preset(s, v, t))
        try:
            w.lbl_main_flow.hal_pin.value_changed.connect(self.show_flow)
            w.lbl_spit_time.hal_pin.value_changed.connect(self.show_spit_time)
        except Exception as e:
            LOG.warning("ColdEnd tab: sliders will not follow the values: {}".format(e))
        w.btn_tab_air.set_true_string('AIR\nON')
        w.btn_tab_air.set_false_string('AIR\nOFF')
        w.btn_tab_air.setText('AIR\nON' if w.btn_tab_air.isChecked() else 'AIR\nOFF')

    def touched(self, counter):
        counter.setValue(counter.value() + 1)

    def preset(self, slider, value, counter):
        slider.setValue(value)
        if counter is not None:
            self.touched(counter)

    def show_flow(self, flow):
        if not self.w.sl_mist.isSliderDown():
            self.w.sl_mist.setValue(int(round(flow)))

    def show_spit_time(self, seconds):
        # with the burst switched off the value is 0, but the setting must stay for later
        if self.w.btn_spit_on.isChecked() and not self.w.sl_spit_time.isSliderDown():
            self.w.sl_spit_time.setValue(int(round(seconds * 10.0)))

    def save(self, name, value, typ):
        try:
            self.prefs.putpref(name, value, typ, SECTION)
        except Exception as e:
            LOG.warning("ColdEnd tab: could not save {}: {}".format(name, e))

    def __getitem__(self, item):
        return getattr(self, item)

    def __setitem__(self, item, value):
        return setattr(self, item, value)


def get_handlers(halcomp, widgets, paths):
    return [HandlerClass(halcomp, widgets, paths)]
