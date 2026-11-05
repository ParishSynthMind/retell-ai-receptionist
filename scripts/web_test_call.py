"""Live end-to-end test over a real Retell web call, no phone line and no microphone needed.

A headless Chromium joins a Retell web call to the agent. Instead of a microphone it plays
pre-recorded caller lines (made with any text-to-speech, e.g. macOS `say`), waiting for the
receptionist to stop talking before each one. Retell transcribes the caller, Claude decides, and
the custom functions run on this server. Clips are played in filename order (01.wav, 02.wav, ...).

  python scripts/web_test_call.py --clips clips/booking --out runs/booking [--hangup-early]

The API key comes from RETELL_API_KEY, or from the macOS Keychain with --keychain SERVICE. The
agent id comes from var/retell_ids.json (written by create_agent.py) or --agent-id. The web-call
access token goes to the page only and is never printed; console lines are saved with tokens redacted.
Needs: pip install playwright && playwright install chromium.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from receptionist.retell_api import RetellAPI  # noqa: E402


def serve(root: Path, port: int):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Quiet, directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def redact(text: str) -> str:
    return re.sub(r"(access_token=|eyJ)[A-Za-z0-9._%-]+", "<token redacted>", text)


def wait_for(page, js: str, timeout: float) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if page.evaluate(js):
            return True
        time.sleep(0.25)
    return False


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--clips", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--title", default="Retell AI receptionist: live web call")
    p.add_argument("--hangup-early", action="store_true", help="hang up while the agent answers the last clip")
    p.add_argument("--port", type=int, default=8798)
    p.add_argument("--agent-id")
    p.add_argument("--ids-file", default=str(ROOT / "var" / "retell_ids.json"))
    p.add_argument("--keychain", help="read the API key from this Keychain item instead of the environment")
    p.add_argument("--keychain-account", default=os.environ.get("RETELL_KEYCHAIN_ACCOUNT", "neo"))
    p.add_argument("--quiet-seconds", type=float, default=2.5)
    a = p.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.keychain:
        key = subprocess.run(["security", "find-generic-password", "-a", a.keychain_account, "-s", a.keychain, "-w"],
                             capture_output=True, text=True, check=True).stdout.strip()
    else:
        key = os.environ.get("RETELL_API_KEY") or sys.exit("Set RETELL_API_KEY, or pass --keychain SERVICE")
    agent_id = a.agent_id or json.loads(Path(a.ids_file).read_text())["agent_id"]
    api = RetellAPI(key)

    root = Path(tempfile.mkdtemp())
    shutil.copy(HERE / "web_caller" / "index.html", root / "index.html")
    clips = sorted(Path(a.clips).glob("*.wav"))
    (root / "clips").mkdir()
    for c in clips:
        shutil.copy(c, root / "clips" / c.name)
    srv = serve(root, a.port)
    quiet = (f"!__state.speaking && __state.lastSpeechEnd > 0 && "
             f"Date.now() - __state.lastSpeechEnd > {a.quiet_seconds * 1000}")
    steps = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required",
                                                          "--use-fake-ui-for-media-stream"])
        page = browser.new_page(viewport={"width": 1100, "height": 900})  # own headless browser, no screen
        logf = (out / "browser-console.log").open("w", buffering=1)
        page.on("console", lambda m: logf.write(f"{m.type}: {redact(m.text)}\n"))
        page.on("pageerror", lambda e: logf.write(f"pageerror: {e}\n"))
        page.goto(f"http://127.0.0.1:{a.port}/index.html")
        page.wait_for_function("window.__ready === true", timeout=60000)
        page.evaluate("([t, s]) => setTitle(t, s)", [a.title, "Real Retell web call. Claude Sonnet 5.5 on Retell, "
                      "custom functions on this FastAPI server. The caller is a scripted synthetic voice."])
        web = api.create_web_call(agent_id)
        call_id = web["call_id"]
        (out / "call_id.txt").write_text(call_id)
        print("call id:", call_id, "transport:", web.get("transport"), "response keys:", sorted(web), flush=True)
        page.evaluate("t => { startCall(t).then(() => { __state.joined = true }).catch(e => { __state.error = 'startCall: ' + (e && e.message || e) }) }", {"token": web["access_token"], "transport": web.get("transport"), "callId": call_id})
        if not wait_for(page, "__state.joined || __state.error", 30):
            print("startCall did not finish in 30s", flush=True)
        print("joined:", page.evaluate("({j: __state.joined, s: __state.started, e: __state.error, g: __state.gum})"), flush=True)
        if not wait_for(page, quiet, 45):
            print("greeting not finished:", page.evaluate("({s: __state.started, e: __state.error, g: __state.gum})"))
        for i, clip in enumerate(clips, 1):
            print("caller says:", clip.name, flush=True)
            page.evaluate("u => playClip(u)", f"clips/{clip.name}")
            page.evaluate("() => { __state.lastSpeechEnd = 0 }")
            steps.append(clip.name)
            if not wait_for(page, "__state.ended || __state.speaking", 30):
                print("  (no reply within 30s)", flush=True)
            if a.hangup_early and i == len(clips):
                time.sleep(1.5)
                print("caller hangs up mid-answer", flush=True)
                page.evaluate("stopCall()")
                break
            if not wait_for(page, f"__state.ended || ({quiet})", 120):
                print("  (still talking after 120s)", flush=True)
            if page.evaluate("__state.ended"):
                break
        wait_for(page, "__state.ended", 25)
        if not page.evaluate("__state.ended"):
            page.evaluate("stopCall()")
            wait_for(page, "__state.ended", 10)
        time.sleep(1)
        page.screenshot(path=str(out / "live-transcript.png"), full_page=True)
        state = page.evaluate("__state")
        (out / "browser-transcript.json").write_text(json.dumps(state["transcript"], indent=2))
        print("ended:", state["ended"], "error:", state["error"], "mic hooked:", state["gum"], flush=True)
        browser.close()
    srv.shutdown()


if __name__ == "__main__":
    main()
