# AGENTS.md: architecture and change guide for SoundGOD

Written for an AI coding agent (or a new human) who has never seen this project and has to modify it. Read this first, then the code. (The project's internal name, still used for the folder, cache directories and the page marker, is `audio-enhance`.) It describes the state of the project at version 0.2.0.

## 1. What it is

SoundGOD is a **local speech-enhancement tool for macOS (Apple silicon and Intel) and Windows**. It takes an audio or video file and writes a new file next to it with the sound improved: noise and room echo removed, quiet speech raised, optionally "rebuilt" in a full-band, studio-like voice. The original is never modified. For video the picture stream is copied untouched and only the sound is replaced.

Nothing leaves the machine. There is no server component other than a loopback web server that serves the UI to the user's own browser.

One engine (`engine/enhance.py`) and three front ends on top of it:

| front end | where | what it is |
|---|---|---|
| CLI | `engine/enhance.py` | the engine itself, JSON-line events with `--json` |
| Web UI | `ui/` | a local page: pick a file, tune parameters with explanations, hear a 15 s before/after, run and save |
| Claude Code skill | `skill/SKILL.md.tmpl` | instructions for an LLM agent that drives the CLI; installed to `~/.claude/skills/studio-audio/` |

Plus launchers that start the web server and open the browser: `start.command` (Mac), `start.bat` (Windows), and a macOS app (`scripts/make-app.sh`).

Language: the UI and the user-facing docs are **Hebrew, right-to-left**. Code, comments, CLI help and this file are English. Keep it that way.

**Non-goals** (decisions already made, do not reverse them without being asked):
- Cloud processing, accounts, telemetry: none.
- Generative models other than Sidon. A different generative restorer (Resemble Enhance) invented wrong words on a quiet, echoey Hebrew lecture. Sidon has only been checked on a clear Hebrew clip.
- Touching the original file.

## 2. Mental model

Three engines, each independently switchable, applied in a fixed order. Everything before and after them is plain ffmpeg plumbing.

```
input file (audio or video)
  │ extract: ffmpeg -> 48 kHz mono float WAV  (dry48)
  │ measure: loudness, SNR, noise floor, bandwidth -> suggested preset
  ▼
[pre-gain]   loudnorm single pass to -20 LUFS, at the model's sample rate (skipped when only "gen" is on)
  ▼
[clean]      engine 1: Nemotron RE-USE (removes noise and reverb): Swift/MLX CLI in bin/ on Apple silicon,
  │          engine/nemotron.py (PyTorch, CPU) everywhere else
  │          output mixed with the dry signal by `wet` (0..100 %)  -> mixed.wav (48 kHz)
  ▼
[gen]        engine 2: Sidon via engine/sidon.py in its own uv environment (PyTorch, CPU): full-band rebuild
  ▼
[polish]     engine 3: ffmpeg filters (highpass 70 Hz, gate, warmth, presence, compressor)
  │          then two-pass loudnorm to the target LUFS and a limiter  -> polished.wav
  ▼
encode: ffmpeg -> next to the input as "<name> - מוגבר ב-AI.<ext>" (video: -c:v copy)
```

The central distinction to keep in mind: **clean and polish are deterministic signal processing or discriminative models that subtract; gen is generative and synthesises.** Clean cannot add words; gen can. This is why the presets and the skill treat them differently.

Engines in one table:

| engine | param | implementation | cost per audio minute (M3 Pro) | notes |
|---|---|---|---|---|
| clean | `clean` | Apple silicon: `bin/noise-reduction enhance --engine nemotron ...` (compiled Swift, MLX on the GPU). Elsewhere: `engine/nemotron.py` (PyTorch + a numba scan, CPU) | MLX: ~7 s at 16 kHz with `hop` 1.0, ~17 s at 48 kHz. PyTorch: ~130 s at 16 kHz, ~430 s at 48 kHz (M3 Pro CPU) | weights bundled in `models/nemotron-re-use/`, shared by both runtimes |
| gen | `gen` | `engine/sidon.py` (PyTorch TorchScript, **CPU only**) | ~20 s | ~1 GB weights downloaded on first use into `models/sidon/` |
| polish | `polish` | ffmpeg filter chain in `polish_filters()` | ~0.3 s | off means only loudness is matched |

Every run also costs about 3 s per audio minute of ffmpeg work regardless of engines.

Presets (`PRESETS` in `engine/enhance.py`):
- `rescue`: quiet, noisy or echoey speech. clean only, 16 kHz, pre-gain on.
- `studio`: the user's own healthy recordings. **gen only** (clean off), warmth and presence boosted.
- `natural`: clean only at `wet` 60, flat EQ, light compression, -18 LUFS.
- `auto` (default): `suggest_preset()` returns `rescue` when lufs < -35 or snr < 18, else `studio`.

Chaining clean then gen was tried and gave no audible gain over gen alone on a clear clip and costs more time, so no preset does it. It is still possible by hand.

## 3. Repository map

```
engine/enhance.py       446 lines  the engine: measuring, stages, CLI, JSON events, time model
engine/nemotron.py      ~260 lines  engine 1 on Windows/Intel/Linux: PyTorch port of NVIDIA's reference code. Own uv environment
engine/sidon.py          70 lines  engine 3 (generative): downloads weights, restores a wav. Own uv environment
engine/check.py          ~80 lines smoke test (10 s preview: loudness target, peak ceiling, length); --full adds a full run on a Hebrew-named file and a server round trip
ui/server.py            271 lines  stdlib http.server: static files, job runner, native file picker
ui/index.html           160 lines  the page (Hebrew, dir="rtl"); a __TOKEN__ placeholder replaced per request
ui/static/app.js        456 lines  all UI logic, vanilla JS, no build step
ui/static/style.css     199 lines  design tokens and styles
skill/SKILL.md.tmpl                skill source; {{ROOT}} is replaced with the project path at install time
scripts/install-skill.sh           renders the template to ~/.claude/skills/studio-audio/SKILL.md
scripts/make-app.sh                builds "סטודיו סאונד.app" (default: ~/Applications)
scripts/make-icon.py               crops assets/logo.jpg into the rounded app-icon .iconset (pillow, via uv)
assets/logo.jpg                    the SoundGOD logo, 2000x2000: source of the app icon, shown in the READMEs
scripts/build-cli.sh               clones and builds the MLX tool at a pinned commit into bin/
scripts/package.sh                 builds dist/SoundGOD-<version>-macos-arm64.zip and -windows-macos-intel.zip
start.command                      Mac double-click launcher (clears quarantine, checks ffmpeg/uv, on Intel prepares the PyTorch env, runs the server)
start.bat                          Windows double-click launcher (checks ffmpeg/uv, prepares the PyTorch env, runs the server)
.github/workflows/check.yml        CI: check.py --full on windows-latest, macos-15-intel, ubuntu-latest
bin/                               compiled Swift CLI + two .bundle dirs (git-ignored; ships in the zip)
models/nemotron-re-use/            Nemotron RE-USE weights (38 MB), config, license, model card, SOURCE.txt
models/sidon/                      Sidon weights, git-ignored, downloaded on demand
licenses/, NOTICE.md, LICENSE      project is MIT; third-party terms in NOTICE.md
README.md, README.he.md            user docs (English, Hebrew)
docs/design.md                     the original short design (Hebrew)
VERSION                            0.2.0
samples/, dist/                    git-ignored: listening samples and built zips
```

The project is published at https://github.com/akucbruhu0-cyber/SoundGOD ; compiled files and large models are not in git. `.gitignore` already excludes `bin/`, `dist/`, `samples/`, `.test/`, `models/sidon/`, `__pycache__/`, `*.profraw`.

All Python entry points are **uv inline-script files** (`#!/usr/bin/env -S uv run --script` plus a `# /// script` header). There is no `pyproject.toml`, no virtualenv to create, no package to install. Run them with `uv run --script path.py`. Each script gets its own cached environment, so `enhance.py` (numpy, soundfile) and `sidon.py` (torch, torchaudio, transformers, ...) never share one. That separation is deliberate: the heavy PyTorch stack is only pulled in when gen is used.

## 4. The engine (`engine/enhance.py`)

### 4.1 CLI modes

```
enhance.py FILE [settings]                      full run, writes the output next to FILE
enhance.py FILE --analyze --json                measure only: {before, suggested_preset}
enhance.py FILE [settings] --estimate --json    expected seconds for these settings, nothing processed
enhance.py FILE [settings] --preview S,D --outdir DIR   process the window [S, S+D] s; writes before.wav, after.wav, before.png, after.png
enhance.py --describe                           presets, parameter ranges, SPEED table, sidon_ready (the UI reads this)
```

Settings: `--preset auto|rescue|studio|natural`, one flag per entry in `PARAMS` (`--wet --chunk --hop --bwe --rate --lufs --presence --warmth --comp --gate`), `--no-pregain`, and `--clean/--no-clean`, `--gen/--no-gen`, `--polish/--no-polish` (argparse `BooleanOptionalAction`, default `None` meaning "take the preset's value"). `--out PATH` overrides the output location.

### 4.2 JSON-line protocol (`--json`)

One JSON object per stdout line. The server and the skill depend on this; do not change shapes casually.

```
{"event":"stage","name":"clean","pct":30,"eta":<seconds|null>,"to":<pct|null>}
{"event":"done", ...result...}        # last line on success
{"event":"error","message":"..."}     # printed by the top-level handler; exit code 1
```

`stage` names in use: `measure extract download pregain clean mix gen polish finalize done`. `eta` and `to` are set on the long stages (`download`, `clean`, `gen`): the UI interpolates the progress bar from `pct` towards `to` over `eta` seconds, because the model calls themselves report no progress. Do not put NaN in any result (JavaScript's `JSON.parse` rejects it); use `null`.

Result of a full run: `output, preset, params, before, after, seconds, model_rate, out_rate, rtf, clean_s, gen_s`. `before` and `after` are the dicts returned by `measure()`: `duration, lufs, peak_db, speech_db, noise_floor_db, snr_db, bandwidth_hz`.

Without `--json` the same information goes to stderr as text, and the result is pretty-printed to stdout.

### 4.3 Function guide

| function | role |
|---|---|
| `estimate()` | the time model, returns `{ai, gen, ffmpeg, total}` seconds. Uses `SPEED` |
| `run()`, `ff()` | subprocess helpers. `run()` sets `LLVM_PROFILE_FILE=/dev/null` and `NEMOTRON_MODEL_DIR` (see pitfalls) |
| `Emitter` | the stage/result printer (JSON lines or text) |
| `lufs_peak()` | ffmpeg `ebur128` integrated loudness and true peak |
| `measure()` | 50 ms RMS frames (floored at -90 dB): speech = 90th percentile, noise floor = 10th, SNR = difference; bandwidth from the spectrum of the loudest 30 % of frames, within 60 dB of the peak bin |
| `suggest_preset()` | the rescue-versus-studio rule |
| `extract()`, `resample()` | ffmpeg wrappers producing mono float WAV |
| `loudnorm_two_pass()` | measure, then apply `loudnorm` with measured values and `linear=true`, then `alimiter=limit=0.84:level=0` |
| `BACKEND`, `APPLE_SILICON` | `mlx` on Apple silicon hardware, else `torch`; `SOUNDGOD_ENGINE=torch` forces the port (for testing on a Mac). Detected with `sysctl hw.optional.arm64`, not `platform.machine()` (see pitfalls) |
| `ensure_model()`, `clean()` | engine 1: calls the Swift CLI or `nemotron.py` (after resampling up to `out_rate` for bandwidth extension), parses `RTF` from its output |
| `sidon_ready()` | both Sidon weight files exist in `models/sidon/` |
| `polish_filters()` | builds the engine-3 ffmpeg chain from the parameters; returns `""` when `polish` is off |
| `process()` | the whole pipeline for one file or window; returns timing info |
| `spectrogram()`, `out_path()`, `encode()`, `has_video_stream()` | output side. `out_path` never overwrites: it appends ` (2)`, ` (3)` |
| `build_params()` | preset values overridden by explicitly given flags, clamped to the ranges in `PARAMS` |
| `main()` | argument parsing and the modes above |

### 4.4 `process()` in detail

1. `extract` the (optionally windowed) source to `dry48.wav`; measure its bandwidth.
2. Decide rates. `rate` = `auto` picks 48 kHz when the source bandwidth exceeds 9 kHz, else 16 kHz. `bwe` (bandwidth extension) can raise the model's *output* rate above its input rate. If `clean` is off, both rates are forced to 48 kHz so nothing is down- or up-sampled for no reason.
3. If `gen` is on and the weights are missing: emit stage `download` and run `sidon.py --fetch` (also builds the uv environment).
4. Pre-gain: unless `pregain` is off, or only `gen` is on, resample to the model rate and `loudnorm` to -20 LUFS so a very quiet source reaches the model at a workable level. Otherwise just resample.
5. clean (if on): stage `clean`, call the CLI with `--engine nemotron --latency <chunk> --hop <hop> [--output-rate N]`, resample both wet and dry to 48 kHz, mix `wet/100 * wet + (1 - wet/100) * dry` into `mixed.wav`. If off: `mixed.wav` is the resampled dry signal.
6. gen (if on): stage `gen`, run `sidon.py mixed.wav gen.wav`; its output replaces the signal.
7. polish: stage `polish`, `loudnorm_two_pass` with `polish_filters()` as a pre-chain, to `polished.wav`.

Stage percentages: clean runs 30 to 70 (30 to 55 when gen follows); gen runs from 30 (alone) or 55 to 85; polish starts at 80 (88 with gen); finalize 92; done 100.

Preview mode runs the same `process()` on a window, then also writes `before.wav` (the original window loudness-matched to the same target, so A/B compares cleanliness and not volume) and spectrogram images.

## 5. Parameters: where each fact lives

A parameter is described in **several places** that must agree. This is the main source of mistakes when changing the project.

| fact | source of truth | copies you must keep in sync |
|---|---|---|
| name, default, min, max, type | `PARAMS` in `enhance.py` | `NUM`/`CHOICE` whitelist in `ui/server.py`; `SLIDERS` entry in `ui/app.js` (min, max, step, formatter); the skill's mapping table |
| preset values | `PRESETS` in `enhance.py` | read by the UI through `--describe`; the preset table in `skill/SKILL.md.tmpl` and the README |
| time model constants | `SPEED` in `enhance.py` (`rtf` is picked from `RTF[BACKEND]`) | `estimate()` (Python) and `calc()` (JS) implement the same formula; the UI receives `SPEED` through `--describe` |
| Hebrew explanation of each control | `SLIDERS` in `ui/app.js` (`what`, `effect`, `time`) | none |
| what the stages are called in the progress bar | `STAGES` in `ui/app.js` | stage names emitted by `enhance.py` |

Parameter semantics worth knowing:
- `chunk` (seconds, 0.5 to 5): Nemotron's chunk length (`--latency` of the CLI). Shorter reacts faster to changing echo but costs more time below 2 s. 2.0 was the best-sounding on the test lecture.
- `hop` (0.5 to 1.0): chunk step as a fraction of the chunk. 0.5 is a 50 % overlap (the CLI default), 1.0 is no overlap and **halves the model time**. 1.0 is the default in all presets. Measured: the output differed from 0.5 by about -23 dB on a clean clip; not yet checked on echoey lectures, where seams between chunks are conceivable. The UI shows it as "overlap" (`(1 - hop) * 100 %`).
- `wet` (0 to 100): share of the cleaned signal in the mix. Does not change compute time.
- `bwe` (`off|32000|48000`) and `rate` (`auto|16000|48000`): see 4.4. 48 kHz is about 2.7x slower than 16 kHz.
- `lufs`, `presence` (3.2 kHz bell), `warmth` (180 Hz low shelf), `comp` (compressor ratio), `gate` (expander threshold and range): polish only.
- `pregain`, `clean`, `gen`, `polish`: booleans. In the UI the three engine switches live in their own card; once the user flips one by hand, applying a preset no longer overrides it (`S.enginesTouched`).

## 6. The time model

`estimate()` / `calc()`: `total = ai + gen + ffmpeg`, with
- `ai = dur * rtf[rate] * (1 + chunk_extra * max(0, 2 - chunk) / 1.5) * (0.5 / hop)` for the clean engine. `rate` is the higher of the model rate and the output rate, bucketed to 16/32/48 kHz.
- `gen = dur * gen_rtf + gen_fixed`.
- `ffmpeg = fixed + dur/60 * (ffmpeg_per_min + polish_extra_per_min)`.

Constants (`SPEED`), measured on an M3 Pro with 18 GB: `rtf` 0.205 / 0.42 / 0.56 for 16/32/48 kHz at `hop` 0.5 on MLX, 4.3 / 9.4 / 14.5 for the PyTorch port on the same CPU (32 kHz interpolated); `chunk_extra` 0.38; `gen_rtf` 0.33; `gen_fixed` 3 s; `ffmpeg_per_min` 3.0; `polish_extra_per_min` 0.35; `fixed` 0.5. The scaling in `hop` (about x0.66 at 0.75, x0.48 at 1.0) was measured. On another machine the numbers will be off; the UI and skill call them estimates. To re-measure, run the engine on a clip of known length with `--json` and compare `clean_s`, `gen_s` and `seconds` in the final event; for the ffmpeg share use `--no-clean --no-gen` on a multi-minute file.

The UI also shows, per control, how much time the current value adds compared with its cheapest value (`CHEAPEST` and `costOf()` in `app.js`).

## 7. The web server (`ui/server.py`)

Python standard library only. Started with `./ui/server.py [--port 8787] [--no-open] [--idle-exit MINUTES]`.

Endpoints:

| method and path | purpose |
|---|---|
| GET `/` | `index.html` with `__TOKEN__` replaced by this run's random token |
| GET `/static/*` | CSS and JS; sent with `Cache-Control: no-store` |
| GET `/api/describe` | runs `enhance.py --describe`; returns presets, params, `speed`, `sidon_ready` |
| GET `/api/ping` | heartbeat: the page calls it every 30 s; keeps `--idle-exit` away |
| GET `/api/job/<id>` | job state: `state` (`running/done/error/cancelled`), `stage`, `pct`, `eta`, `to`, `t` (when the stage started), `result`, `error` |
| GET `/media/<job>/<file>` | before/after audio and spectrograms of a preview, with HTTP Range support for the player |
| POST `/api/pick` | native file chooser: `osascript` (`choose file`) on macOS, tkinter in a child process elsewhere; returns the path |
| POST `/api/analyze`, `/api/preview`, `/api/run` | start a job; body `{path, params, start?, dur?}`; return `{job}` |
| POST `/api/cancel` | terminate a running job's process |
| POST `/api/reveal` | show the file in Finder (`open -R`) or Explorer (`explorer /select,`) |

Job lifecycle: `start_job()` builds the engine command (`uv run --script enhance.py FILE --json <flags> [--analyze | --preview S,D --outdir CACHE/<id>]`), spawns it, and a thread reads stdout lines into the job dict. Jobs live in memory (`JOBS`); preview artifacts live in `$TMPDIR/audio-enhance-ui/<job>/`.

Security model (the server runs a subprocess with a user-supplied path, so keep this tight):
- binds `127.0.0.1` only;
- every request must carry a `Host` header equal to `127.0.0.1:<port>` or `localhost:<port>` (DNS-rebinding defence);
- every API request needs the per-run token (header `X-Token`, or `?t=` for media); the token is injected into the page and changes at every start;
- the browser can only send whitelisted keys: numbers are clamped through `NUM`, choices checked against `CHOICE`, booleans only for `pregain/clean/gen/polish`. Nothing else reaches the engine's argv;
- the file path must be an absolute path to an existing file.

`--idle-exit N`: a watcher thread exits the process when there has been no request for N minutes and no job is running. The launcher app passes 15. Without the flag the server runs until killed.

There is no `do_HEAD`; use GET when testing headers (`curl -D -`).

## 8. The UI (`ui/`)

Vanilla HTML, CSS and JS. No framework, no bundler, no npm. Fonts (Rubik, IBM Plex Sans Hebrew, IBM Plex Mono) load from Google Fonts with system fallbacks, so the page works offline in system fonts.

State is one object `S` in `app.js`: `speed` (time constants), `path`, `info` (the `--analyze` result), `presets`, `preset`, `params` (what the user currently has), `dur`, `start` (preview window start), `busy`, `job`, `enginesTouched`.

Flow:
1. Load: `renderControls()` builds every control from the `SLIDERS` array (groups `engines`, `clean`, `polish`, `adv`), then `/api/describe` fills `S.presets` and `S.speed`.
2. Pick a file (`/api/pick`) then `loadFile()` runs an `analyze` job, shows loudness/SNR/noise/bandwidth, applies the suggested preset.
3. Any control change updates `S.params`, calls `syncControls()`, which refreshes the value labels, the per-control time chips, greys out controls whose engine is off (`needs`), and calls `updateEstimate()` (the time estimate in the bottom bar and on the preview button).
4. Preview (`doPreview`): a 15 s `preview` job, then `showPreview()` loads the before/after audio, draws the waveforms on canvases, shows the spectrogram images, and the A/B player. Apply (`doApply`): a `run` job; on success shows the metrics table and the saved path.
5. `runJob()` polls `/api/job/<id>` every 400 ms and renders progress, including the elapsed-time counter and the interpolated bar for stages with `eta`/`to`.

Design rules (the UI follows a brand book; keep to it):
- Three visual states: still, AI working, live. The AI glow (`.glow`, class `working` on `#wrap`) appears **only while a job runs**. Red is reserved for "live" and is not used here.
- Palette tokens in `:root` of `style.css`: paper `#F5FAF6`, mint `#CDEBD5`, ink `#0F2418`, forest `#1E6A2E`, and the spark colour `#FFB574` used only for the AI icon. Dark mode is handled with `prefers-color-scheme`.
- Radii 12 / 22 / 36 px, pill-shaped buttons, justified paragraphs, no centred layouts, **no logo inside the web UI** (the logo is only the app icon and the README header). Motion tokens: enter 320 ms, breathing 4.2 s; `prefers-reduced-motion` is respected.
- RTL: `<html lang="he" dir="rtl">`; use logical CSS properties. Waveform canvases force `direction: ltr` because audio time runs left to right. Numbers and file paths are isolated LTR.
- A global rule `[hidden]{display:none!important}` exists because components that set `display:flex` otherwise override the `hidden` attribute.

## 9. Launchers, packaging, skill

- `start.command`: for a double-click. Clears macOS quarantine on the folder (needed for a downloaded zip), checks `ffmpeg` and `uv`, `exec`s the server.
- `scripts/make-app.sh [dest]`: creates `סטודיו סאונד.app` with `Contents/MacOS/launch` (zsh), `Info.plist`, an icon made by `make-icon.py` from `assets/logo.jpg` (the crop is the `CENTER`/`SIDE` constants; adjust them if the artwork changes), and `Contents/Resources/root` holding this project's absolute path (the app finds the project through that file, else through its own parent folder). The launcher reuses an already running server (it recognises it by `<meta name="app" content="audio-enhance-ui">` on ports 8787 to 8806) or starts one with `--idle-exit 15`, waits up to two minutes (first run may build the uv environment), then `open`s the URL. If the project folder moves, run the script again. Ad-hoc signed.
- `scripts/package.sh`: rsyncs the project (excluding `dist/`, `samples/`, `docs/`, `models/sidon/`, caches) and zips with `ditto -c -k --keepParent --norsrc --noextattr --noacl`. Those ditto flags matter: without them the zip contains `._` AppleDouble files. Requires `bin/noise-reduction` and the Nemotron weights to exist.
- `scripts/build-cli.sh`: clones the Swift tool at a pinned commit, installs the Xcode Metal Toolchain component if needed (about 840 MB), runs `make build`, copies the binary and its two `.bundle` directories into `bin/`. **Never run end to end from scratch yet** (the binary in `bin/` was built by hand with the same commit).
- `scripts/install-skill.sh`: renders `skill/SKILL.md.tmpl` with `{{ROOT}}` replaced by the project path. Re-run it after editing the template. The skill drives the engine CLI; if you add a flag or change behaviour the skill relies on (the JSON result keys, `--estimate`, engine flags, preset meanings), update the template too.

## 10. Models, downloads, licenses

- **Nemotron RE-USE** (NVIDIA NemotronLabs, 9.6 M parameters, OpenMDW-1.1, commercial use allowed): weights are bundled. `run()` points the CLI at them with `NEMOTRON_MODEL_DIR`. If they are missing, `ensure_model()` falls back to the CLI's own cache and then to `bin/noise-reduction download --engine nemotron`.
- **Swift CLI** (`JacobLinCool/apple-efficient-noise-reduction`, MIT, pinned commit `31a2e64`): MLX port that runs the model. It also contains DeepFilterNet3 and NVIDIA's *Real-time* RE-USE, neither used. The latter is **noncommercial**; its `--engine` default is `reuse`, so every call must pass `--engine nemotron` explicitly.
- **Sidon v0.1** (`sarulab-speech/sidon-v0.1`, MIT): the CPU TorchScript files `feature_extractor_cpu.pt` (795 MB) and `decoder_cpu.pt` (210 MB), downloaded by `sidon.py` into `models/sidon/` at a pinned revision. At run time the feature extractor config of `facebook/w2v-bert-2.0` is read from Hugging Face (tiny, cached after the first call), so the very first gen run needs network.
- The first gen use also makes `uv` install PyTorch, torchaudio and transformers (~0.7 GB).
- Full terms: `NOTICE.md`, `licenses/`, `models/*/`.

## 11. Common changes: checklists

**Add or change a numeric parameter.**
1. `PARAMS` and every preset in `PRESETS` (`engine/enhance.py`); use it in `process()` or the stage that needs it.
2. The server whitelist: `NUM` (or `CHOICE`) in `ui/server.py`.
3. A `SLIDERS` entry in `ui/app.js` with `what`, `effect`, `time` and, if it affects compute time, `costKey` plus an entry in `CHEAPEST`; `needs` if it only matters when an engine is on.
4. If it changes compute time: `SPEED`, `estimate()` and `calc()` (both!), and re-measure.
5. Skill template mapping table and README.

**Add an engine.** Follow `gen`: a boolean in `PARAMS`, preset values, `--engine/--no-engine` flag in `main()`, a stage in `process()` with `eta`/`to`, a `STAGES` label, `engine_flags()` in the server, an `engines` entry in `SLIDERS`, `calc()` in the UI, the skill, `NOTICE.md`. If it needs heavy dependencies, give it its own uv-script file like `sidon.py` rather than adding to `enhance.py`'s environment.

**Change what a preset does.** Edit `PRESETS`; the UI picks it up through `--describe`. Update the preset tables in `skill/SKILL.md.tmpl` and the READMEs. Re-run `scripts/install-skill.sh`.

**Change UI text or layout.** `index.html`, `style.css`, `app.js` only. Static files are served `no-store`, so a browser refresh is enough; the server does not need a restart. Keep Hebrew wording plain and from the user's point of view (say "echo", not "reverb tail").

**Change the engine or server code.** The running server is a Python process that has already loaded `server.py`; restart it. `enhance.py` is spawned fresh per job, so changes apply to the next job, but the server reads `--describe` per page load.

## 12. Verifying a change

```
uv run --script engine/check.py                      # smoke test: loudness target, peak ceiling, length. ~15 s
uv run --script engine/enhance.py FILE --estimate --json
uv run --script engine/enhance.py FILE --preview 30,15 --outdir /tmp/prev --json
python3 -m py_compile engine/enhance.py ui/server.py && node --check ui/static/app.js
```

The UI can be driven in a browser at `http://127.0.0.1:8787/`; in a scripted browser, call `loadFile("<absolute path>")` and `doPreview()` from the console instead of clicking the native file chooser.

Success criteria used throughout: final loudness within 1 dB of the target, peak at or below -1 dBFS, duration within 0.5 s of the source. **These do not tell you whether it sounds good.** Speech quality needs listening, and for any change involving `gen` or `hop`, ideally a transcript comparison before and after (Whisper-based) to catch changed words. There is no automated audio-quality test.

## 13. Pitfalls found the hard way

- **Rosetta Python on Apple silicon:** `uv` may pick an x86_64 Python (it did on the development Mac), and then `platform.machine()` says `x86_64`. The backend is chosen from `sysctl hw.optional.arm64` instead. It only affects the Python scripts; the MLX tool is its own arm64 binary.
- **Intel Macs stop at torch 2.2.2.** It needs numpy 1.x, the last numba with an Intel-Mac wheel is 0.62, and transformers >= 4.50 treat torch 2.2 as "not installed". `nemotron.py` and `sidon.py` pin these with `platform_machine == 'x86_64'` markers. Tested under Rosetta: both match the arm64 output (Sidon bit-identical, clean -52 dB).
- **Depthwise `Conv1d` on the CPU is ~100x slower than the rest** of a Mamba layer in PyTorch (300 ms of 330). `nemotron.py` does it as four shifted multiply-adds. The selective scan is a numba kernel (`_scan`); a loop in PyTorch was far slower.
- **Windows text encoding:** every subprocess pipe is read as UTF-8 (`encoding="utf-8", errors="replace"`) and `enhance.py` reconfigures stdout to UTF-8; otherwise Hebrew paths in the JSON break on a cp1252 console.

- **Stray profile file:** the Swift CLI is built with coverage on and writes a 5 MB `default.profraw` into the working directory on every run. `run()` sets `LLVM_PROFILE_FILE=/dev/null`. Keep it.
- **Limiter:** `alimiter` without `level=0` re-raises the signal to 0 dBFS. The limit is `0.84` (about -1.5 dBFS).
- **SNR inflation:** frames of digital silence would make SNR huge, so frame levels are floored at -90 dB in `measure()`.
- **Time alignment:** the mix of wet and dry assumes the CLI output is sample-aligned with its input (marked with a `ponytail:` comment). Verified on clips of about 40 s only; check it if you change chunking.
- **`NaN` in JSON** breaks the browser: use `None`.
- **`classList.toggle(name, undefined)` toggles** instead of forcing. Wrap the condition in `Boolean(...)`.
- **Sidon on Apple's GPU fails** ("Passed CPU tensor to MPS op"): the published TorchScript files have CPU constants baked in. It runs on CPU. A port exists as ONNX and Core ML on Hugging Face (community conversions, not evaluated here) if speed ever matters.
- **Hugging Face downloads stalled** with the default `hf-xet` backend; `sidon.py` sets `HF_HUB_DISABLE_XET=1`.
- **PyTorch wheels** were not available for Python 3.13 when this was written, so `sidon.py` pins `requires-python = ">=3.10,<3.13"`.
- **Sidon preprocessing** (from the authors' demo): peak-normalise to 0.9, 50 Hz high-pass, resample to 16 kHz, 96-second chunks, one frame of feature context carried across chunk boundaries, output 48 kHz mono trimmed to the input length. Do not change these casually; the whole input file is read into memory at once (fine for hours of mono audio on 18 GB, not unbounded).
- **Paths contain Hebrew and spaces** (the project folder, the app name, output file names). Quote every path in shell. Never run a recursive delete with an unguarded variable (`rm -rf "${VAR:?}/..."`).
- **`ditto` flags** in `package.sh` are required, see section 9.
- **Idle shutdown** is why the page pings the server. Do not remove the ping while the flag exists.
- **Output name suffix** ` - מוגבר ב-AI` is part of the user-facing contract (README, UI, skill).

## 14. Known gaps and ideas

Not verified, say so honestly when it matters:
- `hop` 1.0 and gen on **echoey, quiet lectures**: only measured on a clean clip. Both are possible quality risks there; the user can raise the overlap again in the UI.
- Sidon on any recording but clear Hebrew speech; its Hebrew coverage is likely but not stated explicitly by its authors.
- The native file chooser was never clicked in automated testing (only compiled); the macOS launcher app was exercised with a stubbed browser opener.
- `build-cli.sh` has not been run from a clean machine; the zip has not been tested on a second Mac or under Gatekeeper.
- The skill has not been exercised end to end from a fresh Claude Code session.
- The per-minute ffmpeg cost (3 s) is a large share once the model is fast. The pre-gain `loudnorm` and the two-pass final `loudnorm` dominate; replacing the first with a static gain would change the sound and needs a listening test.
- The UI is Hebrew only.
- Windows was verified only by CI (`check.yml`), never by a person: the tkinter file chooser, `start.bat` and Explorer reveal have not been clicked. The PyTorch engine's speed on a real Windows PC or Intel Mac is unmeasured (the `RTF['torch']` numbers come from an M3 Pro CPU).
- Windows with an NVIDIA GPU could run the port on CUDA (install torch from the CUDA index); not done.
- Possible next steps: a chunked, parallel run for very long files; real per-chunk progress from the CLI; an ONNX or Core ML route for Sidon to avoid PyTorch.
