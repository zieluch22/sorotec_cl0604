#!/usr/bin/env python3
# Userspace HAL component "coldend": the logic between LinuxCNC, the QtDragon
# ColdEnd tab and the ColdEnd mist controller (Modbus via mb2hal "coldend-mb").
# Loaded by hallib/coldend.hal. Settings: INI section [COLDEND].
#
# What it does:
#   - M7 (mist) / M8 (air blast) from G-code or the screen buttons
#     (optional, off for now: only while the spindle turns - INI SPINDLE_GATE)
#   - the board switches keep working (mist / fast / air) and always win
#   - fast (prime) mode from the board switch or the screen "Prime" button
#   - pump rates in ml/h, from the board knobs (default) or from the screen.
#     Knobs work like the original ColdEND firmware:
#       mist knob = mist flow, logarithmic 1..1000 ml/h (off below 1.1 ml/h)
#       spit knob = spit burst time 0..8 s (no burst below 1 s)
#     spit burst and fast/prime run at a fixed rate (original: 1562.5 ml/h)
#   - Modbus link supervision (link-ok, link-lost message)
#
# The heartbeat bit (coldend-mb.cmd.00) is NOT driven from here but directly by
# machine-is-enabled in coldend.hal: E-stop/machine off always stops the pump,
# even if this script hangs.

import math
import os
import subprocess
import sys
import time

import hal

# ---------------- settings from INI [COLDEND] ----------------
DEFAULTS = {
    "MIST_MLH_MAX": 1000.0,   # mist knob fully right [ml/h] (original: 1000, log curve from 1)
    "MIST_OFF_BELOW": 1.1,    # mist flow below this = pump off (original: 1.1 ml/h)
    "FAST_MLH": 1562.5,       # spit burst + fast/prime rate [ml/h] (original: 1562.5)
    "SPIT_TIME_MAX": 8.0,     # spit knob fully right [s] (original: 8 s)
    "SPIT_MIN": 1.0,          # spit time below this = no burst [s] (original: 1 s)
    "MLH_LIMIT": 3000.0,      # absolute max for any rate, also screen values [ml/h]
    "PUMP_REVERSE": 0,        # 1 = reverse pump direction
    "LINK_TIMEOUT": 1.5,      # s without Modbus errors needed for "link OK"
    "FW_VERSION": 3,          # expected firmware version (register 8456; 3 = ml/h)
    "DEVICE": "/dev/coldend", # USB serial port (udev symlink)
    "RECONNECT_HAL": "hallib/coldend.hal",  # file the reconnect script takes the coldend-mb lines from
    "AUTO_RECONNECT": 1,      # 1 = reload mb2hal by itself after a USB drop-out
    "SPINDLE_GATE": 0,        # 1 = M7/M8 only while the spindle turns (not used yet)
    "BOOT_GRACE": 6.0,        # s after (re)opening the port: the Arduino restarts when the
                              # port is opened - do not judge the link during its boot
    "LINK_LOG": "/tmp/coldend_link.log",  # link changes with the reason ("" = no log)
}


def read_ini():
    cfg = dict(DEFAULTS)
    path = os.environ.get("INI_FILE_NAME") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not path:
        return cfg
    try:
        import linuxcnc
        ini = linuxcnc.ini(path)
        for key, default in DEFAULTS.items():
            val = ini.find("COLDEND", key)
            if val is None:
                continue
            if isinstance(default, str):
                cfg[key] = val.strip()
            elif isinstance(default, int):
                cfg[key] = int(float(val))
            else:
                cfg[key] = float(val)
    except Exception as e:
        print("coldend: INI read problem, using defaults: %s" % e, file=sys.stderr)
    return cfg


cfg = read_ini()

# ---------------- pins ----------------
c = hal.component("coldend")
B, F, U, S = hal.HAL_BIT, hal.HAL_FLOAT, hal.HAL_U32, hal.HAL_S32
IN, OUT = hal.HAL_IN, hal.HAL_OUT

for name, typ in (
        # machine
        ("machine-on", B), ("mist-request", B), ("air-request", B), ("spindle-turning", B),
        # from the ColdEnd (mb2hal)
        ("fw-active", B), ("sw-mist", B), ("sw-fast", B), ("sw-air", B),
        ("knob-mist-raw", F), ("knob-spit-raw", F), ("spit-left-ms", F), ("fw-version", F),
        ("errors-cmd", U), ("errors-status", U),
        # from the screen tab (all default to the safe/normal behaviour when not connected)
        ("scr-fast", B),                 # "Prime" button (hold)
        ("use-screen", B),               # 1 = rates from the screen, knobs ignored
        ("run-without-spindle", B),      # 1 = M7/M8 also when the spindle is stopped (only with SPINDLE_GATE = 1)
        ("no-spit", B),                  # 1 = no spit burst
        ("reconnect", B),                # rising edge = reload the Modbus driver now
        ("scr-mist-mlh", F), ("scr-fast-mlh", F), ("scr-spit-time", F)):
    c.newpin(name, typ, IN)

