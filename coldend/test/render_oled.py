#!/usr/bin/env python3
"""Renders what the ColdEnd OLED shows in a few states (PC emulator, no hardware).

    python3 -I render_oled.py <emulator-binary> <work-dir>

Writes <work-dir>/oled_<state>.png and one combined oled_all.png.
"""
import os
import struct
import subprocess
import sys
import termios
import time

from PIL import Image, ImageDraw

EMU, WORK = sys.argv[1], sys.argv[2]
LINK, STATE, INPUTS = (os.path.join(WORK, n) for n in ("ce_pty", "ce_state", "ce_inputs"))


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return struct.pack("<H", crc)


def send(fd, body):
    termios.tcflush(fd, termios.TCIFLUSH)
    os.write(fd, body + crc16(body))
    time.sleep(0.06)


def coils(fd, bits):
    val = sum(1 << i for i, b in enumerate(bits) if b)
    send(fd, struct.pack(">BBHHBB", 6, 15, 8192, len(bits), 1, val))


def regs(fd, vals):
    send(fd, struct.pack(">BBHHB", 6, 16, 8451, len(vals), 2 * len(vals)) + struct.pack(">5H", *vals))


def hold(fd, bits, seconds):
    end = time.time() + seconds
    while time.time() < end:
        coils(fd, bits)
        time.sleep(0.1)


def snapshot(name):
    time.sleep(0.3)
    lines = open(STATE + ".oled").read().split("\n")
    img = Image.new("RGB", (128 * 4 + 16, 64 * 4 + 16), (10, 10, 20))
    d = ImageDraw.Draw(img)
    for page in range(8):
        row = bytes.fromhex(lines[page])
        for x, b in enumerate(row):
            for bit in range(8):
                if b >> bit & 1:
                    y = page * 8 + bit
                    d.rectangle([8 + x * 4, 8 + y * 4, 8 + x * 4 + 2, 8 + y * 4 + 2], fill=(120, 200, 255))
    path = os.path.join(WORK, "oled_%s.png" % name)
    img.save(path)
    return img


with open(INPUTS, "w") as f:
    f.write("400 700 0 0 0\n")
emu = subprocess.Popen([EMU, LINK, STATE, INPUTS])
time.sleep(0.5)
fd = os.open(LINK, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
t = termios.tcgetattr(fd)
t[0] = t[1] = t[3] = 0
t[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
termios.tcsetattr(fd, termios.TCSANOW, t)
shots = []
try:
    regs(fd, [130, 15625, 15625, 5500, 16])    # mist 13 ml/h, fast+spit 1562.5 ml/h, spit 5.5 s
    shots.append(("standby", snapshot("standby")))
    hold(fd, [1, 0, 0, 0, 1, 0, 0], 0.5)
    shots.append(("off", snapshot("off")))
    coils(fd, [1, 1, 1, 0, 1, 0, 0])
    hold(fd, [1, 1, 1, 0, 1, 0, 0], 0.4)
    shots.append(("spit", snapshot("spit")))
    hold(fd, [1, 1, 1, 0, 1, 0, 0], 2.2)
    shots.append(("mist", snapshot("mist")))
    hold(fd, [1, 0, 1, 1, 1, 0, 0], 0.5)
    shots.append(("prime", snapshot("prime")))
    hold(fd, [1, 0, 0, 0, 1, 1, 0], 0.5)
    shots.append(("air", snapshot("air")))
finally:
    emu.terminate()
    emu.wait()

w, h = shots[0][1].size
all_img = Image.new("RGB", (w * 3 + 40, (h + 30) * 2 + 10), (40, 40, 40))
d = ImageDraw.Draw(all_img)
for i, (name, im) in enumerate(shots):
    x, y = 10 + (i % 3) * (w + 10), 10 + (i // 3) * (h + 30)
    d.text((x, y), name.upper(), fill=(230, 230, 230))
    all_img.paste(im, (x, y + 15))
all_img.save(os.path.join(WORK, "oled_all.png"))
print(open(STATE + ".oled").read().split("\n")[8])
