# Sims for the Table tab (datron_probing)

Copies of the sim configs used to develop the Table tab. They run from
`~/linuxcnc/configs/sim_table_nav`, a copy of the stock
`sim.qtdragon_hd.qtdragon_hd_xyz` sample. To rebuild that folder:

1. Copy the stock sample to `~/linuxcnc/configs/sim_table_nav`.
2. Copy these files into it.
3. Link the panel: `mkdir -p qtvcp/panels && ln -s ~/linuxcnc/configs/qthd_sorotec_cl0604/qtvcp/panels/table_nav qtvcp/panels/table_nav`
4. Make a `nc_files` folder in it: PROGRAM_PREFIX points there, away from the Mac share,
   which froze the screen whenever the Mac was asleep.

- `sim_table_nav.ini` - machine limits as the real machine, homes in place, virtual camera,
  virtual block / boss / hole probed through `sim_part.py` (HAL pins).
- `sim_virtual.ini` - same as the real-machine virtual test: `virtual_probe.py` follows the
  machine position, parts at Z -10, probe selected with M64 P3.

Stop a sim by closing its screen (EXIT). Killing the `linuxcnc` launcher leaves it waiting.

The real-machine virtual test is `../start_virtual_probe.sh [top_z] [shift_x] [shift_y]`.
