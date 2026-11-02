#!/usr/bin/env python3
# Tests "last one touched wins" for slider and knob. No hardware or LinuxCNC needed.
# usage: python3 coldend/test/test_mist_source.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "python"))
from coldend_mist import LastTouched

fails = 0


def check(name, got, want):
    global fails
    if got == want:
        print("PASS", name)
    else:
        print("FAIL %s: got %s, want %s" % (name, got, want))
        fails += 1


m = LastTouched()
check("before the link: slider in control", m.update(0, 0, False), True)
check("first real knob reading is no knob move", m.update(0, 738, True), True)
check("knob noise below threshold: stays slider", m.update(0, 750, True), True)
check("knob noise other way: stays slider", m.update(0, 725, True), True)
check("knob turned: knob takes over", m.update(0, 770, True), False)
check("knob keeps control while turning", m.update(0, 500, True), False)
check("touch (button press at any value): slider takes over", m.update(1, 500, True), True)
check("knob noise after that: stays slider", m.update(1, 510, True), True)
check("link lost, knob reads 0: stays slider", m.update(1, 0, False), True)
check("link back, knob really moved: knob", m.update(1, 400, True), False)
check("touch without link: slider", m.update(2, 400, False), True)
check("first reading after the link is no knob move", m.update(2, 900, True), True)

print("\nOK: 0 failure(s)" if not fails else "\nFAILED: %d" % fails)
sys.exit(1 if fails else 0)
