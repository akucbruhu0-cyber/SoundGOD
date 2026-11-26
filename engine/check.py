#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "soundfile"]
# ///
"""Smoke check: a 10 s preview must hit the loudness target, stay under the peak ceiling, keep its length.

  uv run --script engine/check.py [FILE]      (default: a 10 s tone burst train made with ffmpeg)
  uv run --script engine/check.py --full      also a full run on a Hebrew-named file and a web-server round trip
                                              (what the Windows / Intel Mac CI job runs)
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
UV = shutil.which("uv") or "uv"
TEXT = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace"}
sys.stdout.reconfigure(encoding="utf-8")  # prints Hebrew file names; a Windows console is cp1252
full = "--full" in sys.argv
args = [a for a in sys.argv[1:] if a != "--full"]


def engine(*a: str) -> dict:
    p = subprocess.run([UV, "run", "--script", str(HERE / "enhance.py"), *a, "--json"], **TEXT)
    last = json.loads(p.stdout.strip().splitlines()[-1])
    assert last["event"] == "done", p.stdout + p.stderr
    return last


def server_round_trip(src: Path) -> None:
    srv = subprocess.Popen([UV, "run", "--script", str(HERE.parent / "ui" / "server.py"), "--no-open", "--port", "8899"],
                           stdout=subprocess.PIPE, **{k: v for k, v in TEXT.items() if k != "capture_output"})
    try:
        url = re.search(r"http://\S+", srv.stdout.readline()).group(0)  # type: ignore[union-attr]
        token = re.search(r'name="token" content="([^"]+)"', urllib.request.urlopen(url).read().decode()).group(1)

        def api(path: str, body: dict | None = None) -> dict:
            req = urllib.request.Request(url + path.lstrip("/"), headers={"X-Token": token, "Content-Type": "application/json"},
                                         data=json.dumps(body).encode() if body is not None else None)
            return json.loads(urllib.request.urlopen(req, timeout=120).read())

        print("server backend:", api("/api/describe")["backend"])
        job = api("/api/analyze", {"path": str(src), "params": {}})["job"]
        for _ in range(300):
            j = api(f"/api/job/{job}")
            if j["state"] != "running":
                break
            time.sleep(1)
        assert j["state"] == "done", j
        print("server analyze ok:", j["result"]["suggested_preset"])
    finally:
        srv.terminate()


with tempfile.TemporaryDirectory() as tmp:
    src = Path(args[0]) if args else Path(tmp) / "בדיקה קצרה.wav"  # Hebrew and a space: the paths users actually have
    if not args:  # speech-like bursts at a very low level + noise (fixed seed: with random noise the loudness landed 1-3 dB low about one run in three)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "sine=f=180:d=12,tremolo=f=4:d=0.9,volume=0.01", "-f", "lavfi", "-i", "anoisesrc=d=12:a=0.003:seed=7",
                        "-filter_complex", "amix=inputs=2:normalize=0", str(src)], check=True)
    last = engine(str(src), "--preview", "1,10", "--outdir", tmp + "/out", "--lufs", "-16")
    a = last["after"]
    assert abs(a["lufs"] + 16) <= 1.0, f"loudness {a['lufs']} not near -16"
    assert a["peak_db"] <= -1.0, f"peak {a['peak_db']} above ceiling"
    assert abs(a["duration"] - 10) <= 0.2, f"duration {a['duration']}"
    assert (Path(tmp) / "out" / "before.png").exists()
    print("ok", a)
    if full:
        r = engine(str(src), "--preset", "rescue")
        out = Path(r["output"])
        assert out.exists() and out.name.endswith(" - מוגבר ב-AI.wav"), r["output"]
        assert abs(r["after"]["duration"] - r["before"]["duration"]) <= 0.5, r
        print("full run ok:", out.name, f"{r['seconds']} s, clean {r.get('clean_s')} s, rtf {r['rtf']}")
        server_round_trip(src)
