"""Render the README images headless with Playwright, from the live Retell test in examples/live-run/.

    python scripts/render_media.py   (needs: pip install playwright && playwright install chromium)
"""
import html
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "examples" / "live-run"
MEDIA = ROOT / "media"
FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "'SF Mono', Menlo, Consolas, monospace"
STYLE = f"""<style>
 body{{margin:0;background:#0f1115;font-family:{FONT};color:#e8e8e8}}
 .wrap{{display:inline-block;width:1000px;padding:26px 30px}}
 h1{{font-size:22px;margin:0 0 4px}} .sub{{color:#9aa3ad;font-size:14px;margin-bottom:6px;line-height:1.4}}
 .stats{{color:#c9d1d9;font-size:13px;margin:8px 0 14px}} .stats b{{color:#3ecf8e}}
 .row{{margin:7px 0;padding:9px 14px;border-radius:10px;line-height:1.4;font-size:15px}}
 .agent{{background:#1d2a22;border-left:4px solid #3ecf8e}} .user{{background:#1f2433;border-left:4px solid #6c8cff}}
 .fn{{background:#2a2418;border-left:4px solid #e0a43a;font-family:{MONO};font-size:12.5px}}
 .who{{font-size:11.5px;color:#9aa3ad;margin-bottom:2px;letter-spacing:.03em}}
 .call{{margin-top:22px}} h2{{font-size:17px;margin:0 0 2px}}
</style>"""


def short(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " ..."


def conversation(call: dict) -> str:
    rows = []
    for t in call["conversation"]:
        if t["role"] in ("agent", "user"):
            who = "RECEPTIONIST (Claude on Retell)" if t["role"] == "agent" else "CALLER (synthetic voice)"
            rows.append(f"<div class='row {t['role']}'><div class='who'>{who}</div>{html.escape(t['text'].strip())}</div>")
        elif t["role"] == "function_call":
            if t["name"] == "end_call":
                rows.append("<div class='row fn'><div class='who'>RETELL</div>end_call</div>")
                continue
            args = ", ".join(f"{k}={json.dumps(v)}" for k, v in t["arguments"].items())
            rows.append(f"<div class='row fn'><div class='who'>RETELL CALLS THIS SERVER (signed)</div>"
                        f"{html.escape(t['name'])}({html.escape(short(args, 150))})</div>")
        elif t["role"] == "function_result" and t.get("result"):
            try:
                text = json.loads(t["result"]).get("result", t["result"])
            except (ValueError, AttributeError):
                text = t["result"]
            rows.append(f"<div class='row fn'><div class='who'>SERVER ANSWERS</div>{html.escape(short(text, 170))}</div>")
    lat = call["latency_ms_p50"]
    stats = (f"<div class='stats'>{call['duration_seconds']:.0f} seconds &middot; ended: {call['disconnection_reason']} "
             f"&middot; cost ${call['cost_usd']:.2f} &middot; median reply time <b>{lat['e2e'] / 1000:.1f}s</b> "
             f"(Claude {lat['llm'] / 1000:.1f}s)</div>")
    return stats + "".join(rows)


def booking(calls) -> str:
    c = calls[0]
    return f"""<html><head>{STYLE}</head><body><div class="wrap" id="wrap">
<h1>{html.escape(c['scenario'])}</h1>
<div class="sub">A real Retell web call, 5 November 2026. Claude Sonnet 5.5 on Retell's voice pipeline; the functions ran on
this FastAPI server behind a tunnel. The caller was a scripted synthetic voice. From Retell's own call record.</div>
{conversation(c)}</div></body></html>"""


def others(calls) -> str:
    parts = "".join(f"<div class='call'><h2>{html.escape(c['scenario'])}</h2>{conversation(c)}</div>" for c in calls[1:])
    return f"""<html><head>{STYLE}</head><body><div class="wrap" id="wrap">
<h1>Two more live calls</h1>
<div class="sub">Same live test. In call 3 the caller hung up before the receptionist could send its summary, so the server emailed Retell's own
post-call summary instead (see the next image).</div>{parts}</div></body></html>"""


def record(calls) -> str:
    log = json.loads((RUN / "2-call-log.json").read_text())
    emails = json.loads((RUN / "3-team-emails.json").read_text())
    order = [c["call_id"] for c in calls]
    log.sort(key=lambda r: order.index(r["call_id"]) if r["call_id"] in order else 99)
    rows = "".join(
        f"<tr><td>{n}</td><td>{html.escape(r['ended_reason'] or '')}</td><td>{r['duration_seconds'] or 0:.0f}s</td>"
        f"<td>{'$%.2f' % r['cost'] if r['cost'] is not None else ''}</td><td>{html.escape(r['sentiment'] or '')}</td>"
        f"<td>{html.escape(short(r['outcome'] or '(none)', 80))}</td><td>{'yes' if r['summary_emailed'] else 'no'}</td></tr>"
        for n, r in zip(["Call 1", "Call 2", "Call 3", "Never joined"], log))
    mails = "".join(f"<div class='mail'><div style='font-weight:700'>{html.escape(m['subject'])}</div>"
                    f"<pre>{html.escape(m['body'].split(chr(10) + chr(10), 1)[1].strip())}</pre></div>" for m in emails)
    return f"""<html><head><style>
 body{{margin:0;background:#f6f8fa;font-family:{FONT};color:#1f2328}}
 .wrap{{display:inline-block;width:1040px;padding:24px 30px;font-size:14px}}
 table{{border-collapse:collapse;width:100%;background:#fff;border:1px solid #d0d7de;border-radius:8px}}
 th,td{{text-align:left;padding:6px 10px;border-bottom:1px solid #eaeef2;vertical-align:top}} th{{background:#f0f3f6}}
 .mail{{border:1px solid #d0d7de;border-radius:8px;padding:10px 14px;margin-top:10px;background:#fff}}
 pre{{font-family:{MONO};font-size:12px;white-space:pre-wrap;margin:6px 0 0}}
</style></head><body><div class="wrap" id="wrap">
<div style="font-size:21px;font-weight:700">What the server recorded from the live calls</div>
<div style="color:#555;margin:4px 0 14px">The call log (GET /calls, filled from Retell's signed webhooks) and every email
the server sent. All emails went to one test address and were marked as tests.</div>
<table><tr><th></th><th>Ended</th><th>Length</th><th>Cost</th><th>Sentiment</th><th>Outcome</th><th>Summary emailed</th></tr>
{rows}</table>{mails}</div></body></html>"""


def main():
    MEDIA.mkdir(exist_ok=True)
    calls = json.loads((RUN / "1-live-calls.json").read_text())
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page(viewport={"width": 1500, "height": 900}, device_scale_factor=2)
        for doc, out in [(booking(calls), "live-call-booking.png"), (others(calls), "live-calls-handover-hangup.png"),
                         (record(calls), "live-call-record-and-emails.png")]:
            page.set_content(doc)
            page.locator("#wrap").screenshot(path=str(MEDIA / out))
            print("wrote media/" + out)
        b.close()


if __name__ == "__main__":
    main()
