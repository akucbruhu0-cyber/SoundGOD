# SoundGOD

<p align="center"><img src="assets/logo.jpg" alt="SoundGOD" width="180"></p>

Local speech cleanup for very bad recordings (a far-away lecturer, echoey rooms, noise) and a "studio microphone" polish for your own videos. Everything runs on your computer (Mac or Windows). Nothing is uploaded.

`README.he.md` has a Hebrew version. The web UI itself is in Hebrew (RTL).

```
Engine 1  CLEAN   NVIDIA Nemotron RE-USE                 removes noise and reverb, does not invent words
                  (MLX/GPU on Apple silicon, PyTorch/CPU on Windows and Intel Macs)
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

| | Apple silicon Mac | Intel Mac | Windows 10/11 |
|---|---|---|---|
| zip to download | `SoundGOD-<version>-macos-arm64.zip` | `SoundGOD-<version>-windows-macos-intel.zip` | `SoundGOD-<version>-windows-macos-intel.zip` |
| install once | `brew install ffmpeg uv` | `brew install ffmpeg uv` | `winget install Gyan.FFmpeg` and `winget install astral-sh.uv` |
| start | `start.command` | `start.command` | `start.bat` |
| clean engine runs on | MLX, on the GPU (fast) | PyTorch, on the CPU | PyTorch, on the CPU |

The clean engine is the same NVIDIA model with the same weights everywhere. NVIDIA publishes it for Linux with an NVIDIA GPU only, so on Windows and Intel Macs it runs through `engine/nemotron.py`, a plain-PyTorch port of NVIDIA's reference code (output matches the Mac tool to about -55 dB). It is much slower: measured on an M3 Pro's CPU, about 2 minutes of processing per audio minute at 16 kHz (`rescue`) and about 7 at 48 kHz; on GitHub's 4-core Windows test machine it was about 7 minutes per audio minute at 16 kHz. The UI shows the estimate before you run. The first run on Windows or an Intel Mac downloads PyTorch (about 1 GB, once).

## Quick start on Windows

1. Install the two tools once, in a terminal (PowerShell): `winget install Gyan.FFmpeg` and `winget install astral-sh.uv`, then close the terminal.
2. Download `SoundGOD-<version>-windows-macos-intel.zip` from the Releases page and unzip it (right-click → Extract All).
3. Double-click `start.bat`. The first time it prepares the AI engine for a few minutes, then your browser opens the UI.
   If Windows SmartScreen warns about the file: More info → Run anyway.

## Quick start on a Mac (release zip, nothing to build)

1. Download the zip for your Mac (see the table) from the Releases page and unzip it.
2. macOS quarantines downloaded tools. Once, in Terminal: `xattr -dr com.apple.quarantine /path/to/SoundGOD-*`
   (or right-click `start.command` → Open).
3. Double-click `start.command`. Your browser opens the UI.
   For a real app icon (Dock, Spotlight, Launchpad): `./scripts/make-app.sh` builds `סטודיו סאונד.app` in `~/Applications`. It starts the local server when you open it and quits it after 15 idle minutes. Run the script again if you move the project folder.
4. Optional, for the Claude Code skill: `./scripts/install-skill.sh`

## From a git clone

The repo contains the source and the model weights, but not the compiled Apple-silicon tool (`bin/`). On Windows and Intel Macs nothing needs building: run `start.bat` / `start.command`. On Apple silicon:

```sh
./scripts/build-cli.sh      # clones + builds the MLX tool at a pinned commit; needs Xcode (~840 MB Metal Toolchain on first run)
./start.command
```

`./scripts/package.sh` builds both release zips (on an Apple silicon Mac). `.github/workflows/check.yml` runs `engine/check.py --full` on Windows, an Intel Mac and Linux on every push.

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

Apple silicon (MLX): about 11 s of processing per minute of audio at 16 kHz, about 30 s per minute at 48 kHz.
Windows / Intel (PyTorch, CPU): about 2 min per audio minute at 16 kHz, about 7 min at 48 kHz on the same machine's CPU; your PC will differ.
Sidon (`studio`) runs on the CPU everywhere: about 20 s per minute on the M3 Pro.

## What this does not do

- Generative restoration (Sidon) is off in `rescue`. In tests on a quiet Hebrew/Aramaic lecture another generative model (Resemble Enhance) invented wrong words, and Sidon has only been checked on a clear Hebrew clip (its Whisper transcript matched the original). Listen before trusting it on weak recordings.
- It never modifies the original file.

## Layout

```
engine/       enhance.py (the engine), nemotron.py (PyTorch clean engine), sidon.py, check.py (smoke test)
ui/           server.py (stdlib only) + static/ (vanilla JS/CSS)
skill/        SKILL.md.tmpl, installed by scripts/install-skill.sh
models/       NVIDIA Nemotron RE-USE weights + their license
scripts/      build-cli.sh, package.sh, install-skill.sh, make-app.sh
start.command, start.bat   launchers (Mac, Windows)
licenses/     upstream licenses     NOTICE.md  summary of third-party terms
```

## Credits and licenses

Project code: MIT. Model and the reference code `engine/nemotron.py` is ported from: NVIDIA NemotronLabs RE-USE, OpenMDW-1.1. MLX tool: JacobLinCool/apple-efficient-noise-reduction (MIT). See `NOTICE.md`.
