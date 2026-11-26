# SoundGOD

Local speech cleanup for very bad recordings (a far-away lecturer, echoey rooms, noise) and a "studio microphone" polish for your own videos. Everything runs on your Mac. Nothing is uploaded.

`README.he.md` has a Hebrew version. The web UI itself is in Hebrew (RTL).

```
Engine 1  CLEAN   NVIDIA Nemotron RE-USE (MLX / Metal)   removes noise and reverb, does not invent words
Engine 2  GEN     Sidon (PyTorch, CPU)                    generative restoration: full-band, studio-like voice
Engine 3  POLISH  ffmpeg                                  gate, warmth, presence, compression, final loudness
(each engine can be switched off; `studio` uses GEN, `rescue` and `natural` use CLEAN)
```

One engine, three front ends:

| Front end | What it is |
|---|---|
| **Web UI** | a local page (`127.0.0.1`): pick a file, tune sliders (each explains what it does), hear a 15 s before/after, save next to the original as `name - מוגבר ב-AI.ext` |
| **Claude Code skill** | `studio-audio`: say "clean and boost the audio of FILE"; it measures, picks parameters, runs, verifies, and hands the file back |
| **CLI** | `engine/enhance.py FILE [--preset rescue|studio|natural] [--clean/--no-clean --gen/--no-gen --polish/--no-polish] [--wet --chunk --hop --lufs --presence --warmth --comp --gate ...]`; add `--estimate --json` to get the expected time without processing |

Nemotron RE-USE is **included** (`models/nemotron-re-use/`, 38 MB). The optional Sidon engine (about 1 GB of weights plus a PyTorch environment) is downloaded automatically the first time you switch it on; it is not in git or the release zip.

## Requirements

- Apple silicon Mac, macOS 14 or newer (the model runs on MLX/Metal; no Intel, Windows or Linux)
- `ffmpeg` and `uv`: `brew install ffmpeg uv`

## Quick start (release zip, nothing to build)

1. Download `SoundGOD-<version>-macos-arm64.zip` from the Releases page and unzip it.
2. macOS quarantines downloaded tools. Once, in Terminal: `xattr -dr com.apple.quarantine /path/to/SoundGOD-*`
   (or right-click `start.command` → Open).
3. Double-click `start.command`. Your browser opens the UI.
   For a real app icon (Dock, Spotlight, Launchpad): `./scripts/make-app.sh` builds `סטודיו סאונד.app` in `~/Applications`. It starts the local server when you open it and quits it after 15 idle minutes. Run the script again if you move the project folder.
4. Optional, for the Claude Code skill: `./scripts/install-skill.sh`

## From a git clone

The repo contains the source and the model weights, but not the compiled tool (`bin/`, platform specific):

```sh
./scripts/build-cli.sh      # clones + builds the MLX tool at a pinned commit; needs Xcode (~840 MB Metal Toolchain on first run)
./start.command
```

`./scripts/package.sh` builds the release zip (bin + models + engine + UI + skill + licenses).

## Time estimate and engines

Once a file is loaded the UI shows how long the full run will take with the current settings (and the 15 s preview), and every setting shows how much time it adds. `--hop 1.0` (no overlap between chunks) halves the model time; on a healthy test clip the output differed by about -23 dB, but it was not checked on an echoey lecture. Two switches under "Processing engines" skip a whole stage: the AI model (the heavy part, most of the time) or the classic polish chain. CLI: `--no-clean`, `--no-polish`. The numbers come from `SPEED` in `engine/enhance.py`, measured on an M3 Pro, and are estimates.

## Presets

| | for | key values |
|---|---|---|
| `rescue` | quiet, noisy, echoey speech | model at 16 kHz, clean 100 %, -16 LUFS, strong pre-gain |
| `studio` | your own healthy recordings | model rate auto, clean 90 %, warmth +1.5 dB, presence +1.5 dB |
| `natural` | stay close to the original | clean 60 %, -18 LUFS, light compression |

`--preset auto` (default) measures loudness and SNR and picks one.

## Speed (M3 Pro)

About 11 s of processing per minute of audio at 16 kHz, about 30 s per minute at 48 kHz.

## What this does not do

- Generative restoration (Sidon) is off in `rescue`. In tests on a quiet Hebrew/Aramaic lecture another generative model (Resemble Enhance) invented wrong words, and Sidon has only been checked on a clear Hebrew clip (its Whisper transcript matched the original). Listen before trusting it on weak recordings.
- It never modifies the original file.

## Layout

```
engine/       enhance.py (the engine), check.py (smoke test)
ui/           server.py (stdlib only) + static/ (vanilla JS/CSS)
skill/        SKILL.md.tmpl, installed by scripts/install-skill.sh
models/       NVIDIA Nemotron RE-USE weights + their license
scripts/      build-cli.sh, package.sh, install-skill.sh
licenses/     upstream licenses     NOTICE.md  summary of third-party terms
```

## Credits and licenses

Project code: MIT. Model: NVIDIA NemotronLabs RE-USE, OpenMDW-1.1. MLX tool: JacobLinCool/apple-efficient-noise-reduction (MIT). See `NOTICE.md`.
