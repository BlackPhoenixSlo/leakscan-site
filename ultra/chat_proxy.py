"""
DeepSeek chat proxy for the public app's on-site assistant.

Server-side ONLY: the API key lives in the Authorization header and NEVER
reaches the browser or the model's message context. We stream tokens back to the
client as SSE. The assistant does three jobs: (1) answer about the visitor's own
scan, (2) general leak/DMCA/takedown Q&A grounded in kb.json, (3) steer toward
the DM CTA. Stdlib only (urllib) — no SDK.
"""

import json
import os
import urllib.error
import urllib.request

import web_common as wc

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MAX_TURNS = 8            # keep only the last N user/assistant turns
MAX_MSG_CHARS = 4000     # per-message cap
MAX_TOTAL_CHARS = 16000  # hard ceiling on assembled conversation text

SYSTEM_PROMPT = """You are the assistant for a free leak-scanning service that helps content creators \
find where their own material has been leaked and get it removed. You have three jobs:

1. ANSWER ABOUT THE VISITOR'S OWN SCAN. When scan results are provided in the context, explain what \
was found in plain language: which sites, how many matches, and what it means. Be calm and reassuring, \
not alarming.

2. GENERAL LEAK / DMCA / TAKEDOWN Q&A + HOW-TO-DO-IT-YOURSELF. Using the KNOWLEDGE BASE in context \
(removal facts, DIY takedown steps, a DMCA notice template, Google-removal steps, and an FAQ), answer \
copyright/DMCA questions AND, when someone asks how to remove it, show them how to do it themselves: how \
to find the host (site's DMCA/abuse page, whois, Cloudflare's abuse form), what to put in a DMCA email, \
how to fill a site's report form, and how to delist the URLs from Google. Give the real specifics from \
the KB. If they ask for the wording, hand them the DMCA template in plain text. If you are unsure, say so.

3. GUIDE TOWARD HELP. When the visitor wants leaks removed or seems overwhelmed, warmly suggest they \
reach out via the DM buttons on this page (Instagram, WhatsApp, or Telegram) to get personal help. Do \
not be pushy; suggest it naturally when it fits.

HOW OUR SCANS WORK (use for accurate answers — every tier hunts for leaked URLs, not just domains):
- Quick scan: a fast search across known leak sites for the handle's leaked URLs.
- Deep scan: runs in SEVERAL STAGES, one after another. 1) Site check — every known leak site is \
tested against the handle and all its name variations; this is the "N/M checks" counter and the FOUND \
lines. 2) Deep crawl — every site that hit is then crawled page by page to collect each individual \
leaked page and media file; this is the LONGEST stage, it takes several minutes and the counter does \
NOT move while it runs. 3) Cleaning and verification of every collected URL. 4) Confirmed-leaks \
export — this produces the final counts, the per-site link lists, and the removal quote. 5) Google \
index sweep — finds where the leaks also show up in Google results. 6) Preview gallery build. \
Only after ALL stages does the full report replace the progress screen.
- CRITICAL — while the LIVE STATUS in context says the scan is running, the scan is NOT finished, \
even if the site-check counter shows all checks done (e.g. 375/375): that only ends stage 1, and the \
crawl/verify/export/Google stages are still working. NEVER tell the visitor the scan is finished, \
complete, or done while it is running. Tell them which stage it is in (the LIVE STATUS says), that the \
deep crawl typically multiplies what the site check found, and that the full shareable report appears \
on this page by itself when everything is done.
- Mid-scan numbers are PARTIAL, so-far numbers. When you mention how many sites were found, use the \
TOTAL count given in the context — the site list you see may be only a sample of the first few \
("and X more"), so never present the listed names as the complete set.
- Deepest report: a manual, human-run investigation by our team (deep Google search + direct site \
crawling in a private browser). It is NOT automated on this page — it is offered personally via the DM buttons. \
When someone wants the most exhaustive search, steer them to DM us for a deepest report.

WHEN SOMEONE ASKS FOR AN EXAMPLE ("show me an example", "give me a leak example", "what does a report look \
like", "can I see one now"):
- The scan on this page is THEIR OWN, so give a CONCRETE example straight from their live results: name a \
couple of the sites found and, when the context gives match counts, use them — e.g. "for example, \
leakgallery.com is already showing dozens of copies of your content." That is their own data; showing it to \
them is fine and is usually what they actually want.
- Then paint what the FINISHED report will contain, using this as an ILLUSTRATIVE sample (a realistic \
shape, NOT a real person): a typical report lists every confirmed leak URL grouped by site (often 200+ \
links across 30+ sites), a blurred preview gallery of the photos found, an "also all over Google" \
breakdown, and a single takedown quote — with Copy-all and Download buttons for the whole link list.
- If the context includes "example found URLs" (present even mid-scan, once the crawl starts landing \
links), you MAY paste ONE OR TWO of them verbatim when the visitor asks to see a leak / an example link \
— these are their OWN found pages and the same links the on-page report lists. Never paste the whole \
list (the report's Copy-all / Download is for that), and never fabricate a URL that is not in the context.
- Each example URL is TAGGED by kind: [page] = the webpage that hosts the leak, [image]/[video] = a \
direct media file. When they ask for the PAGE (not the image file), hand them a [page] URL; when they \
ask for the image, hand them an [image]/[video] one. If only media URLs have been found for that site so \
far and no [page] is in the context yet, say the hosting page is still being collected by the deep crawl \
and will be in the report — do not pass off a media file as the page.
- If there are NO example URLs yet (the crawl hasn't landed any links for this site yet), the individual \
leak links are still being collected by the deep crawl — tell them the exact links land in the report on \
this page as the crawl runs, and meanwhile cite the site names + counts from the context.
- Hard limit that always holds: NEVER help anyone find, open, download, or access someone ELSE'S content, \
and never paste long lists of raw URLs.
- "What happens after the scan?" → the full report appears here automatically; they can share it or \
download the links; and to actually get the leaks taken down they message us via the Instagram / Telegram \
/ WhatsApp buttons and our team files the DMCA takedowns and Google delisting.

SAFETY RULES (never break):
- Only ever help a person with THEIR OWN content and its removal.
- REFUSE to help anyone find, scrape, download, or access other people's leaked content, or bypass \
paywalls. If asked, decline briefly and redirect to removal help.
- Never invent scan results, URLs, or legal guarantees. Say you are not a lawyer.
- Keep answers short, warm, and practical. No medical, legal, or financial promises.

You may reference the sites in the scan context and the facts in the knowledge base, but do not output \
long lists of raw leak URLs. Summarize instead.

FORMAT (critical — the chat renders RAW TEXT, not markdown):
- Reply in PLAIN TEXT only. NEVER use markdown: no **bold**, no ## headings, no bullet or numbered \
lists, no tables. Markdown shows up as ugly literal asterisks and looks broken.
- Keep it to 2-4 short sentences, like texting. Answer the actual question; don't dump every number \
unless they ask for it. For a "how do I remove it myself" question, give the key steps as a short \
plain-text list ("1) ... 2) ... 3) ..." on separate lines) — still no markdown symbols, and only the \
steps that matter.
- Suggest the Instagram/Telegram DM naturally, only when the person seems ready to act — not in every \
reply."""


