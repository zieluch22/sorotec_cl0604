#!/bin/bash
# Reconnect the VFD Modbus link (USB-RS485) without restarting LinuxCNC.
# Used by mcodes/M190 (button) and hallib/vfd_watchdog.sh (automatic retries).
#   arg1 = seconds to wait for /dev/vfd485 to appear (default 10)
#   arg2 = who called (for the log)
# Exit 0 = driver reloaded, 1 = failed / refused.  Log: /tmp/vfd_reconnect.log

CFG="$(cd "$(dirname "$0")/.." && pwd)"
DEV=/dev/vfd485
WAIT=${1:-10}
WHO=${2:-manual}
cd "$CFG" || exit 1
exec >> /tmp/vfd_reconnect.log 2>&1

# only one reconnect at a time (button + watchdog)
exec 8>/tmp/vfd_reconnect.lock
flock -n 8 || { echo "$(date +%T) [$WHO] reconnect already running - skipped"; exit 1; }

echo "=== $(date) VFD reconnect [$WHO]"

if [ "$(halcmd getp spindle.0.on)" = "TRUE" ]; then
    echo "spindle is ON - refused"; exit 1
fi

for i in $(seq 1 $((WAIT*2))); do [ -e "$DEV" ] && break; sleep 0.5; done
if [ ! -e "$DEV" ]; then
    echo "$DEV not present - USB adapter not found, nothing changed"; exit 1
fi

# from here on: treat the link as LOST until the new driver is up
halcmd sets vfd-driver-down 1 || echo "(vfd-driver-down missing - restart LinuxCNC)"

# stop the old driver (if running) and wait until it is really gone
if halcmd list comp | tr ' ' '\n' | grep -qx mb2hal; then
    halcmd unload mb2hal
    for i in $(seq 1 20); do
        halcmd list comp | tr ' ' '\n' | grep -qx mb2hal || break
        sleep 0.5
    done
fi
if halcmd list comp | tr ' ' '\n' | grep -qx mb2hal; then
    echo "old mb2hal did not exit - restart LinuxCNC"; exit 1
fi

# keep the drawbar locked until real readings arrive (10 Hz > 0.5 Hz standstill)
halcmd sets vfd-freq-actual 100 || true

if halcmd -f hallib/vfd_reconnect.hal; then
    sleep 1
    halcmd sets vfd-driver-down 0 || true
    echo "OK - mb2hal reloaded"
    exit 0
else
    echo "FAILED to load/connect mb2hal - link stays LOST"
    exit 1
fi
