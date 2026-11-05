# Nudge

An offline, handheld word-finding aid for people with post-stroke aphasia.

![Nudge](docs/renders/nudge-hero.jpg)

Nudge listens to the conversation on-device. When the speaker stalls on a word and presses
the button, it shows and says the three words they most likely meant, in about a second,
with no internet. They say the word themselves. Nothing leaves the device.

- **Recognition over retrieval.** Anomia is a retrieval problem. Three candidates, best first.
- **They say the word.** The device never speaks into the conversation on their behalf.
- **One second.** A smarter answer at three seconds loses the conversation.
- **Their world.** A personal lexicon (names, places, meds, hobbies) rides in every prompt.
- **Nothing leaves the box.** Audio is transcribed in RAM and discarded. No network needed.

## Status (Nov 5, 2026)

Software is complete for v1 and running on the first unit's compute module (Jetson Orin NX 16GB,
JetPack 6.0, MAXN). The GPU run of the stall harness passed the field gate on synthetic stalls:
Qwen2.5-7B Q4 gives **96% top-3 at a 0.94 s median** (p90 1.19 s, max 1.28 s). The 7B is now the default.

| Piece | State |
| --- | --- |
| Aphasia prompt + resolver + prefix cache | done, running on the Jetson GPU |
| Sound-alike engine (CMUdict + wordfreq, gated) | done; sound swaps 100% top-3 on the 7B |
| Personal lexicon + confirmed-word boosting | done |
| 60 s ring buffer | done |
| Stall test harness, 46 synthetic cases | done; **96% top-3, 0.94 s median** on Qwen2.5-7B Q4 (GPU) |
| Service loop, button events, empty-tail guard | done, smoke-tested in `--dev` |
| Touchscreen kiosk UI + family page + stall log | done |
| whisper-stream (CUDA) + Piper (static binary) | built and installed on the Jetson; need the mic/speaker to test end to end |
| XIAO RP2040 button firmware | written; needs the board to flash |
| Jetson setup script | done; ran clean on JetPack 6.0 (systemd units deferred until the screen arrives) |
| Recording ingest → real stall set | written; needs a recording |

Accuracy, 46 synthetic stalls, top-3 (top-1 in parentheses for the GPU runs):

| Config | ALL | anomic | sound | semantic | circumlocution | lexicon | median latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Qwen2.5 1.5B, naive prompt, CPU | 11% | | | | | | |
| Qwen2.5 1.5B, aphasia prompt, CPU | 35% | | | | | | |
| Qwen2.5 3B, aphasia prompt, CPU | 59% | 58% | 50% | 50% | 80% | | 3.6 s |
| Qwen2.5 3B + gated hints, CPU | 63% | 67% | 70% | 50% | 70% | 50% | 3.6 s |
| Qwen2.5 3B + gated hints, Orin NX GPU | 61% (50%) | 67% | 70% | 50% | 60% | 50% | 0.52 s |
| **Qwen2.5 7B + gated hints, Orin NX GPU** | **96% (87%)** | 92% | 100% | 90% | 100% | 100% | **0.94 s** (p90 1.19 s) |

The two 7B misses: "grab something for dinner at the…" → restaurant/diner/cafe (store), and
"the pan… the thing you flip them with" → griddle/skillet (spatula). Both defensible.

Gate to the field unit: 80% top-3 on real stalls, under 1.5 s. Synthetic is passed; real stalls from
a recording of Dad are the next test.

## Hardware (v1 handheld)

One sealed unit, ~100 × 160 × 48 mm, USB-C charged. Jetson Orin NX 16GB (Seeed reComputer Mini J4012),
5" 800×480 touch panel via USB-C→HDMI, 40 mm speaker + PAM8403, electret mic via USB codec, 30 mm arcade
button through a XIAO RP2040 (USB HID), 4× 21700 cells (4S) with an IP2368 USB-C charger board.
Full BOM and exploded view in `docs/`.

## Layout

```
nudge/
  prompt.py      the aphasia prompt
  resolver.py    backend + three-word parser + said-word filter
  phono.py       sound-alike hints (gated on a finished phrase)
  lexicon.py     his world, plus confirmed words
  ring.py        60 s rolling transcript, RAM only
  listener.py    whisper-stream → ring (TypedListener for dev)
  speak.py       Piper → speaker (PrintSpeaker for dev)
  button.py      evdev reader for the XIAO; Button.fire() event bus
  screen.py      HTTP + SSE server for the kiosk page and the family page
  static/        index.html (kiosk), family.html (lexicon editor, log)
  log.py         opt-in CSV stall log
  service.py     the loop
tests/harness.py            scores top-1/top-3 on tests/stalls/{stalls,real}.yaml
tools/ingest_recording.py   recording → transcript → suspected stalls → review YAML → real.yaml
firmware/xiao_button/       Arduino sketch: F13/F14/F15 on click/double/long
scripts/jetson_setup.sh     one-shot CUDA builds, models, systemd, kiosk
```

## Run

On the Jetson (JetPack 6):

```
git clone https://github.com/albertjonasbrand/nudge ~/nudge && cd ~/nudge
./scripts/jetson_setup.sh                     # ~1 h first time; MODEL=qwen2.5-7b for the bigger model
python3 -m tests.harness --model models/qwen2.5-3b-instruct-q4_k_m.gguf
sudo systemctl start nudge nudge-kiosk
```

Anywhere, no hardware:

```
pip install -r requirements.txt
python3 -m tests.harness --model models/<any>.gguf
python3 -m nudge.service --dev                # type lines; blank line = press
```

From a recording of the user:

```
pip install faster-whisper pyannote.audio
python3 tools/ingest_recording.py call.m4a --diarize --dad first
# fill in target words in tests/stalls/review/call.yaml, then
python3 tools/ingest_recording.py --merge tests/stalls/review/call.yaml
python3 -m tests.harness --set real --model models/<any>.gguf
```

## Jetson notes (first unit, Nov 5)

- Seeed reComputer Mini J4012 ships on JetPack 6.0 (L4T 36.3), CUDA 12.2, in 15 W mode with 4 of 8
  cores. `nvpmodel -m 0` (MAXN) needs a reboot; the setup script asks for it.
- No Wi-Fi card in the M.2 Key E slot. Until one is fitted (Intel AX210), the unit gets internet over
  the micro-USB device port through the Mac's Internet Sharing: `nudge-usbnet.service` adds
  192.168.2.2/24 on `l4tbr0` with the Mac at 192.168.2.1. SSH as `albert@192.168.2.2`.
- Serial console: `screen /dev/tty.usbmodem* 115200` on the Mac.
- The repo is private; the Jetson pulls with a read-only deploy key.

## Checklist when the parts land

1. Plug in the Sabrent adapter + mic + speaker; `python3 -m nudge.service` and talk to it.
2. Screen via the Anker USB-C→HDMI; re-run `scripts/jetson_setup.sh` without `NO_SERVICE=1` to install
   the systemd units and the kiosk.
3. Flash the XIAO, wire the button, press it.
4. Fit the Wi-Fi card; drop `nudge-usbnet.service`.
5. Record a call with Dad; ingest; tune on real stalls.
