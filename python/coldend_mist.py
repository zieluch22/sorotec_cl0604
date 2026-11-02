# Slider or board knob: "last one touched wins".
# Separate from coldend.py so that it can be tested without HAL (coldend/test/test_mist_source.py).


class LastTouched:
    """True from update() = the slider sets the value, False = the knob does.

    The slider is in control after a start. Turning the knob by at least
    knob_takeover counts (0..1023) hands control to the knob; a touch of the slider
    (touch = counter from the screen, changes on every touch) takes it back. The threshold keeps ADC noise from taking the value away from the slider.
    """

    def __init__(self, knob_takeover=20.0):
        self.knob_takeover = knob_takeover
        self.by_slider = True
        self.touch_last = None
        self.knob_ref = None

    def update(self, touch, knob_raw, link_ok):
        if self.touch_last is None:
            self.touch_last = touch
        elif touch != self.touch_last:
            self.touch_last = touch
            self.by_slider = True
            self.knob_ref = None
        # the knob reading only means something with a link
        if link_ok:
            if self.knob_ref is None:
                self.knob_ref = knob_raw
            elif self.by_slider and abs(knob_raw - self.knob_ref) >= self.knob_takeover:
                self.by_slider = False
        return self.by_slider
