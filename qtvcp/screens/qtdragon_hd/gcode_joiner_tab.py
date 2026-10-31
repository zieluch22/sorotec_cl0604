"""
G-code Joiner tab for QtDragon HD (PyQt5).

Joins several Fusion 360 NC files (one tool / operation each) into one program.
The joining itself is done by gcode_joiner.py (same file as the desktop tool),
this module is only the Qt user interface.

Added to the Utilities tab by qtdragon_hd_handler.py (init_utils).
"""

import os

from PyQt5 import QtCore, QtWidgets

import gcode_joiner as gj

NC_FILTER = "G-code (*.ngc *.nc *.tap *.gcode *.cnc);;All files (*)"
COL_N, COL_FILE, COL_TOOLS, COL_STEP, COL_VER = range(5)


class _OrderTree(QtWidgets.QTreeWidget):
    """Flat list whose rows can be reordered by dragging."""
    reordered = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRootIsDecorated(False)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.setDragDropOverwriteMode(False)
        self.setAlternatingRowColors(True)

    def dropEvent(self, event):
        super().dropEvent(event)
        self.reordered.emit()


class GcodeJoinerTab(QtWidgets.QWidget):
    """
    start_dir     : folder the file dialogs open in (INI [DISPLAY] PROGRAM_PREFIX)
    load_callback : function(path) -> bool, loads the joined program into LinuxCNC
                    (None = no 'Join & Load' button)
    status_callback: function(text, level) for QtDragon's status line (optional)
    """

    def __init__(self, start_dir=None, load_callback=None, status_callback=None, parent=None):
        super().__init__(parent)
        self.setObjectName("gcode_joiner_tab")
        self.paths = []
        self.auto_name = ""
        self.last_dir = start_dir if start_dir and os.path.isdir(start_dir) else os.path.expanduser("~")
        self.load_callback = load_callback
        self.status_callback = status_callback
        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)

        info = QtWidgets.QLabel(
            "Operation order: drag rows or use Up/Down. Files with s<N> in the name are sorted by N (s1 first). "
            "Selecting an opN file offers the other opN files from the same folder. "
            "Only the highest v<N> of a file is used.")
        info.setWordWrap(True)
        lay.addWidget(info)

        self.tree = _OrderTree()
        self.tree.setHeaderLabels(["#", "File", "Tool(s)", "Step", "Version"])
        hdr = self.tree.header()
        hdr.setSectionResizeMode(COL_FILE, QtWidgets.QHeaderView.Stretch)
        for c in (COL_N, COL_TOOLS, COL_STEP, COL_VER):
            hdr.setSectionResizeMode(c, QtWidgets.QHeaderView.ResizeToContents)
        self.tree.reordered.connect(self._sync_from_tree)
        lay.addWidget(self.tree, 1)

        bar = QtWidgets.QHBoxLayout()
        for text, slot in (("Add files…", self.add_files), ("▲ Up", lambda: self.move(-1)),
                           ("▼ Down", lambda: self.move(1)), ("Remove", self.remove),
                           ("Sort by s", self.sort_steps), ("Clear", self.clear)):
            b = QtWidgets.QPushButton(text)
            b.setMinimumHeight(40)
            b.clicked.connect(slot)
            bar.addWidget(b)
        lay.addLayout(bar)

        out = QtWidgets.QHBoxLayout()
        out.addWidget(QtWidgets.QLabel("Output:"))
        self.out_edit = QtWidgets.QLineEdit()
        self.out_edit.setMinimumHeight(36)
        out.addWidget(self.out_edit, 1)
        b = QtWidgets.QPushButton("…")
        b.setMinimumHeight(36)
        b.setFixedWidth(50)
        b.clicked.connect(self.browse_out)
        out.addWidget(b)
        lay.addLayout(out)

        act = QtWidgets.QHBoxLayout()
        act.addStretch(1)
        self.btn_save = QtWidgets.QPushButton("Join && Save")
        self.btn_save.setMinimumHeight(48)
        self.btn_save.clicked.connect(lambda: self.join(load=False))
        act.addWidget(self.btn_save)
        if self.load_callback:
            self.btn_load = QtWidgets.QPushButton("Join && Load")
            self.btn_load.setMinimumHeight(48)
            self.btn_load.clicked.connect(lambda: self.join(load=True))
            act.addWidget(self.btn_load)
        lay.addLayout(act)

    # ------------------------------------------------------------------ helpers
    def _status(self, text, level=0):
        if self.status_callback:
            try:
                self.status_callback(text, level)
                return
            except Exception:
                pass
        print("G-code Joiner:", text)

    def _ask(self, text):
        return QtWidgets.QMessageBox.question(
            self, "G-code Joiner", text,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No) == QtWidgets.QMessageBox.Yes

    def _info(self, text):
        QtWidgets.QMessageBox.information(self, "G-code Joiner", text)

    def _error(self, text):
        QtWidgets.QMessageBox.critical(self, "G-code Joiner", text)

    def _selected(self):
        it = self.tree.currentItem()
        return self.tree.indexOfTopLevelItem(it) if it else None

    def refresh(self, select=None):
        dups = gj.duplicate_steps(self.paths)
        self.tree.clear()
        for i, p in enumerate(self.paths):
            try:
                tools = ",".join(f"T{t}" for t in gj.load(p).tools) or "?"
            except Exception:
                tools = "ERR"
            k = gj.order_key(p)
            v = gj.version_of(p)[1]
            step = "-" if k is None else (f"{k} ⚠ dup" if k in dups else str(k))
            it = QtWidgets.QTreeWidgetItem([str(i + 1), os.path.basename(p), tools, step, f"v{v}" if v else "-"])
            it.setData(COL_FILE, QtCore.Qt.UserRole, p)
            it.setToolTip(COL_FILE, p)
            # rows can be dragged, but nothing can be dropped *onto* a row (keeps the list flat)
            it.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsDragEnabled)
            self.tree.addTopLevelItem(it)
        if select is not None and 0 <= select < len(self.paths):
            self.tree.setCurrentItem(self.tree.topLevelItem(select))
        # suggest op<N>_<part>_all.ngc unless the user typed their own name
        cur = self.out_edit.text().strip()
        if self.paths and (not cur or cur == self.auto_name):
            self.auto_name = gj.suggest_output_name(self.paths)
            self.out_edit.setText(self.auto_name)
        elif not self.paths and cur == self.auto_name:
            self.out_edit.clear()

    def _sync_from_tree(self):
        moved = self.tree.currentItem()
        self.paths = [self.tree.topLevelItem(i).data(COL_FILE, QtCore.Qt.UserRole)
                      for i in range(self.tree.topLevelItemCount())]
        sel = self.tree.indexOfTopLevelItem(moved) if moved else None
        self.refresh(sel)

    # ------------------------------------------------------------------ actions
    def add_files(self):
        fs, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Select G-code files", self.last_dir, NC_FILTER,
            options=QtWidgets.QFileDialog.DontUseNativeDialog)
        if not fs:
            return
        self.last_dir = os.path.dirname(fs[0])
        new = [f for f in fs if f not in self.paths]
        if not new:
            return
        # user's selection first; if it has an opN prefix, offer the other opN files too
        extra = [s for s in gj.siblings(new[0]) if s not in self.paths and s not in new]
        if extra:
            pre = gj.op_of(new[0])
            proposal, older = gj.keep_latest(self.paths + new + extra)
            proposal = gj.sort_by_order([p for p in proposal if p not in self.paths])
            if any(p not in new for p in proposal) or older:
                listing = "\n".join(
                    f"{n}. {os.path.basename(p)}" + ("" if gj.order_key(p) is not None else "   (no s, at end)")
                    for n, p in enumerate(proposal, 1))
                extra_txt = ""
                if older:
                    extra_txt += "\n\nOlder versions skipped:\n" + "\n".join("  " + os.path.basename(p) for p in older)
                d = gj.duplicate_steps(proposal)
                if d:
                    extra_txt += ("\n\n⚠ Same step number on several files (remove the ones you don't need):\n"
                                  + "\n".join(f"  s{k}: " + ", ".join(os.path.basename(p) for p in v)
                                              for k, v in sorted(d.items())))
                if self._ask(f"Found more '{pre}' file(s) in this folder.\nAdd them all in this order?\n\n"
                             f"{listing}{extra_txt}\n\nNo = keep only the file(s) you selected."):
                    new = proposal
        merged, older = gj.keep_latest(self.paths + new)
        if older:
            self._info("Older versions left out (a higher v<N> is in the list):\n\n"
                       + "\n".join(os.path.basename(p) for p in older))
        self.paths = gj.sort_by_order(merged)
        self.refresh()

    def move(self, delta):
        i = self._selected()
        if i is None:
            return
        j = i + delta
        if 0 <= j < len(self.paths):
            self.paths[i], self.paths[j] = self.paths[j], self.paths[i]
            self.refresh(j)

    def remove(self):
        i = self._selected()
        if i is not None:
            self.paths.pop(i)
            self.refresh(min(i, len(self.paths) - 1))

    def sort_steps(self):
        self.paths = gj.sort_by_order(self.paths)
        self.refresh()

    def clear(self):
        self.paths = []
        self.out_edit.clear()
        self.auto_name = ""
        self.refresh()

    def browse_out(self):
        cur = self.out_edit.text().strip()
        f, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save joined program", cur or os.path.join(self.last_dir, "op_all.ngc"),
            "G-code (*.ngc *.nc);;All files (*)", options=QtWidgets.QFileDialog.DontUseNativeDialog)
        if f:
            if not os.path.splitext(f)[1]:
                f += ".ngc"
            self.out_edit.setText(f)

    def join(self, load=False):
        if not self.paths:
            self._info("Add some files first.")
            return
        out = self.out_edit.text().strip()
        if not out:
            self.browse_out()
            out = self.out_edit.text().strip()
            if not out:
                return
        out = os.path.expanduser(out)
        if os.path.abspath(out) in map(os.path.abspath, self.paths):
            self._error("Output file is one of the input files.")
            return
        try:
            text, warns = gj.join(self.paths, os.path.splitext(os.path.basename(out))[0])
        except Exception as ex:
            self._error(str(ex))
            return
        if warns and not self._ask("Warnings:\n\n" + "\n".join(warns) + "\n\nSave anyway?"):
            return
        if os.path.exists(out) and not self._ask(f"Overwrite\n{out}?"):
            return
        try:
            with open(out, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as ex:
            self._error(f"Could not write {out}:\n{ex}")
            return
        self._status(f"G-code Joiner: saved {out} ({len(self.paths)} operations)")
        if load:
            if self.load_callback(out) is False:
                return
        else:
            order = "\n".join(f"{n}. {os.path.basename(p)}" for n, p in enumerate(self.paths, 1))
            self._info(f"Saved {out}\n\n{order}")


if __name__ == "__main__":
    # stand-alone test outside LinuxCNC:  python3 gcode_joiner_tab.py
    import sys
    app = QtWidgets.QApplication(sys.argv)
    w = GcodeJoinerTab(start_dir=os.path.expanduser("~/linuxcnc/nc_files"),
                       load_callback=lambda p: print("LOAD", p) or True)
    w.resize(900, 600)
    w.setWindowTitle("G-code Joiner")
    w.show()
    sys.exit(app.exec_())
