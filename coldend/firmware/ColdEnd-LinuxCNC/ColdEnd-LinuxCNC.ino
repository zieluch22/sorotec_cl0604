/*
  ColdEnd-LinuxCNC  -  firmware for the ColdEND pump board (Arduino Nano)
  Controlled by LinuxCNC over Modbus RTU on the Nano's USB port (mb2hal).

  Based on "ColdEND v1.0 Minimum Quantity Lubrication @ TallaMod"
  (Peter Damerau / Talla83, END-CNC), Creative Commons BY-NC-SA 4.0.
  Same pins and same Modbus register addresses as TallaMod.

  Changes compared to TallaMod:
   - Modbus RTU slave built in: NO extra libraries needed (only the Arduino IDE)
   - Step pulses from Timer1 directly (no TimerOne library)
   - Pump rates in ml/h with the calibration of the original ColdEND firmware:
     14400 step pulses per ml (4 pulses/s per ml/h), independent of the
     microstep jumpers - same flow as the original on the same board
   - Rate 0 or a wrong microstep value can no longer divide by zero
   - Link timeout in milliseconds (1 s), not in loop counts
   - Fast mode has priority over coolant mode (TallaMod: both on = pump off)
   - Spit burst starts again every time coolant mode is switched on
   - Bit 8199 reports "firmware active" (LinuxCNC heartbeat received)
   - Knobs and switches are reported even while inactive
   - Register 8456 = firmware version
   - OLED display (SSD1306 128x64, I2C 0x3C/0x3D, like the original ColdEND):
     link status, mode, mist ml/h, spit time, fast ml/h. Works without a display too.

  Serial: 9600 baud, 8N1, slave ID 6.
  Libraries: only Wire (part of the Arduino IDE).

  ---------------- Register map ----------------
  Bits  (read: fn 01/02, write: fn 05/15 - only 8192..8198 writable)
   8192  active / heartbeat   LinuxCNC writes 1 continuously while the machine is on.
                              No write with 1 for 1 s (or a 0 written) = everything OFF.
   8193  LED output           board "Spit on LED" terminal (pin 12)
   8194  coolant mode         pump (mist rate) + air valve
   8195  fast mode            pump only (fast rate) - priming. Has priority.
   8196  spit enable          coolant mode starts with a burst (spit rate, spit time)
   8197  air                  air valve only (when no pump mode is on)
   8198  pump direction
   8199  r  firmware active   1 = heartbeat OK, outputs follow the commands
   8200  r  mist switch       1 = closed
   8201  r  fast switch       1 = closed
   8202  r  air switch        1 = closed
  Words (read: fn 03/04, write: fn 06/16 - only 8451..8455 writable)
   8448  r  mist knob         0..1023
   8449  r  spit knob         0..1023
   8450  r  spit time left    ms
   8451  mist rate            0.1 ml/h  (120 = 12.0 ml/h, 0 = pump off)
   8452  fast rate            0.1 ml/h  (prime)
   8453  spit rate            0.1 ml/h  (burst at mist start)
   8454  spit time            ms        (0 = no burst)
   8455  (reserved - was microstep, not used: calibration is in step pulses)
   8456  r  firmware version
*/

#include <Arduino.h>
#include <Wire.h>

// ---------------- Pins (ColdEND board, same as TallaMod) ----------------
#define PIN_POT_MIST    A0
#define PIN_POT_SPIT    A1
#define PIN_DIR         2
#define PIN_STEP        3      // PD3 - toggled in the Timer1 interrupt
#define PIN_ENA         4      // LOW = stepper driver enabled
#define PIN_SW_FAST     7
#define PIN_SW_MIST     8
#define PIN_SW_AIR      9
#define PIN_AIR_VALVE   10     // LOW = valve open
#define PIN_MIST_VALVE  11     // LOW = valve open (opened while the pump runs)
#define PIN_LED         12

// ---------------- Settings ----------------
#define SLAVE_ID              6
#define BAUD                  9600
#define HEARTBEAT_TIMEOUT_MS  1000UL
#define FRAME_GAP_US          4000UL   // Modbus 3.5 character gap at 9600 baud
#define MIN_HALF_PERIOD_US    25UL     // max 20 kHz step rate
#define HALF_PERIOD_X_RATE    1250000UL // half period [us] = this / rate [0.1 ml/h]
                                        // = original ColdEND: Timer1 period 125000/(ml/h) us,
                                        //   pin toggled each period -> 14400 pulses per ml
