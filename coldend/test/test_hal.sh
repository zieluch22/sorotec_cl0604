#!/bin/bash
# End-to-end test WITHOUT hardware and WITHOUT LinuxCNC running:
#   firmware emulator  <->  real mb2hal (hallib/coldend_mb2hal.ini)  <->  python/coldend.py
#   wired with the nets from hallib/coldend.hal, machine signals faked with "sets".
# usage: coldend/test/test_hal.sh <work-dir>      (run from anywhere; LinuxCNC must be stopped)
set -u
CFG="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="${1:?work dir}"
TEST="$CFG/coldend/test"
mkdir -p "$WORK"
if pgrep -x milltask >/dev/null || pgrep -x rtapi_app >/dev/null; then
    echo "LinuxCNC / HAL is running - stop it first"; exit 2
fi

g++ -std=c++11 -O1 -I"$TEST/shim" -o "$WORK/ce_emu" "$TEST/emulator.cpp" || exit 2
echo "400 700 0 0 0" > "$WORK/ce_inputs"
# stable short link (mb2hal truncates SERIAL_PORT at 31 chars), needed for the replug test
LINK=/tmp/ce_test_pty
"$WORK/ce_emu" "$LINK" "$WORK/ce_state" "$WORK/ce_inputs" &
EMU=$!
cleanup() { kill $EMU 2>/dev/null; rm -f "$LINK"; halcmd unload all >/dev/null 2>&1; halrun -U >/dev/null 2>&1; }
trap cleanup EXIT
sleep 0.5
sed "s#^SERIAL_PORT=.*#SERIAL_PORT=$LINK#" "$CFG/hallib/coldend_mb2hal.ini" > "$WORK/test_mb2hal.ini"
cat > "$WORK/test.ini" <<EOF
[COLDEND]
LINK_LOG = $WORK/link.log
DEVICE = $LINK
RECONNECT_HAL = $WORK/test.hal
EOF
# coldend.hal without the realtime message part (no servo-thread in halrun)
sed -e "s#config=hallib/coldend_mb2hal.ini#config=$WORK/test_mb2hal.ini#" \
    -e '/m_coldend/d' "$CFG/hallib/coldend.hal" > "$WORK/test.hal"

cd "$CFG"
export INI_FILE_NAME="$WORK/test.ini"
( sleep 120 | halrun -I -f "$WORK/test.hal" > "$WORK/halrun.log" 2>&1 ) &
for i in $(seq 1 40); do halcmd list comp 2>/dev/null | grep -qw coldend && break; sleep 0.5; done
if ! halcmd list comp 2>/dev/null | grep -qw coldend; then echo "HAL file did not load:"; grep -v "ERR\|ret\[" "$WORK/halrun.log" | tail; exit 2; fi
sleep 1
if grep -q "does not exist\|not found" "$WORK/halrun.log"; then echo "HAL net error:"; grep "does not exist\|not found" "$WORK/halrun.log"; exit 2; fi

fails=0
g()  { halcmd getp "$1" 2>/dev/null; }
st() { sleep 0.15; tr ' ' '\n' < "$WORK/ce_state" | grep "^$1=" | cut -d= -f2; }
check() { if [ "$2" = "$3" ]; then echo "PASS $1"; else echo "FAIL $1 (got '$2', want '$3')"; fails=$((fails+1)); fi; }
wait_for() { for i in $(seq 1 30); do [ "$($1)" = "$2" ] && return 0; sleep 0.1; done; return 1; }

sleep 2
check "pins exist: coldend-mb.cmd.00.bit"            "$(halcmd list pin coldend-mb.cmd.00.bit | grep -c cmd.00.bit)" 1
check "firmware version read (3)"                 "$(g coldend-mb.status.08.float)" 3
check "link OK"                                   "$(g coldend.link-ok)" TRUE
check "mist knob raw 400 read"                    "$(g coldend.knob-mist-raw)" 400
check "machine off: pump off"                     "$(st ena)" 1

