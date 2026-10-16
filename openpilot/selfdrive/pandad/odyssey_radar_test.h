#pragma once

#include <cstddef>
#include <cstdint>

// Parked diagnostics may only read known identifiers or acknowledge ISO-TP data.
inline bool odyssey_radar_test_tx(uint32_t address, uint8_t bus, const uint8_t *data, size_t size) {
  if (bus != 1 || (address != 0x18DAB0F1U && address != 0x18DAB5F1U) || size != 8) return false;
  for (size_t i = 4; i < size; ++i) {
    if (data[i] != 0) return false;
  }
  const bool flow_control = data[0] == 0x30 && data[1] == 0 && data[2] == 0 && data[3] == 0;
  const bool read = data[0] == 3 && data[1] == 0x22 && data[2] == 0xF1 &&
                    (data[3] == 0x81 || data[3] == 0x12 || data[3] == 0x91);
  return flow_control || read;
}
