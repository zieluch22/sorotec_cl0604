#!/usr/bin/env python3
"""Firmware protocol test against the PC emulator (no hardware needed).

    python3 -I test_protocol.py <emulator-binary> <work-dir>

Starts the emulator, talks raw Modbus RTU to it and checks replies and pump/valve state.
"""
import os
import struct
import subprocess
import sys
import termios
import time

EMU, WORK = sys.argv[1], sys.argv[2]
LINK, STATE, INPUTS = (os.path.join(WORK, n) for n in ("ce_pty", "ce_state", "ce_inputs"))
fails = 0


def check(name, cond, extra=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  " + str(extra)))
    if not cond:
        fails += 1


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return struct.pack("<H", crc)


def frame(*parts):
    body = bytes(parts[0]) if len(parts) == 1 else b"".join(parts)
    return body + crc16(body)


def xfer(fd, req, wait=0.08):
    termios.tcflush(fd, termios.TCIFLUSH)
    os.write(fd, req)
    time.sleep(wait)
    try:
        return os.read(fd, 256)
    except BlockingIOError:
        return b""


def state():
    time.sleep(0.12)
    with open(STATE) as f:
        return dict(kv.split("=") for kv in f.read().split())


def set_inputs(pm, ps, sm, sf, sa):
    with open(INPUTS, "w") as f:
        f.write(f"{pm} {ps} {sm} {sf} {sa}\n")
    time.sleep(0.25)


def wr_coils(fd, bits, addr=8192, sid=6):
    val = sum(1 << i for i, b in enumerate(bits) if b)
    return xfer(fd, frame(struct.pack(">BBHHBB", sid, 15, addr, len(bits), 1, val)))


def wr_regs(fd, vals, addr=8451):
    return xfer(fd, frame(struct.pack(">BBHHB", 6, 16, addr, len(vals), 2 * len(vals)),
                          struct.pack(">" + "H" * len(vals), *vals)))


def rd(fd, fn, addr, qty, sid=6):
    return xfer(fd, frame(struct.pack(">BBHH", sid, fn, addr, qty)))


set_inputs(400, 700, 0, 1, 0)
emu = subprocess.Popen([EMU, LINK, STATE, INPUTS])
time.sleep(0.5)
fd = os.open(LINK, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
t = termios.tcgetattr(fd)
t[0] = t[1] = t[3] = 0
t[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
termios.tcsetattr(fd, termios.TCSANOW, t)

try:
    # --- idle: everything off, knobs and switches still reported
    s = state()
    check("idle: driver disabled, valves closed", s["ena"] == "1" and s["air"] == "1" and s["mistvalve"] == "1", s)
    r = rd(fd, 3, 8448, 9)
    check("read 9 regs: length + CRC", len(r) == 23 and crc16(r[:-2]) == r[-2:], r.hex())
    regs = struct.unpack(">9H", r[3:21])
    check("knobs reported while inactive", regs[0] == 400 and regs[1] == 700, regs)
    check("firmware version = 3 (ml/h)", regs[8] == 3, regs)
    r = rd(fd, 2, 8199, 4)
    check("discrete inputs: fast switch only", r[:3] == bytes([6, 2, 1]) and r[3] == 0b0100, r.hex())

    # --- rates
    r = wr_regs(fd, [200, 1500, 1000, 1500, 16])
    check("write 5 rate regs: echo", r[:6] == struct.pack(">BBHH", 6, 16, 8451, 5), r.hex())

    # --- coolant on with spit: burst at spit rate first, then mist rate
    r = wr_coils(fd, [1, 1, 1, 0, 1, 0, 0])
    check("write 7 coils: echo", r[:6] == struct.pack(">BBHH", 6, 15, 8192, 7), r.hex())
    s = state()
    check("coolant: fw active, driver on, valves open", s["fw_active"] == "1" and s["ena"] == "0"
          and s["air"] == "0" and s["mistvalve"] == "0" and s["led"] == "1", s)
    # spit 100.0 ml/h: 1250000/1000 = 1250 us (original ColdEND: 125000/(ml/h))
    check("spit burst at spit rate (1250 us)", s["half_us"] == "1250", s)
    check("spit time left reported", 0 < int(s["spit_left"]) <= 1500, s)
    for _ in range(18):                  # keep heartbeat going for ~1.8 s
        wr_coils(fd, [1, 1, 1, 0, 1, 0, 0])
    s = state()
    # mist 20.0 ml/h: 1250000/200 = 6250 us
    check("after spit: mist rate (6250 us)", s["half_us"] == "6250" and s["spit_left"] == "0", s)

    # --- reserved register 8455 (old microstep) has no effect
    wr_regs(fd, [200, 1500, 1000, 1500, 4])
    wr_coils(fd, [1, 1, 1, 0, 1, 0, 0])
    s = state()
    check("register 8455 ignored: still 6250 us", s["half_us"] == "6250", s)
    wr_regs(fd, [200, 1500, 1000, 1500, 16])

    # --- original ColdEND fast speed 1562.5 ml/h = 80 us (same as its Timer1.setPeriod(80))
    wr_regs(fd, [200, 15625, 1000, 1500, 16])
    wr_coils(fd, [1, 0, 1, 1, 1, 0, 0])
    s = state()
    check("1562.5 ml/h = 80 us like the original", s["half_us"] == "80", s)
    wr_regs(fd, [200, 1500, 1000, 1500, 16])

    # --- fast has priority over coolant, air follows the air bit
    wr_coils(fd, [1, 0, 1, 1, 1, 0, 0])
    s = state()
    check("fast priority: 150 ml/h (833 us), air closed", s["half_us"] == "833" and s["air"] == "1", s)

    # --- air only
    wr_coils(fd, [1, 0, 0, 0, 0, 1, 0])
    s = state()
    check("air only: pump off, air open", s["ena"] == "1" and s["running"] == "0" and s["air"] == "0", s)

    # --- rate 0 does not crash, pump just stops
    wr_regs(fd, [0, 0, 0, 0, 0])
    wr_coils(fd, [1, 0, 1, 0, 0, 0, 0])
    s = state()
    check("rate 0: pump stopped, no crash", s["running"] == "0" and emu.poll() is None, s)
    wr_regs(fd, [200, 1500, 1000, 1500, 16])

    # --- heartbeat 0 -> off at once
    wr_coils(fd, [1, 0, 1, 0, 0, 0, 0])
    s = state()
    check("coolant running again", s["running"] == "1", s)
    wr_coils(fd, [0, 0, 1, 0, 0, 0, 0])
    s = state()
    check("active bit 0: all off immediately", s["running"] == "0" and s["ena"] == "1" and s["air"] == "1", s)

    # --- heartbeat timeout (LinuxCNC gone): off after ~1 s
    wr_coils(fd, [1, 0, 1, 0, 0, 0, 0])
    time.sleep(0.4)
    check("still running 0.4 s after last write", state()["running"] == "1")
    time.sleep(1.0)
    s = state()
    check("timeout: all off ~1 s after last write", s["running"] == "0" and s["fw_active"] == "0", s)

    # --- errors
    r = rd(fd, 3, 9000, 1)
    check("bad address -> exception 2", r[:3] == bytes([6, 0x83, 2]), r.hex())
    r = rd(fd, 3, 65530, 9)
    check("address wrap -> exception", r[:2] == bytes([6, 0x83]), r.hex())
    r = xfer(fd, frame(struct.pack(">BBHH", 6, 6, 8448, 5)))
    check("write read-only reg -> exception 2", r[:3] == bytes([6, 0x86, 2]), r.hex())
    r = xfer(fd, frame(struct.pack(">BBHH", 6, 8, 0, 0)))
    check("unknown function -> exception 1", r[:3] == bytes([6, 0x88, 1]), r.hex())
    r = rd(fd, 3, 8448, 1, sid=1)
    check("other slave ID (VFD = 1) ignored", r == b"", r.hex())
    bad = bytearray(frame(struct.pack(">BBHH", 6, 3, 8448, 1)))
    bad[-1] ^= 0xFF
    check("bad CRC ignored", xfer(fd, bytes(bad)) == b"")

    # --- switches change live
    set_inputs(1023, 0, 1, 0, 1)
    r = rd(fd, 2, 8199, 4)
    check("switches mist+air reported", r[3] == 0b1010, r.hex())
    regs = struct.unpack(">2H", rd(fd, 3, 8448, 2)[3:7])
    check("knob change reported (1023, 0)", regs == (1023, 0), regs)
finally:
    emu.terminate()
    emu.wait()

print("\n%s: %d failure(s)" % ("OK" if fails == 0 else "FAILED", fails))
sys.exit(1 if fails else 0)
