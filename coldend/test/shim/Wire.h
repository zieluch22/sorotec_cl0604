// Wire stand-in for the PC emulator: behaves like an SSD1306 128x64 at 0x3C
// (or no display at all when sim_oled_addr = 0). Keeps the display RAM in
// sim_oled_fb[page][column] so tests can render what the OLED would show.
#pragma once
#include <stdint.h>
#include <stddef.h>
extern uint8_t sim_oled_addr;
extern uint8_t sim_oled_fb[8][128];
extern unsigned long sim_oled_bytes;
class TwoWire {
  uint8_t addr = 0, buf[40], n = 0;
  uint8_t colStart = 0, colEnd = 127, pageStart = 0, pageEnd = 7, col = 0, page = 0;
  int pend = 0; uint8_t pendCmd = 0, pendArg = 0;
public:
  void begin() {}
  void setClock(uint32_t) {}
  void setWireTimeout(uint32_t = 25000, bool = false) {}
  void beginTransmission(uint8_t a) { addr = a; n = 0; }
  size_t write(uint8_t b) { if (n < sizeof(buf)) buf[n++] = b; return 1; }
  uint8_t endTransmission() {
    if (addr != sim_oled_addr || sim_oled_addr == 0) return 2;   // NACK
    if (n == 0) return 0;
    if (n > 32) return 1;                                         // Wire buffer is 32 bytes
    sim_oled_bytes += n;
    if (buf[0] == 0x00) {                                         // commands
      for (uint8_t i = 1; i < n; i++) cmd(buf[i]);
    } else if (buf[0] == 0x40) {                                  // data
      for (uint8_t i = 1; i < n; i++) {
        sim_oled_fb[page & 7][col & 127] = buf[i];
        if (col >= colEnd) { col = colStart; page = (page >= pageEnd) ? pageStart : page + 1; }
        else col++;
      }
    }
    return 0;
  }
private:
  void cmd(uint8_t c) {
    if (pend) {
      if (pendCmd == 0x21) { if (pendArg == 0) colStart = c; else { colEnd = c; col = colStart; } }
      if (pendCmd == 0x22) { if (pendArg == 0) pageStart = c; else { pageEnd = c; page = pageStart; } }
      pendArg++; pend--; return;
    }
    pendCmd = c; pendArg = 0;
    switch (c) {
      case 0x21: case 0x22: pend = 2; break;
      case 0xD5: case 0xA8: case 0xD3: case 0x8D: case 0x20: case 0xDA: case 0x81: case 0xD9: case 0xDB: pend = 1; break;
      default: pend = 0;
    }
  }
};
extern TwoWire Wire;
