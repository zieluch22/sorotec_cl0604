#!/usr/bin/env python3
"""
G-code Joiner - combine several Fusion 360 NC files (one tool / operation each)
into a single program that runs all operations in order.

Order of operations:
  * If a file name contains an  s<N>  token (op1_t5_s4.ngc, s2_t23_dat.ngc,
    op4_s1_t1.ngc -> step N), files are sorted by N automatically, lowest first.
  * Only the highest v<N> of the same file is used (op1_t1_s1_v4 beats op1_t1_s1).
  * Otherwise they keep the order you add them in; reorder with the
    Up / Down buttons or by dragging rows in the list.

GUI:  python3 gcode_joiner.py
CLI:  python3 gcode_joiner.py --cli [-o out.ngc] file1.ngc file2.ngc ...
      (files sorted by _s<N> when present, else in the given order)
"""

import os
import re
import sys

# _s<N> = operation order (lower N runs first): op1_t5_s4.ngc, op1_t5_s4_v2.ngc, op1_t5_s4v2.ngc
# s<N> as its own token anywhere in the name: s2_t23_dat, op4_s1_t1, op1_t5_s4v2, op2+t4_s4
ORDER_RE = re.compile(r"(?<![^_\-\s+.])s(\d+)(?!\d)", re.IGNORECASE)
# v<N> = version: op1_t5_s4_v2.ngc, op1_t5_s4v2.ngc, op1_t5_s4-v3.ngc  (highest wins)
VERSION_RE = re.compile(r"(?<=[_\-\d])[_\-]?v(\d+)(?!\d)", re.IGNORECASE)
TOOL_CHANGE_RE = re.compile(r"^\s*T(\d+)\s*M0?6\b", re.IGNORECASE)
TOOL_COMMENT_RE = re.compile(r"^\s*\(T\d+\b.*\)\s*$", re.IGNORECASE)
END_RE = re.compile(r"^\s*(N\d+\s*)?M0?(30|2)\s*$", re.IGNORECASE)
WCS_RE = re.compile(r"\bG5[4-9](\.\d)?\b", re.IGNORECASE)
# modal "setup" lines that make up the Fusion header (before the first operation)
LINE_NO_RE = re.compile(r"^\s*N\d+\s*", re.IGNORECASE)
SETUP_RE = re.compile(r"^\s*((G\d+(\.\d+)?)\s*)+$", re.IGNORECASE)


def order_key(path):
    """Return the _s<N> number from the file name, or None."""
    m = ORDER_RE.search(os.path.splitext(os.path.basename(path))[0])
    return int(m.group(1)) if m else None


NC_EXT = (".ngc", ".nc", ".tap", ".gcode", ".cnc")
OP_RE = re.compile(r"^(op\d+)(?!\d)", re.IGNORECASE)


OP_DIR_RE = re.compile(r"^op\d+$", re.IGNORECASE)
JOINED_MARK = "(JOINED BY GCODE_JOINER)"
# folder names that say nothing about the part
GENERIC_DIRS = {"nc programs", "fusion 360", "documents", "desktop", "downloads", "gcode", "g-code", "nc", ""}


def op_prefix(path):
    """'op2' for op2_t5_s4.ngc, else None (file name only)."""
    m = OP_RE.match(os.path.basename(path))
    return m.group(1).lower() if m else None


def folder_op(path):
    """'op1' when the file sits in a folder named op1, else None."""
    d = os.path.basename(os.path.dirname(os.path.abspath(path)))
    return d.lower() if OP_DIR_RE.match(d) else None


def op_of(path):
    """Operation (setup) of a file: from the file name, else from its folder name."""
    return op_prefix(path) or folder_op(path)


def part_name(path):
    """Part name from the folder, or the folder above if the folder is just 'opN'. None if unclear."""
    d = os.path.dirname(os.path.abspath(path))
    for _ in range(2):  # the folder and one above
        name = os.path.basename(d)
        if OP_DIR_RE.match(name):
            d = os.path.dirname(d)
            continue
        if name.strip().lower() in GENERIC_DIRS:
            return None
        clean = re.sub(r"[\s_]+", "_", name).strip("_")
        return clean or None
    return None