#define INPUT_READ_MS         20UL
#define FW_VERSION            3        // 3 = rates in ml/h (2 was rpm)

// ---------------- Register map ----------------
#define BIT_BASE        8192
#define BIT_COUNT       16
#define BIT_WRITABLE    7              // 8192..8198
#define WORD_BASE       8448
#define WORD_COUNT      9
#define WORD_WR_FIRST   3              // 8451
#define WORD_WR_LAST    7              // 8455

enum { B_ACTIVE = 0, B_LED, B_COOLANT, B_FAST, B_SPIT, B_AIR, B_DIR,
       B_FW_ACTIVE, B_SW_MIST, B_SW_FAST, B_SW_AIR };
enum { W_POT_MIST = 0, W_POT_SPIT, W_SPIT_LEFT, W_MIST_RATE, W_FAST_RATE,
       W_SPIT_RATE, W_SPIT_TIME, W_MICROSTEP, W_VERSION };

static bool     bits[BIT_COUNT];
static uint16_t words[WORD_COUNT];

static unsigned long lastHeartbeatMs = 0;
static bool          heartbeatSeen   = false;

// ======================================================================
//  Stepper (Timer1 CTC, interrupt toggles the STEP pin)
// ======================================================================
static uint32_t curHalfUs = 0;          // 0 = stopped

static void timerSetHalfPeriod(uint32_t us) {
  static const uint16_t prescale[] = {1, 8, 64, 256, 1024};
  static const uint8_t  csBits[]   = {1, 2, 3, 4, 5};
  uint8_t  i;
  uint32_t ticks = 0;
  for (i = 0; i < 5; i++) {
    ticks = (us * 16UL) / prescale[i];  // 16 MHz clock
    if (ticks <= 65536UL) break;
  }
  if (i == 5) { i = 4; ticks = 65536UL; }
  if (ticks < 2) ticks = 2;
  noInterrupts();
  TCCR1A = 0;                           // no PWM on pins 9/10
  TCCR1B = _BV(WGM12) | csBits[i];      // CTC mode, prescaler
  OCR1A  = (uint16_t)(ticks - 1);
  if (TCNT1 > OCR1A) TCNT1 = 0;
  TIMSK1 |= _BV(OCIE1A);
  interrupts();
}

ISR(TIMER1_COMPA_vect) {
  PIND = _BV(3);                        // toggle PD3 = STEP (two toggles = one step)
}

static void stepperStop() {
  noInterrupts();
  TIMSK1 &= ~_BV(OCIE1A);
  TCCR1B = 0;
  interrupts();
  curHalfUs = 0;
  digitalWrite(PIN_STEP, LOW);
  digitalWrite(PIN_ENA, HIGH);
  digitalWrite(PIN_MIST_VALVE, HIGH);
}

// rate in 0.1 ml/h
static void stepperRun(uint16_t rate) {
  if (rate == 0) { stepperStop(); return; }
  uint32_t half = HALF_PERIOD_X_RATE / rate;
  if (half < MIN_HALF_PERIOD_US) half = MIN_HALF_PERIOD_US;
  digitalWrite(PIN_MIST_VALVE, LOW);
  digitalWrite(PIN_ENA, LOW);
  if (half != curHalfUs) {
    timerSetHalfPeriod(half);
    curHalfUs = half;
  }
}

static void setAir(bool on) {
  digitalWrite(PIN_AIR_VALVE, on ? LOW : HIGH);
}

// ======================================================================
//  Modbus RTU slave
// ======================================================================
static uint8_t       rxBuf[64];
static uint8_t       rxLen      = 0;
static bool          rxOverflow = false;
static unsigned long lastByteUs = 0;
static uint8_t       txBuf[40];

static uint16_t crc16(const uint8_t *d, uint8_t n) {
  uint16_t crc = 0xFFFF;
  for (uint8_t i = 0; i < n; i++) {
    crc ^= d[i];
    for (uint8_t b = 0; b < 8; b++)
      crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : (crc >> 1);
  }
  return crc;
}

static uint16_t be16(const uint8_t *p) { return ((uint16_t)p[0] << 8) | p[1]; }

