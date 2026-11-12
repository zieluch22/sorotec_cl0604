# sorotec_cl0604
#test

## Probe screen turned 180°

On this machine X+ points left and Y+ points down on the screen, so the Versa Probe
buttons (outside, inside, skew) are moved to the opposite place at start-up.

- Switch: `[PROBE] ROTATE_180 = 1` in `qthd_sorotec_cl0604.ini` (0 = stock layout).
  `start_virtual_probe.sh` copies it into the virtual probe INI.
- Code: `rotate_probe_screen()` in `qtvcp/screens/qtdragon_hd/qtdragon_hd_handler.py`.
- Icons: `qtvcp/images/probe_icons_rot180/`, made by `python/make_probe_icons_rot180.py`
  (opposite stock icon with the +/- signs swapped). Only places and icons change, not probe moves.
- Everything lives in this config, so a LinuxCNC update does not overwrite it. If a new
  LinuxCNC version renames or moves the probe buttons, that group stays in the stock layout
  and a warning shows on the screen: then check the buttons before probing.
