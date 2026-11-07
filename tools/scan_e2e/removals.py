"""Scenario `removals` (see tools/scan_e2e.py for what it proves)."""
import re
from urllib.parse import urlsplit

from .common import COUNTS, FX, PIP_AWAY, bring, cfg, check, new_ctx, served, settled_count
from .scan import open_all_sites

# [ms, score, hadRecentInput, a shifted node inside #removals] (the Ask AI launcher slides up with the sticky bar elsewhere)
LAYOUT_SHIFTS = "window.__ls = []; try { new PerformanceObserver(l => l.getEntries().forEach(e => window.__ls.push([e.startTime, e.value, e.hadRecentInput, (e.sources || []).some(x => x.node && x.node.closest && !!x.node.closest('#removals'))]))).observe({type: 'layout-shift', buffered: true}); } catch (e) {}"


# ---------- removals (js/removals.js, css/removals.css: the #removals "Where I remove from" panels) ----------
RM_PANELS = ("mega", "x", "reddit", "site")
RM_STATE = """() => { const y0 = scrollY, out = [...document.querySelectorAll('#removals .rm-card')].map(c => {
  const s = c.querySelector('.rm-stage'), b = c.querySelector('.rm-btn');
  s.scrollIntoView({block: 'center', behavior: 'instant'});
  const r = s.getBoundingClientRect(), top = document.elementFromPoint(r.left + r.width * .75, r.top + r.height / 2), cb = c.getBoundingClientRect();
  const hr = c.querySelector('.rm-handle').getBoundingClientRect(), cm = /inset\\(0px 0px 0px ([\\d.]+)%\\)/.exec(getComputedStyle(c.querySelector('.rm-gone')).clipPath);
  return {k: c.dataset.rm, p: c.querySelector('.rm-handle').getAttribute('aria-valuenow'), pressed: b.getAttribute('aria-pressed'),
    mid: +(hr.left - r.left - r.width / 2).toFixed(1), hp: +((hr.left - r.left) / r.width * 100).toFixed(2), cp: cm ? +cm[1] : null,
    label: b.textContent, clip: getComputedStyle(c.querySelector('.rm-gone')).clipPath,
    shown: top && top.closest('.rm-gone') ? 'gone' : top && top.closest('.rm-live') ? 'live' : String(top && top.className),
    box: [r.x, r.y + scrollY, r.width, r.height].map(Math.round), card: [cb.x, cb.y + scrollY, cb.width, cb.height].map(Math.round)}; });
  scrollTo({top: y0, behavior: 'instant'}); return out; }"""
RM_TEXT = """() => Object.fromEntries([...document.querySelectorAll('#removals .rm-live [data-rm-k]')].filter(e => !e.closest('[hidden]')).map(e => [e.dataset.rmK, e.textContent]))"""
# per panel, what its live layer shows: {key: text} of the visible keyed slots + the srcs of the visible photos
RM_PANEL = """() => [...document.querySelectorAll('#removals .rm-card')].map(c => ({k: c.dataset.rm,
  t: Object.fromEntries([...c.querySelectorAll('.rm-live [data-rm-k]')].filter(e => !e.closest('[hidden]')).map(e => [e.dataset.rmK, e.textContent])),
  img: [...c.querySelectorAll('.rm-live .rm-img')].filter(i => !i.closest('[hidden]')).map(i => i.getAttribute('src'))}))"""
# idle (all live): the knob's box vs every visible text / photo box of the live layer, and the edge line's opacity. The
# leak-site panel's photo grid is not counted: a full-bleed wall of blurred tiles cropped by the stage like a screenshot
# (#75's fapello page), so the parked knob sits on a tile corner at every width (text and every other photo still are)
RM_IDLE = """() => [...document.querySelectorAll('#removals .rm-card')].map(c => {
  const k = c.querySelector('.rm-knob').getBoundingClientRect(), hit = [];
  for (const e of c.querySelectorAll('.rm-live *')) {
    if (e.closest('[hidden]') || !(e.matches('.rm-th, .agg-th, .rd-media') || [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()))) continue;
    const r = e.getBoundingClientRect();
    if (e.matches('.fp-grid .rm-th')) continue;
    if (r.width && r.right > k.left && r.left < k.right && r.bottom > k.top && r.top < k.bottom) hit.push(e.className || e.tagName);
  }
  return [c.dataset.rm, hit, getComputedStyle(c.querySelector('.rm-handle'), '::before').opacity]; })"""
# the whole DOM, every same-origin frame included (walked in the page: a lazy iframe that never loaded can't stall it)
DOM_ALL = """() => { const out = [], walk = d => { if (!d || !d.documentElement) return; out.push(d.documentElement.outerHTML);
  for (const f of d.querySelectorAll('iframe')) { try { walk(f.contentDocument); } catch (e) { out.push('<cross-origin frame>'); } } };
  walk(document); return out.join(' '); }"""
NEUTRAL_RE = re.compile(r"\b(onlyfans|leaked|leaks)\b", re.I)   # L11: Ads policy, the mock panels' own copy
UNSAFE_RE = re.compile(r"onlyfan|fansly|leak|nud[ei]|naked|porn|xxx|sex|fap", re.I)   # words no panel may show (a sample, not removals.js's list)


def brand(d):   # js/removals.js brand(): the leak-site wordmark = host without its TLD
    p = d.split(".")[:-1]
    if len(p) > 1 and p[-1] in ("co", "com", "net", "org"):
        p.pop()
    return p[-1]


# every aria-valuenow change of the 4 handles from here on: [ms, card index, value]
SW_REC = """() => { window.__sw = []; document.querySelectorAll('#removals .rm-handle').forEach((h, i) => new MutationObserver(() =>
  window.__sw.push([Math.round(performance.now()), i, +h.getAttribute('aria-valuenow')])).observe(h, {attributes: true, attributeFilter: ['aria-valuenow']})); }"""
# per panel whose removed layer clones the live chrome: [selector, live rect, removed rect] of each shared row (top, left,
# width, height in px): the two layers must keep one geometry, so nothing of the removed post sits beside a different
# row of the live one at the edge
RM_ALIGN = """() => [...document.querySelectorAll('#removals .rm-card')].flatMap(c => ['.xp-head', '.xp-text', '.xp-media', '.xp-acts', '.rd-head', '.rd-title', '.rd-media', '.rd-acts', '.fp-bar', '.fp-search']
  .filter(q => c.querySelector('.rm-live ' + q) && c.querySelector('.rm-gone ' + q) && !c.querySelector('.rm-live ' + q).closest('[hidden]'))
  .map(q => [c.dataset.rm + ' ' + q, ...['.rm-live ', '.rm-gone '].map(l => { const r = c.querySelector(l + q).getBoundingClientRect(); return [r.top, r.left, r.width, r.height].map(Math.round); })]))"""