for name, typ in (
        # to the ColdEnd (mb2hal)
        ("cmd-led", B), ("cmd-coolant", B), ("cmd-fast", B), ("cmd-spit", B),
        ("cmd-air", B), ("cmd-dir", B),
        ("reg-mist-rate", F), ("reg-fast-rate", F), ("reg-spit-rate", F),
        ("reg-spit-time", F), ("reg-microstep", F),   # reg-microstep: reserved register, always 16
        # for the screen
        ("mist-on", B), ("air-on", B), ("fast-on", B), ("link-ok", B), ("link-lost-msg", B),
        ("mist-mlh", F), ("fast-mlh", F), ("spit-time", F),
        ("knob-mist-pct", F), ("knob-spit-pct", F), ("spit-left-s", F), ("errors", S),
        ("reconnecting", B), ("reconnect-count", S)):
    c.newpin(name, typ, OUT)

c.ready()


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


class Knob:
    """Raw 0..1023 with a small hysteresis so the value does not flicker."""

    def __init__(self):
        self.value = None

    def update(self, raw):
        raw = clamp(raw, 0.0, 1023.0)
        if self.value is None or abs(raw - self.value) >= 3 or raw in (0.0, 1023.0):
            self.value = raw
        return self.value / 1023.0


def knob_mist_mlh(raw):
    """Original ColdEND curve: flow = 1000 ^ ((1000 - adc) / 1000), adc = 1023 - raw
    (the firmware reports the knob inverted). 1..1000 ml/h, off below 1.1 ml/h,
    0.1 ml/h steps below 10, whole ml/h above."""
    x = clamp((raw - 23.0) / 1000.0, 0.0, 1.0)
    flow = math.exp(math.log(cfg["MIST_MLH_MAX"]) * x)
    if flow < cfg["MIST_OFF_BELOW"]:
        return 0.0
    return round(flow, 1) if flow < 10.0 else float(int(flow + 1e-6))


def knob_spit_s(raw):
    """Original ColdEND: spit time = map(adc, 0, 1023, 8000, 0) ms, no burst up to 1 s."""
    t = clamp(raw, 0.0, 1023.0) / 1023.0 * cfg["SPIT_TIME_MAX"]
    return round(t, 1) if t > cfg["SPIT_MIN"] else 0.0


def reg_rate(mlh, minimum):
    # firmware unit 0.1 ml/h (0 = pump off); max 50000 = 5000 ml/h
    return float(clamp(int(round(mlh * 10.0)), minimum, 50000))


knob_mist, knob_spit = Knob(), Knob()
last_err = (None, None)
last_err_time = time.monotonic()
version_seen = False
machine_on_since = None
LIMIT = cfg["MLH_LIMIT"]
lost_since = None
last_try = -1e9
reconnect_proc = None
reconnect_btn_last = False
reconnects = 0
RECONNECT_SH = os.path.join("hallib", "coldend_reconnect.sh")
driver_stopped = False
grace_until = time.monotonic() + cfg["BOOT_GRACE"]   # LinuxCNC start = port opened = Arduino boots
link_state = None
fw_seen_time = None


def link_log(text):
    if not cfg["LINK_LOG"]:
        return
    try:
        with open(cfg["LINK_LOG"], "a") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except OSError:
        pass


link_log("coldend logic started (expects firmware %d, device %s)" % (int(cfg["FW_VERSION"]), cfg["DEVICE"]))


def start_reconnect():
    global reconnect_proc, last_try, reconnects, grace_until, version_seen
    version_seen = False                               # the new connection must prove itself
    last_try = time.monotonic()
    grace_until = last_try + 3.0 + cfg["BOOT_GRACE"]   # reload takes ~1-3 s, then the Arduino boots
    reconnects += 1
    link_log("reconnect #%d started" % reconnects)
    try:
        reconnect_proc = subprocess.Popen(["bash", RECONNECT_SH, cfg["DEVICE"], cfg["RECONNECT_HAL"]])
    except Exception as e:
        print("coldend: reconnect failed to start: %s" % e, file=sys.stderr)
        reconnect_proc = None