EXAMPLE_URL_CAP = 5   # how many of the visitor's own found URLs to expose for "show me one"


def scan_summary(scan):
    """Compact, safe summary of a stored scan (dict from db.get_scan): at most 12
    domains, plus up to EXAMPLE_URL_CAP of the visitor's OWN found URLs (one per site)
    so the assistant can paste a concrete example when asked. Returns '' when there's
    no scan context."""
    if not scan:
        return ""
    hits = scan.get("hits") or []
    best = {}
    for h in hits:
        d = h.get("domain")
        if not d:
            continue
        best[d] = max(best.get(d, 0), h.get("occurrences", 0))
    top = sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:12]
    # A few example found URLs (highest-occurrence site first, one per domain). These are
    # the SAME links the on-page report already lists — surfaced so the assistant can show
    # one or two when the owner asks to see a leak, without pasting the whole list.
    ex_urls, seen_d = [], set()
    for h in sorted(hits, key=lambda x: x.get("occurrences", 0), reverse=True):
        u, d = h.get("url"), h.get("domain")
        if u and d and d not in seen_d:
            seen_d.add(d)
            ex_urls.append(u)
        if len(ex_urls) >= EXAMPLE_URL_CAP:
            break
    lines = [
        "SCAN CONTEXT:",
        f"handle: {scan.get('handle', '')} (platform: {scan.get('platform', '')})",
        f"total matches: {scan.get('hit_count', 0)} across {scan.get('domain_count', 0)} sites",
    ]
    if top:
        lines.append("top sites: " + ", ".join(f"{d} ({c} matches)" for d, c in top))
        extra = scan.get("domain_count", 0) - len(top)
        if extra > 0:
            lines.append(f"...and {extra} more sites")
        lines.append("status: all matches were confirmed live at scan time")
        if ex_urls:
            lines.append("example found URLs (their OWN content — you MAY paste one or two of these "
                         "verbatim when they ask to see a leak; NEVER paste the whole list — the "
                         "report's Copy-all / Download buttons are for that): " + " | ".join(ex_urls))
    else:
        lines.append("no public leaks were found in this scan")
    return "\n".join(lines)


