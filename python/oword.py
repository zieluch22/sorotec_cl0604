# Python O-word subs for the interpreter (imported by toplevel.py)
#
# o<pz_param> call [n]  ->  #<_value> = probe screen (VersaProbe) parameter n
#
#   n  parameter            live HAL pin               qtdragon.pref key
#   1  search velocity      qtversaprobe.searchvel     ps_searchvel
#   2  probe velocity       qtversaprobe.probevel      ps_probevel
#   3  latch return dist    qtversaprobe.backoffdist   ps_probe_latch
#   4  max Z travel         -                          ps_probe_max_z_travel
#   5  Z clearance          -                          ps_z_clearance
#   6  rapid velocity       -                          ps_probe_rapid_vel
#   7  Z adjust (offs_z)    -                          ps_offs_z
#   8  auto zero (1/0)      -                          use_auto_zero
#
# Values 1-3 are live from the probe screen. 4-8 only exist in qtdragon.pref,
# which QtDragon writes when it closes - edits made there take effect for this
# macro after the next QtDragon restart.
# Returns -1 when a value can't be read (the macro aborts on it).

import os
import configparser

try:
    import hal
except Exception:
    hal = None

_PARAMS = {
    1: ('qtversaprobe.searchvel',   'ps_searchvel',          -1.0),
    2: ('qtversaprobe.probevel',    'ps_probevel',           -1.0),
    3: ('qtversaprobe.backoffdist', 'ps_probe_latch',        -1.0),
    4: (None,                       'ps_probe_max_z_travel', -1.0),
    5: (None,                       'ps_z_clearance',        -1.0),
    6: (None,                       'ps_probe_rapid_vel',    -1.0),
    7: (None,                       'ps_offs_z',              0.0),
    8: (None,                       'use_auto_zero',          0.0),
}


def _pref_file():
    ini = os.environ.get('INI_FILE_NAME')
    folder = os.path.dirname(os.path.abspath(ini)) if ini else os.getcwd()
    return os.path.join(folder, 'qtdragon.pref')


def pz_param(self, idx, *args):
    pin, key, default = _PARAMS.get(int(idx), (None, None, -1.0))
    if key is None:
        return -1.0

    if pin and hal is not None:
        try:
            value = float(hal.get_value(pin))
            if value > 0:
                return value
        except Exception:
            pass

    try:
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        cp.read(_pref_file())
        text = cp.get('VERSA_PROBE_OPTIONS', key).strip()
        if text in ('True', 'False'):
            return 1.0 if text == 'True' else 0.0
        return float(text)
    except Exception:
        return default
