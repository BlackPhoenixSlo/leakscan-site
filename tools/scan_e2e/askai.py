"""Scenario `askai` (see tools/scan_e2e.py for what it proves)."""
import json
import time
import urllib.request
from urllib.parse import urlsplit

from .common import LOOP, ROOT, bring, cfg, check, new_ctx


def overlap(a, b):
    return a and b and a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"] \
        and a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"]


def chat_log():
    with urllib.request.urlopen(cfg.base + "api/_chat-log") as r:
        return json.loads(r.read())


def askai(browser, vp_name, vp):
    """The Ask-AI popup on the homepage, one viewport. See module docstring."""
    v = f"{vp_name} askai"
    # console errors count when logged from loopback / file: pages; Chrome logs every non-2xx fetch as one, and the
    # stub-429 one is the expected path, not a bug
    ctx, net = new_ctx(browser, vp_name, vp, console_ok=lambda m: not (
        urlsplit(m.location.get("url") or cfg.base).hostname in LOOP or (m.location.get("url") or "").startswith("file:"))
        or ("status of 429" in m.text and "/api/chat" in (m.location.get("url") or "")))
    reqs = []
    page = ctx.new_page()
    page.on("request", lambda q: reqs.append(q.url))

    def shot(name):
        for scheme in ("light", "dark"):
            page.emulate_media(color_scheme=scheme)
            page.wait_for_timeout(150)
            page.screenshot(path=str(cfg.out / f"{vp_name}-askai-{name}-{scheme}.png"))
        page.emulate_media(color_scheme="light")

    L = page.locator(".askai-launcher")
    dlg = page.locator("#askai")
    inp = page.locator("#askai-input")
    is_open = lambda: page.evaluate("document.getElementById('askai').open")
    active_in_dialog = lambda: page.evaluate("document.getElementById('askai').contains(document.activeElement)")
    bot = page.locator(".askai-bot")

    def ask(q):
        inp.fill(q)
        inp.press("Enter")

    def settle():
        page.wait_for_selector(".askai-log[aria-busy=false]", timeout=10000)

    def click_L():   # hidden over the hero (phone), the report card's actions or the phones (any width): scroll to where it shows
        shown = "(() => { const L = document.querySelector('.askai-launcher'), c = L.classList; return !c.contains('in-quiet') && !(c.contains('in-hero') && innerWidth < 720) && getComputedStyle(L).opacity === '1'; })()"
        for sec in (None, "how", "pricing", "faq"):
            if sec:
                bring(page, "#" + sec)
            page.wait_for_timeout(450)   # IntersectionObserver / rAF + the pill's fade settle
            if page.evaluate(shown):
                break
        L.click()

    # 1. launcher: covers no hero text / control at load (phone: hidden until the hero scrolls away)
    page.goto(cfg.base, wait_until="load")
    page.wait_for_selector(".askai-launcher:not([hidden])", state="attached", timeout=5000)
    page.wait_for_timeout(500)
    covered = page.evaluate("""() => { const L = document.querySelector('.askai-launcher');
      if (getComputedStyle(L).visibility === 'hidden') return [];
      const b = L.getBoundingClientRect(), hit = [], w = document.createTreeWalker(document.querySelector('.hero'), NodeFilter.SHOW_TEXT);
      for (let n; (n = w.nextNode());) { if (!n.textContent.trim()) continue; const r = document.createRange(); r.selectNodeContents(n);
        for (const q of r.getClientRects()) if (q.right > b.left && q.left < b.right && q.bottom > b.top && q.top < b.bottom) hit.push(n.textContent.trim()); }
      return hit; }""")
    check(f"{v} launcher covers no hero text at load", covered == [], covered)
    check(f"{v} launcher hidden while hero on screen", not L.is_visible())
    bring(page, "#how")
    if vp_name == "phone":
        page.wait_for_selector(".mobile-cta.show", timeout=3000)
    page.wait_for_timeout(500)
    check(f"{v} launcher visible + labelled", L.is_visible() and L.get_attribute("aria-label") == "Ask AI before you DM me"
          and "Ask AI before you DM me" in L.inner_text(), L.inner_text())
    lb = L.bounding_box()
    if vp_name == "phone":
        mb = page.locator(".mobile-cta").bounding_box()
        check(f"{v} launcher clear of sticky scan bar", not overlap(lb, mb), f"launcher={lb} bar={mb}")
    else:
        cta = page.locator("#scan button[type=submit]").bounding_box()
        check(f"{v} launcher clear of hero CTA", not overlap(lb, cta), f"launcher={lb} cta={cta}")
    check(f"{v} launcher inside viewport bottom-right", lb["x"] + lb["width"] <= vp["width"] and lb["y"] + lb["height"] <= vp["height"]
          and vp["width"] - (lb["x"] + lb["width"]) <= 32 and vp["height"] - (lb["y"] + lb["height"]) <= (100 if vp_name == "phone" else 32), lb)   # phone: above the sticky bar
    shot("1-launcher")
    if vp_name == "phone":
        page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")

    # 2. open / close / focus
    click_L()
    page.wait_for_timeout(300)
    d = page.get_by_role("dialog", name="Ask about Abolita")
    check(f"{v} opens role=dialog named, aria-modal, input focused", is_open() and d.count() == 1 and d.is_visible()
          and dlg.get_attribute("aria-modal") == "true" and page.evaluate("document.activeElement.id") == "askai-input")
    box = dlg.bounding_box()
    if vp_name == "phone":
        check(f"{v} bottom sheet", abs(box["y"] + box["height"] - vp["height"]) < 2 and box["width"] == vp["width"], box)
    else:
        check(f"{v} 380px panel bottom-right", round(box["width"]) == 380 and box["x"] + box["width"] <= vp["width"] - 20, box)
    note = page.locator(".askai-note")
    check(f"{v} disclaimer + 3 contacts", "Answers come from this page. For your case, message Jaka" in note.inner_text()
          and note.locator("a[href='https://t.me/jakabasej']").count() == 1 and note.locator("a[href='https://wa.me/38640703992']").count() == 1
          and note.locator("a[href='mailto:me@jackbase.dev']").count() == 1)
    faq_q = page.eval_on_selector_all("#faq details summary", "els => els.map(e => e.textContent.trim())")
    chips = page.eval_on_selector_all(".askai-chip", "els => els.map(e => e.textContent)")
    check(f"{v} greeting + chips from page FAQ", bot.first.is_visible() and chips[:1] == ["What does it cost?"]
          and len(chips) >= 4 and chips[1:] == faq_q[:len(chips) - 1], chips)
    trapped = True
    for _ in range(14):
        page.keyboard.press("Tab")
        trapped = trapped and active_in_dialog()
    for _ in range(4):
        page.keyboard.press("Shift+Tab")
        trapped = trapped and active_in_dialog()
    check(f"{v} focus trapped in dialog (Tab/Shift+Tab)", trapped)
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    check(f"{v} Esc closes, focus back on launcher", not is_open()
          and page.evaluate("document.activeElement.classList.contains('askai-launcher')"))
    click_L()
    page.locator(".askai-close").click()
    check(f"{v} close button closes, focus back", not is_open()
          and page.evaluate("document.activeElement.classList.contains('askai-launcher')"))
    click_L()
    page.mouse.click(8, 8)
    page.wait_for_timeout(200)
    check(f"{v} backdrop click closes", not is_open())
    faq_link = page.locator("#faq a[data-askai-open]")
    bring(page, "#faq a[data-askai-open]", "center")
    faq_link.click()
    page.wait_for_timeout(200)
    opened = is_open()
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    check(f"{v} FAQ 'Ask the AI' link opens it, focus returns to link", opened and not is_open()
          and page.evaluate("document.activeElement.hasAttribute('data-askai-open')"))
    page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")

    # 3. cached answers: chips + fuzzy typed questions, zero network
    click_L()
    n = len(reqs)
    t0 = time.time()
    page.locator(".askai-chip", has_text="What does it cost?").click()
    page.wait_for_selector("[data-source=cached]", timeout=2000)
    ms = (time.time() - t0) * 1000
    c1 = page.locator("[data-source=cached]").last
    check(f"{v} chip → instant cached answer, 0 requests", len(reqs) == n and "€250" in c1.inner_text() and "€500" in c1.inner_text(),
          f"{ms:.0f} ms, {len(reqs) - n} requests")
    check(f"{v} cached answer: section link + more-detail option",
          c1.locator("a.askai-anchor[href='#pricing']").inner_text() == "Pricing"
          and c1.locator("button", has_text="Ask the AI for more detail").count() == 1)
    shot("2-cached")
    faq_a = page.eval_on_selector("#faq details p", "e => e.textContent.replace(/\\s+/g, ' ').trim()")
    page.locator(".askai-chip", has_text=faq_q[0]).click()
    c2 = page.locator("[data-source=cached]").last
    check(f"{v} FAQ chip answer = page text + FAQ link", " ".join(c2.inner_text().split()).startswith(faq_a)
          and c2.locator("a.askai-anchor[href='#faq']").inner_text() == "FAQ" and len(reqs) == n)
    for q in ("how much does it cost", "how much", "Is it legal?", "can I cancel"):
        k = page.locator("[data-source=cached]").count()
        ask(q)
        page.wait_for_timeout(150)
        check(f"{v} fuzzy '{q}' → cached, 0 requests", page.locator("[data-source=cached]").count() == k + 1 and len(reqs) == n
              and page.locator(".askai-user").last.inner_text() == q)
    check(f"{v} 'how much' → pricing answer", "€250" in page.locator("[data-source=cached]").nth(3).inner_text())
    inp.fill("line one")
    inp.press("Shift+Enter")
    inp.type("line two")
    check(f"{v} Shift+Enter = newline, no send", inp.input_value() == "line one\nline two"
          and page.locator(".askai-user").last.inner_text() == "can I cancel")
    inp.fill("")

    # 4. streamed answers (a scan slug in localStorage, as scan/ leaves it, is sent along; set only now so
    # personalize.js's own fetches for it can't land inside the zero-request windows above)
    page.evaluate("localStorage.setItem('leakscan.last', JSON.stringify({slug: 'demoR3port01', handle: 'demo.creator'}))")
    nlog = len(chat_log())
    q = "Do you work with agencies?"
    ask(q)
    page.wait_for_selector("[data-source=ai]:not(.askai-typing)", timeout=5000)
    first_len = len(page.locator("[data-source=ai]").last.inner_text())
    busy_mid = page.locator(".askai-log").get_attribute("aria-busy") == "true"
    settle()
    ai = page.locator("[data-source=ai]").last
    final = ai.inner_text()
    check(f"{v} other question → streamed answer (grows token by token)", busy_mid and 0 < first_len < len(final)
          and "Short answer" in final, f"{first_len} → {len(final)} chars")
    log = chat_log()
    body = log[-1] if len(log) > nlog else {}
    check(f"{v} chat request: kb, slug, last user msg, ≤8 msgs", body.get("kb") == "landing" and body.get("slug") == "demoR3port01"
          and body.get("messages", [{}])[-1] == {"role": "user", "content": q} and len(body["messages"]) <= 8
          and body["messages"][0]["role"] == "user", {k: (len(v_) if k == "messages" else v_) for k, v_ in body.items()})
    ask("blorp fizzle wug")
    settle()
    log = chat_log()
    check(f"{v} nonsense → not cached, history capped at 8", len(log) == nlog + 2 and len(log[-1]["messages"]) <= 8
          and page.locator("[data-source=ai]").count() == 2, len(log[-1]["messages"]))

    # 5. link rules (on the first streamed answer)
    hrefs = ai.evaluate("b => [...b.querySelectorAll('a')].map(a => [a.getAttribute('href'), a.textContent, a.target, a.rel])")
    check(f"{v} links: #pricing is <a> 'Pricing'", ["#pricing", "Pricing", "", ""] in hrefs, hrefs)
    check(f"{v} links: t.me is <a> target=_blank rel=noopener", ["https://t.me/jakabasej", "Telegram", "_blank", "noopener"] in hrefs, hrefs)
    check(f"{v} links: javascript: is plain text", not any("javascript" in (h[0] or "").lower() for h in hrefs)
          and "Don't click x or" in final, hrefs)
    check(f"{v} links: evil.example is plain text", not any("evil.example" in (h[0] or "") for h in hrefs)
          and "this deal" in final and "https://evil.example/raw" in final, hrefs)
    check(f"{v} links: bare #contact → labelled anchor", ["#contact", "Ran the scan? Send me the report link", "", ""] in hrefs, hrefs)
    check(f"{v} bold + bullets rendered, no on* attrs", ai.locator("strong").count() == 3 and ai.locator("li").count() == 3
          and ai.evaluate("b => [...b.querySelectorAll('*')].every(e => ![...e.attributes].some(a => a.name.startsWith('on')))"))
    shot("3-streamed")
    ai.locator("a[href='#pricing']").click()
    try:   # smooth scroll over ~7000px takes ~1.5 s; settles at the page's scroll-padding-top (header + 12px)
        page.wait_for_function("Math.abs(document.getElementById('pricing').getBoundingClientRect().top"
                               " - parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop)) < 8", timeout=5000)
    except Exception:
        pass
    top = page.evaluate("document.getElementById('pricing').getBoundingClientRect().top")
    check(f"{v} anchor click scrolls to #pricing" + (" (sheet closed)" if vp_name == "phone" else " (panel stays)"),
          0 <= top < 120 and is_open() == (vp_name != "phone"), f"top={top:.0f} open={is_open()}")

    # 6. failure paths
    if not is_open():
        click_L()
    for word, kind, text in (("stub-fail", "failed", "couldn’t answer"), ("stub-429", "rate_limited", "Too many")):
        ask(f"{word} please")
        page.wait_for_selector(f"[data-source=error][data-kind={kind}]", timeout=5000)
        e = page.locator(f"[data-source=error][data-kind={kind}]").last
        hs = e.evaluate("b => [...b.querySelectorAll('a')].map(a => a.href)")
        check(f"{v} {kind} → message + 3 contact links + retry", text in e.inner_text() and len(hs) == 3
              and hs[0].startswith("https://t.me/jakabasej") and hs[1].startswith("https://wa.me/38640703992")
              and hs[2].startswith("mailto:me@jackbase.dev") and e.locator("button", has_text="Try again").count() == 1, hs)
        settle()
    shot("4-fallback")
    k = len(chat_log())
    page.locator("[data-source=error] button", has_text="Try again").last.click()
    page.wait_for_selector("[data-source=error][data-kind=rate_limited]", timeout=5000)
    settle()
    check(f"{v} retry resends", len(chat_log()) == k + 1 and chat_log()[-1]["messages"][-1]["content"] == "stub-429 please")
    k = page.locator("[data-source=cached]").count()
    page.locator("[data-source=cached] button", has_text="Ask the AI for more detail").first.click()
    settle()
    check(f"{v} 'more detail' → AI request", chat_log()[-1]["messages"][-1]["content"] == "Can you give me more detail on that?")

    # 7. storage: sessionStorage restore, nothing in localStorage/cookies
    page.reload(wait_until="load")
    click_L()
    users = page.eval_on_selector_all(".askai-user", "els => els.map(e => e.textContent)")
    check(f"{v} reload restores chat from sessionStorage", q in users and "how much" in users, len(users))
    check(f"{v} no localStorage writes, no cookies", page.evaluate("Object.keys(localStorage)") == ["leakscan.last"]
          and ctx.cookies() == [], page.evaluate("Object.keys(localStorage)"))
    page.keyboard.press("Escape")

    # 8. no API origin: page opened from disk (no data-api, not http) → nothing to call
    k, kl, ne, nc = len(reqs), len(chat_log()), len(net["errors"]), len(net["console"])
    page.goto((ROOT / "site" / "index.html").as_uri(), wait_until="load")
    click_L()
    page.locator(".askai-chip", has_text="What does it cost?").click()
    ask("Do you work with agencies?")
    page.wait_for_selector("[data-source=error][data-kind=no_api]", timeout=3000)
    e = page.locator("[data-source=error][data-kind=no_api]")
    check(f"{v} no API origin → cached still works, fallback + contacts, no request", len(chat_log()) == kl
          and e.locator("a").count() == 3 and not any("/api/chat" in u for u in reqs[k:]),
          {"chat_posts": len(chat_log()) - kl, "links": e.locator("a").count(), "api": [u for u in reqs[k:] if "/api/" in u]})
    page.keyboard.press("Escape")
    # From disk the showcase iframe opens Chrome's directory listing, whose own scripts throw; keep only chat.js errors.
    net["errors"][ne:] = [x for x in net["errors"][ne:] if "chat.js" in x]
    net["console"][nc:] = [x for x in net["console"][nc:] if "chat.js" in x]

    # 9. reduced motion
    anim = lambda: page.eval_on_selector(".askai-panel", "e => getComputedStyle(e).animationName")
    page.goto(cfg.base, wait_until="load")
    click_L()
    a1 = anim()
    page.keyboard.press("Escape")
    page.emulate_media(reduced_motion="reduce")
    click_L()
    a2 = anim()
    page.keyboard.press("Escape")
    page.emulate_media(reduced_motion="no-preference")
    check(f"{v} reduced motion: no open animation", a1 == "askai-in" and a2 == "none", f"{a1} / {a2}")

    check(f"{v} no request left loopback (popup / main frame / the demo iframe: no Google Fonts)", not net["outside"], net["outside"])
    check(f"{v} no console / JS errors", not net["errors"] + net["console"], net["errors"] + net["console"])
    ctx.close()

    # 10. JS off: no launcher, no dialog
    ctx, _ = new_ctx(browser, vp_name, vp, java_script_enabled=False)
    page = ctx.new_page()
    page.goto(cfg.base, wait_until="load")
    check(f"{v} JS off: launcher + dialog hidden", not page.locator(".askai-launcher").is_visible()
          and not page.locator("#askai").is_visible())
    ctx.close()
