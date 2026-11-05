// Nudge button: Seeed XIAO RP2040 as a USB keyboard.
//
// Wiring: arcade button between D0 and GND (internal pull-up, no resistor).
//         Optional: button LED anode to D1 through 220R, cathode to GND.
//
// Sends: F13 on a single click, F14 on a double click, F15 on a long press.
// The Jetson reads these with evdev (nudge/button.py).
//
// Flash: Arduino IDE -> board "Seeed XIAO RP2040" (install the Raspberry Pi
// Pico/RP2040 core by Earle Philhower), Tools -> USB Stack: "Adafruit TinyUSB",
// then Upload. Hold BOOT while plugging in if it won't enter the bootloader.

#include <Adafruit_TinyUSB.h>

const int BUTTON_PIN = D0;
const int LED_PIN = D1;

const unsigned long DEBOUNCE_MS = 25;
const unsigned long DOUBLE_MS = 400;     // second press within this = double
const unsigned long LONG_MS = 700;       // held this long = long press

uint8_t const desc_hid_report[] = { TUD_HID_REPORT_DESC_KEYBOARD() };
Adafruit_USBD_HID usb_hid(desc_hid_report, sizeof(desc_hid_report), HID_ITF_PROTOCOL_KEYBOARD, 2, false);

bool pressed = false;
unsigned long pressedAt = 0, releasedAt = 0, lastChange = 0;
bool longFired = false;
int clicks = 0;

void sendKey(uint8_t keycode) {
  if (!usb_hid.ready()) return;
  uint8_t keys[6] = { keycode, 0, 0, 0, 0, 0 };
  usb_hid.keyboardReport(0, 0, keys);
  delay(8);
  usb_hid.keyboardRelease(0);
  digitalWrite(LED_PIN, HIGH); delay(40); digitalWrite(LED_PIN, LOW);
}

void setup() {
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  USBDevice.setManufacturerDescriptor("Nudge");
  USBDevice.setProductDescriptor("XIAO Nudge Button");
  usb_hid.begin();
  while (!TinyUSBDevice.mounted()) delay(1);
}

void loop() {
  unsigned long now = millis();
  bool down = digitalRead(BUTTON_PIN) == LOW;

  if (down != pressed && now - lastChange > DEBOUNCE_MS) {
    lastChange = now;
    pressed = down;
    if (pressed) {
      pressedAt = now;
      longFired = false;
    } else {
      releasedAt = now;
      if (!longFired) clicks++;
    }
  }

  // long press fires while still held, so he gets feedback without letting go
  if (pressed && !longFired && now - pressedAt >= LONG_MS) {
    longFired = true;
    clicks = 0;
    sendKey(HID_KEY_F15);
  }

  // resolve single vs double once the double-click window has passed
  if (!pressed && clicks > 0 && now - releasedAt > DOUBLE_MS) {
    sendKey(clicks >= 2 ? HID_KEY_F14 : HID_KEY_F13);
    clicks = 0;
  }
  delay(2);
}