static void mbSend(uint8_t len) {
  uint16_t crc = crc16(txBuf, len);
  txBuf[len++] = crc & 0xFF;
  txBuf[len++] = crc >> 8;
  Serial.write(txBuf, len);
}

static void mbException(uint8_t fn, uint8_t code) {
  txBuf[0] = SLAVE_ID;
  txBuf[1] = fn | 0x80;
  txBuf[2] = code;
  mbSend(3);
}

static void bitsWritten(uint16_t first, uint16_t qty) {
  // heartbeat: a write that covers 8192 with value 1
  if (first == BIT_BASE && qty >= 1 && bits[B_ACTIVE]) {
    lastHeartbeatMs = millis();
    heartbeatSeen   = true;
  }
}

static void mbHandle(const uint8_t *f, uint8_t n) {
  if (n < 4) return;
  if (crc16(f, n - 2) != (uint16_t)(f[n - 2] | (f[n - 1] << 8))) return;
  if (f[0] != SLAVE_ID) return;               // other slave or broadcast: ignore
  uint8_t fn = f[1];
  txBuf[0] = SLAVE_ID;
  txBuf[1] = fn;

  switch (fn) {
    case 1:                                   // read coils
    case 2: {                                 // read discrete inputs
      if (n != 8) return;
      uint16_t addr = be16(f + 2), qty = be16(f + 4);
      if (qty < 1 || qty > BIT_COUNT) { mbException(fn, 3); return; }
      if (addr < BIT_BASE || (uint32_t)addr + qty > BIT_BASE + BIT_COUNT) { mbException(fn, 2); return; }
      uint8_t bytes = (qty + 7) / 8;
      txBuf[2] = bytes;
      for (uint8_t i = 0; i < bytes; i++) txBuf[3 + i] = 0;
      for (uint16_t i = 0; i < qty; i++)
        if (bits[addr - BIT_BASE + i]) txBuf[3 + i / 8] |= 1 << (i % 8);
      mbSend(3 + bytes);
      return;
    }
    case 3:                                   // read holding registers
    case 4: {                                 // read input registers
      if (n != 8) return;
      uint16_t addr = be16(f + 2), qty = be16(f + 4);
      if (qty < 1 || qty > WORD_COUNT) { mbException(fn, 3); return; }
      if (addr < WORD_BASE || (uint32_t)addr + qty > WORD_BASE + WORD_COUNT) { mbException(fn, 2); return; }
      txBuf[2] = qty * 2;
      for (uint16_t i = 0; i < qty; i++) {
        uint16_t v = words[addr - WORD_BASE + i];
        txBuf[3 + 2 * i] = v >> 8;
        txBuf[4 + 2 * i] = v & 0xFF;
      }
      mbSend(3 + qty * 2);
      return;
    }
    case 5: {                                 // write single coil
      if (n != 8) return;
      uint16_t addr = be16(f + 2), val = be16(f + 4);
      if (val != 0xFF00 && val != 0x0000) { mbException(fn, 3); return; }
      if (addr < BIT_BASE || addr >= BIT_BASE + BIT_WRITABLE) { mbException(fn, 2); return; }
      bits[addr - BIT_BASE] = (val == 0xFF00);
      bitsWritten(addr, 1);
      for (uint8_t i = 2; i < 6; i++) txBuf[i] = f[i];
      mbSend(6);
      return;
    }
    case 6: {                                 // write single register
      if (n != 8) return;
      uint16_t addr = be16(f + 2), val = be16(f + 4);
      if (addr < WORD_BASE + WORD_WR_FIRST || addr > WORD_BASE + WORD_WR_LAST) { mbException(fn, 2); return; }
      words[addr - WORD_BASE] = val;
      for (uint8_t i = 2; i < 6; i++) txBuf[i] = f[i];
      mbSend(6);
      return;
    }
    case 15: {                                // write multiple coils
      if (n < 10) return;
      uint16_t addr = be16(f + 2), qty = be16(f + 4);
      uint8_t  bc = f[6];
      if (n != 9 + bc) return;
      if (qty < 1 || qty > BIT_WRITABLE || bc != (qty + 7) / 8) { mbException(fn, 3); return; }
      if (addr < BIT_BASE || (uint32_t)addr + qty > BIT_BASE + BIT_WRITABLE) { mbException(fn, 2); return; }
      for (uint16_t i = 0; i < qty; i++)
        bits[addr - BIT_BASE + i] = (f[7 + i / 8] >> (i % 8)) & 1;
      bitsWritten(addr, qty);
      for (uint8_t i = 2; i < 6; i++) txBuf[i] = f[i];
      mbSend(6);
      return;
    }
    case 16: {                                // write multiple registers
      if (n < 11) return;
      uint16_t addr = be16(f + 2), qty = be16(f + 4);
      uint8_t  bc = f[6];
      if (n != 9 + bc) return;
      if (qty < 1 || qty > WORD_COUNT || bc != qty * 2) { mbException(fn, 3); return; }
      if (addr < WORD_BASE + WORD_WR_FIRST || (uint32_t)addr + qty > WORD_BASE + WORD_WR_LAST + 1) { mbException(fn, 2); return; }
      for (uint16_t i = 0; i < qty; i++) words[addr - WORD_BASE + i] = be16(f + 7 + 2 * i);
      for (uint8_t i = 2; i < 6; i++) txBuf[i] = f[i];
      mbSend(6);
      return;
    }
    default:
      mbException(fn, 1);                     // illegal function
      return;
  }
}

