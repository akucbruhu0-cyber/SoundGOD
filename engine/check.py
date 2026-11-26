#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "soundfile"]
# ///
"""Smoke check: a 10 s preview must hit the loudness target, stay under the peak ceiling, keep its length.

  uv run --script engine/check.py [FILE]      (default: a 10 s tone burst train made with ffmpeg)
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
with tempfile.TemporaryDirectory() as tmp:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tmp) / "in.wav"
    if len(sys.argv) < 2:  # speech-like bursts at a very low level + noise: enough to exercise every stage
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "sine=f=180:d=12,tremolo=f=4:d=0.9,volume=0.01", "-f", "lavfi", "-i", "anoisesrc=d=12:a=0.003",
                        "-filter_complex", "amix=inputs=2:normalize=0", str(src)], check=True)
    p = subprocess.run([str(HERE / "enhance.py"), str(src), "--preview", "1,10", "--outdir", tmp + "/out", "--lufs", "-16", "--json"],
                       capture_output=True, text=True)
    last = json.loads(p.stdout.strip().splitlines()[-1])
    assert last["event"] == "done", p.stdout + p.stderr
    a = last["after"]
    assert abs(a["lufs"] + 16) <= 1.0, f"loudness {a['lufs']} not near -16"
    assert a["peak_db"] <= -1.0, f"peak {a['peak_db']} above ceiling"
    assert abs(a["duration"] - 10) <= 0.2, f"duration {a['duration']}"
    assert (Path(tmp) / "out" / "before.png").exists()
    print("ok", a)
