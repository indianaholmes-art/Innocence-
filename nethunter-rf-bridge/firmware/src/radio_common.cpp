#include "radio_hal.h"
#include <string.h>

const char* modulationName(Modulation m) {
  switch (m) {
    case Modulation::FSK2: return "2-FSK";
    case Modulation::GFSK: return "GFSK";
    case Modulation::ASK_OOK: return "ASK/OOK";
    case Modulation::FSK4: return "4-FSK";
    case Modulation::MSK: return "MSK";
  }
  return "?";
}

bool modulationFromName(const char* s, Modulation& out) {
  if (!s) return false;
  struct { const char* n; Modulation m; } t[] = {
      {"2-FSK", Modulation::FSK2}, {"FSK", Modulation::FSK2}, {"2FSK", Modulation::FSK2},
      {"GFSK", Modulation::GFSK},  {"ASK/OOK", Modulation::ASK_OOK}, {"ASK", Modulation::ASK_OOK},
      {"OOK", Modulation::ASK_OOK}, {"4-FSK", Modulation::FSK4}, {"4FSK", Modulation::FSK4},
      {"MSK", Modulation::MSK}};
  for (auto& e : t) if (strcasecmp(s, e.n) == 0) { out = e.m; return true; }
  return false;
}

const char* radioStateName(RadioState s) {
  switch (s) {
    case RadioState::Uninit: return "uninitialized";
    case RadioState::Idle: return "idle";
    case RadioState::Rx: return "receiving";
    case RadioState::Tx: return "transmitting";
    case RadioState::Error: return "error";
  }
  return "?";
}
