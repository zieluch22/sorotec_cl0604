#!/bin/bash
# Automatic VFD Modbus reconnect. Started by spindle_setup.hal (loadusr).
# When vfd-commlost is TRUE and the spindle is OFF, it retries the reconnect
# after 2 s, then 3 s, then 5 s. After 3 failed tries it gives up and leaves it
# to the "VFD Reconnect" button (M190). Re-arms once the link is OK again.
# Exits by itself when LinuxCNC/HAL stops. Log: /tmp/vfd_reconnect.log

DIR="$(cd "$(dirname "$0")" && pwd)"
DELAYS=(2 3 5)
LOG=/tmp/vfd_reconnect.log

# single instance
exec 9>/tmp/vfd_watchdog.lock
flock -n 9 || exit 0

lost() { [ "$(halcmd gets vfd-commlost 2>/dev/null)" = "TRUE" ]; }
hal_alive() { halcmd getp spindle.0.on >/dev/null 2>&1; }

sleep 10   # let LinuxCNC finish starting
attempt=0
while hal_alive; do
    if lost; then
        if [ $attempt -lt ${#DELAYS[@]} ]; then
            d=${DELAYS[$attempt]}
            attempt=$((attempt+1))
            echo "$(date +%T) [auto] comm lost - try $attempt/${#DELAYS[@]} in ${d}s" >> $LOG
            # wait, but stop waiting if the link comes back by itself
            for i in $(seq 1 $((d*2))); do sleep 0.5; lost || break; done
            if lost; then
                if [ "$(halcmd getp spindle.0.on)" = "TRUE" ]; then
                    echo "$(date +%T) [auto] spindle still ON - skip this try" >> $LOG
                else
                    bash "$DIR/vfd_reconnect.sh" 2 "auto $attempt"
                    sleep 4   # let comm-lost detection settle
                fi
            fi
            [ $attempt -eq ${#DELAYS[@]} ] && lost && \
                echo "$(date +%T) [auto] giving up - use the VFD Reconnect button" >> $LOG
        fi
    else
        [ $attempt -gt 0 ] && echo "$(date +%T) [auto] link OK - watchdog re-armed" >> $LOG
        attempt=0
    fi
    sleep 0.5
done
