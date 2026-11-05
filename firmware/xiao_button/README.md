# XIAO button firmware

The 30 mm arcade button talks to the Jetson as a USB keyboard through a Seeed
XIAO RP2040, because the reComputer Mini's base board has no GPIO header.

| Press | Key sent | Nudge does |
| --- | --- | --- |
| click | F13 | three words |
| double click | F14 | three more |
| hold 0.7 s | F15 | say the three again |

## Wiring

- Button NO terminal → XIAO **D0**; other terminal → **GND** (internal pull-up, no resistor)
- Optional button LED: anode → **D1** via 220 Ω, cathode → GND (flashes on each press)
- XIAO USB-C → the Mini's USB-A port with a short cable

## Flashing

1. Arduino IDE → Boards Manager → install "Raspberry Pi Pico/RP2040" (Earle Philhower)
2. Board: **Seeed XIAO RP2040**; Tools → USB Stack: **Adafruit TinyUSB**
3. Open `xiao_button.ino`, Upload. If it won't connect, hold **BOOT** while plugging in, release, upload again.

On the Jetson, `ls /dev/input/by-id/ | grep -i nudge` should show it. `nudge/button.py`
finds it by name ("XIAO" in the device name) and keeps rescanning if it's unplugged.