def is_joined_output(path):
    """True for files written by this program (marker line in the header)."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return JOINED_MARK in f.read(4096)
    except OSError:
        return False


def siblings(path):
    """All NC files in the same folder belonging to the same opN (not joined outputs)."""
    pre = op_of(path)
    if not pre:
        return []
    d = os.path.dirname(path)
    return [os.path.join(d, f) for f in sorted(os.listdir(d))
            if f.lower().endswith(NC_EXT) and op_of(os.path.join(d, f)) == pre
            and not is_joined_output(os.path.join(d, f))]


def suggest_output_name(paths):
    """op<N>_<part>_all.ngc; parts that can't be worked out are left out (op1_all.ngc)."""
    first = paths[0]
    pre = op_of(first)
    part = part_name(first)
    name = "_".join(x for x in (pre, part) if x) or "op"
    name += "_all.ngc"
    return os.path.join(os.path.dirname(first), name)


def version_of(path):
    """(base_name_without_version, version_number). No v<N> -> version 0."""
    stem = os.path.splitext(os.path.basename(path))[0]
    m = None
    for m in VERSION_RE.finditer(stem):
        pass  # take the last v<N> in the name
    if not m:
        return stem.lower(), 0
    base = (stem[:m.start()].rstrip("_-") + stem[m.end():]).lower()
    return base, int(m.group(1))


def keep_latest(paths):
    """Keep only the highest v<N> of files that differ just by version.
    Returns (kept, dropped); kept preserves the input order."""
    best = {}
    for p in paths:
        key = (os.path.dirname(os.path.abspath(p)), version_of(p)[0])
        if key not in best or version_of(p)[1] > version_of(best[key])[1]:
            best[key] = p
    winners = set(best.values())
    return [p for p in paths if p in winners], [p for p in paths if p not in winners]


def duplicate_steps(paths):
    """{N: [files]} for s<N> numbers used by more than one file."""
    seen = {}
    for p in paths:
        k = order_key(p)
        if k is not None:
            seen.setdefault(k, []).append(p)
    return {k: v for k, v in seen.items() if len(v) > 1}


def sort_by_order(paths):
    """Sort ascending by _s<N> (s1 first). Files without a number keep their order, after numbered ones."""
    numbered = [p for p in paths if order_key(p) is not None]
    plain = [p for p in paths if order_key(p) is None]
    numbered.sort(key=order_key)
    return numbered + plain


_CACHE = {}


def load(path):
    """Parse a file once; re-parse only if it changed on disk."""
    st = os.stat(path)
    key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    f = _CACHE.get(key)
    if f is None:
        f = _CACHE[key] = NcFile(path)
    return f


class NcFile:
    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            # drop N line numbers (N10, N15 ...) - optional in G-code, and duplicates after joining
            lines = [LINE_NO_RE.sub("", l.rstrip("\r\n")) for l in f]
        self.header, self.body = self._split(lines)
        self.tool_comments = [l.strip() for l in self.header if TOOL_COMMENT_RE.match(l)]
        self.setup = [l.strip() for l in self.header if SETUP_RE.match(l)]
        self.units = self._units()
        self.tools = [int(m.group(1)) for m in (TOOL_CHANGE_RE.match(l) for l in self.body) if m]
        self.wcs = sorted({m.group(0).upper() for l in self.body for m in WCS_RE.finditer(l)})

    @staticmethod
    def _split(lines):
        """Header = leading %, comments and pure G-code setup lines. Body = the rest,
        with program end (% / M30 / M2) removed."""
        i = 0
        while i < len(lines):
            s = lines[i].strip()
            if s == "" or s == "%" or (s.startswith("(") and s.endswith(")")) or SETUP_RE.match(s):
                i += 1
            else:
                break
        header, body = lines[:i], lines[i:]
        body = [l for l in body if l.strip() != "%" and not END_RE.match(l)]
        while body and body[-1].strip() == "":
            body.pop()
        return header, body

    def _units(self):
        u = set()
        for l in self.setup:
            if re.search(r"\bG21\b", l, re.I):
                u.add("mm")
            if re.search(r"\bG20\b", l, re.I):
                u.add("inch")
        return "/".join(sorted(u)) or "?"


