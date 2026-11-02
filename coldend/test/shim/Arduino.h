// Minimal Arduino/AVR stand-in so the ColdEnd firmware can run on a PC (tests only).
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#define PROGMEM
#define pgm_read_byte(p) (*(const uint8_t *)(p))
#define A0 14
#define A1 15
#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define _BV(b) (1u << (b))
#define WGM12 3
#define OCIE1A 1
#define ISR(v) void v(void)
extern volatile uint8_t TCCR1A, TCCR1B, TIMSK1, PIND;
extern volatile uint16_t OCR1A, TCNT1;
extern int sim_pin[32];
extern int sim_mode[32];
extern int sim_analog[32];
void pinMode(int p, int m);
void digitalWrite(int p, int v);
int digitalRead(int p);
int analogRead(int p);
unsigned long millis(void);
unsigned long micros(void);
static inline void noInterrupts(void) {}
static inline void interrupts(void) {}
class SimSerial {
public:
  void begin(long) {}
  int available(void);
  int read(void);
  size_t write(const uint8_t *b, size_t n);
};
extern SimSerial Serial;
