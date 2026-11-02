#!/bin/bash
# Loads the ColdEnd QtDragon tab (qtvcp/panels/coldend) standalone under halrun,
# without a display, and checks that every panel pin used in
# hallib/coldend_postgui.hal exists (standalone the prefix is "coldend." instead
# of "qtdragon.coldend."). LinuxCNC must be stopped.
# usage: coldend/test/test_panel.sh <work-dir>
set -u
CFG="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="${1:?work dir}"; mkdir -p "$WORK"
if pgrep -x milltask >/dev/null || pgrep -x rtapi_app >/dev/null; then
    echo "LinuxCNC / HAL is running - stop it first"; exit 2
fi
export QT_QPA_PLATFORM=offscreen
( echo "loadusr -Wn coldend qtvcp $CFG/qtvcp/panels/coldend/coldend.ui"; sleep 30 ) | halrun -I > "$WORK/panel.log" 2>&1 &
HR=$!
cleanup() { halcmd unload all >/dev/null 2>&1; sleep 1; pkill -f "qtvcp $CFG/qtvcp/panels/coldend" 2>/dev/null; halrun -U >/dev/null 2>&1; }
trap cleanup EXIT
for i in $(seq 1 40); do halcmd list comp 2>/dev/null | grep -qw coldend && break; sleep 0.5; done
sleep 2
halcmd show pin coldend > "$WORK/panel_pins.txt" 2>&1

fails=0
if grep -q "CRITICAL\|Traceback" "$WORK/panel.log"; then
    echo "FAIL panel load errors:"; grep -A3 "CRITICAL\|Traceback" "$WORK/panel.log" | head -20; fails=$((fails+1))
else
    echo "PASS panel loaded without errors"
fi
for pin in $(grep -o 'qtdragon\.coldend\.[A-Za-z0-9_][A-Za-z0-9_.-]*' "$CFG/hallib/coldend_postgui.hal" | sort -u); do
    p=${pin#qtdragon.}
    if grep -qE "[[:space:]]$p\$" "$WORK/panel_pins.txt"; then
        echo "PASS pin $p ($(grep -E "[[:space:]]$p\$" "$WORK/panel_pins.txt" | awk '{print $2, $3}'))"
    else
        echo "FAIL pin $p missing"; fails=$((fails+1))
    fi
done
echo
[ $fails -eq 0 ] && echo "OK: 0 failures" || echo "FAILED: $fails"
exit $fails
