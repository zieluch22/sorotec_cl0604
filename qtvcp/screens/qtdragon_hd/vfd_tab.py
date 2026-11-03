#!/usr/bin/env python3
# "VFD" tab under Utilities: extra values from the Simphoenix E500 over Modbus.
# Display and warning only, the spindle safety logic does not use any of this.
# Registers and read rates: hallib/vfd_e500_mb2hal.ini. Scaling: INI [VFD].
# Faults are appended to vfd_fault.log in the config folder.

import os
import time

from PyQt5 import QtCore, QtWidgets

FAULT_LOG = "vfd_fault.log"
# the fault history is read every 5 s, so wait for a fresh read before logging it
FAULT_LOG_DELAY_MS = 6000
TEMP_WARN_HOLD_S = 5.0
TEMP_WARN_HYST = 5.0


class VfdTab(QtWidgets.QWidget):
    def __init__(self, get_pin, gains, temp_warn, log_dir, status_callback=None, parent=None):
        super().__init__(parent)
        self.get_pin = get_pin
        self.gains = gains
        self.temp_warn = temp_warn
        self.log_path = os.path.join(log_dir, FAULT_LOG)
        self.status = status_callback or (lambda text: None)
        self.last_fault = 0
        self.temp_high_since = None
        self.temp_warned = False
        self.values = {}

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.box("Live values", (
            ("temp", "VFD module temperature"),
            ("dc", "DC bus voltage"),
            ("ac", "Input AC voltage"))))
        layout.addWidget(self.box("Last 4 faults (d-23 to d-26)", (
            ("flt1", "First record"),
            ("flt2", "Second record"),
            ("flt3", "Third record"),
            ("flt4", "Fourth record"))))
        layout.addWidget(self.box("Conditions at the most recent fault", (
            ("flt_freq", "Output frequency"),
            ("flt_amps", "Output current"),
            ("flt_volts", "Output voltage"),
            ("flt_dc", "DC voltage"),
            ("flt_temp", "VFD module temperature"))))
        note = QtWidgets.QLabel("Faults are logged in {}".format(self.log_path))
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_values)
        self.timer.start(500)
        self.update_values()

    def box(self, title, rows):
        group = QtWidgets.QGroupBox(title)
        grid = QtWidgets.QGridLayout(group)
        for row, (key, text) in enumerate(rows):
            value = QtWidgets.QLabel("--")
            self.values[key] = value
            grid.addWidget(QtWidgets.QLabel(text), row, 0)
            grid.addWidget(value, row, 1)
        grid.setColumnStretch(1, 1)
        return group

    def temp(self):
        return self.get_pin("vfd-temp") * self.gains["temp"]

    def fault_text(self, pin):
        code = int(self.get_pin(pin))
        return "none" if code == 0 else "Fu.{:02d}".format(code)

    def fault_rows(self):
        return (
            ("flt1", self.fault_text("vfd-fault-1")),
            ("flt2", self.fault_text("vfd-fault-2")),
            ("flt3", self.fault_text("vfd-fault-3")),
            ("flt4", self.fault_text("vfd-fault-4")),
            ("flt_freq", "{:.1f} Hz".format(self.get_pin("vfd-fault-freq") * 0.1)),
            ("flt_amps", "{:.1f} A".format(self.get_pin("vfd-fault-amps") * 0.1)),
            ("flt_volts", "{:.0f} V".format(self.get_pin("vfd-fault-volts"))),
            ("flt_dc", "{:.0f} V".format(self.get_pin("vfd-fault-dc") * self.gains["dc"])),
            ("flt_temp", "{:.1f} C".format(self.get_pin("vfd-fault-temp") * self.gains["temp"])),
        )

    def update_values(self):
        comm_ok = self.get_pin("vfd-comm-ok")
        if comm_ok:
            self.values["temp"].setText("{:.1f} C".format(self.temp()))
            self.values["dc"].setText("{:.0f} V".format(self.get_pin("vfd-dc-volts") * self.gains["dc"]))
            self.values["ac"].setText("{:.0f} V".format(self.get_pin("vfd-ac-volts") * self.gains["ac"]))
            for key, text in self.fault_rows():
                self.values[key].setText(text)
            self.check_temp()
        else:
            # stale values must not look live; a lost link never raises the warning
            for key in ("temp", "dc", "ac"):
                self.values[key].setText("--")
            self.temp_high_since = None
        self.check_fault()

    def check_temp(self):
        if self.temp_warn <= 0:
            return
        temp = self.temp()
        if temp >= self.temp_warn:
            now = time.monotonic()
            if self.temp_high_since is None:
                self.temp_high_since = now
            if not self.temp_warned and now - self.temp_high_since >= TEMP_WARN_HOLD_S:
                self.temp_warned = True
                self.values["temp"].setStyleSheet("background-color: rgb(202, 0, 0);")
                self.status("WARNING: VFD module temperature {:.1f} C (limit {:.0f} C)".format(temp, self.temp_warn))
        else:
            self.temp_high_since = None
            if self.temp_warned and temp < self.temp_warn - TEMP_WARN_HYST:
                self.temp_warned = False
                self.values["temp"].setStyleSheet("")

    def check_fault(self):
        code = int(self.get_pin("spindle-fault"))
        if code != 0 and self.last_fault == 0:
            QtCore.QTimer.singleShot(FAULT_LOG_DELAY_MS, lambda c=code: self.log_fault(c))
        self.last_fault = code

    def log_fault(self, code):
        rows = ", ".join("{} {}".format(key, text) for key, text in self.fault_rows())
        line = "{} active Fu.{:02d}: {}\n".format(time.strftime("%Y-%m-%d %H:%M:%S"), code, rows)
        try:
            with open(self.log_path, "a") as f:
                f.write(line)
        except OSError as e:
            self.status("VFD fault log not written: {}".format(e))


class LoadMonitor(QtCore.QObject):
    """LOAD bar under POWER: current as % of [VFD]OVERLOAD_AMPS, with a warning above 100 %.
    The text shows the real value, the bar stops at 100 %. Warning only: the feed hold is in HAL."""
    HOLD_S = 2.0        # ignores the short current peak of a speed change
    CLEAR_PERCENT = 95
    RED = "QProgressBar::chunk { background-color: rgb(202, 0, 0); }"

    def __init__(self, bar, get_amps, limit, status_callback, parent=None):
        super().__init__(parent)
        self.bar = bar
        self.get_amps = get_amps
        self.limit = limit
        self.status = status_callback
        self.high_since = None
        self.warned = False
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(250)
        self.update()

    def update(self):
        percent = max(0, int(self.get_amps() / self.limit * 100))
        self.bar.setValue(min(100, percent))
        self.bar.setFormat("LOAD {}%".format(percent))
        if percent > 100:
            now = time.monotonic()
            if self.high_since is None:
                self.high_since = now
            if not self.warned and now - self.high_since >= self.HOLD_S:
                self.warned = True
                self.bar.setStyleSheet(self.RED)
                self.status("WARNING: spindle load {}% ({:.1f} A, limit {:.1f} A)".format(
                    percent, self.get_amps(), self.limit))
        else:
            self.high_since = None
            if self.warned and percent < self.CLEAR_PERCENT:
                self.warned = False
                self.bar.setStyleSheet("")
