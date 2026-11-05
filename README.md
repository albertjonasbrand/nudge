# Nudge

An offline, pocket-size word-finding aid for people with post-stroke aphasia.

Nudge listens to the conversation on-device. When the speaker stalls on a word and clicks
a button, it shows and whispers the three most likely words they meant, in about one second,
with no internet. They pick one and say it themselves.

Built for one person first. Design spec lives in the Claude project; the short version:

- **Recognition over retrieval.** Anomia is a retrieval problem. Three candidates, best first.
- **He says the word.** The device never speaks into the conversation on his behalf.
- **One second.** A smarter answer at three seconds loses the conversation.
- **His world.** A personal lexicon (names, places, meds, hobbies) rides in the prompt.
- **Nothing leaves the box.** Audio is transcribed in RAM and discarded. No network needed.

## Hardware (v1)

- NVIDIA Jetson Orin NX 16GB in a Seeed reComputer Mini J4012
- Clip-on lav mic + USB audio adapter, wired mono earbud
- Pocket BLE clicker (Flic 2 or camera shutter) + one button on the box
- 3.5" screen as fallback view
- USB-C PD power bank → XT30

## Software

```
mic → whisper.cpp (streaming) → 60 s text ring buffer → llama.cpp (warm prefix cache)
                                                             ↓ on click
                                                   3 words → Piper TTS → earbud
                                                           → screen
```

| Module | Does |
| --- | --- |
| `nudge/listener.py` | Streams mic audio through whisper.cpp into the ring buffer |
| `nudge/ring.py` | 60 s rolling transcript, RAM only |
| `nudge/resolver.py` | Builds the aphasia prompt, calls the LLM, parses three words |
| `nudge/lexicon.py` | Loads the personal lexicon and confirmed-word boosts |
| `nudge/speak.py` | Piper TTS to the earbud |
| `nudge/button.py` | BLE clicker and GPIO button events |
| `nudge/service.py` | The loop that ties it together |
| `tests/harness.py` | Scores top-1 / top-3 hit rate on a stall test set |

## Development

The resolver and test harness run on any machine with `llama-cpp-python` and a GGUF model;
the full service needs the Jetson (CUDA builds of whisper.cpp and llama.cpp).

```
pip install -r requirements.txt
python -m tests.harness --model models/qwen2.5-3b-instruct-q4_k_m.gguf
```

`scripts/jetson_setup.sh` builds the CUDA stack on JetPack 6.