# the screen is not loaded here: set the sliders to their start values by hand
halcmd setp coldend.scr-slider-mlh 40
halcmd setp coldend.scr-spit-tenths 30
halcmd sets machine-is-enabled 1
halcmd sets coolant-mist 1
wait_for "st running" 1
check "M7 with spindle stopped: mist on (no spindle gating)" "$(st running)" 1
check "  coldend.mist-on TRUE"                    "$(g coldend.mist-on)" TRUE
check "firmware sees heartbeat"                   "$(st fw_active)" 1
check "  air valve open"                          "$(st air)" 0
check "  LED lamp on"                             "$(st led)" 1
wait_for "st rate_mist" 400
check "start: slider in control, 40 ml/h"         "$(st rate_mist)" 400
check "start: slider in control, 3 s"             "$(st spit_ms)" 3000
# knob 420 -> original curve 1000^((420-23)/1000) = 15.5 -> 15 ml/h -> reg 150
# spit knob 720 -> 720/1023*8 = 5.63 -> 5.6 s
echo "420 720 0 0 0" > "$WORK/ce_inputs"
wait_for "st rate_mist" 150
check "mist knob turned: original curve (15 ml/h)" "$(st rate_mist)" 150
check "spit knob turned: spit time 5.6 s"         "$(st spit_ms)" 5600
check "spit/fast rate = original 1562.5 ml/h"     "$(st rate_fast)$(st rate_spit)" 1562515625
halcmd setp coldend.scr-spit-flow 100
wait_for "st rate_spit" 1000
check "spit flow slider: 100 ml/h, prime unchanged" "$(st rate_spit) $(st rate_fast)" "1000 15625"
halcmd setp coldend.scr-spit-flow 1562
wait_for "st rate_spit" 15625
check "spit flow slider top: original 1562.5 ml/h" "$(st rate_spit)" 15625

echo "1023 700 0 0 0" > "$WORK/ce_inputs"
wait_for "st rate_mist" 10000
check "knob fully right -> 1000 ml/h"             "$(st rate_mist)" 10000
check "  screen value follows knob (1000)"        "$(g coldend.mist-mlh)" 1000

halcmd setp coldend.scr-slider-mlh 55
halcmd setp coldend.scr-mist-touch 1
wait_for "st rate_mist" 550
check "slider moved: 55 ml/h, knob ignored"       "$(st rate_mist)" 550
echo "700 700 0 0 0" > "$WORK/ce_inputs"
wait_for "g coldend.mist-by-slider" FALSE
check "knob turned: knob takes over"              "$(g coldend.mist-by-slider)" FALSE
echo "1023 700 0 0 0" > "$WORK/ce_inputs"
wait_for "st rate_mist" 10000

halcmd sets coolant-mist 0
echo "1023 700 1 0 0" > "$WORK/ce_inputs"
wait_for "st running" 1
check "board mist switch: mist on (no M7, no spindle)" "$(st running)" 1
check "  sw-mist seen by LinuxCNC"                "$(g coldend.sw-mist)" TRUE

halcmd setp coldend.scr-fast 1
wait_for "st air" 1
check "prime button: fast wins, air closed"       "$(st air)" 1
check "  fast-on"                                 "$(g coldend.fast-on)" TRUE
halcmd setp coldend.scr-fast 0
echo "1023 700 0 0 0" > "$WORK/ce_inputs"

halcmd sets coolant-flood 1
wait_for "st air" 0
check "M8: air only"                              "$(st air)$(st running)" 00

halcmd sets coolant-mist 1
wait_for "st running" 1
halcmd sets machine-is-enabled 0
wait_for "st running" 0
check "machine off / E-stop: everything off"      "$(st running)$(st air)$(st ena)" 011

# link loss: kill the emulator, machine on
halcmd sets machine-is-enabled 1
kill $EMU; wait $EMU 2>/dev/null
for i in $(seq 1 60); do [ "$(g coldend.link-lost-msg)" = TRUE ] && break; sleep 0.1; done
check "USB gone: link-ok FALSE"                   "$(g coldend.link-ok)" FALSE
check "USB gone: link-lost message"               "$(g coldend.link-lost-msg)" TRUE
sleep 1
check "USB gone: ColdEnd driver stopped (no log flood)" "$(halcmd list comp | tr ' ' '\n' | grep -cx coldend-mb)" 0

# replug: emulator back (Arduino restarts), knob now 500 -> automatic reconnect
echo "500 700 0 0 0" > "$WORK/ce_inputs"
"$WORK/ce_emu" "$LINK" "$WORK/ce_state" "$WORK/ce_inputs" &
EMU=$!
for i in $(seq 1 250); do [ "$(g coldend.link-ok)" = TRUE ] && break; sleep 0.1; done
check "USB back: reconnected by itself, link OK"  "$(g coldend.link-ok)" TRUE
check "  new knob value read (500)"               "$(g coldend.knob-mist-raw)" 500
check "  reconnect counted"                       "$( [ "$(g coldend.reconnect-count)" -ge 1 ] && echo yes)" yes
wait_for "st running" 1
check "  mist running again (M7 still on)"        "$(st running)" 1
check "  VFD driver untouched (no mb2hal comp)"   "$(halcmd list comp | tr ' ' '\n' | grep -cx mb2hal)" 0

echo
[ $fails -eq 0 ] && echo "OK: 0 failures" || { echo "FAILED: $fails"; echo "--- halrun log:"; tail -20 "$WORK/halrun.log"; }
exit $fails
