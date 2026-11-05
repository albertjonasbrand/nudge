#!/usr/bin/env bash
# One-shot setup for the reComputer Mini J4012 (Jetson Orin NX 16GB, JetPack 6.x).
#
#   git clone https://github.com/albertjonasbrand/nudge ~/nudge
#   cd ~/nudge && ./scripts/jetson_setup.sh
#
# Idempotent: re-running skips what's done. Roughly 45–60 min the first time,
# almost all of it compiling llama.cpp and whisper.cpp for CUDA.
#
# Env overrides:  MODEL=qwen2.5-7b   (default qwen2.5-3b, also: qwen2.5-7b)
#                 WHISPER=medium.en  (default small.en)
#                 NO_SERVICE=1       (don't install the systemd units)

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODEL="${MODEL:-qwen2.5-3b}"
WHISPER="${WHISPER:-small.en}"
JOBS="$(nproc)"
export PATH="/usr/local/cuda/bin:$PATH"

say() { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }

say "checking we're on a Jetson"
if ! command -v nvcc >/dev/null; then
  echo "nvcc not found. Install JetPack (sudo apt install nvidia-jetpack) and re-run." >&2; exit 1
fi
nvcc --version | tail -1
CUDA_ARCH=87   # Orin

say "apt packages"
sudo apt-get update -qq
sudo apt-get install -y -qq git build-essential cmake python3-pip python3-venv python3-dev \
  libsdl2-dev alsa-utils libasound2-dev portaudio19-dev \
  chromium-browser xserver-xorg xinit openbox unclutter upower \
  libevdev-dev curl jq >/dev/null

say "python deps"
pip3 install --user -q -r "$ROOT/requirements.txt"
# llama-cpp-python with CUDA: build from source against the Jetson's CUDA
if ! python3 -c "import llama_cpp, sys; sys.exit(0 if llama_cpp.llama_supports_gpu_offload() else 1)" 2>/dev/null; then
  say "building llama-cpp-python with CUDA (this is the slow part)"
  CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=${CUDA_ARCH}" \
    pip3 install --user -q --no-cache-dir --force-reinstall "llama-cpp-python>=0.3"
fi

say "whisper.cpp (CUDA) + whisper-stream"
mkdir -p "$ROOT/third_party" && cd "$ROOT/third_party"
if [ ! -x whisper.cpp/build/bin/whisper-stream ]; then
  [ -d whisper.cpp ] || git clone --depth 1 https://github.com/ggml-org/whisper.cpp
  cd whisper.cpp
  cmake -B build -DGGML_CUDA=1 -DCMAKE_CUDA_ARCHITECTURES=${CUDA_ARCH} -DWHISPER_SDL2=ON >/dev/null
  cmake --build build --config Release -j"$JOBS" --target whisper-stream >/dev/null
  cd ..
fi
sudo ln -sf "$ROOT/third_party/whisper.cpp/build/bin/whisper-stream" /usr/local/bin/whisper-stream

say "piper tts"
if ! command -v piper >/dev/null; then
  pip3 install --user -q piper-tts || true
  if ! command -v piper >/dev/null; then
    # fall back to the static binary
    cd "$ROOT/third_party"
    curl -sL https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz | tar xz
    sudo ln -sf "$ROOT/third_party/piper/piper" /usr/local/bin/piper
  fi
fi

say "models"
mkdir -p "$ROOT/models/piper" && cd "$ROOT/models"
[ -f "ggml-${WHISPER}.bin" ] || curl -sL -o "ggml-${WHISPER}.bin" \
  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-${WHISPER}.bin"
case "$MODEL" in
  qwen2.5-3b) GGUF=qwen2.5-3b-instruct-q4_k_m.gguf; URL="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/$GGUF" ;;
  qwen2.5-7b) GGUF=qwen2.5-7b-instruct-q4_k_m.gguf; URL="https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/$GGUF" ;;
  *) echo "unknown MODEL=$MODEL" >&2; exit 1 ;;
esac
[ -f "$GGUF" ] || curl -sL -o "$GGUF" "$URL"
for f in en_US-lessac-medium.onnx en_US-lessac-medium.onnx.json; do
  [ -f "piper/$f" ] || curl -sL -o "piper/$f" \
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/$f"
done
sed -i "s#^  path: .*#  path: models/$GGUF#" "$ROOT/config/settings.yaml"
sed -i "s#^  model: .*\.en.*#  model: $WHISPER#" "$ROOT/config/settings.yaml"

say "permissions (mic, evdev button, no sudo needed at runtime)"
sudo usermod -aG audio,input "$USER" || true
sudo tee /etc/udev/rules.d/99-nudge-button.rules >/dev/null <<'EOF'
SUBSYSTEM=="input", ATTRS{product}=="XIAO Nudge Button", MODE="0660", GROUP="input"
EOF
sudo udevadm control --reload

say "power mode: 15 W, clocks pinned"
sudo nvpmodel -m 0 >/dev/null 2>&1 || true   # mode 0 = MAXN on NX; set to the 15W mode id if you want to cap
sudo jetson_clocks >/dev/null 2>&1 || true

if [ -z "${NO_SERVICE:-}" ]; then
  say "systemd: nudge.service + nudge-kiosk.service"
  sudo tee /etc/systemd/system/nudge.service >/dev/null <<EOF
[Unit]
Description=Nudge word-finding service
After=sound.target network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$ROOT
Environment=NUDGE_ROOT=$ROOT
Environment=PATH=/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin
ExecStart=/usr/bin/python3 -m nudge.service
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  sudo tee /etc/systemd/system/nudge-kiosk.service >/dev/null <<EOF
[Unit]
Description=Nudge touchscreen kiosk
After=nudge.service

[Service]
Type=simple
User=$USER
Environment=HOME=$HOME
ExecStart=/usr/bin/xinit $ROOT/scripts/kiosk.sh -- :0 -nocursor
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable nudge.service nudge-kiosk.service
  sudo systemctl set-default multi-user.target   # no desktop; the kiosk is the UI
fi

say "quick checks"
python3 -c "import llama_cpp; print('llama-cpp-python GPU offload:', llama_cpp.llama_supports_gpu_offload())"
whisper-stream -h 2>&1 | head -1 || true
piper --help 2>&1 | head -1 || true
arecord -l | grep -i card || echo "no capture device yet (plug in the USB sound adapter)"

cat <<EOF

Done. Next:
  python3 -m tests.harness --model models/$GGUF      # accuracy + latency on the GPU
  python3 -m nudge.service --dev                     # typed test, no hardware
  sudo systemctl start nudge nudge-kiosk             # the real thing
  journalctl -fu nudge                               # watch it
Family page: http://$(hostname -I | awk '{print $1}'):8765/family
EOF
