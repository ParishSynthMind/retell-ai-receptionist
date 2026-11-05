"""Render the README images headless with Playwright, from the real local run in examples/local-run/.

    python scripts/render_media.py   (needs: pip install playwright && playwright install chromium)
"""
import html
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "examples" / "local-run"
MEDIA = ROOT / "media"
FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "'SF Mono', Menlo, Consolas, monospace"


def colour(line: str) -> str:
    t = html.escape(line)
    if line.startswith("$"):
        return f"<span style='color:#7ee787'>{t}</span>"
    if "HTTP 401" in line or "not available" in line:
        return f"<span style='color:#d29922'>{t}</span>"
    if "HTTP 20" in line:
        green = t.replace("HTTP 20", "<b style='color:#3fb950'>HTTP 20", 1)
        return green + "</b>"
    return t


def terminal() -> str:
    lines = (RUN / "1-simulated-call.txt").read_text().splitlines()
    wrapped = []
    for line in lines:  # keep long tool answers readable
        while len(line) > 150:
            cut = line.rfind(" ", 0, 150)
            wrapped.append(line[:cut])
            line = "        " + line[cut + 1:]
        wrapped.append(line)
    body = "\n".join(colour(x) for x in wrapped)
    return f"""<html><body style="margin:0;background:#0d1117">
<div id="wrap" style="display:inline-block;padding:22px 28px;background:#0d1117">
<div style="font-family:{FONT};color:#8b949e;font-size:13px;margin-bottom:10px">Real local run, 5 November 2026: the
server under uvicorn, driven by requests signed exactly as Retell signs them (X-Retell-Signature).</div>
<pre style="margin:0;font-family:{MONO};font-size:13px;line-height:1.5;color:#c9d1d9">{body}</pre></div></body></html>"""


def record() -> str:
    call = json.loads((RUN / "2-call-log.json").read_text())[0]
    emails = json.loads((RUN / "3-team-emails.json").read_text())
    rows = "".join(f"<tr><td style='padding:4px 10px 4px 0;color:#57606a'>{html.escape(k)}</td>"
                   f"<td style='padding:4px 0'>{html.escape(str(call[k]))}</td></tr>"
                   for k in ("call_id", "caller", "ended_reason", "duration_seconds", "cost", "outcome",
                             "analysis_summary", "sentiment"))
    tools = "".join(f"<li><b>{html.escape(e['tool'])}</b>: {html.escape(e['result'] if len(e['result']) <= 105 else e['result'][:105].rsplit(' ', 1)[0] + ' ...')}</li>"
                    for e in call["tool_events"])
    mails = "".join(f"<div style='border:1px solid #d0d7de;border-radius:8px;padding:10px 14px;margin-top:10px;"
                    f"background:#fff'><div style='font-weight:700'>{html.escape(m['subject'])}</div>"
                    f"<pre style='font-family:{MONO};font-size:12px;white-space:pre-wrap;margin:6px 0 0'>"
                    f"{html.escape(m['body'])}</pre></div>" for m in emails)
    return f"""<html><body style="margin:0;background:#f6f8fa;font-family:{FONT}">
<div id="wrap" style="display:inline-block;width:980px;padding:24px 30px;font-size:14px">
<div style="font-size:21px;font-weight:700">One call, as the server recorded it</div>
<div style="color:#555;margin:4px 0 14px">From the same local run: the call log (GET /calls), the functions Retell
called, and the two emails sent to the one team address.</div>
<div style="background:#fff;border:1px solid #d0d7de;border-radius:10px;padding:14px 18px">
<table style="border-collapse:collapse">{rows}</table>
<div style="margin-top:10px;font-weight:600">Functions called</div><ol style="margin:6px 0 0 18px;padding:0">{tools}</ol>
</div>{mails}</div></body></html>"""


def main():
    MEDIA.mkdir(exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page(viewport={"width": 1500, "height": 900}, device_scale_factor=2)
        for doc, out in [(terminal(), "local-signed-run.png"), (record(), "call-record-and-emails.png")]:
            page.set_content(doc)
            page.locator("#wrap").screenshot(path=str(MEDIA / out))
            print("wrote media/" + out)
        b.close()


if __name__ == "__main__":
    main()