def check(files):
    """Return a list of warning strings."""
    warns = []
    units = {f.units for f in files}
    if len(units) > 1:
        warns.append("UNITS DIFFER between files: " + ", ".join(f"{f.name}={f.units}" for f in files))
    wcs = {tuple(f.wcs) for f in files}
    if len(wcs) > 1:
        warns.append("WORK OFFSETS differ: " + ", ".join(f"{f.name}={'/'.join(f.wcs) or '-'}" for f in files))
    for k, ps in sorted(duplicate_steps([f.path for f in files]).items()):
        warns.append(f"STEP s{k} is used by {len(ps)} files: " + ", ".join(os.path.basename(p) for p in ps))
    for f in files:
        if not f.tools:
            warns.append(f"{f.name}: no tool change (T.. M6) found")
    return warns


def ends_with_code(body, code, tail=6):
    """True if `code` (e.g. M9) appears in the last `tail` G-code lines of body,
    before any later move that could re-enable it (M3/M4/M7/M8)."""
    word = re.compile(r"\b" + code[0] + r"0*" + code[1:] + r"\b", re.IGNORECASE)
    undo = re.compile(r"\bM0*(3|4)\b" if code.upper() == "M5" else r"\bM0*(7|8)\b", re.IGNORECASE)
    n = 0
    for l in reversed(body):
        s = re.sub(r"\(.*?\)|;.*", "", l).strip()
        if not s:
            continue
        if undo.search(s):
            return False
        if word.search(s):
            return True
        n += 1
        if n >= tail:
            break
    return False


def join(paths, program_name="COMBINED"):
    files = [load(p) for p in paths]
    if not files:
        raise ValueError("No files selected")
    # 1) original header of the first file, untouched (%, program name, MACHINE, tool, G90.., G21)
    out = list(files[0].header)
    while out and out[-1].strip() == "":
        out.pop()
    # 2) joiner info as comments
    out.append(JOINED_MARK)
    out.append(f"({program_name.upper()})")
    out.append("(OPERATION ORDER:)")
    for n, f in enumerate(files, 1):
        out.append(f"(  {n}. {f.name} - T{','.join(map(str, f.tools)) or '?'})")
    first_tools = set(c.upper() for c in files[0].tool_comments)
    extra = []
    for f in files[1:]:
        for c in f.tool_comments:
            if c.upper() not in first_tools and c not in extra:
                extra.append(c)
    if extra:
        out.append("(MORE TOOLS:)")
        out.extend(extra)

    # 3) operations
    for n, f in enumerate(files, 1):
        out.append("")
        out.append(f"(===== OPERATION {n}: {f.name} =====)")
        if n > 1:
            # spindle + coolant OFF before the next tool change - only if the
            # previous file's tail doesn't already do it (Fusion ends with M9)
            for code in ("M5", "M9"):
                if not ends_with_code(files[n - 2].body, code):
                    out.append(code)
            # restore modal state - previous file may have left G18/G19 or G91 active
            out.extend(f.setup or files[0].setup)
        out.extend(f.body)

    # 4) program end like the original Fusion files
    out += ["M30", "%"]
    return "\n".join(out) + "\n", check(files)


# ----------------------------------------------------------------------------- CLI
def cli(argv):
    import argparse
    ap = argparse.ArgumentParser(description="Join G-code files into one program")
    ap.add_argument("files", nargs="+")
    ap.add_argument("-o", "--output", help="default: op<N>_<folder>_all.ngc")
    ap.add_argument("--keep-order", action="store_true", help="ignore _s<N> in names")
    a = ap.parse_args(argv)
    paths, dropped = keep_latest(a.files)
    for p in dropped:
        print("skipped older version:", os.path.basename(p))
    paths = paths if a.keep_order else sort_by_order(paths)
    a.output = a.output or suggest_output_name(paths)
    name = os.path.splitext(os.path.basename(a.output))[0]
    text, warns = join(paths, name)
    with open(a.output, "w", encoding="utf-8") as f:
        f.write(text)
    for n, p in enumerate(paths, 1):
        print(f"{n}. {os.path.basename(p)}")
    for w in warns:
        print("WARNING:", w, file=sys.stderr)
    print("Written:", a.output)