# one card mid-drag: the edge vs the finger, the clip vs the edge, what shows 12 px either side of the edge
RM_MID = """k => { const c = document.querySelector(`#removals .rm-card[data-rm="${k}"]`), st = c.querySelector('.rm-stage'), r = st.getBoundingClientRect(),
  hr = c.querySelector('.rm-handle').getBoundingClientRect(), cm = /inset\\(0px 0px 0px ([\\d.]+)%\\)/.exec(getComputedStyle(c.querySelector('.rm-gone')).clipPath),
  y = r.top + r.height * .3, at = x => { const e = document.elementFromPoint(x, y); return e && e.closest('.rm-gone') ? 'gone' : e && e.closest('.rm-live') ? 'live' : String(e && e.className); };
  return {edge: hr.left, hp: (hr.left - r.left) / r.width * 100, cp: cm ? +cm[1] : null, left: at(hr.left - 12), right: at(hr.left + 12), p: c.querySelector('.rm-handle').getAttribute('aria-valuenow')}; }"""
SW_SEEN = """() => [...document.querySelectorAll('#removals .rm-card')].map(c => { const r = c.querySelector('.rm-stage').getBoundingClientRect();
  return r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth; })"""
FP_STATE = """() => { const c = document.querySelector('#removals .rm-card[data-rm="site"]'), q = s => c.querySelector(s), cs = e => getComputedStyle(e);
  const live = q('.rm-live'), st = q('.rm-stage').getBoundingClientRect();
  return {ring: cs(q('.fp-ring')).backgroundImage, av: [cs(q('.fp-av')).borderTopWidth, cs(q('.fp-av')).borderTopColor, cs(q('.fp-av')).borderTopLeftRadius],
    name: q('.rm-live .fp-name').textContent, aka: q('.fp-aka').textContent, hosts: [...c.querySelectorAll('.fp-logo')].map(e => e.textContent),
    tags: [...c.querySelectorAll('.fp-tags span')].map(e => [e.textContent, cs(e).backgroundColor, cs(e).color]),
    acts: [...c.querySelectorAll('.fp-acts span')].map(e => [e.textContent, cs(e).backgroundColor]),
    count: [...c.querySelectorAll('.fp-count span')].map(e => [e.textContent.replace(/\\s+/g, ' ').trim(), cs(e.querySelector('b')).fontWeight]),
    search: [q('.fp-search').textContent.trim(), cs(q('.fp-search')).backgroundColor], bars: c.querySelectorAll('.fp-bar').length,
    bar: cs(q('.fp-bar')).backgroundColor, bg: cs(live).backgroundColor, font: cs(live).fontFamily,
    tiles: [...c.querySelectorAll('.fp-grid .rm-img')].map(i => [i.complete && i.naturalWidth > 0, Math.round(i.parentElement.getBoundingClientRect().height)]),
    cols: cs(q('.fp-grid')).gridTemplateColumns.split(' ').length, next: q('.rm-live .fp-next').textContent, gone: [q('.fp-404').textContent, q('.fp-gh').textContent],
    goneShell: !!q('.rm-gone .fp-bar') && !!q('.rm-gone .fp-search'), crop: [live.scrollHeight > live.clientHeight, cs(live).overflowY, Math.round(st.height)],
    logo: [q('.fp-logo').scrollWidth, q('.fp-logo').clientWidth],
    row1: (() => { const ts = [...c.querySelectorAll('.fp-grid .rm-th')], y = Math.round(ts[0].getBoundingClientRect().top);
      return ts.filter(t => Math.round(t.getBoundingClientRect().top) === y).map(t => { const r = t.getBoundingClientRect(); return [Math.round(r.top - st.top), Math.round(st.bottom - r.bottom)]; }); })(),
    sexual: /live sex|undress|brazzers|porn/i.test(c.textContent)}; }"""


def fp_row(tag, w, fp):
    check(f"{tag} fp: first tile row fully inside the stage at edge 100 ({w} px)", len(fp["row1"]) >= 2 and all(t >= 0 and b >= 0 for t, b in fp["row1"]), fp["row1"])


def fp_checks(tag, vp_name, fp, name, aka, w):
    """The "Leak sites" panel drawn after fapello.com's profile page (structure + palette, default texts)."""
    check(f"{tag} fp: leak-site live layer = light fapello-style page (#f0f2f5, white bar + search, system sans), same shell on the removed layer",
          fp["bg"] == "rgb(240, 242, 245)" and fp["bar"] == "rgb(255, 255, 255)" and fp["search"] == ["Search", "rgb(255, 255, 255)"] and fp["bars"] == 2
          and fp["goneShell"] and "Inter" not in fp["font"] and "system-ui" in fp["font"] and not fp["sexual"], fp)
    check(f"{tag} fp: avatar = yellow-600 → pink-600 gradient ring + 4px white border, round",
          "linear-gradient" in fp["ring"] and "rgb(202, 138, 4)" in fp["ring"] and "rgb(219, 39, 119)" in fp["ring"]
          and fp["av"][0] == "4px" and fp["av"][1] == "rgb(255, 255, 255)" and fp["av"][2] == "50%", [fp["ring"], fp["av"]])
    check(f"{tag} fp: name + aka, OnlyFans / Patreon / Instagram pills (blue / pink / purple-300), Follow (pink-500) + Discuss (7) (blue-500) + heart",
          fp["name"] == name and fp["aka"] == aka and fp["tags"] == [["OnlyFans", "rgb(147, 197, 253)", "rgb(255, 255, 255)"],
          ["Patreon", "rgb(249, 168, 212)", "rgb(255, 255, 255)"], ["Instagram", "rgb(216, 180, 254)", "rgb(255, 255, 255)"]]
          and [a[0] for a in fp["acts"]] == ["Follow", "Discuss (7)", "\u2665"] and fp["acts"][0][1] == "rgb(236, 72, 153)" and fp["acts"][1][1] == "rgb(59, 130, 246)",
          [fp["name"], fp["aka"], fp["tags"], fp["acts"]])
    check(f"{tag} fp: counters '74 Media' / '137 Likes' (bold labels)", fp["count"] == [["74 Media", "700"], ["137 Likes", "700"]], fp["count"])
    th = 112 if vp_name == "phone" else 160
    check(f"{tag} fp: grid of {len(fp['tiles'])} photo tiles (>= 6, all loaded, {th} px tall, {2 if vp_name == 'phone' else 4} columns), 'Next Page', cropped by the stage (no inner scroll)",
          len(fp["tiles"]) >= 6 and all(t == [True, th] for t in fp["tiles"]) and fp["cols"] == (2 if vp_name == "phone" else 4)
          and fp["next"] == "Next Page" and fp["crop"] == [True, "hidden", 372], [fp["tiles"], fp["cols"], fp["next"], fp["crop"]])
    if vp_name == "phone":   # the ask is phones (desktop: 160 px tiles, its approved look)
        fp_row(tag, w, fp)
    check(f"{tag} fp: wordmark = the host without its TLD, never cut", name != "Orla Brennick" or (fp["hosts"] == ["leak-mirror"] * 2 and fp["logo"][0] <= fp["logo"][1]), [fp["hosts"], fp["logo"]])
    check(f"{tag} fp: removed layer = '404' + 'This model has been removed due to a DMCA complaint.'",
          fp["gone"] == ["404", "This model has been removed due to a DMCA complaint."], fp["gone"])