static void mbPoll() {
  while (Serial.available() > 0) {
    int b = Serial.read();
    if (b < 0) break;
    if (rxLen < sizeof(rxBuf)) rxBuf[rxLen++] = (uint8_t)b;
    else rxOverflow = true;
    lastByteUs = micros();
  }
  if (rxLen > 0 && (unsigned long)(micros() - lastByteUs) > FRAME_GAP_US) {
    if (!rxOverflow) mbHandle(rxBuf, rxLen);
    rxLen = 0;
    rxOverflow = false;
  }
}

// ======================================================================
//  OLED display  (SSD1306 128x64 on I2C A4/A5, optional)
//  Text only, no frame buffer (saves 1 KB RAM). One 8-pixel row ("page")
//  is sent every OLED_PAGE_MS and only if its text changed, so the loop is
//  never blocked for more than ~3 ms (Modbus and step pulses keep running).
// ======================================================================
#define OLED_PAGE_MS    15UL
#define OLED_RETRY_MS   5000UL

// 5x7 font, ASCII 32..126 (Adafruit GFX "glcdfont", BSD license)
static const uint8_t font5x7[] PROGMEM = {
  0x00, 0x00, 0x00, 0x00, 0x00,  // ' '
  0x00, 0x00, 0x5F, 0x00, 0x00,  // '!'
  0x00, 0x07, 0x00, 0x07, 0x00,  // '"'
  0x14, 0x7F, 0x14, 0x7F, 0x14,  // '#'
  0x24, 0x2A, 0x7F, 0x2A, 0x12,  // '$'
  0x23, 0x13, 0x08, 0x64, 0x62,  // '%'
  0x36, 0x49, 0x56, 0x20, 0x50,  // '&'
  0x00, 0x08, 0x07, 0x03, 0x00,  // '''
  0x00, 0x1C, 0x22, 0x41, 0x00,  // '('
  0x00, 0x41, 0x22, 0x1C, 0x00,  // ')'
  0x2A, 0x1C, 0x7F, 0x1C, 0x2A,  // '*'
  0x08, 0x08, 0x3E, 0x08, 0x08,  // '+'
  0x00, 0x80, 0x70, 0x30, 0x00,  // ','
  0x08, 0x08, 0x08, 0x08, 0x08,  // '-'
  0x00, 0x00, 0x60, 0x60, 0x00,  // '.'
  0x20, 0x10, 0x08, 0x04, 0x02,  // '/'
  0x3E, 0x51, 0x49, 0x45, 0x3E,  // '0'
  0x00, 0x42, 0x7F, 0x40, 0x00,  // '1'
  0x72, 0x49, 0x49, 0x49, 0x46,  // '2'
  0x21, 0x41, 0x49, 0x4D, 0x33,  // '3'
  0x18, 0x14, 0x12, 0x7F, 0x10,  // '4'
  0x27, 0x45, 0x45, 0x45, 0x39,  // '5'
  0x3C, 0x4A, 0x49, 0x49, 0x31,  // '6'
  0x41, 0x21, 0x11, 0x09, 0x07,  // '7'
  0x36, 0x49, 0x49, 0x49, 0x36,  // '8'
  0x46, 0x49, 0x49, 0x29, 0x1E,  // '9'
  0x00, 0x00, 0x14, 0x00, 0x00,  // ':'
  0x00, 0x40, 0x34, 0x00, 0x00,  // ';'
  0x00, 0x08, 0x14, 0x22, 0x41,  // '<'
  0x14, 0x14, 0x14, 0x14, 0x14,  // '='
  0x00, 0x41, 0x22, 0x14, 0x08,  // '>'
  0x02, 0x01, 0x59, 0x09, 0x06,  // '?'
  0x3E, 0x41, 0x5D, 0x59, 0x4E,  // '@'
  0x7C, 0x12, 0x11, 0x12, 0x7C,  // 'A'
  0x7F, 0x49, 0x49, 0x49, 0x36,  // 'B'
  0x3E, 0x41, 0x41, 0x41, 0x22,  // 'C'
  0x7F, 0x41, 0x41, 0x41, 0x3E,  // 'D'
  0x7F, 0x49, 0x49, 0x49, 0x41,  // 'E'
  0x7F, 0x09, 0x09, 0x09, 0x01,  // 'F'
  0x3E, 0x41, 0x41, 0x51, 0x73,  // 'G'
  0x7F, 0x08, 0x08, 0x08, 0x7F,  // 'H'
  0x00, 0x41, 0x7F, 0x41, 0x00,  // 'I'
  0x20, 0x40, 0x41, 0x3F, 0x01,  // 'J'
  0x7F, 0x08, 0x14, 0x22, 0x41,  // 'K'
  0x7F, 0x40, 0x40, 0x40, 0x40,  // 'L'
  0x7F, 0x02, 0x1C, 0x02, 0x7F,  // 'M'
  0x7F, 0x04, 0x08, 0x10, 0x7F,  // 'N'
  0x3E, 0x41, 0x41, 0x41, 0x3E,  // 'O'
  0x7F, 0x09, 0x09, 0x09, 0x06,  // 'P'
  0x3E, 0x41, 0x51, 0x21, 0x5E,  // 'Q'
  0x7F, 0x09, 0x19, 0x29, 0x46,  // 'R'
  0x26, 0x49, 0x49, 0x49, 0x32,  // 'S'
  0x03, 0x01, 0x7F, 0x01, 0x03,  // 'T'
  0x3F, 0x40, 0x40, 0x40, 0x3F,  // 'U'
  0x1F, 0x20, 0x40, 0x20, 0x1F,  // 'V'
  0x3F, 0x40, 0x38, 0x40, 0x3F,  // 'W'
  0x63, 0x14, 0x08, 0x14, 0x63,  // 'X'
  0x03, 0x04, 0x78, 0x04, 0x03,  // 'Y'
  0x61, 0x59, 0x49, 0x4D, 0x43,  // 'Z'
  0x00, 0x7F, 0x41, 0x41, 0x41,  // '['
  0x02, 0x04, 0x08, 0x10, 0x20,  // 'backslash'
  0x00, 0x41, 0x41, 0x41, 0x7F,  // ']'
  0x04, 0x02, 0x01, 0x02, 0x04,  // '^'
  0x40, 0x40, 0x40, 0x40, 0x40,  // '_'
  0x00, 0x03, 0x07, 0x08, 0x00,  // '`'
  0x20, 0x54, 0x54, 0x78, 0x40,  // 'a'
  0x7F, 0x28, 0x44, 0x44, 0x38,  // 'b'
  0x38, 0x44, 0x44, 0x44, 0x28,  // 'c'
  0x38, 0x44, 0x44, 0x28, 0x7F,  // 'd'
  0x38, 0x54, 0x54, 0x54, 0x18,  // 'e'
  0x00, 0x08, 0x7E, 0x09, 0x02,  // 'f'
  0x18, 0xA4, 0xA4, 0x9C, 0x78,  // 'g'
  0x7F, 0x08, 0x04, 0x04, 0x78,  // 'h'
  0x00, 0x44, 0x7D, 0x40, 0x00,  // 'i'
  0x20, 0x40, 0x40, 0x3D, 0x00,  // 'j'
  0x7F, 0x10, 0x28, 0x44, 0x00,  // 'k'
  0x00, 0x41, 0x7F, 0x40, 0x00,  // 'l'
  0x7C, 0x04, 0x78, 0x04, 0x78,  // 'm'
  0x7C, 0x08, 0x04, 0x04, 0x78,  // 'n'
  0x38, 0x44, 0x44, 0x44, 0x38,  // 'o'
  0xFC, 0x18, 0x24, 0x24, 0x18,  // 'p'
  0x18, 0x24, 0x24, 0x18, 0xFC,  // 'q'
  0x7C, 0x08, 0x04, 0x04, 0x08,  // 'r'
  0x48, 0x54, 0x54, 0x54, 0x24,  // 's'
  0x04, 0x04, 0x3F, 0x44, 0x24,  // 't'
  0x3C, 0x40, 0x40, 0x20, 0x7C,  // 'u'
  0x1C, 0x20, 0x40, 0x20, 0x1C,  // 'v'
  0x3C, 0x40, 0x30, 0x40, 0x3C,  // 'w'
  0x44, 0x28, 0x10, 0x28, 0x44,  // 'x'
  0x4C, 0x90, 0x90, 0x90, 0x7C,  // 'y'
  0x44, 0x64, 0x54, 0x4C, 0x44,  // 'z'
  0x00, 0x08, 0x36, 0x41, 0x00,  // '{'
  0x00, 0x00, 0x77, 0x00, 0x00,  // '|'
  0x00, 0x41, 0x36, 0x08, 0x00,  // '}'
  0x02, 0x01, 0x02, 0x04, 0x02,  // '~'
};

