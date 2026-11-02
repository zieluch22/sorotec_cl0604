# Build + flash the ColdEnd firmware from the LinuxCNC PC (no Arduino IDE needed).
#   needs: sudo apt install gcc-avr avr-libc arduino-core-avr arduino-mk avrdude
#   make            build -> build-nano-atmega328/ColdEnd-LinuxCNC_.hex
#   make upload     build + flash to /dev/coldend (Nano, new bootloader, 115200)
ARDUINO_DIR      = /usr/share/arduino
BOARD_TAG        = nano
BOARD_SUB        = atmega328
ARDUINO_LIBS     = Wire
MONITOR_PORT     = /dev/coldend
AVRDUDE_ARD_BAUDRATE = 115200
# Debian's avr-gcc float.h lacks DECIMAL_DIG (needed by the core's WString.cpp)
CPPFLAGS        += -DDECIMAL_DIG=17
include /usr/share/arduino/Arduino.mk
