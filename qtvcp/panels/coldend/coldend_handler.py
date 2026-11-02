#!/usr/bin/env python3
# Handler for the embedded QtDragon "ColdEnd" tab (qtvcp/panels/coldend/coldend.ui).
# Remembers the screen settings (rates, spit time, check boxes) in the QtDragon
# preference file, section [COLDEND]. All HAL wiring is in hallib/coldend_postgui.hal.

import os

from PyQt5 import QtCore, QtGui
from qtvcp import logger

LOG = logger.getLogger(__name__)
SECTION = "COLDEND"

SPINS = ("ds_mist", "ds_fast", "ds_spit_time")
CHECKS = ("chk_spit", "chk_use_screen")

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
        try:
            self.prefs = self.w.MAIN.PREFS_
        except AttributeError:
            self.prefs = None
        if not self.prefs:
            LOG.warning("ColdEnd tab: no preference file - screen settings will not be remembered")
            return
        for name in SPINS:
            wid = getattr(self.w, name)
            wid.setValue(self.prefs.getpref(name, wid.value(), float, SECTION))
            wid.valueChanged.connect(lambda v, n=name: self.save(n, float(v), float))
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