static const uint8_t oledInitSeq[] PROGMEM = {
  0xAE,             // display off
  0xD5, 0x80,       // clock
  0xA8, 0x3F,       // multiplex 64 lines
  0xD3, 0x00,       // no offset
  0x40,             // start line 0
  0x8D, 0x14,       // charge pump on
  0x20, 0x00,       // horizontal addressing
  0xA1, 0xC8,       // segment remap + COM scan direction (normal orientation)
  0xDA, 0x12,       // COM pins for 128x64
  0x81, 0xCF,       // contrast
  0xD9, 0xF1,       // pre-charge
  0xDB, 0x40,       // VCOM detect
  0xA4, 0xA6,       // show RAM, not inverted
  0x2E,             // no scrolling
  0xAF              // display on
};

enum { MODE_STANDBY = 0, MODE_OFF, MODE_MIST, MODE_SPIT, MODE_PRIME, MODE_AIR };
static uint8_t       dispMode    = MODE_STANDBY;
static uint8_t       oledAddr    = 0;          // 0 = no display found
static unsigned long oledLastMs  = 0;
static unsigned long oledRetryMs = 0;
static uint8_t       oledPage    = 0;
static char          oledShown[8][22];         // text currently on each page

static bool oledProbe(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

static bool oledCmds(const uint8_t *c, uint8_t n, bool progmem) {
  Wire.beginTransmission(oledAddr);
  Wire.write((uint8_t)0x00);                    // control byte: commands
  for (uint8_t i = 0; i < n; i++) Wire.write(progmem ? pgm_read_byte(c + i) : c[i]);
  return Wire.endTransmission() == 0;
}

static void oledInit() {
  oledAddr = oledProbe(0x3C) ? 0x3C : (oledProbe(0x3D) ? 0x3D : 0);
  if (!oledAddr) return;
  if (!oledCmds(oledInitSeq, sizeof(oledInitSeq), true)) { oledAddr = 0; return; }
  memset(oledShown, 0, sizeof(oledShown));      // force a full redraw
  oledPage = 0;
}

static uint8_t glyphCol(char ch, uint8_t col) {
  if (ch < 32 || ch > 126) ch = ' ';
  if (col >= 5) return 0;                       // 1 pixel gap between characters
  return pgm_read_byte(&font5x7[(ch - 32) * 5 + col]);
}

static uint8_t stretch4(uint8_t nib) {          // 4 pixel bits -> 8 (double height)
  uint8_t r = 0;
  for (uint8_t i = 0; i < 4; i++) if (nib & (1 << i)) r |= 3 << (2 * i);
  return r;
}

// big: 0 = normal text (21 chars), 1 = top half, 2 = bottom half of 2x text (10 chars)
static bool oledWritePage(uint8_t page, const char *txt, uint8_t big) {
  const uint8_t addr[] = {0x21, 0, 127, 0x22, page, page};
  if (!oledCmds(addr, sizeof(addr), false)) return false;
  for (uint8_t x = 0; x < 128; x += 16) {
    Wire.beginTransmission(oledAddr);
    Wire.write((uint8_t)0x40);                  // control byte: data
    for (uint8_t j = 0; j < 16; j++) {
      uint8_t col = x + j, b = 0;
      if (!big) {
        uint8_t ci = col / 6;
        if (ci < 21) b = glyphCol(txt[ci], col % 6);
      } else {
        uint8_t ci = col / 12;
        if (ci < 10) {
          uint8_t g = glyphCol(txt[ci], (col % 12) / 2);
          b = stretch4(big == 1 ? (g & 0x0F) : (g >> 4));
        }
      }
      Wire.write(b);
    }
    if (Wire.endTransmission() != 0) return false;
  }
  return true;
}

static void padLine(char *buf, uint8_t width) { // fill with spaces up to width
  uint8_t n = strlen(buf);
  while (n < width) buf[n++] = ' ';
  buf[width] = 0;
}

// ml/h like the original display: one decimal below 10 ml/h, whole numbers above
static void fmtFlow(char *buf, const char *label, uint16_t rate) {
  if (rate < 100) snprintf(buf, 22, "%-10s%4u.%u ml/h", label, rate / 10, rate % 10);
  else            snprintf(buf, 22, "%-10s%6u ml/h", label, (rate + 5) / 10);
}

static void oledText(uint8_t page, char *buf) {
  buf[0] = 0;
  bool active = bits[B_FW_ACTIVE];
  switch (page) {
    case 0:
      strcpy(buf, active ? "ColdEnd   LinuxCNC OK" : "ColdEnd       NO LINK");
      break;
    case 1:
    case 2: {                                   // big mode text, centred
      char m[11];
      switch (dispMode) {
        case MODE_OFF:   strcpy(m, "OFF");   break;
        case MODE_MIST:  strcpy(m, "MIST");  break;
        case MODE_PRIME: strcpy(m, "PRIME"); break;
        case MODE_AIR:   strcpy(m, "AIR");   break;
        case MODE_SPIT: {
          uint16_t t = (words[W_SPIT_LEFT] + 99) / 100;   // 0.1 s, rounded up
          snprintf(m, sizeof(m), "SPIT %u.%u", t / 10, t % 10);
          break;
        }
        default:         strcpy(m, "STANDBY"); break;
      }
      uint8_t pad = (10 - strlen(m)) / 2;
      memset(buf, ' ', pad);
      strcpy(buf + pad, m);
      padLine(buf, 10);
      return;
    }
    case 4:
      if (words[W_MIST_RATE] == 0) strcpy(buf, "Mist             off");
      else fmtFlow(buf, "Mist", words[W_MIST_RATE]);
      break;
    case 5: {
      uint16_t t = (words[W_SPIT_TIME] + 50) / 100;   // 0.1 s
      if (t == 0) strcpy(buf, "Spit time        off");
      else snprintf(buf, 22, "Spit time   %4u.%u s", t / 10, t % 10);
      break;
    }
    case 6: fmtFlow(buf, "Spit/Fast", words[W_FAST_RATE]); break;
    default: break;                             // pages 3 and 7: empty
  }
  padLine(buf, 21);
}

static void displayTask(unsigned long now) {
  if (!oledAddr) {
    if (now - oledRetryMs >= OLED_RETRY_MS || oledRetryMs == 0) {
      oledRetryMs = now | 1;
      oledInit();
    }
    return;
  }
  if (now - oledLastMs < OLED_PAGE_MS) return;
  oledLastMs = now;
  char buf[24];
  oledText(oledPage, buf);
  if (strcmp(buf, oledShown[oledPage]) != 0) {
    uint8_t big = (oledPage == 1) ? 1 : (oledPage == 2) ? 2 : 0;
    if (oledWritePage(oledPage, buf, big)) {
      strcpy(oledShown[oledPage], buf);
    } else {
      oledAddr = 0;                             // display gone - look again later
      oledRetryMs = now | 1;
    }
  }
  oledPage = (oledPage + 1) & 7;
}

// ======================================================================
//  Main
// ======================================================================
static unsigned long lastInputMs = 0;
static bool          coolantWas  = false;
static unsigned long spitStartMs = 0;

static void allOff() {
  stepperStop();
  setAir(false);
  digitalWrite(PIN_LED, LOW);
  digitalWrite(PIN_DIR, LOW);
  coolantWas = false;
  words[W_SPIT_LEFT] = 0;
}

void setup() {
  // outputs to a safe state BEFORE they become outputs
  digitalWrite(PIN_ENA, HIGH);
  digitalWrite(PIN_AIR_VALVE, HIGH);
  digitalWrite(PIN_MIST_VALVE, HIGH);
  digitalWrite(PIN_STEP, LOW);
  digitalWrite(PIN_DIR, LOW);
  digitalWrite(PIN_LED, LOW);
  pinMode(PIN_ENA, OUTPUT);
  pinMode(PIN_AIR_VALVE, OUTPUT);
  pinMode(PIN_MIST_VALVE, OUTPUT);
  pinMode(PIN_STEP, OUTPUT);
  pinMode(PIN_DIR, OUTPUT);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_SW_MIST, INPUT_PULLUP);
  pinMode(PIN_SW_FAST, INPUT_PULLUP);
  pinMode(PIN_SW_AIR, INPUT_PULLUP);

  words[W_MIST_RATE] = 100;    // 10 ml/h      - LinuxCNC overwrites these
  words[W_FAST_RATE] = 15625;  // 1562.5 ml/h  = original fast / spit speed
  words[W_SPIT_RATE] = 15625;
  words[W_SPIT_TIME] = 0;
  words[W_MICROSTEP] = 16;
  words[W_VERSION]   = FW_VERSION;

  allOff();
  Serial.begin(BAUD);          // 8N1

  Wire.begin();
  Wire.setClock(400000);
  Wire.setWireTimeout(5000, true);  // a broken display must never hang the pump control
}

