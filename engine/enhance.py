#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "soundfile"]
# ///
"""audio-enhance core: clean (Nemotron RE-USE), generative restoration (Sidon) and polish (ffmpeg) for speech in audio/video.

One engine, two front-ends: the Claude Code skill and the local web UI both call this file.

  enhance.py FILE                       full run, writes "<name> - מוגבר ב-AI.<ext>" next to FILE
  enhance.py FILE --analyze --json      measure only, suggest a preset
  enhance.py FILE [settings] --estimate --json   expected seconds for those settings, split by engine
  enhance.py FILE --preview 30,15 --outdir DIR   15 s before/after (+spectrograms) into DIR

Stage 1 CLEAN (ML, removes noise + reverb, does not invent speech) -> optional dry/wet mix
Stage 2 POLISH (ffmpeg DSP: highpass, gate, warmth, presence, compression, loudness)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "bin" / "noise-reduction"
BUNDLED = ROOT / "models" / "nemotron-re-use"  # weights shipped with the project (OpenMDW-1.1, see models/*/LICENSE)
WEIGHTS = Path.home() / "Library/Application Support/EfficientNoiseReduction/NVIDIA-NemotronLabs-RE-USE"  # CLI's own cache
TORCH_CLEAN = ROOT / "engine" / "nemotron.py"  # the same model in PyTorch on the CPU: Windows, Intel Macs, Linux
SIDON = ROOT / "engine" / "sidon.py"  # engine 3: generative restoration (own uv environment with torch)
SIDON_DIR = ROOT / "models" / "sidon"
UV = shutil.which("uv") or "/opt/homebrew/bin/uv"
SUFFIX = " - מוגבר ב-AI"
SR = 48000  # internal mixing/polish rate
# clean engine runtime: the MLX tool on Apple silicon, the PyTorch port everywhere else (SOUNDGOD_ENGINE=torch forces it)
# ask the hardware, not this Python: uv may pick an Intel Python that runs under Rosetta and reports x86_64
APPLE_SILICON = sys.platform == "darwin" and (platform.machine() == "arm64" or subprocess.run(
    ["sysctl", "-n", "hw.optional.arm64"], capture_output=True, text=True).stdout.strip() == "1")
BACKEND = os.environ.get("SOUNDGOD_ENGINE") or ("mlx" if APPLE_SILICON else "torch")

# name -> (default, min, max, type). The web UI reads this via --describe.
PARAMS = {
    "wet": (100, 0, 100, float),
    "chunk": (2.0, 0.5, 5.0, float),
    "hop": (0.5, 0.5, 1.0, float),  # chunk step as a fraction of the chunk: 0.5 = 50 % overlap (default), 1.0 = no overlap, twice as fast
    "bwe": ("off", None, None, str),  # off | 32000 | 48000
    "rate": ("auto", None, None, str),  # auto | 16000 | 48000
    "lufs": (-16.0, -23.0, -12.0, float),
    "presence": (0.0, -6.0, 6.0, float),
    "warmth": (0.0, -6.0, 6.0, float),
    "comp": (30, 0, 100, float),
    "gate": (10, 0, 100, float),
    "pregain": (True, None, None, bool),
    "clean": (True, None, None, bool),  # engine 1: Nemotron RE-USE, removes noise and reverb. Off = skip it entirely
    "gen": (False, None, None, bool),  # engine 2: Sidon, generative restoration (full band, studio-like). Needs a one-time ~1.7 GB setup
    "polish": (True, None, None, bool),  # engine 3: gate / EQ / compression. Off = only loudness is matched
}

# Measured on an M3 Pro (33 s clip, 2 s chunks). The UI shows its time estimate from these numbers.
# rtf = processing seconds per second of audio, by the rate the model produces output at.
RTF = {
    "mlx": {"16000": 0.205, "32000": 0.42, "48000": 0.56},
    # PyTorch port on the CPU, measured on the same M3 Pro's CPU (hop 1.0 gave 2.14 / 7.21, doubled to hop 0.5; 32 kHz interpolated).
    # A Windows PC or an Intel Mac will differ, often slower: the UI calls these estimates.
    "torch": {"16000": 4.3, "32000": 9.4, "48000": 14.5},
}
SPEED = {
    "rtf": RTF.get(BACKEND, RTF["torch"]),
    "hop_ref": 0.5,  # rtf above is at hop 0.5; time scales as 0.5/hop (measured: hop 0.75 -> x0.66, hop 1.0 -> x0.48)
    "chunk_extra": 0.38,  # a 0.5 s chunk costs ~38 % more than a 2 s chunk; above 2 s no further saving
    "ffmpeg_per_min": 3.0,  # extract, resample, loudness (two passes), encode: seconds per audio minute (5 min file: 15.7 s without the model)
    "polish_extra_per_min": 0.35,  # the EQ/gate/compressor chain adds this per audio minute
    "fixed": 0.5,
    "gen_rtf": 0.33,  # Sidon on the CPU (the published files do not run on MPS)
    "gen_fixed": 3.0,  # python + torch import, loading ~1 GB of weights (measured: 33.6 s clip took 12.5 s)
}


def estimate(dur: float, model_rate: int, out_rate: int, chunk: float, clean: bool = True, polish: bool = True, hop: float = 0.5, gen: bool = False) -> dict:
    """Expected seconds for `dur` seconds of audio, split by engine."""
    m = dur / 60
    ai = 0.0
    if clean:
        rate = max(model_rate, out_rate)
        key = "48000" if rate >= 48000 else "32000" if rate >= 32000 else "16000"
        ai = dur * SPEED["rtf"][key] * (1 + SPEED["chunk_extra"] * max(0.0, 2.0 - chunk) / 1.5) * SPEED["hop_ref"] / hop
    ff = SPEED["fixed"] + m * (SPEED["ffmpeg_per_min"] + (SPEED["polish_extra_per_min"] if polish else 0))
    g = dur * SPEED["gen_rtf"] + SPEED["gen_fixed"] if gen else 0.0
    return {"ai": round(ai, 1), "gen": round(g, 1), "ffmpeg": round(ff, 1), "total": round(ai + g + ff, 1)}

PRESETS = {
    "rescue": dict(wet=100, chunk=2.0, hop=1.0, bwe="off", rate="16000", lufs=-16, presence=2.0, warmth=0.0, comp=40, gate=15, pregain=True, clean=True, gen=False, polish=True),
    "studio": dict(wet=90, chunk=2.0, hop=1.0, bwe="off", rate="auto", lufs=-16, presence=1.5, warmth=1.5, comp=35, gate=10, pregain=True, clean=False, gen=True, polish=True),
    "natural": dict(wet=60, chunk=2.0, hop=1.0, bwe="off", rate="auto", lufs=-18, presence=0.0, warmth=0.0, comp=15, gate=0, pregain=True, clean=True, gen=False, polish=True),
}


# ---------------------------------------------------------------- plumbing

def ffmpeg_bin() -> str:
    return shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    # the Swift CLI is built with coverage on and would drop a 5 MB default.profraw into the cwd on every run
    env = {**os.environ, "LLVM_PROFILE_FILE": os.devnull}
    if (BUNDLED / "model.safetensors").exists():
        env["NEMOTRON_MODEL_DIR"] = str(BUNDLED)  # the CLI looks here before its own cache
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if check and p.returncode != 0:
        raise RuntimeError(f"{Path(str(cmd[0])).name} failed: {p.stderr.strip()[-600:]}")
    return p


def ff(*args: str) -> subprocess.CompletedProcess:
    return run([ffmpeg_bin(), "-hide_banner", "-nostats", "-y", *args])


class Emitter:
    """JSON lines on stdout with --json (for the UI server), plain text otherwise."""

    def __init__(self, as_json: bool):
        self.as_json = as_json
        self.t0 = time.time()

    def stage(self, name: str, pct: int, eta: float | None = None, to: int | None = None) -> None:
        if self.as_json:
            print(json.dumps({"event": "stage", "name": name, "pct": pct, "eta": eta, "to": to}), flush=True)
        else:
            print(f"[{pct:3d}%] {name}", file=sys.stderr, flush=True)

    def result(self, data: dict) -> None:
        if self.as_json:
            print(json.dumps({"event": "done", **data}, ensure_ascii=False), flush=True)
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- measuring

def lufs_peak(path: Path) -> tuple[float, float]:
    p = run([ffmpeg_bin(), "-hide_banner", "-nostats", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"])
    # the summary block repeats "I:" and "Peak:" once at the end; the running lines carry other tags
    i = re.findall(r"\bI:\s+(-?[\d.]+)\s+LUFS", p.stderr)
    k = re.findall(r"Peak:\s+(-?[\d.]+)\s+dBFS", p.stderr)
    return (float(i[-1]) if i else -70.0, float(k[-1]) if k else -90.0)


def measure(path: Path) -> dict:
    x, sr = sf.read(path, dtype="float32")
    if x.ndim > 1:
        x = x.mean(1)
    n = int(sr * 0.05)
    m = len(x) // n
    if m < 4:
        raise RuntimeError("audio is too short to measure")
    fr = x[: m * n].reshape(m, n)
    db = np.maximum(20 * np.log10(np.sqrt((fr**2).mean(1)) + 1e-9), -90.0)  # floor: digital silence must not inflate SNR
    speech, noise = float(np.percentile(db, 90)), float(np.percentile(db, 10))
    loud = fr[db >= np.percentile(db, 70)]
    pdb = 10 * np.log10((np.abs(np.fft.rfft(loud * np.hanning(n), axis=1)) ** 2).mean(0) + 1e-20)
    f = np.fft.rfftfreq(n, 1 / sr)
    bw = float(f[np.where(pdb >= pdb.max() - 60)[0].max()])
    lufs, peak = lufs_peak(path)
    return {
        "duration": round(len(x) / sr, 2),
        "lufs": round(lufs, 1),
        "peak_db": round(peak, 1),
        "speech_db": round(speech, 1),
        "noise_floor_db": round(noise, 1),
        "snr_db": round(speech - noise, 1),
        "bandwidth_hz": int(round(bw, -2)),
    }


def suggest_preset(m: dict) -> str:
    # a quiet or noisy source is a rescue job; a healthy one only needs studio polish
    return "rescue" if (m["lufs"] < -35 or m["snr_db"] < 18) else "studio"


# ---------------------------------------------------------------- stages

def extract(src: Path, dst: Path, rate: int, seg: tuple[float, float] | None = None) -> None:
    args = []
    if seg:
        args += ["-ss", str(seg[0]), "-t", str(seg[1])]
    ff(*args, "-i", str(src), "-vn", "-ac", "1", "-ar", str(rate), "-c:a", "pcm_f32le", str(dst))


def resample(src: Path, dst: Path, rate: int) -> None:
    ff("-i", str(src), "-ar", str(rate), "-ac", "1", "-c:a", "pcm_f32le", str(dst))


def loudnorm_two_pass(src: Path, dst: Path, target: float, pre: str = "") -> None:
    """Linear loudness match: measure, then apply with the measured values (no pumping)."""
    chain = (pre + "," if pre else "") + f"loudnorm=I={target}:TP=-1.5:LRA=11"
    p = run([ffmpeg_bin(), "-hide_banner", "-nostats", "-i", src, "-af", chain + ":print_format=json", "-f", "null", "-"])
    j = json.loads(re.findall(r"\{[^{}]*\}", p.stderr)[-1])
    if j["input_i"] in ("-inf", "inf"):
        raise RuntimeError("source is silent")
    second = (
        chain
        + f":measured_I={j['input_i']}:measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}"
        + f":measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true"
    )
    ff("-i", str(src), "-af", second + ",alimiter=limit=0.84:level=0", "-ar", str(SR), "-c:a", "pcm_f32le", str(dst))


def ensure_model() -> None:
    if BACKEND != "mlx":
        if not (BUNDLED / "model.safetensors").exists():
            raise RuntimeError(f"missing {BUNDLED / 'model.safetensors'} — download the release zip again")
        return
    if not CLI.exists():
        raise RuntimeError(f"missing {CLI} — see README (setup)")
    if (BUNDLED / "model.safetensors").exists() or WEIGHTS.exists():
        return
    run([CLI, "download", "--engine", "nemotron"])  # last resort: fetch the pinned weights from Hugging Face


def clean(dry_in: Path, out: Path, model_rate: int, out_rate: int, chunk: float, hop: float = 0.5) -> float:
    """Nemotron RE-USE via the MLX CLI (Apple silicon) or the PyTorch port. Returns real-time factor."""
    ensure_model()
    if BACKEND != "mlx":
        if out_rate != model_rate:  # bandwidth extension: the port runs at the file's rate, so upsample first (as NVIDIA's --BWE)
            up = out.with_name("bwe_in.wav")
            resample(dry_in, up, out_rate)
            dry_in = up
        cmd = [UV, "run", "--script", TORCH_CLEAN, dry_in, out, "--chunk", chunk, "--hop", hop]
    else:
        cmd = [CLI, "enhance", dry_in, out, "--engine", "nemotron", "--latency", chunk, "--hop", hop]
        if out_rate != model_rate:
            cmd += ["--output-rate", out_rate]  # bandwidth extension
    p = run(cmd)
    m = re.search(r"RTF ([\d.]+)", p.stdout + p.stderr)
    return float(m.group(1)) if m else float("nan")


def polish_filters(p: dict) -> str:
    if not p["polish"]:
        return ""
    f = ["highpass=f=70"]
    if p["gate"] > 0:
        g = p["gate"]
        thr = max(10 ** ((-62 + g * 0.24) / 20), 0.001)
        rng = 10 ** (-(10 + g * 0.15) / 20)
        f.append(f"agate=threshold={thr:.5f}:ratio={2 + g * 0.04:.2f}:range={rng:.4f}:attack=8:release=150")
    if p["warmth"]:
        f.append(f"lowshelf=f=180:g={p['warmth']}")
    if p["presence"]:
        f.append(f"equalizer=f=3200:t=o:w=1.6:g={p['presence']}")
    if p["comp"] > 0:
        f.append(f"acompressor=threshold=0.1:ratio={1 + p['comp'] * 0.03:.2f}:attack=10:release=180:makeup=1")
    return ",".join(f)


def sidon_ready() -> bool:
    return all((SIDON_DIR / f).exists() for f in ("feature_extractor_cpu.pt", "decoder_cpu.pt"))


def process(src: Path, params: dict, work: Path, em: Emitter, seg: tuple[float, float] | None = None) -> dict:
    """src (audio or video) -> work/polished.wav. Returns timing + model info."""
    t = {}
    em.stage("extract", 5)
    dry48 = work / "dry48.wav"
    extract(src, dry48, SR, seg)
    bw = measure(dry48)["bandwidth_hz"]

    model_rate = int(params["rate"]) if params["rate"] != "auto" else (48000 if bw > 9000 else 16000)
    out_rate = int(params["bwe"]) if params["bwe"] != "off" else model_rate
    out_rate = max(out_rate, model_rate)
    if not params["clean"]:
        model_rate = out_rate = SR  # no model: keep everything at the working rate, no needless down/up-sampling

    gen_only = params["gen"] and not params["clean"]  # Sidon normalises the level itself, so no pre-gain pass
    if params["gen"] and not sidon_ready():
        em.stage("download", 3, eta=420, to=12)  # ~4 MB/s: weights 1 GB + the torch environment 0.7 GB
        run([UV, "run", "--script", SIDON, "--fetch"])

    em.stage("pregain", 15)
    dry_in = work / "dry_in.wav"
    if params["pregain"] and not gen_only:
        pre = work / "pre.wav"
        resample(dry48, pre, model_rate)
        # single-pass loudnorm lifts a very quiet source into the model's comfortable range
        ff("-i", str(pre), "-af", "loudnorm=I=-20:TP=-2:LRA=11", "-ar", str(model_rate), "-c:a", "pcm_f32le", str(dry_in))
    else:
        resample(dry48, dry_in, model_rate)

    rtf = None
    clean_to = 55 if params["gen"] else 70
    if params["clean"]:
        eta = estimate(sf.info(dry_in).duration, model_rate, out_rate, params["chunk"], hop=params["hop"])["ai"]
        em.stage("clean", 30, eta=eta, to=clean_to)
        wet_raw = work / "wet_raw.wav"
        t0 = time.time()
        rtf = clean(dry_in, wet_raw, model_rate, out_rate, params["chunk"], params["hop"])
        t["clean_s"] = round(time.time() - t0, 1)

        em.stage("mix", clean_to)
        wet48, dry48g = work / "wet48.wav", work / "dry48g.wav"
        resample(wet_raw, wet48, SR)
        resample(dry_in, dry48g, SR)
        w, d = sf.read(wet48, dtype="float32")[0], sf.read(dry48g, dtype="float32")[0]
        n = min(len(w), len(d))  # ponytail: assumes the CLI output is time-aligned; verified on 40 s clips
        a = params["wet"] / 100.0
        sf.write(work / "mixed.wav", a * w[:n] + (1 - a) * d[:n], SR, subtype="FLOAT")
    else:
        resample(dry_in, work / "mixed.wav", SR)

    polished_in = work / "mixed.wav"
    if params["gen"]:
        gstart = clean_to if params["clean"] else 30
        em.stage("gen", gstart, eta=estimate(sf.info(polished_in).duration, SR, SR, 2.0, clean=False, polish=False, gen=True)["gen"], to=85)
        t0 = time.time()
        gen_out = work / "gen.wav"
        run([UV, "run", "--script", SIDON, polished_in, gen_out])
        t["gen_s"] = round(time.time() - t0, 1)
        polished_in = gen_out

    em.stage("polish", 88 if params["gen"] else 80)
    loudnorm_two_pass(polished_in, work / "polished.wav", params["lufs"], pre=polish_filters(params))
    return {"model_rate": model_rate, "out_rate": out_rate, "rtf": rtf, **t}


def spectrogram(src: Path, dst: Path) -> None:
    ff("-i", str(src), "-lavfi", "showspectrumpic=s=900x200:legend=0:scale=log:stop=16000", str(dst))


def out_path(src: Path, has_video: bool) -> Path:
    ext = src.suffix.lower()
    if not has_video and ext not in (".wav", ".mp3", ".m4a", ".aac", ".flac"):
        ext = ".wav"
    p = src.with_name(src.stem + SUFFIX + ext)
    k = 2
    while p.exists():
        p = src.with_name(f"{src.stem}{SUFFIX} ({k}){ext}")
        k += 1
    return p


def encode(src: Path, polished: Path, dst: Path, has_video: bool) -> None:
    ext = dst.suffix.lower()
    codec = {".mp3": ["libmp3lame", "-b:a", "320k"], ".flac": ["flac"], ".wav": ["pcm_s24le"], ".webm": ["libopus", "-b:a", "192k"]}.get(
        ext, ["aac", "-b:a", "256k"]
    )
    if has_video:
        ff("-i", str(src), "-i", str(polished), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", *codec, "-shortest", str(dst))
    else:
        ff("-i", str(polished), "-c:a", *codec, str(dst))


def has_video_stream(src: Path) -> bool:
    p = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type,disposition", "-of", "json", src])
    streams = json.loads(p.stdout).get("streams", [])
    # cover art in an mp3/m4a is a "video" stream with attached_pic; not a real video
    return any(not s.get("disposition", {}).get("attached_pic") for s in streams)


# ---------------------------------------------------------------- CLI

def build_params(a: argparse.Namespace, preset: str) -> dict:
    p = dict(PRESETS[preset])
    for k, (_, lo, hi, typ) in PARAMS.items():
        v = getattr(a, k, None)
        if v is None:
            continue
        if typ is float and lo is not None:
            v = min(max(float(v), lo), hi)
        p[k] = v
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?")
    ap.add_argument("--preset", default="auto", choices=["auto", *PRESETS])
    for k, (_, _, _, typ) in PARAMS.items():
        if typ is bool:
            continue
        ap.add_argument(f"--{k}", type=str if typ is str else float)
    ap.add_argument("--no-pregain", action="store_true")
    for k, h in (("clean", "Nemotron RE-USE: noise and reverb removal"), ("gen", "Sidon: generative restoration, needs a one-time ~1.7 GB setup"), ("polish", "gate/EQ/compression")):
        ap.add_argument(f"--{k}", action=argparse.BooleanOptionalAction, default=None, help=h)
    ap.add_argument("--out", help="output path (default: next to the input)")
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--estimate", action="store_true", help="measure, then print the expected processing time for these settings (nothing is processed)")
    ap.add_argument("--preview", metavar="START,DUR", help="process only this window, write before/after to --outdir")
    ap.add_argument("--outdir")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--describe", action="store_true", help="print presets and parameter ranges as JSON")
    a = ap.parse_args()

    if a.describe:
        print(json.dumps({"sidon_ready": sidon_ready(), "backend": BACKEND, "speed": SPEED, "presets": PRESETS, "params": {k: {"default": v[0], "min": v[1], "max": v[2]} for k, v in PARAMS.items()}}))
        return 0
    if not a.input:
        ap.error("input is required")
    src = Path(a.input).expanduser().resolve()
    if not src.exists():
        raise SystemExit(f"not found: {src}")

    em = Emitter(a.json)
    with tempfile.TemporaryDirectory(prefix="audio-enhance-") as tmp:
        work = Path(tmp)
        em.stage("measure", 2)
        probe = work / "probe.wav"
        extract(src, probe, SR)
        before = measure(probe)
        preset = suggest_preset(before) if a.preset == "auto" else a.preset
        if a.analyze:
            em.result({"before": before, "suggested_preset": preset})
            return 0

        a.pregain = False if a.no_pregain else None
        params = build_params(a, preset)
        if a.estimate:
            mr = int(params["rate"]) if params["rate"] != "auto" else (48000 if before["bandwidth_hz"] > 9000 else 16000)
            out = max(int(params["bwe"]) if params["bwe"] != "off" else mr, mr)
            em.result({"preset": preset, "params": params, "sidon_ready": sidon_ready(), "duration": before["duration"],
                       "estimate_s": estimate(before["duration"], mr, out, params["chunk"], params["clean"], params["polish"], params["hop"], params["gen"])})
            return 0
        t0 = time.time()

        if a.preview:
            start, dur = (float(x) for x in a.preview.split(","))
            outdir = Path(a.outdir or tempfile.mkdtemp(prefix="audio-enhance-prev-"))
            outdir.mkdir(parents=True, exist_ok=True)
            info = process(src, params, work, em, seg=(start, dur))
            # "before" is the original window at the same loudness, so A/B is fair
            raw = work / "seg.wav"
            extract(src, raw, SR, (start, dur))
            loudnorm_two_pass(raw, outdir / "before.wav", params["lufs"])
            shutil.copy(work / "polished.wav", outdir / "after.wav")
            spectrogram(outdir / "before.wav", outdir / "before.png")
            spectrogram(outdir / "after.wav", outdir / "after.png")
            em.stage("done", 100)
            em.result({"preset": preset, "params": params, "outdir": str(outdir), "after": measure(outdir / "after.wav"),
                       "seconds": round(time.time() - t0, 1), **info})
            return 0

        video = has_video_stream(src)
        info = process(src, params, work, em)
        em.stage("finalize", 92)
        dst = Path(a.out).expanduser() if a.out else out_path(src, video)
        encode(src, work / "polished.wav", dst, video)
        after = measure(work / "polished.wav")
        em.stage("done", 100)
        em.result({"output": str(dst), "preset": preset, "params": params, "before": before, "after": after,
                   "seconds": round(time.time() - t0, 1), **info})
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # JSON with Hebrew paths; Windows consoles default to a legacy code page
    try:
        sys.exit(main())
    except RuntimeError as e:
        print(json.dumps({"event": "error", "message": str(e)}, ensure_ascii=False))
        sys.exit(1)