def sweep_flow(ctx_, vp_name, tag):
    """The ambient sweep, never touched first: glides on screen, per card, stops for good on that card's first input."""
    ctx = ctx_()
    page = ctx.new_page()
    page.goto(cfg.base, wait_until="load")
    page.evaluate(SW_REC)
    page.wait_for_timeout(2500)
    off = page.evaluate("window.__sw")
    check(f"{tag} sweep: off screen nothing moves (2.5 s at the page top)", not off, off)
    cards = page.locator("#removals .rm-card").all()
    hds = page.locator("#removals .rm-handle").all()
    val = lambda i: int(hds[i].get_attribute("aria-valuenow"))
    since = lambda t0: [e for e in page.evaluate("window.__sw") if e[0] >= t0]
    tnow = lambda: page.evaluate("Math.round(performance.now())")
    page.evaluate("() => document.querySelector('#removals .rm-card').scrollIntoView({block: 'start', behavior: 'instant'})")
    seen = page.evaluate(SW_SEEN)
    page.evaluate("() => { window.__ls.length = 0; window.__box = [...document.querySelectorAll('#removals .rm-card')].map(c => JSON.stringify(c.getBoundingClientRect())); }")
    t0 = tnow()
    page.wait_for_timeout(2600)
    dur = page.evaluate("() => getComputedStyle(document.querySelector('#removals .rm-gone')).transitionDuration")
    page.screenshot(path=str(cfg.out / f"removals-{vp_name}-sweep-1.png"))
    m1 = [val(i) for i in range(4)]
    page.wait_for_timeout(3600)
    page.screenshot(path=str(cfg.out / f"removals-{vp_name}-sweep-2.png"))
    m2 = [val(i) for i in range(4)]
    page.wait_for_timeout(2800)
    rec = since(t0)
    vis = [i for i in range(4) if seen[i]]
    per = {i: [e[2] for e in rec if e[1] == i] for i in vis}
    need = 1 if vp_name == "phone" else 2   # phone: one column, one or two stages on screen
    check(f"{tag} sweep: on-screen edges glide by themselves, no input (9 s: 2+ stops each, all near the middle, 42-58; {need}+ cards on screen)", len(vis) >= need and all(
        len(per[i]) >= 2 and all(42 <= v <= 58 for v in per[i]) for i in vis), {"visible": vis, "per": per})
    times = {i: [e[0] for e in rec if e[1] == i] for i in vis}
    synced = [(i, j) for i in vis for j in vis if i < j and len(times[i]) == len(times[j]) and all(abs(x - y) < 50 for x, y in zip(times[i], times[j]))]
    if vp_name != "phone":   # needs 2+ cards on screen: desktop's 2x2 (same JS on phones)
        check(f"{tag} sweep: cards not in lockstep (each its own stops and times)", len(vis) >= 2 and len({tuple(per[i]) for i in vis}) == len(vis)
              and not synced, {"times": times, "per": per, "synced": synced})
    secs = float(dur[:-1]) if dur.endswith("s") and dur[:-1].replace(".", "", 1).isdigit() else 0
    ls = page.evaluate("() => [window.__ls.filter(e => !e[2] && e[3]).reduce((a, e) => a + e[1], 0), [...document.querySelectorAll('#removals .rm-card')].every((c, i) => JSON.stringify(c.getBoundingClientRect()) === window.__box[i])]")
    check(f"{tag} sweep: glide = CSS transition 1-2 s, CLS 0 in #removals, card boxes unchanged", 1 <= secs <= 2 and ls == [0, True], [dur, ls])
    (cfg.out / f"removals-{vp_name}-sweep.txt").write_text(f"moment 1 edges (mega, x, reddit, site): {m1}\nmoment 2 edges: {m2}\n"
                                                             f"visible cards: {vis}\nrecorded stops per visible card: {per}\nglide transition: {dur}\n")
    # input stops only that card: Remove pressed (held 5.5 s, then released) on card 0, card 1 keeps going
    bring(page, "#removals .rm-card .rm-btn", "center")
    b = cards[0].locator(".rm-btn").bounding_box()
    page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    page.mouse.down()
    t1 = tnow()
    page.wait_for_timeout(5500)   # > the longest step gap (2 s glide + 3 s hold)
    held = [e for e in since(t1) if e[1] == 0]
    page.mouse.up()
    check(f"{tag} sweep: pressing Remove (held 5.5 s) already stops that card, before the click", not held, held)
    a0, t1 = val(0), tnow()
    page.wait_for_timeout(6000)
    rec = since(t1)
    check(f"{tag} sweep: toggle: Remove tap stops that card for good (6 s still), the next card keeps gliding",
          a0 in (0, 100) and not [e for e in rec if e[1] == 0] and any(e[1] == 1 for e in rec), [a0, rec])
    page.screenshot(path=str(cfg.out / f"removals-{vp_name}-sweep-3-stopped.png"))
    # a tap on card 1's stage: stops its sweep; the edge stays where it was (a tap never moves it: L9)
    bring(page, '#removals .rm-card[data-rm="x"] .rm-stage', "center")
    r = cards[1].locator(".rm-stage").bounding_box()
    a_pre = val(1)
    page.mouse.click(r["x"] + r["width"] * .3, r["y"] + r["height"] * .4)
    a1, t1 = val(1), tnow()
    page.wait_for_timeout(5500)
    rec = [e for e in since(t1) if e[1] == 1]
    check(f"{tag} sweep: a tap on the stage stops it where it was (no edge move, 5.5 s still)", a1 == a_pre and not rec and val(1) == a1, [a_pre, a1, rec])
    # handle keys on card 2, once it is gliding
    bring(page, '#removals .rm-card[data-rm="reddit"]', "center")
    try:
        page.wait_for_function("() => document.querySelectorAll('#removals .rm-handle')[2].getAttribute('aria-valuenow') !== '100'", timeout=4500)
    except Exception:
        pass
    moving = val(2) != 100
    hds[2].focus()
    page.keyboard.press("ArrowLeft")
    a2, t1 = val(2), tnow()
    page.evaluate("document.activeElement.blur()")
    page.wait_for_timeout(5500)
    rec = [e for e in since(t1) if e[1] == 2]
    check(f"{tag} sweep: ArrowLeft on a gliding card's handle steps 10 and stops it (5.5 s still)", moving and not rec and val(2) == a2, [moving, a2, rec])
    # document hidden: card 3 pauses, resumes when visible again
    bring(page, '#removals .rm-card[data-rm="site"]', "center")
    try:
        page.wait_for_function("() => document.querySelectorAll('#removals .rm-handle')[3].getAttribute('aria-valuenow') !== '100'", timeout=4500)
    except Exception:
        pass
    vis_flip = "h => { Object.defineProperty(document, 'hidden', {configurable: true, get: () => h}); Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => h ? 'hidden' : 'visible'}); document.dispatchEvent(new Event('visibilitychange')); }"
    page.evaluate(vis_flip, True)
    t1 = tnow()
    page.wait_for_timeout(5500)
    hid = [e for e in since(t1) if e[1] == 3]
    page.evaluate(vis_flip, False)
    t1 = tnow()
    try:
        page.wait_for_function("t => window.__sw.some(e => e[1] === 3 && e[0] >= t)", arg=t1, timeout=4000)
    except Exception:
        pass
    back = [e for e in since(t1) if e[1] == 3]
    check(f"{tag} sweep: pauses while the tab is hidden (5.5 s), resumes when visible", not hid and bool(back), [hid, back])
    # reduced motion switched on mid-visit (OS setting flipped): card 3, still gliding, stops
    page.emulate_media(reduced_motion="reduce")
    t1 = tnow()
    page.wait_for_timeout(5000)
    rm = since(t1)
    check(f"{tag} sweep: reduced motion switched on mid-visit: no edge moves after (5 s)", bool(back) and not rm, rm)
    ctx.close()