static void control(unsigned long now);

void loop() {
  mbPoll();
  unsigned long now = millis();
  control(now);
  displayTask(now);
}

static void control(unsigned long now) {

  if (now - lastInputMs >= INPUT_READ_MS) {
    lastInputMs = now;
    words[W_POT_MIST] = 1023 - analogRead(PIN_POT_MIST);
    words[W_POT_SPIT] = 1023 - analogRead(PIN_POT_SPIT);
    bits[B_SW_MIST]   = !digitalRead(PIN_SW_MIST);
    bits[B_SW_FAST]   = !digitalRead(PIN_SW_FAST);
    bits[B_SW_AIR]    = !digitalRead(PIN_SW_AIR);
  }

  bool active = bits[B_ACTIVE] && heartbeatSeen &&
                (now - lastHeartbeatMs < HEARTBEAT_TIMEOUT_MS);
  bits[B_FW_ACTIVE] = active;

  if (!active) {
    if (curHalfUs != 0 || coolantWas || digitalRead(PIN_ENA) == LOW) allOff();
    setAir(false);
    digitalWrite(PIN_LED, LOW);
    dispMode = MODE_STANDBY;
    return;
  }

  digitalWrite(PIN_DIR, bits[B_DIR] ? HIGH : LOW);
  digitalWrite(PIN_LED, bits[B_LED] ? HIGH : LOW);

  bool fast    = bits[B_FAST];
  bool coolant = bits[B_COOLANT] && !fast;

  if (coolant) {
    if (!coolantWas) spitStartMs = now;
    coolantWas = true;
    uint16_t rate = words[W_MIST_RATE];
    unsigned long elapsed = now - spitStartMs;
    if (bits[B_SPIT] && elapsed < words[W_SPIT_TIME]) {
      rate = words[W_SPIT_RATE];
      words[W_SPIT_LEFT] = words[W_SPIT_TIME] - elapsed;
    } else {
      words[W_SPIT_LEFT] = 0;
    }
    setAir(true);
    stepperRun(rate);
    dispMode = words[W_SPIT_LEFT] ? MODE_SPIT : MODE_MIST;
  } else {
    coolantWas = false;
    words[W_SPIT_LEFT] = 0;
    if (fast) stepperRun(words[W_FAST_RATE]);
    else      stepperStop();
    setAir(bits[B_AIR]);
    dispMode = fast ? MODE_PRIME : (bits[B_AIR] ? MODE_AIR : MODE_OFF);
  }
}