# ----------------------------------------------------------------------------- GUI
def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("G-code Joiner")
    root.geometry("760x520")
    paths = []
    auto_name = [""]
    last_dir = [os.path.expanduser("~/Documents/Fusion 360/NC Programs")]

    # --- list
    frame = ttk.Frame(root, padding=10)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Operation order (drag rows or use Up/Down). Files with s<N> in the name are sorted by N (s1 first).\n"
                          "Selecting an opN_ file offers the other opN files from the same folder.").pack(anchor="w")
    cols = ("n", "file", "tools", "s", "v")
    tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
    for c, t, w in (("n", "#", 40), ("file", "File", 400), ("tools", "Tool(s)", 80), ("s", "_s order", 70),
                    ("v", "Version", 60)):
        tree.heading(c, text=t)
        tree.column(c, width=w, anchor="w" if c == "file" else "center")
    tree.pack(fill="both", expand=True, pady=6)

    def row_values(i, p):
        try:
            tools = ",".join(f"T{t}" for t in load(p).tools) or "?"
        except Exception:
            tools = "ERR"
        k = order_key(p)
        v = version_of(p)[1]
        sk = "-" if k is None else (f"{k} ⚠ dup" if k in dups[0] else k)
        return (i + 1, os.path.basename(p), tools, sk, f"v{v}" if v else "-")

    dups = [{}]

    def refresh(select=None):
        dups[0] = duplicate_steps(paths)
        # update rows in place (no delete/re-create -> no flicker)
        rows = tree.get_children()
        for i, p in enumerate(paths):
            vals = row_values(i, p)
            if i < len(rows):
                if tuple(str(x) for x in tree.item(rows[i], "values")) != tuple(str(x) for x in vals):
                    tree.item(rows[i], values=vals)
            else:
                tree.insert("", "end", iid=str(i), values=vals)
        if len(rows) > len(paths):
            tree.delete(*rows[len(paths):])
        if select is not None and 0 <= select < len(paths):
            tree.selection_set(str(select))
            tree.see(str(select))
        # suggest output name op<N>_<part>_all.ngc unless the user typed their own
        cur = out_var.get().strip()
        if paths and (not cur or cur == auto_name[0]):
            auto_name[0] = suggest_output_name(paths)
            out_var.set(auto_name[0])
        elif not paths and cur == auto_name[0]:
            out_var.set("")

    def sel():
        s = tree.selection()
        return int(s[0]) if s else None

    def add_files():
        fs = filedialog.askopenfilenames(
            initialdir=last_dir[0], title="Select G-code files",
            filetypes=[("G-code", "*.ngc *.nc *.tap *.gcode *.cnc"), ("All files", "*")])
        if not fs:
            return
        last_dir[0] = os.path.dirname(fs[0])
        new = [f for f in fs if f not in paths]
        if not new:
            return
        # user's selection first; if it has an opN prefix, offer the other opN files too
        extra = [s for s in siblings(new[0]) if s not in paths and s not in new]
        if extra:
            pre = op_of(new[0])
            proposal, older = keep_latest(paths + new + extra)
            proposal = sort_by_order([p for p in proposal if p not in paths])
            if any(p not in new for p in proposal) or older:
                listing = "\n".join(
                    f"{n}. {os.path.basename(p)}" + ("" if order_key(p) is not None else "   (no _s, at end)")
                    for n, p in enumerate(proposal, 1))
                skipped = ("\n\nOlder versions skipped:\n" + "\n".join("  " + os.path.basename(p) for p in older)
                           if older else "")
                d = duplicate_steps(proposal)
                if d:
                    skipped += ("\n\n⚠ Same step number on several files (remove the ones you don't need):\n"
                                + "\n".join(f"  s{k}: " + ", ".join(os.path.basename(p) for p in v)
                                             for k, v in sorted(d.items())))
                if messagebox.askyesno(
                        "G-code Joiner",
                        f"Found more '{pre}' file(s) in this folder.\n"
                        f"Add them all in this order?\n\n{listing}{skipped}\n\n"
                        f"No = keep only the file(s) you selected."):
                    new = proposal
        # only the highest v<N> of the same file stays in the list
        merged, older = keep_latest(paths + new)
        if older:
            messagebox.showinfo("G-code Joiner", "Older versions left out (a higher v<N> is in the list):\n\n"
                                + "\n".join(os.path.basename(p) for p in older))
        # _s<N> ascending: s1 first; files without _s stay in order at the end (move them by hand)
        paths[:] = sort_by_order(merged)
        refresh()

    def move(delta):
        i = sel()
        if i is None:
            return
        j = i + delta
        if 0 <= j < len(paths):
            paths[i], paths[j] = paths[j], paths[i]
            refresh(j)

    def remove():
        i = sel()
        if i is not None:
            paths.pop(i)
            refresh(min(i, len(paths) - 1))

    def clear():
        paths.clear()
        out_var.set("")
        auto_name[0] = ""
        refresh()

    def sort_s():
        paths[:] = sort_by_order(paths)
        refresh()

    # drag & drop reordering - row follows the mouse, list is rebuilt once on release
    drag = {"i": None, "moved": False}

    def on_press(e):
        row = tree.identify_row(e.y)
        drag.update(i=tree.index(row) if row else None, moved=False)

    def on_motion(e):
        if drag["i"] is None:
            return
        row = tree.identify_row(e.y)
        if not row:
            return
        j = tree.index(row)
        if j != drag["i"]:
            item = tree.get_children()[drag["i"]]
            tree.move(item, "", j)          # cheap visual move, no re-parsing
            paths.insert(j, paths.pop(drag["i"]))
            drag.update(i=j, moved=True)

    def on_release(e):
        if drag["moved"]:
            # re-number iids/rows to match the new order
            j = drag["i"]
            tree.delete(*tree.get_children())
            refresh(j)
        drag.update(i=None, moved=False)

    tree.bind("<ButtonPress-1>", on_press, add="+")
    tree.bind("<B1-Motion>", on_motion)
    tree.bind("<ButtonRelease-1>", on_release, add="+")

    # --- buttons
    bar = ttk.Frame(frame)
    bar.pack(fill="x")
    for t, cmd in (("Add files…", add_files), ("▲ Up", lambda: move(-1)), ("▼ Down", lambda: move(1)),
                   ("Remove", remove), ("Sort by _s", sort_s), ("Clear", clear)):
        ttk.Button(bar, text=t, command=cmd).pack(side="left", padx=2)

    # --- options / output
    opt = ttk.Frame(frame)
    opt.pack(fill="x", pady=(10, 0))
    row = ttk.Frame(opt)
    row.pack(fill="x", pady=6)
    ttk.Label(row, text="Output:").pack(side="left")
    out_var = tk.StringVar()
    ttk.Entry(row, textvariable=out_var).pack(side="left", fill="x", expand=True, padx=4)

    def browse_out():
        f = filedialog.asksaveasfilename(
            initialdir=os.path.dirname(out_var.get()) or last_dir[0],
            initialfile=os.path.basename(out_var.get()) or "combined.ngc",
            defaultextension=".ngc", filetypes=[("G-code", "*.ngc *.nc"), ("All files", "*")])
        if f:
            out_var.set(f)
    ttk.Button(row, text="…", width=3, command=browse_out).pack(side="left")

    def save():
        if not paths:
            messagebox.showwarning("G-code Joiner", "Add some files first.")
            return
        out = out_var.get().strip()
        if not out:
            browse_out()
            out = out_var.get().strip()
            if not out:
                return
        if os.path.abspath(out) in map(os.path.abspath, paths):
            messagebox.showerror("G-code Joiner", "Output file is one of the input files.")
            return
        try:
            text, warns = join(paths, os.path.splitext(os.path.basename(out))[0])
        except Exception as ex:
            messagebox.showerror("G-code Joiner", str(ex))
            return
        if warns and not messagebox.askyesno("G-code Joiner", "Warnings:\n\n" + "\n".join(warns) + "\n\nSave anyway?"):
            return
        if os.path.exists(out) and not messagebox.askyesno("G-code Joiner", f"Overwrite\n{out}?"):
            return
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        order = "\n".join(f"{n}. {os.path.basename(p)}" for n, p in enumerate(paths, 1))
        messagebox.showinfo("G-code Joiner", f"Saved {out}\n\n{order}")

    ttk.Button(opt, text="Join && Save", command=save).pack(anchor="e")

    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        cli(sys.argv[2:])
    else:
        gui()
