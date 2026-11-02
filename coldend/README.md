# ColdEnd mist controller over Modbus (branch `coldend_modbus`)

The ColdEnd pump board (Arduino Nano) gets new firmware and is connected to the PC by
USB. LinuxCNC controls it with M7 / M8 / M9 and the QtDragon screen. The board knobs
and switches keep working, and LinuxCNC shows their values live.

Based on ColdEnd TallaMod (Talla83 / END-CNC, CC BY-NC-SA 4.0), same register map.

## What it does

| | |
|---|---|
| **M7** | Mist: pump at mist rate + air valve. Starts with a spit burst (optional). |
| **M8** | Air blast only (QtDragon FLOOD button is labelled **AIR**). |
| **M9** | Mist and air off. |
| **Board switches** | Mist / Fast / Air switches still work and always win over the screen. |
| **Board knobs** | Mist knob = mist rate, spit knob = spit + prime rate. Shown live in QtDragon. |
| **Screen rates** | Tick "Set rates here" on the USER page: the screen values are used, knobs ignored. |
| **PRIME** | Main screen button (hold) = pump only at fast rate, to fill the line. |
| **E-stop / machine off** | Everything off (heartbeat stops; firmware switches off after max. 1 s). |
| **OLED display** | Board display (SSD1306 128x64, 0x3C): link status, mode (STANDBY / OFF / MIST / SPIT x.x / PRIME / AIR) in big letters, mist / spit / prime rpm, knob %. |
| **USB unplugged** | "ColdEnd Modbus link lost" message, pump off, automatic reconnect when it is back. |
| Spindle gating | Prepared but **off** (`[COLDEND]SPINDLE_GATE = 0`) - later stage. |

Screen:
- **MAIN, PROGRAM box**: MIST / AIR buttons (= M7 / M8) and the COLDEND strip
  (link light, mist light, mist rpm, PRIME).
- **USER button**: ColdEnd page with status, board switch lights, Modbus errors,
  Reconnect button, rates and spit settings. Settings are remembered (qtdragon.pref).

## Files

| File | |
|---|---|
| `coldend/firmware/ColdEnd-LinuxCNC/ColdEnd-LinuxCNC.ino` | Arduino firmware - no extra libraries needed |
| `coldend/udev/99-cnc-serial.rules` | USB names `/dev/vfd485` (CH340) + `/dev/coldend` (FTDI serial AR0KKVM0) |
| `hallib/coldend.hal` | loads mb2hal `coldend-mb` + logic `coldend`, nets |
| `hallib/coldend_mb2hal.ini` | Modbus: 9600 8N1, slave 6, `/dev/coldend` |
| `hallib/coldend_postgui.hal` | screen pins |
| `hallib/coldend_reconnect.sh` | reloads the ColdEnd driver after a USB drop-out |
| `python/coldend.py` | logic (M7/M8, switches, knobs, rates, link check, reconnect) |
| `qtvcp/panels/coldend/` | ColdEnd page (`coldend.ui`) + handler (remembers settings) |
| `coldend/test/` | tests without hardware (firmware emulator) |

Changed: `qthd_sorotec_cl0604.ini` (embed tab, HALFILE, `[COLDEND]`),
`hallib/messages.hal` (+ `m_coldend`), `hallib/postgui_call_list.hal` (+ source line),
`qtvcp/screens/qtdragon_hd/qtdragon_hd_handler.py` (`init_coldend_main`: moves the
COLDEND strip into the PROGRAM box in place of the unused SPINDLE LIFT / Z AXIS COMP
displays, FLOOD -> AIR).

The VFD Modbus link is not changed: separate driver instance, the M190 / watchdog
reconnect only touches the VFD driver.

## Installation (in this order)

### 0. Backup the current ColdEnd firmware - DONE 2026-11-02
Saved and verified in `coldend/firmware/original_backup/` (flash + EEPROM, Nano with
new bootloader = 115200 baud). Restore = standalone ColdEnd as before:
```
avrdude -p m328p -c arduino -P /dev/coldend -b 115200 \
  -U flash:w:coldend/firmware/original_backup/coldend_original_flash.hex:i \
  -U eeprom:w:coldend/firmware/original_backup/coldend_original_eeprom.hex:i
```
(fuses cannot be read through the bootloader - not needed for a restore)

Also note the microstep jumpers JP1-JP3 on the board (A4988: all 3 on = 1/16).

### 1. USB names
The VFD adapter (CH340, no serial number) and the ColdEnd Nano (FTDI FT232R, serial
AR0KKVM0) have different chips, so the rule matches them by chip / serial number:
both can be plugged into any USB port.
```
sudo cp coldend/udev/99-cnc-serial.rules /etc/udev/rules.d/
sudo rm /etc/udev/rules.d/99-vfd485.rules
sudo udevadm control --reload && sudo udevadm trigger
ls -l /dev/vfd485 /dev/coldend     # two different ttyUSB devices
```
Use a short shielded USB cable with a ferrite for the Nano, away from the spindle /
motor cables.

### 2. Flash the new firmware - DONE 2026-11-02 (verified, Modbus answers)
From this PC (tools: `sudo apt install gcc-avr avr-libc arduino-core-avr arduino-mk avrdude`):
```
cd coldend/firmware/ColdEnd-LinuxCNC
make            # build
make upload     # build + flash to /dev/coldend
```
Or the Arduino IDE: board **Arduino Nano**, processor **ATmega328P** (new bootloader).
Only library: Wire (built in).

### 3. (nothing to do - was: port setup, not needed with the serial-number rule)

### 4. Settings
`[COLDEND]` in the INI: `MICROSTEP` must match JP1-JP3. Knob ranges `MIST_RPM_*`,
`SPIT_RPM_*`, `FAST_RPM_*` - start with the defaults, adjust after watching the pump.

### 5. Start LinuxCNC and test
1. USER page: "Modbus link OK" on, knobs show % and rpm while turning them.
2. Machine on: "ColdEnd active" on.
3. MIST button (or MDI `M7`): spit burst, then mist; `M9` off. AIR button / `M8`: air only.
4. Board switches: lights on the USER page follow them, the pump reacts.
5. PRIME (hold): pump runs, air closed.
6. E-stop while mist runs: pump and air off.
7. Unplug the ColdEnd USB: message, pump off. Plug back: link OK again within ~10 s.
8. Spindle start/stop and M190 VFD reconnect still work.

Logs: `/tmp/coldend_reconnect.log`.

## Going back
- Comment out `HALFILE = hallib/coldend.hal` and the three `EMBED_TAB_*` lines in the INI
  and `source hallib/coldend_postgui.hal` in `postgui_call_list.hal` (or switch branch).
- Flash the backup back (step 0) = standalone ColdEnd as before.

## Tests (no hardware, LinuxCNC stopped)
```
S=$(mktemp -d)
g++ -std=c++11 -O1 -Icoldend/test/shim -o $S/ce_emu coldend/test/emulator.cpp
python3 -I coldend/test/test_protocol.py $S/ce_emu $S     # firmware protocol
python3 -I coldend/test/render_oled.py $S/ce_emu $S       # pictures of the OLED screens ($S/oled_all.png)
coldend/test/test_hal.sh $S                               # emulator + mb2hal + logic
coldend/test/test_panel.sh $S                             # screen panel pins
```
`test_hal.sh` uses `/tmp/ce_test_pty` (mb2hal accepts max. 31 characters for the port name).
