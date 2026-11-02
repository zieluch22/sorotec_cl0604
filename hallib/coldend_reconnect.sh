#!/bin/bash
# Reload the ColdEnd Modbus driver (mb2hal "coldend-mb") after a USB drop-out,
# without restarting LinuxCNC. mb2hal does not recover by itself once the
# USB serial port has disappeared.
# Called by python/coldend.py (automatic, max. once per 10 s, or the
# "Reconnect" button on the ColdEnd tab).
#   arg1 = device (default /dev/coldend)
#   arg2 = HAL file to take the coldend-mb lines from (default hallib/coldend.hal)
# Never touches the VFD driver ("mb2hal"). Log: /tmp/coldend_reconnect.log
# While the driver is unloaded the firmware times out after 1 s -> pump off.

CFG="$(cd "$(dirname "$0")/.." && pwd)"
cd "$CFG" || exit 1
DEV=${1:-/dev/coldend}
HALSRC=${2:-hallib/coldend.hal}
exec >> /tmp/coldend_reconnect.log 2>&1

exec 8>/tmp/coldend_reconnect.lock
flock -n 8 || { echo "$(date +%T) reconnect already running - skipped"; exit 1; }

echo "=== $(date) ColdEnd reconnect"
if [ ! -e "$DEV" ]; then
    echo "$DEV not present - USB not connected, nothing changed"; exit 1
fi

if halcmd list comp | tr ' ' '\n' | grep -qx coldend-mb; then
    halcmd unload coldend-mb
    for i in $(seq 1 20); do
        halcmd list comp | tr ' ' '\n' | grep -qx coldend-mb || break
        sleep 0.5
    done
fi
if halcmd list comp | tr ' ' '\n' | grep -qx coldend-mb; then
    echo "old coldend-mb did not exit - restart LinuxCNC"; exit 1
fi
# forget the last firmware version read, so "link OK" needs a fresh answer
halcmd sets ce-fw-version 0 2>/dev/null

# same loadusr + nets as in coldend.hal (taken from it, so they never get out of sync)
TMP=$(mktemp)
grep -E '^[[:space:]]*(loadusr[^#]*coldend-mb|net[^#]*coldend-mb)' "$HALSRC" > "$TMP"
# mb2hal inherits stdout/stderr: keep its endless error lines out of the log
if halcmd -f "$TMP" >/dev/null 2>&1; then
    echo "OK - coldend-mb reloaded"; rc=0
else
    echo "FAILED to reload coldend-mb"; rc=1
fi
rm -f "$TMP"
exit $rc