try:
    while True:
        now = time.monotonic()
        machine_on = c["machine-on"]

        # ---- link supervision ----
        errs = (c["errors-cmd"], c["errors-status"])
        if errs != last_err:
            if last_err != (None, None) and now >= grace_until:
                last_err_time = now
            last_err = errs
        ver = int(round(c["fw-version"]))
        if ver == int(cfg["FW_VERSION"]) and not driver_stopped:
            version_seen = True
        if machine_on:
            machine_on_since = machine_on_since or now
        else:
            machine_on_since = None
        if c["fw-active"]:
            fw_seen_time = now
        in_grace = now < grace_until
        no_errors = (now - last_err_time) > cfg["LINK_TIMEOUT"]
        # with the machine on, the firmware must also see our heartbeat
        # (1.5 s tolerance: one missed read of the flag must not count as "lost")
        hb_ok = (not machine_on_since or (now - machine_on_since) < 3.0
                 or (fw_seen_time is not None and now - fw_seen_time < 1.5))
        link_ok = version_seen and no_errors and hb_ok
        # Modbus works but the Arduino has other firmware: reconnecting cannot help
        wrong_fw = no_errors and not in_grace and ver not in (0, int(cfg["FW_VERSION"]))
        c["link-ok"] = link_ok
        c["link-lost-msg"] = bool(machine_on_since and (now - machine_on_since) > 3.0
                                  and not link_ok and not in_grace)
        c["errors"] = int(min(sum(errs), 2**31 - 1))

        # log every change of the link state with the reason
        if link_ok != link_state and not (in_grace and not link_ok):
            if link_ok:
                link_log("link OK (firmware %d, errors cmd/status %s/%s)" % (ver, errs[0], errs[1]))
            else:
                why = []
                if wrong_fw:
                    why.append("WRONG FIRMWARE: Arduino has version %d, this config needs %d "
                               "- flash coldend/firmware (make upload)" % (ver, int(cfg["FW_VERSION"])))
                elif not version_seen:
                    why.append("no answer from the Arduino yet")
                if not no_errors:
                    why.append("Modbus errors (cmd %s, status %s)" % errs)
                if not hb_ok:
                    why.append("firmware does not see the LinuxCNC heartbeat")
                link_log("link LOST: " + ("; ".join(why) or "unknown"))
            link_state = link_ok

        # ---- reconnect after a USB drop-out (mb2hal does not recover by itself) ----
        if link_ok or in_grace:
            lost_since = None
        elif version_seen or last_err != (None, None):
            lost_since = lost_since or now
        busy = reconnect_proc is not None and reconnect_proc.poll() is None
        btn = c["reconnect"]
        dev_present = os.path.exists(cfg["DEVICE"])
        if not busy and cfg["AUTO_RECONNECT"]:
            # USB device gone: stop the driver, otherwise it retries hundreds of
            # times per second and floods the LinuxCNC log. Started again below
            # as soon as the device is back.
            if not dev_present and not driver_stopped:
                subprocess.Popen(["sh", "-c", "halcmd unload coldend-mb && halcmd sets ce-fw-version 0"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                driver_stopped = True
                version_seen = False
                link_log("USB device %s gone - driver stopped until it is back" % cfg["DEVICE"])
            elif dev_present and driver_stopped:
                driver_stopped = False
                start_reconnect()
                busy = True
        if not busy:
            if btn and not reconnect_btn_last:
                start_reconnect()
            elif (cfg["AUTO_RECONNECT"] and lost_since and now - lost_since > 3.0 and not wrong_fw
                  and now - last_try > 10.0 and os.path.exists(cfg["DEVICE"])):
                start_reconnect()
        reconnect_btn_last = btn
        c["reconnecting"] = reconnect_proc is not None and reconnect_proc.poll() is None
        c["reconnect-count"] = reconnects

        # ---- modes ----
        gate = (not cfg["SPINDLE_GATE"]) or c["spindle-turning"] or c["run-without-spindle"]
        fast = c["sw-fast"] or c["scr-fast"]
        mist = (c["mist-request"] and gate) or c["sw-mist"]
        air = (c["air-request"] and gate) or c["sw-air"]
        coolant = mist and not fast           # firmware: fast has priority anyway
        on = machine_on
        c["cmd-coolant"] = coolant and on
        c["cmd-fast"] = fast and on
        c["cmd-air"] = air and on
        c["cmd-spit"] = not c["no-spit"]
        c["cmd-led"] = coolant and on         # board LED terminal = "mist running" lamp
        c["cmd-dir"] = bool(cfg["PUMP_REVERSE"])
        c["mist-on"] = coolant and on and link_ok
        c["fast-on"] = fast and on and link_ok
        c["air-on"] = (air or coolant) and on and link_ok

        # ---- rates (ml/h) ----
        pm = knob_mist.update(c["knob-mist-raw"])
        ps = knob_spit.update(c["knob-spit-raw"])
        c["knob-mist-pct"] = pm * 100.0
        c["knob-spit-pct"] = ps * 100.0
        if c["use-screen"]:
            mist_mlh = clamp(c["scr-mist-mlh"], 0.0, LIMIT)
            fast_mlh = clamp(c["scr-fast-mlh"], 1.0, LIMIT)
            spit_time = clamp(c["scr-spit-time"], 0.0, 30.0)
        else:
            mist_mlh = knob_mist_mlh(pm * 1023.0)
            fast_mlh = clamp(cfg["FAST_MLH"], 1.0, LIMIT)
            spit_time = knob_spit_s(ps * 1023.0)
        if c["no-spit"]:
            spit_time = 0.0

        c["mist-mlh"], c["fast-mlh"], c["spit-time"] = mist_mlh, fast_mlh, spit_time
        c["reg-mist-rate"] = reg_rate(mist_mlh, 0)
        c["reg-fast-rate"] = reg_rate(fast_mlh, 1)
        c["reg-spit-rate"] = reg_rate(fast_mlh, 1)     # spit burst = fast rate (original)
        c["reg-spit-time"] = float(int(spit_time * 1000.0))
        c["reg-microstep"] = 16.0
        c["spit-left-s"] = max(0.0, c["spit-left-ms"]) / 1000.0

        time.sleep(0.05)
except KeyboardInterrupt:
    pass
