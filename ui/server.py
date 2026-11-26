#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# ///
"""Local web UI server for audio-enhance. Stdlib only, 127.0.0.1 only.

  ./ui/server.py [--port 8787] [--no-open]

It can pick files on this computer and write next to them, so it is guarded three ways:
loopback bind, Host-header check (DNS rebinding), and a per-run token on every API/media request.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine" / "enhance.py"
UI = ROOT / "ui"
CACHE = Path(tempfile.gettempdir()) / "audio-enhance-ui"
TOKEN = secrets.token_urlsafe(24)
UV = shutil.which("uv") or "/opt/homebrew/bin/uv"

# whitelist: key -> validator. Nothing else from the browser reaches the engine's argv.
NUM = {"wet": (0, 100), "chunk": (0.5, 5), "hop": (0.5, 1), "lufs": (-23, -12), "presence": (-6, 6), "warmth": (-6, 6), "comp": (0, 100), "gate": (0, 100)}
CHOICE = {"bwe": {"off", "32000", "48000"}, "rate": {"auto", "16000", "48000"}, "preset": {"auto", "rescue", "studio", "natural"}}

TEXT = {"text": True, "encoding": "utf-8", "errors": "replace"}  # the engine prints UTF-8 JSON; Windows would decode it as cp1252
PROMPT = "בחר הקלטה או סרטון"
# Windows/Linux file chooser: tkinter in a child process (a dialog cannot run on the server's worker thread)
TK_PICK = ("import tkinter as t, tkinter.filedialog as f, sys; r = t.Tk(); r.withdraw(); r.attributes('-topmost', True); "
           "sys.stdout.reconfigure(encoding='utf-8'); print(f.askopenfilename(title=sys.argv[1]) or '')")

LAST = [time.time()]  # last request; the optional idle shutdown (--idle-exit) watches this
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()


def engine_flags(p: dict) -> list[str]:
    flags: list[str] = []
    for k, (lo, hi) in NUM.items():
        if k in p:
            v = float(p[k])
            flags += [f"--{k}", str(min(max(v, lo), hi))]
    for k, ok in CHOICE.items():
        if k in p:
            v = str(p[k])
            if v not in ok:
                raise ValueError(f"bad {k}")
            flags += [f"--{k}", v]
    if p.get("pregain") is False:
        flags.append("--no-pregain")
    for k in ("clean", "gen", "polish"):  # explicit on/off, because the presets differ in which engines they use
        if isinstance(p.get(k), bool):
            flags.append(f"--{k}" if p[k] else f"--no-{k}")
    return flags


def valid_media(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute() or not p.is_file():
        raise ValueError("file not found")
    return p


def start_job(kind: str, body: dict) -> str:
    src = valid_media(body["path"])
    cmd = [UV, "run", "--script", str(ENGINE), str(src), "--json", *engine_flags(body.get("params", {}))]
    jid = uuid.uuid4().hex[:10]
    if kind == "analyze":
        cmd.append("--analyze")
    elif kind == "preview":
        start, dur = max(float(body["start"]), 0.0), min(max(float(body["dur"]), 3.0), 60.0)
        cmd += ["--preview", f"{start},{dur}", "--outdir", str(CACHE / jid)]
    job = {"id": jid, "kind": kind, "state": "running", "stage": "starting", "pct": 0, "eta": None, "to": None, "t": time.time(), "result": None, "error": None, "proc": None}
    with LOCK:
        JOBS[jid] = job

    def work() -> None:
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **TEXT)
            job["proc"] = proc
            for line in proc.stdout:  # type: ignore[union-attr]
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("event") == "stage":
                    job["stage"], job["pct"], job["eta"], job["to"], job["t"] = ev["name"], ev["pct"], ev.get("eta"), ev.get("to"), time.time()
                elif ev.get("event") == "done":
                    job["result"] = ev
                elif ev.get("event") == "error":
                    job["error"] = ev.get("message")
            proc.wait()
            if job["state"] == "cancelled":
                return
            if proc.returncode != 0 and not job["error"]:
                job["error"] = (proc.stderr.read() or "engine failed")[-400:]  # type: ignore[union-attr]
            job["state"] = "error" if job["error"] else "done"
        except Exception as e:  # noqa: BLE001
            job["error"], job["state"] = str(e), "error"

    threading.Thread(target=work, daemon=True).start()
    return jid


def pick_file() -> str | None:
    if sys.platform == "darwin":
        cmd = ["osascript", "-e", f'POSIX path of (choose file with prompt "{PROMPT}")']
    else:
        cmd = [sys.executable, "-c", TK_PICK, PROMPT]
    p = subprocess.run(cmd, capture_output=True, timeout=600, **TEXT)
    return str(Path(p.stdout.strip())) if p.stdout.strip() else None


def reveal(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", str(path)])
    elif sys.platform == "win32":
        subprocess.run(["explorer", f"/select,{path}"])  # explorer returns 1 even on success
    else:
        subprocess.run(["xdg-open", str(path.parent)])


def public(job: dict) -> dict:
    return {k: v for k, v in job.items() if k != "proc"}


class Handler(BaseHTTPRequestHandler):
    server_version = "audio-enhance"

    def log_message(self, *_a) -> None:  # quiet
        pass

    # ---- helpers
    def host_ok(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def token_ok(self, query: dict) -> bool:
        return secrets.compare_digest(self.headers.get("X-Token") or (query.get("t") or [""])[0], TOKEN)

    def send_json(self, data: dict, status: int = 200) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def send_file(self, path: Path, ctype: str | None = None) -> None:
        size = path.stat().st_size
        start, end = 0, size - 1
        status = HTTPStatus.OK
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a) if a else 0
            end = int(b) if b else size - 1
            status = HTTPStatus.PARTIAL_CONTENT
        self.send_response(status)
        self.send_header("Content-Type", ctype or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")  # the UI files change between versions; never serve a stale copy
        self.send_header("Content-Length", str(end - start + 1))
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(65536, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    # ---- routes
    def do_GET(self) -> None:  # noqa: N802
        LAST[0] = time.time()
        if not self.host_ok():
            return self.send_error(HTTPStatus.FORBIDDEN)
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            html = (UI / "index.html").read_text(encoding="utf8").replace("__TOKEN__", TOKEN)
            raw = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)
            return
        if u.path.startswith("/static/"):
            f = (UI / "static" / unquote(u.path[8:])).resolve()
            if (UI / "static") in f.parents and f.is_file():
                return self.send_file(f)
            return self.send_error(HTTPStatus.NOT_FOUND)
        if not self.token_ok(q):
            return self.send_error(HTTPStatus.FORBIDDEN)
        if u.path == "/api/ping":  # the page calls this every 30 s while it is open
            return self.send_json({})
        if u.path.startswith("/api/job/"):
            job = JOBS.get(u.path.rsplit("/", 1)[1])
            return self.send_json(public(job)) if job else self.send_error(HTTPStatus.NOT_FOUND)
        if u.path.startswith("/media/"):
            f = (CACHE / unquote(u.path[7:])).resolve()
            if CACHE.resolve() in f.parents and f.is_file():
                return self.send_file(f)
        if u.path == "/api/describe":
            p = subprocess.run([UV, "run", "--script", str(ENGINE), "--describe"], capture_output=True, **TEXT)
            return self.send_json(json.loads(p.stdout))
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        LAST[0] = time.time()
        u = urlparse(self.path)
        if not self.host_ok() or not self.token_ok(parse_qs(u.query)):
            return self.send_error(HTTPStatus.FORBIDDEN)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        try:
            if u.path == "/api/pick":
                return self.send_json({"path": pick_file()})
            if u.path in ("/api/analyze", "/api/preview", "/api/run"):
                return self.send_json({"job": start_job(u.path.rsplit("/", 1)[1], body)})
            if u.path == "/api/cancel":
                job = JOBS.get(body.get("job", ""))
                if job and job.get("proc") and job["state"] == "running":
                    job["state"] = "cancelled"
                    job["proc"].terminate()
                return self.send_json({"ok": True})
            if u.path == "/api/reveal":
                reveal(valid_media(body["path"]))
                return self.send_json({"ok": True})
        except (ValueError, KeyError) as e:
            return self.send_json({"error": str(e)}, 400)
        self.send_error(HTTPStatus.NOT_FOUND)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--idle-exit", type=int, default=0, metavar="MIN", help="quit after this many minutes without the page open or a job running (used by the app launcher)")
    a = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    srv = None
    for port in range(a.port, a.port + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if srv is None:
        sys.exit("no free port")
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"audio-enhance UI: {url}", flush=True)
    if not a.no_open:
        webbrowser.open(url)
    if a.idle_exit:
        def watch() -> None:
            while True:
                time.sleep(30)
                busy = any(j["state"] == "running" for j in JOBS.values())
                if not busy and time.time() - LAST[0] > a.idle_exit * 60:
                    os._exit(0)
        threading.Thread(target=watch, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
