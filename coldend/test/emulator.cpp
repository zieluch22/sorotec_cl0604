// ColdEnd firmware emulator: runs the real .ino on a PC, connected to a pseudo
// terminal so mb2hal / test scripts can talk Modbus to it.
//   usage: emulator <symlink-for-pty> <state-file> <inputs-file>
//   inputs-file: "pot_mist pot_spit sw_mist sw_fast sw_air" (raw 0..1023, 0/1), re-read every 100 ms
//   state-file : written every 50 ms with the output pin states
//   <state-file>.oled : OLED RAM as 8 lines of 256 hex chars (page 0..7)
//   env SIM_NO_OLED=1 : behave as if no display is connected
#include "Arduino.h"
#include "Wire.h"
#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <termios.h>
#include <time.h>
#include <string.h>
#include <errno.h>
#include <signal.h>

volatile uint8_t TCCR1A, TCCR1B, TIMSK1, PIND;
volatile uint16_t OCR1A, TCNT1;
int sim_pin[32], sim_mode[32], sim_analog[32];
static int ptyfd = -1;
SimSerial Serial;
TwoWire Wire;
uint8_t sim_oled_addr = 0x3C;
uint8_t sim_oled_fb[8][128];
unsigned long sim_oled_bytes = 0;

static unsigned long long t0;
static unsigned long long now_us() { timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts); return ts.tv_sec * 1000000ULL + ts.tv_nsec / 1000; }
unsigned long millis() { return (unsigned long)((now_us() - t0) / 1000); }
unsigned long micros() { return (unsigned long)(now_us() - t0); }
void pinMode(int p, int m) { sim_mode[p] = m; if (m == INPUT_PULLUP) sim_pin[p] = 1; }
void digitalWrite(int p, int v) { sim_pin[p] = v ? 1 : 0; }
int digitalRead(int p) { return sim_pin[p]; }
int analogRead(int p) { return sim_analog[p]; }
int SimSerial::available() { return 1; }  // read() returns -1 when empty
int SimSerial::read() { uint8_t b; int r = ::read(ptyfd, &b, 1); return r == 1 ? b : -1; }
size_t SimSerial::write(const uint8_t *b, size_t n) { return ::write(ptyfd, b, n); }

#include "../firmware/ColdEnd-LinuxCNC/ColdEnd-LinuxCNC.ino"

static const char *linkpath;
static void bye(int) { unlink(linkpath); _exit(0); }

int main(int argc, char **argv) {
  if (argc < 4) { fprintf(stderr, "usage: %s link state inputs\n", argv[0]); return 1; }
  linkpath = argv[1];
  t0 = now_us();
  ptyfd = posix_openpt(O_RDWR | O_NOCTTY);
  grantpt(ptyfd); unlockpt(ptyfd);
  termios t; tcgetattr(ptyfd, &t); cfmakeraw(&t); tcsetattr(ptyfd, TCSANOW, &t);
  fcntl(ptyfd, F_SETFL, O_NONBLOCK);
  unlink(linkpath);
  if (symlink(ptsname(ptyfd), linkpath)) { perror("symlink"); return 1; }
  // keep a slave fd open so the master does not see EIO before a client connects
  int keep = open(ptsname(ptyfd), O_RDWR | O_NOCTTY);
  { termios s; tcgetattr(keep, &s); cfmakeraw(&s); tcsetattr(keep, TCSANOW, &s); }
  signal(SIGTERM, bye); signal(SIGINT, bye);
  if (getenv("SIM_NO_OLED")) sim_oled_addr = 0;
  setup();
  unsigned long lastIn = 0, lastOut = 0;
  for (;;) {
    loop();
    unsigned long m = millis();
    if (m - lastIn >= 100) {
      lastIn = m;
      FILE *f = fopen(argv[3], "r");
      if (f) { int a, b, c, d, e; if (fscanf(f, "%d %d %d %d %d", &a, &b, &c, &d, &e) == 5) {
          sim_analog[A0] = 1023 - a; sim_analog[A1] = 1023 - b;   // firmware inverts
          sim_pin[8] = !c; sim_pin[7] = !d; sim_pin[9] = !e; } fclose(f); }
    }
    if (m - lastOut >= 50) {
      lastOut = m;
      char tmp[512]; snprintf(tmp, sizeof tmp, "%s.tmp", argv[2]);
      FILE *f = fopen(tmp, "w");
      if (f) {
        fprintf(f, "ena=%d air=%d mistvalve=%d led=%d dir=%d half_us=%lu running=%d fw_active=%d rate_mist=%u rate_fast=%u rate_spit=%u spit_ms=%u ustep=%u spit_left=%u\n",
                sim_pin[PIN_ENA], sim_pin[PIN_AIR_VALVE], sim_pin[PIN_MIST_VALVE], sim_pin[PIN_LED], sim_pin[PIN_DIR],
                (unsigned long)curHalfUs, (TIMSK1 & _BV(OCIE1A)) ? 1 : 0, bits[B_FW_ACTIVE],
                words[W_MIST_RATE], words[W_FAST_RATE], words[W_SPIT_RATE], words[W_SPIT_TIME], words[W_MICROSTEP], words[W_SPIT_LEFT]);
        fclose(f);
        rename(tmp, argv[2]);
      }
      char fbn[512], fbt[512];
      snprintf(fbn, sizeof fbn, "%s.oled", argv[2]); snprintf(fbt, sizeof fbt, "%s.oled.tmp", argv[2]);
      FILE *o = fopen(fbt, "w");
      if (o) {
        for (int pg = 0; pg < 8; pg++) { for (int c = 0; c < 128; c++) fprintf(o, "%02X", sim_oled_fb[pg][c]); fprintf(o, "\n"); }
        fprintf(o, "bytes=%lu present=%d\n", sim_oled_bytes, oledAddr ? 1 : 0);
        fclose(o); rename(fbt, fbn);
      }
    }
    usleep(200);
  }
}