def panel_mix(demo, now):
    """H3: per panel, all the demo (every slot as in the markup) or all hers (no slot / photo of the demo left)."""
    out = {}
    for d, n in zip(demo, now):
        is_demo = n["t"] == d["t"] and n["img"] == d["img"]
        is_hers = all(n["t"][k] != d["t"].get(k) for k in n["t"]) and not any(u.startswith("img/removals/") for u in n["img"])
        out[n["k"]] = "demo" if is_demo else "hers" if is_hers else "MIXED"
    return out


def removals_flow(browser, vp_name, vp):
    tag = f"{vp_name} removals:"
    net = {"outside": [], "errors": [], "results": [], "dialogs": []}

    def ctx_(scheme="light", motion="no-preference"):
        ctx = new_ctx(browser, vp_name, vp, net, init=[LAYOUT_SHIFTS, PIP_AWAY], color_scheme=scheme, reduced_motion=motion)[0]   # player put away: #90's 640 px floating pip covers the x card's edge (pip scenario covers the player)
        ctx.on("page", lambda pg: pg.on("request", lambda q: "/api/scan-result/" in q.url and net["results"].append(q.url)))
        return ctx

    first = {}

    def open_(ctx, q="", settle=True):
        page = ctx.new_page()
        page.goto(cfg.base + q, wait_until="load")
        first["state"] = page.evaluate(RM_STATE)   # one sync task: no sweep step can run before it
        bring(page, "#removals .section-head", "center")
        bring(page, "#removals .rm-grid", "center")
        page.wait_for_timeout(700)
        if settle:   # the ambient sweep stops on input: End on each handle = real input, edge back at 100
            for hd in page.locator("#removals .rm-handle").all():
                hd.focus()
                page.keyboard.press("End")
            page.evaluate("document.activeElement.blur()")
            page.wait_for_timeout(300)
        return page

    def settled_imgs(page):
        try:
            page.wait_for_function("() => [...document.querySelectorAll('#removals .rm-img')].every(i => i.complete && i.naturalWidth > 0)", timeout=6000)
        except Exception:
            pass

    for scheme in ("light", "dark"):
        ctx = ctx_(scheme)
        page = open_(ctx)
        order = page.evaluate("() => { const r = document.getElementById('removals'); return [r && r.previousElementSibling && r.previousElementSibling.id, r && r.nextElementSibling && r.nextElementSibling.id, r && r.closest('main') && r.closest('main').id]; }")
        if scheme == "light":
            check(f"{tag} section sits after #faq, directly before #contact, inside <main>", order == ["faq", "contact", "main"], order)
            t = page.evaluate(RM_TEXT)
            check(f"{tag} defaults: demo creator (Orla Brennick / brennickclay) in every panel",
                  t.get("name") == "Orla Brennick" and t.get("mega-title") == "brennickclay – pack" and t.get("x-l1") == "Orla Brennick full set"
                  and "READ THIS.txt" in t.get("mega-note", "")
                  and t.get("aka") == "brennickclay, orlabrennick" and t.get("host") == "leak-mirror", t)
            copy = page.evaluate("() => [...document.querySelectorAll('#removals .rm-stage, .phone .phone-screen')].map(s => { const c = s.cloneNode(true); c.querySelectorAll('.m-search').forEach(e => e.remove()); return c.textContent; }).join(' | ')")   # #86/#91: both phones' Google query '<name> nude leaks' is the owner's chosen search, exempt
            check(f"{tag} L11: mock panels and the Before (#free) / After phones carry no 'onlyfans' / 'leaked' / 'leaks' (removed layers, hidden tabs included; the phones' Google query aside)", not NEUTRAL_RE.search(copy),
                  NEUTRAL_RE.findall(copy))
            gone = page.evaluate("() => [...document.querySelectorAll('#removals .rm-card')].map(c => [c.dataset.rm, [...c.querySelectorAll('.rm-gone .xp-head, .rm-gone .xp-text, .rm-gone .xp-acts, .rm-gone .rd-head, .rm-gone .rd-title, .rm-gone .rd-acts, .rm-gone .fp-bar, .rm-gone .fp-search')].length, c.querySelectorAll('[data-rm-copy]').length])")
            check(f"{tag} removed layers carry the live post's chrome (copied once from the live layer)",
                  gone == [["mega", 0, 0], ["x", 3, 0], ["reddit", 3, 0], ["site", 2, 0]], gone)
            outs = page.eval_on_selector_all("#removals .rm-out", "es => es.map(e => e.textContent)")
            check(f"{tag} one outcome line per panel", outs == ["Folders behind aggregator packs disabled", "Media disabled after copyright report",
                                                             "Removed on copyright notice", "Profile 404 after a DMCA notice"], outs)
            DEMO = page.evaluate(RM_PANEL)
            check(f"{tag} no links in the section (mock-ups only)", page.locator("#removals a").count() == 0)
        settled_imgs(page)
        blur = page.eval_on_selector_all("#removals .rm-img", "es => es.map(e => [e.getAttribute('src'), getComputedStyle(e).filter, e.naturalWidth])")
        check(f"{tag} {scheme}: every leak-side image blurred by default, loaded from site/img", len(blur) == 13 and all(
            "blur(" in b[1] and b[0].startswith("img/removals/") and b[2] > 0 for b in blur), blur)
        sw = page.evaluate("() => [document.documentElement.scrollWidth, innerWidth, Math.max(...[...document.querySelectorAll('#removals *')].map(e => e.parentElement.closest('.rm-stage') || (e.parentElement.closest('.rm-grid') && getComputedStyle(document.querySelector('#removals .rm-grid')).overflowX === 'auto') ? 0 : e.getBoundingClientRect().right))]")   # phone: the swipe row clips its panels
        check(f"{tag} {scheme}: no horizontal overflow", sw[0] <= sw[1] and sw[2] <= sw[1] + 0.5, sw)
        cols = page.evaluate("() => { const cs = [...document.querySelectorAll('#removals .rm-card')].map(c => c.getBoundingClientRect()); return [new Set(cs.map(r => Math.round(r.x))).size, new Set(cs.map(r => Math.round(r.y + scrollY))).size, cs.length, cs.every(r => r.width > 0 && r.height > 0 && r.left >= 0 && r.right <= innerWidth), document.querySelectorAll('.swipe-nav').length]; }")
        check(f"{tag} {scheme}: layout {'one column (4 rows)' if vp_name == 'phone' else '2x2'}, all 4 cards on the page within its width, no carousel nav",
              cols == ([1, 4, 4, True, 0] if vp_name == "phone" else [2, 2, 4, True, 0]), cols)
        page.locator("#removals .rm-grid").screenshot(path=str(cfg.out / f"removals-{vp_name}-{scheme}-0-layout.png"))
        if scheme == "light":
            fp_checks(tag, vp_name, page.evaluate(FP_STATE), "Orla Brennick", "brennickclay, orlabrennick", vp["width"])
        before = page.evaluate(RM_STATE)
        check(f"{tag} {scheme}: starts mid-stage (edge 50 % ± 10 px per card, clip at the edge, left leak / right removed, 'Preview removal')", all(
            abs(s["mid"]) <= 10 and s["cp"] is not None and abs(s["cp"] - s["hp"]) <= .6 and s["pressed"] == "false" and s["label"] == "Preview removal" and s["shown"] == "gone"
            for s in first["state"]) and len({s["mid"] for s in first["state"]}) > 1, [[s["k"], s["mid"], s["cp"], s["hp"], s["shown"], s["label"]] for s in first["state"]])
        check(f"{tag} {scheme}: End on the handle = all live (edge 100, removed layer clipped away)", all(
            s["p"] == "100" and s["pressed"] == "false" and s["label"] == "Preview removal" and s["shown"] == "live" for s in before), before)
        al = page.evaluate(RM_ALIGN)
        check(f"{tag} {scheme}: removed layer aligned with the live one (X / Reddit / leak-site shared rows: same box)", len(al) >= 10 and all(a[1] == a[2] for a in al),
              [a for a in al if a[1] != a[2]] or len(al))
        stg = page.evaluate("() => [...document.querySelectorAll('#removals .rm-stage')].map(s => [getComputedStyle(s).filter, getComputedStyle(s).touchAction])")
        check(f"{tag} {scheme}: no CSS filter on a stage (iOS repaints a filtered parent of the moving clip late), touch-action pan-y (a vertical swipe scrolls the page)",
              all(x == ["none", "pan-y"] for x in stg), stg)
        idle = page.evaluate(RM_IDLE)
        check(f"{tag} {scheme}: L10: idle, the handle covers no text / photo of the live leak and no edge line shows (leak-site photo grid aside)",
              all(not x[1] and x[2] == "0" for x in idle), idle)
        for k, card in zip(RM_PANELS, page.locator("#removals .rm-card").all()):
            card.screenshot(path=str(cfg.out / f"removals-{vp_name}-{scheme}-{k}-1-live.png"))
        page.evaluate("() => { window.__ls.length = 0; }")
        for b in page.locator("#removals .rm-btn").all():
            b.click()
        page.wait_for_timeout(1000)
        after = page.evaluate(RM_STATE)
        check(f"{tag} {scheme}: toggle: Remove flips all 4 panels to removed (edge 0, removed layer on top, 'Show again')",
              [s["k"] for s in after] == list(RM_PANELS) and all(s["p"] == "0" and s["pressed"] == "true" and s["label"] == "Show again"
                                                               and s["shown"] == "gone" and s["clip"] == "inset(0px 0px 0px 0%)" for s in after), after)
        ls = page.evaluate("() => window.__ls.filter(e => !e[2]).reduce((a, e) => a + e[1], 0)")
        check(f"{tag} {scheme}: CLS 0 on toggle, stage + card boxes unchanged", ls == 0 and [s["box"] + s["card"] for s in before] == [s["box"] + s["card"] for s in after],
              f"cls={ls}")
        for k, card in zip(RM_PANELS, page.locator("#removals .rm-card").all()):
            card.screenshot(path=str(cfg.out / f"removals-{vp_name}-{scheme}-{k}-2-removed.png"))
        page.locator("#removals .rm-btn").first.click()
        page.wait_for_timeout(1000)
        back = page.evaluate(RM_STATE)[0]
        check(f"{tag} {scheme}: toggle: Show again puts the leak back", back["p"] == "100" and back["shown"] == "live" and back["label"] == "Preview removal", back)
        if scheme == "light":
            # drag: grab the stage near its right edge, pull to 30 %
            st = page.locator('#removals .rm-card[data-rm="x"] .rm-stage')
            bring(page, '#removals .rm-card[data-rm="x"] .rm-stage', "center")
            r = st.bounding_box()
            y = r["y"] + r["height"] * .4
            page.mouse.move(r["x"] + r["width"] - 4, y)
            page.mouse.down()
            for f in (.8, .6, .45, .3):
                page.mouse.move(r["x"] + r["width"] * f, y, steps=3)
            page.mouse.up()
            d = page.evaluate(RM_STATE)[1]
            check(f"{tag} drag moves the edge and the clip (left = leak, right = removed)", 27 <= int(d["p"]) <= 33
                  and d["cp"] is not None and abs(d["cp"] - int(d["p"])) <= .5 and abs(d["cp"] - d["hp"]) <= .6 and d["shown"] == "gone", d)
            st.screenshot(path=str(cfg.out / f"removals-{vp_name}-drag-x-30.png"))
            if vp_name == "phone":   # a real touch drag (CDP touch events): the edge follows the finger on every move, before the finger lifts
                cdp = ctx.new_cdp_session(page)
                sel = '#removals .rm-card[data-rm="reddit"] .rm-stage'
                bring(page, sel, "center")
                page.wait_for_timeout(200)
                r = page.locator(sel).bounding_box()
                y = r["y"] + r["height"] * .3
                tp = lambda t, x: cdp.send("Input.dispatchTouchEvent", {"type": t, "touchPoints": [] if t == "touchEnd" else [{"x": x, "y": y}]})
                xs = [r["x"] + r["width"] * f for f in (.8, .78, .74, .7, .62, .55, .48, .4, .32, .25)]
                pos0 = page.evaluate("[scrollX, scrollY]")
                tp("touchStart", xs[0])
                mids = []
                for i, x in enumerate(xs[1:]):
                    tp("touchMove", x)
                    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")   # Chromium hands touch moves over per frame
                    mids.append([round(x, 1), page.evaluate(RM_MID, "reddit")])
                    if i == 5:
                        page.locator(sel).screenshot(path=str(cfg.out / f"removals-{vp_name}-touch-drag-1-mid.png"))
                pos1 = page.evaluate("[scrollX, scrollY]")
                tp("touchEnd", xs[-1])
                page.wait_for_timeout(300)
                page.locator(sel).screenshot(path=str(cfg.out / f"removals-{vp_name}-touch-drag-2-settled.png"))
                live = mids[2:]   # past the 8 px sideways intent
                check(f"{tag} touch drag: the edge follows the finger on every move before it lifts (±2 px), clip = edge, leak left / removed right of it, page still",
                      len(live) >= 6 and all(abs(m["edge"] - x) <= 2 and m["cp"] is not None and abs(m["cp"] - m["hp"]) <= .6 and m["left"] == "live" and m["right"] == "gone" for x, m in live)
                      and all(a[1]["edge"] > b[1]["edge"] for a, b in zip(live, live[1:])) and pos1 == pos0, [pos0, pos1, mids])
                p0 = page.evaluate(RM_MID, "reddit")["p"]
                y0 = page.evaluate("scrollY")
                cdp.send("Input.synthesizeScrollGesture", {"x": int(r["x"] + r["width"] * .5), "y": int(r["y"] + r["height"] * .5), "xDistance": 0, "yDistance": 220,
                                                           "gestureSourceType": "touch", "speed": 800})
                page.wait_for_timeout(600)
                y1, p1 = page.evaluate("scrollY"), page.evaluate(RM_MID, "reddit")["p"]
                check(f"{tag} touch: a vertical swipe on a stage scrolls the page (up 220 px), the edge stays", y0 - y1 >= 100 and p1 == p0, [y0, y1, p0, p1])
                cdp.detach()
            page.locator('#removals .rm-card[data-rm="x"] .rm-handle').focus()
            page.keyboard.press("End")
            sr = page.locator('#removals .rm-card[data-rm="reddit"] .rm-stage')
            bring(page, '#removals .rm-card[data-rm="reddit"] .rm-stage', "center")
            b = sr.bounding_box()
            tp0 = page.evaluate(RM_STATE)[2]["p"]
            if vp_name == "phone":
                page.touchscreen.tap(b["x"] + b["width"] * .5, b["y"] + b["height"] * .5)
            else:
                page.mouse.click(b["x"] + b["width"] * .5, b["y"] + b["height"] * .5)
            page.wait_for_timeout(200)
            tp = page.evaluate(RM_STATE)[2]["p"]
            check(f"{tag} L9: a {'tap' if vp_name == 'phone' else 'click'} on the stage (no sideways drag) leaves the edge where it was", tp == tp0, [tp0, tp])
            page.locator('#removals .rm-card[data-rm="x"] .rm-handle').focus()
            page.keyboard.press("End")
            k1 = page.evaluate(RM_STATE)[1]
            page.keyboard.press("ArrowLeft")
            k2 = page.evaluate(RM_STATE)[1]
            check(f"{tag} keyboard on the handle: End = all leak, ArrowLeft steps 10", k1["p"] == "100" and k2["p"] == "90", [k1["p"], k2["p"]])
            page.locator("#removals .rm-reveal").click()
            page.wait_for_timeout(500)   # filter transition .25s
            rv = page.eval_on_selector_all("#removals .rm-img", "es => es.map(e => getComputedStyle(e).filter)")
            check(f"{tag} Show demo images unblurs, Blur demo images re-blurs", all(f == "none" for f in rv) and page.locator("#removals .rm-reveal").inner_text().strip() == "Blur demo images")
            page.locator("#removals .rm-reveal").click()
        ctx.close()

    # reduced motion: no transition, the flip is immediate
    ctx = ctx_(motion="reduce")
    page = open_(ctx, settle=False)
    page.evaluate(SW_REC)
    page.wait_for_timeout(4000)
    rec = page.evaluate("window.__sw")
    vals = [h.get_attribute("aria-valuenow") for h in page.locator("#removals .rm-handle").all()]
    check(f"{tag} sweep: reduced motion: no edge moves by itself (4 s on screen, all still mid-stage, 47-53)", not rec and all(47 <= int(v) <= 53 for v in vals), [rec, vals])
    page.locator("#removals .rm-btn").first.click()
    rm = page.evaluate("() => [getComputedStyle(document.querySelector('#removals .rm-gone')).transitionDuration, document.querySelector('#removals .rm-handle').getAttribute('aria-valuenow')]")
    check(f"{tag} toggle: reduced motion flips with no transition", rm == ["0s", "0"], rm)
    ctx.close()

    sweep_flow(ctx_, vp_name, tag)

    # the narrowest phones: nothing in the section (the leak-site header included) runs sideways. Not is_mobile: that widens
    # the layout viewport to the page's widest box (#free is 360 px wide at 320 today, outside this section)
    if vp_name == "phone":
        for w, hgt in ((320, 640), (360, 740)):
            nctx = new_ctx(browser, f"phone{w}", {"width": w, "height": hgt}, net, device_scale_factor=2, has_touch=True)[0]
            pg = nctx.new_page()
            pg.goto(cfg.base, wait_until="load")
            bring(pg, '#removals .rm-card[data-rm="site"]', "center")
            pg.wait_for_timeout(400)
            sw = pg.evaluate("""() => [document.documentElement.scrollWidth, innerWidth, Math.max(...[...document.querySelectorAll('#removals *')].map(e => e.parentElement.closest('.rm-stage') ? 0 : e.getBoundingClientRect().right)),
              [...document.querySelectorAll('#removals .fp-bar, #removals .fp-head, #removals .fp-who > *')].filter(e => e.scrollWidth > e.clientWidth + 1 && !/fp-(name|aka)/.test(e.className)).map(e => e.className)]""")
            check(f"{tag} fp: {w} px: nothing in #removals runs past the screen, leak-site header (wordmark uncut) / profile rows fit their box", sw[1] == w and sw[2] <= w + 0.5 and not sw[3], sw)
            if w == 320:
                fp_row(tag, w, pg.evaluate(FP_STATE))
            pg.locator('#removals .rm-card[data-rm="site"]').screenshot(path=str(cfg.out / f"removals-phone{w}-site-1-live.png"))
            nctx.close()

    # personalized: ?r=<slug> (shared scan-result request), the backend's mega[], x / reddit / leak-site hits, thumbs still blurred
    MEGA = {"meta": "6.2 GB · 412 images · 88 videos · 3 days ago"}
    RM = served("demoRemove1")   # the wire payload
    AGG = {h.lower() for x in RM["mega"] for h in (x["host"], x["via"])}
    HIT_HOSTS = {h["domain"] for h in RM["hits"]}

    def leak_host_ok(h):
        """observables only (not removals.js's rules re-implemented): one of her served hit hosts, not under a mega[] host, no unsafe word"""
        return h in HIT_HOSTS and not any(h == a or h.endswith("." + a) for a in AGG) and not UNSAFE_RE.search(h)

    def leak_brand_ok(b):
        """the wordmark: brand() of such a host"""
        return any(brand(h) == b and leak_host_ok(h) for h in HIT_HOSTS)
    name = FX["profile"]["display_name"]
    for scheme in ("light", "dark"):
        ctx = ctx_(scheme)
        net["results"].clear()
        page = open_(ctx, "?r=demoRemove1")
        try:
            page.wait_for_function("() => document.getElementById('removals').getAttribute('data-rm-for') === 'demo.creator'", timeout=6000)
        except Exception:
            pass
        settled_imgs(page)
        t = page.evaluate(RM_TEXT)
        if scheme == "light":
            check(f"{tag} ?r=: Mega panel = her name + handle, mega[] size / counts / age, no third-party title, no demo pill",
                  t.get("name") == name and t.get("mega-title") == "demo.creator – pack" and t.get("mega-meta") == MEGA["meta"]
                  and t.get("mega-img") == "412 files" and t.get("mega-vid") == "88 files" and "mega-pill" not in t
                  and RM["mega"][0]["title"] not in page.inner_html("#removals"), t)
            check(f"{tag} C13: ?r=: her Mega panel shows only her pack (the demo's own 'READ THIS.txt' row hidden)",
                  "mega-note" not in t and "READ THIS" not in page.locator("#removals [data-rm=mega] .rm-live").inner_text(), t.get("mega-note"))
            check(f"{tag} ?r=: X = a poster off her x.com hits, Reddit = a subreddit off her reddit hits (ones with leak words skipped), "
                  f"leak site = one of her served hit hosts (wordmark without its TLD), never under a mega[] host, no unsafe word ({t.get('host')}); her name + '<handle>, <name>' aka, no third-party title",
                  t.get("x-at") == "@demo_reposter" and t.get("x-l1") == name and "x-l2" not in t and "x-acts" not in t and "x-age" not in t
                  and t.get("sub") == "r/demo_pics" and t.get("rd-title") == name and "rd-acts" not in t
                  and leak_brand_ok(t.get("host")) and t.get("aka") == "demo.creator, " + re.sub(r"[^a-z0-9]+", "", name.lower()), t)
            fp = page.evaluate(FP_STATE)
            check(f"{tag} fp: ?r=: leak-site profile = scanned name + '<handle>, <name>' aka, the wordmark on both layers, not cut",
                  fp["name"] == name and fp["aka"] == t.get("aka") and fp["hosts"] == [t.get("host")] * 2 and fp["logo"][0] <= fp["logo"][1],
                  [fp["name"], fp["aka"], fp["hosts"], fp["logo"]])
            mix = panel_mix(DEMO, page.evaluate(RM_PANEL))
            check(f"{tag} H3: ?r= with data for every panel: each panel all hers (no demo slot / photo beside her data)",
                  mix == {k: "hers" for k in RM_PANELS}, mix)
            html = page.inner_html("#removals")
            check(f"{tag} ?r=: no URL rendered, no links, no leak words from her hits", "mega.nz/" not in html and "x.com/" not in html
                  and "reddit.com/" not in html and page.locator("#removals a").count() == 0
                  and not UNSAFE_RE.search(" ".join(v for k, v in t.items() if k not in ("name",))), t)
            check(f"{tag} ?r=: one /api/scan-result request (shared with the hero card)", len(net["results"]) == 1, net["results"])
        th = page.eval_on_selector_all("#removals .rm-img", "es => es.filter(e => !e.closest('[hidden]')).map(e => [e.getAttribute('src'), getComputedStyle(e).filter, e.naturalWidth])")
        check(f"{tag} ?r= {scheme}: real thumbs via <API>/api/thumb, still blurred", all(
            s[0].startswith(cfg.api + "/api/thumb?u=") and "blur(" in s[1] and s[2] > 0 for s in th), th[:2])
        site = page.locator('#removals .rm-card[data-rm="site"]')
        page.locator("#removals .rm-grid").screenshot(path=str(cfg.out / f"removals-{vp_name}-{scheme}-personalized-1-live.png"))
        site.screenshot(path=str(cfg.out / f"removals-{vp_name}-{scheme}-site-personalized-1-live.png"))
        for b in page.locator("#removals .rm-btn").all():
            b.click()
        page.wait_for_timeout(1000)
        page.locator("#removals .rm-grid").screenshot(path=str(cfg.out / f"removals-{vp_name}-{scheme}-personalized-2-removed.png"))
        site.screenshot(path=str(cfg.out / f"removals-{vp_name}-{scheme}-site-personalized-2-removed.png"))
        ctx.close()

    # B1 / C14: demoRemove1 carries mega[] (leakshaven.com share page) + stale pack rows an older API kept: a
    # leakshaven.com hit (most-seen host of all), an s.leakshaven.com hit, a result on an innocent domain whose url host
    # is S.LeakShaven.com. No page that renders it (landing: hero card, #free phone, before phone, removals; scan page;
    # the demo site) may show an aggregator host or pack url, as text, href, src or anywhere else in the DOM (frames
    # included; case-insensitive), nor an anchor to one
    ctx = ctx_()
    page = ctx.new_page()
    agg_seen = {}
    for q, ready in (("?r=demoRemove1", ".phone-free.is-live"), ("scan/?r=demoRemove1", "#lx-list .lx-site"), ("showcase/?r=demoRemove1", "body")):
        page.goto(cfg.base + q, wait_until="load")
        try:
            page.wait_for_selector(ready, timeout=8000)
            if q.startswith("scan/"):
                open_all_sites(page)   # the sites list builds a site's links only once it is opened: every one in the DOM
        except Exception:
            pass
        page.wait_for_timeout(1500)
        html = page.evaluate(DOM_ALL).lower()
        agg_seen[q] = [w for w in ("leakshaven", "demopack", "packmirror.example") if w in html]
    check(f"{tag} B1 / C14: no aggregator host / pack url (subdomain, url host, any case) anywhere in the DOM (landing, scan page, "
          "demo site; text, hrefs, frames)", not any(agg_seen.values()), agg_seen)
    ctx.close()

    # S33 / C21: demoPackImg1 = the fixture + a Google result on a pack's host WITH a thumb, stored before the rule (that
    # thumb leads its images[]), served through the API's own off_row. The thumb shows in no view (hero strip + Images
    # grid, #free phone, scan page grid) and in no count: each equals the same fixture's without that result
    # (demoR3port01 = the oracle; nothing re-derived here)
    ctx = ctx_()
    page = ctx.new_page()
    seen = {}
    for slug in (FX["slug"], "demoPackImg1"):
        page.goto(cfg.base + "?r=" + slug, wait_until="load")
        page.wait_for_selector(".report-card #tab-report-images", timeout=8000)
        page.locator("#tab-report-images").click()
        settled_count(page, "#tab-report-images .live-tab-n")
        page.wait_for_selector(".phone-free.is-live", timeout=8000)
        page.locator("#tab-free-images").click()
        page.wait_for_timeout(600)
        land = page.evaluate(COUNTS), "packthumb" in page.evaluate(DOM_ALL).lower()   # the thumb's token (the slug says "pack" too)
        page.goto(cfg.base + "scan/?r=" + slug, wait_until="load")
        page.wait_for_selector("#tab-google-images", timeout=8000)
        page.locator("#tab-google-images").click()
        page.wait_for_timeout(800)
        seen[slug] = [land[0], page.locator("#tab-google-images").inner_text().strip(),
                      land[1] or "packthumb" in page.evaluate(DOM_ALL).lower()]
    check(f"{tag} S33: a pack-host result's thumb shows nowhere (hero strip / grid, #free phone, scan page) and counts nowhere "
          "(every image count = the fixture's without it)", seen["demoPackImg1"][:2] == seen[FX["slug"]][:2]
          and all(seen[FX["slug"]][0]) and not seen["demoPackImg1"][2], seen)
    ctx.close()

    # no mega[] / no x / reddit hits → demo shapes with her name; hostile values never reach the DOM
    ctx = ctx_()
    page = open_(ctx, "?r=demoNoProf01")
    try:
        page.wait_for_function("() => document.getElementById('removals').getAttribute('data-rm-for') === 'demo.creator'", timeout=6000)
    except Exception:
        pass
    t = page.evaluate(RM_TEXT)
    mix = panel_mix(DEMO, page.evaluate(RM_PANEL))
    check(f"{tag} H3: no mega[] / no x / reddit hits → those panels all the demo, the leak-site panel all hers (handle as name)",
          mix == {"mega": "demo", "x": "demo", "reddit": "demo", "site": "hers"} and t.get("aka") == "demo.creator, democreator", (mix, t))
    page.goto(cfg.base + "?r=evilR3port01", wait_until="load")
    page.wait_for_timeout(1500)
    html = page.inner_html("#removals")
    t = page.evaluate(RM_TEXT)
    check(f"{tag} hostile mega[] dropped (no markup, no javascript:, no oversize)", "onerror" not in html and "javascript" not in html
          and "xxxxx" not in html and page.locator("#removals img:not(.rm-img)").count() == 0 and not net["dialogs"], t.get("mega-meta"))
    ctx.close()
    hosts = {urlsplit(u).hostname for u in net["outside"]}
    check(f"{tag} no request left loopback (the demo iframe included: no Google Fonts), no JS errors", not hosts and not net["errors"],
          sorted(hosts) + net["errors"])