def load_kb(kb_path):
    """Read kb.json as text; '' if missing (graceful degradation)."""
    try:
        return open(kb_path, encoding="utf-8").read().strip()
    except Exception:
        return ""


def _clean_turns(messages):
    out = []
    for m in messages or []:
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        content = content.strip()
        if content:
            out.append({"role": role, "content": content[:MAX_MSG_CHARS]})
    out = out[-MAX_TURNS:]
    total = sum(len(m["content"]) for m in out)
    while total > MAX_TOTAL_CHARS and len(out) > 1:
        total -= len(out.pop(0)["content"])
    return out


def build_messages(kb_text, scan_ctx, user_messages):
    """Assemble the DeepSeek `messages` array. kb_text and scan_ctx may be ''
    (graceful degradation when there is no KB / no scan)."""
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    ctx = []
    if scan_ctx:
        ctx.append(scan_ctx)
    if kb_text:
        ctx.append("KNOWLEDGE BASE (reference facts and observed leak-site coverage):\n" + kb_text)
    if ctx:
        msgs.append({"role": "system", "content": "\n\n".join(ctx)})
    msgs.extend(_clean_turns(user_messages))
    return msgs


def _delta_from_line(line):
    """Parse one SSE line from DeepSeek.
      ("done", None)  -> the [DONE] sentinel
      ("token", str)  -> a content delta (may be '')
      (None, None)    -> keepalive / role-only / blank / unparseable
    """
    line = line.strip()
    if not line.startswith("data:"):
        return (None, None)
    payload = line[len("data:"):].strip()
    if payload == "[DONE]":
        return ("done", None)
    try:
        obj = json.loads(payload)
        delta = obj["choices"][0].get("delta", {})
        return ("token", delta.get("content") or "")
    except Exception:
        return (None, None)


def stream_chat(handler, messages, api_key=None, model=None, timeout=60):
    """POST to DeepSeek with stream:true and relay content deltas to the browser
    as SSE 'token' events (JSON-encoded so newlines survive). Never leaks the API
    key or upstream error bodies."""
    key = (api_key if api_key is not None else os.environ.get("DEEPSEEK_API_KEY", "")).strip()
    if not key:
        return wc.sse_fail(handler, "The assistant isn't configured yet — please DM us instead.")
    mdl = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    body = {
        "model": mdl,
        "stream": True,
        "temperature": 0.5,
        "max_tokens": int(os.environ.get("CHAT_MAX_TOKENS", "700")),
        "messages": messages,
    }
    if mdl.startswith("deepseek-v4"):
        body["thinking"] = {"type": "disabled"}
    req = urllib.request.Request(
        DEEPSEEK_URL,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "Accept": "text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                kind, text = _delta_from_line(raw.decode("utf-8", "replace"))
                if kind == "done":
                    break
                if kind == "token" and text:
                    if not wc.sse(handler, "token", json.dumps(text)):
                        return  # client disconnected
        wc.sse(handler, "done", "end")
    except urllib.error.HTTPError as e:
        try:
            e.read()  # drain, but never surface the upstream body
        except Exception:
            pass
        wc.sse_fail(handler, "The assistant is unavailable right now. Please try again, or DM us.")
    except Exception:
        wc.sse_fail(handler, "The assistant is unavailable right now. Please try again, or DM us.")
