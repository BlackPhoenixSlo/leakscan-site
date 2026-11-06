// #removals "Where I remove from": four mock panels (Mega, X, Reddit, a leak site) behind four tabs, each a live leak vs.
// its removed state. Show removal / Show again animates the compare edge; the handle moves it (arrow keys on it; drag it, or drag sideways
// anywhere on the stage: a tap or a vertical swipe never moves it): left of it = the live leak, right = removed. Idle
// (all live) the handle is parked in the stage's bottom corner with no edge line, so nothing of the live leak is covered.
// Personalized per panel from the page's scan result (E.currentSlug() → E.fetchResult, the one request shared with the
// hero card; again on `leakscan:result` after an in-page scan): a panel is all hers or all the demo, never a mix. Shown
// of hers: name / handle, a poster / subreddit / host read off her hits, mega[] counts and age, her Google thumbs.
// Never a third-party title, never a leak URL (read for its host / path only), never an aggregator host. textContent
// only. Own file so it merges next to other work.
// Ambient sweep: on screen each edge glides by itself to a random spot and holds there, per card, never in step;
// the first input on a card (a Remove press, a stage tap, a handle key) stops its sweep for good. None under
// prefers-reduced-motion.
// LeakScanRemovals.model(raw) (defined before the #removals check: site/js/video-overlays.js, whose page has none).
(function () {
  'use strict';
  var E = window.LeakScanEngine;
  if (!E) return;
  var C = E.clean, each = function (list, fn) { Array.prototype.forEach.call(list, fn); };

  // ---------- personalization: per panel, all hers or all the demo ----------
  // A third-party string that does show (an X poster, a subreddit, a leak host) must not carry adult / leak words (Ads
  // policy): an unsafe one is skipped for the next candidate; none left = that panel stays the demo.
  var UNSAFE = /onlyfan|fansly|leak|nud[ei]|naked|nsfw|porn|xxx|sex|hentai|erotic|fap|slut|escort|tits|boob|puss|cock|dick|cum|18\+|adult|explicit/i;
  var safe = function (s) { return s && !UNSAFE.test(s) ? s : null; };
  var PLATFORM_HOST = /(^|\.)(instagram|tiktok|onlyfans|fansly|patreon|youtube|threads|twitch|google|facebook)\.(com|net|tv)$/;
  // mega[].size is bytes → "6.2 GB" / "740 MB"; mega[].age an ISO UTC timestamp → "7 minutes ago"
  function bytes(v) {
    if (typeof v !== 'number' || !isFinite(v) || v <= 0 || v > 1e15) return null;
    var g = v / 1073741824, mb = v / 1048576;
    return g >= 1 ? (g < 10 ? g.toFixed(1).replace(/\.0$/, '') : Math.round(g)) + ' GB' : Math.max(1, Math.round(mb)) + ' MB';
  }
  function ago(v) {
    var t = typeof v === 'string' && v.length <= 40 && /^\d{4}-\d\d-\d\dT[\d:.]+(Z|[+-]\d\d:?\d\d)?$/.test(v) ? Date.parse(v) : NaN;
    if (!isFinite(t)) return null;
    var s = Math.max(0, (Date.now() - t) / 1000), u = [[86400 * 365, 'year'], [86400 * 30, 'month'], [86400, 'day'], [3600, 'hour'], [60, 'minute']];
    for (var i = 0; i < u.length; i++) {
      var n = Math.floor(s / u[i][0]);
      if (n >= 1) return n + ' ' + u[i][1] + (n > 1 ? 's' : '') + ' ago';
    }
    return 'just now';
  }
  function num(v) { return typeof v === 'number' && isFinite(v) && v >= 0 && v < 1e7 ? Math.round(v) : null; }
  // ---------- readers of the scan result, shared by the panels and model() ----------
  // the first hit on a host matching hostRe whose path gives re's capture (not `skip`; ok(capture) when given) →
  // {cap, hit}, else null
  function fromHits(raw, hostRe, re, skip, ok) {
    var out = null;
    (Array.isArray(raw.hits) ? raw.hits : []).slice(0, 1000).some(function (x) {
      var d = x && C.domain(x.domain), u = d && hostRe.test(d) && C.link(x.url), m = u && re.exec(u.pathname);
      if (m && !(skip && skip.test(m[1])) && (!ok || ok(m[1]))) out = { cap: m[1], hit: x };
      return !!out;
    });
    return out;
  }
  var X_AT = /^\/([A-Za-z0-9_]{1,15})(?:\/|$)/, X_NOT = /^(i|search|hashtag|home|explore)$/i, R_SUB = /^\/r\/([A-Za-z0-9_]{2,21})(?:\/|$)/;
  // the first mega[] item → {mg, img, vid, meta: "6.2 GB · 412 images · 88 videos · 3 days ago"}, else null. Its url /
  // host are an aggregator share page: never read here
  function megaMeta(raw) {
    var mg = (Array.isArray(raw.mega) ? raw.mega : []).filter(function (x) { return x && typeof x === 'object'; })[0];
    if (!mg) return null;
    var img = num(mg.images), vid = num(mg.videos);
    return { mg: mg, img: img, vid: vid,
      meta: [bytes(mg.size), img !== null ? img + ' images' : null, vid !== null ? vid + ' videos' : null, ago(mg.age)].filter(Boolean).join(' · ') || null };
  }
  // her Google thumbs (/api/thumb urls), at most 10
  function thumbsOf(raw) { return (Array.isArray(raw.images) ? raw.images : []).filter(C.thumbOk).slice(0, 10).map(E.thumb).filter(Boolean); }

  // One row per panel: the hosts it stands for (they never count as "a leak site") and fill(raw, who) → its values by
  // data-rm-k key, or null = the demo. In her panel a key without a value (null) hides its slot: no demo meta next to her.
  // Every third-party string shown passes safe(); mega[]'s title is never shown here.
  var PANELS = {
    mega: { hosts: /(^|\.)mega\.(nz|io)$/, fill: function (raw, who) {
      var mm = megaMeta(raw);
      return mm && { name: who.name, 'mega-title': who.handle + ' – pack', 'mega-pill': null, 'mega-meta': mm.meta,
        'mega-img': mm.img !== null ? mm.img + ' files' : null, 'mega-vid': mm.vid !== null ? mm.vid + ' files' : null, 'mega-note': null };   // the demo's own file row
    } },
    x: { hosts: /(^|\.)(x|twitter)\.com$/, fill: function (raw, who) {
      var x = fromHits(raw, PANELS.x.hosts, X_AT, X_NOT, safe), at = x && x.cap;
      return at && { 'x-at': '@' + at, 'x-name': at, 'x-av': at.charAt(0).toUpperCase(), 'x-age': null, 'x-l1': who.name, 'x-l2': null, 'x-acts': null };
    } },
    reddit: { hosts: /(^|\.)(reddit\.com|redd\.it)$/, fill: function (raw, who) {
      var r = fromHits(raw, PANELS.reddit.hosts, R_SUB, null, safe);
      return r && { sub: 'r/' + r.cap, 'rd-age': null, 'rd-title': who.name, 'rd-acts': null };
    } },
    site: { fill: function (raw, who) {   // a custom leak site: her most-seen host (E.rankHosts) that no other row claims
      var top = E.rankHosts(raw).filter(function (x) { return !notLeak(x.domain) && safe(x.domain); })[0];
      return top && { host: brand(top.domain), name: who.name, aka: aka(who) };
    } }
  };
  // leak-site wordmark: the host without its TLD ("leakvault.example" → "leakvault"), like fapello's bare logo; aliases
  // line: "<handle>, <name squashed>" (the way those sites list a model), just the handle without one
  function brand(d) { var p = d.split('.'); p.pop(); if (p.length > 1 && /^(co|com|net|org)$/.test(p[p.length - 1])) p.pop(); return p[p.length - 1]; }
  function aka(w) { var v = w.name.toLowerCase().replace(/[^a-z0-9]+/g, ''); return v && v !== w.handle ? w.handle + ', ' + v : w.handle; }
  function notLeak(d) {
    return PLATFORM_HOST.test(d) || Object.keys(PANELS).some(function (k) { return PANELS[k].hosts && PANELS[k].hosts.test(d); });
  }

  // ---------- LeakScanRemovals.model(raw): the video page's prefab values (site/js/video-overlays.js) ----------
  // The panels' readers, the same picks (first mega[] item, X poster / subreddit off the first hit that has one, the
  // most-seen other host, the thumbs). Deliberately unlike the panels, the video shows the leak posts as they read:
  // that hit's title, mega[]'s title (else a mega.nz hit's), leak words kept (no safe()): that page is noindex and in
  // no ad. A title is one line with no URL in it. null = no valid handle.
  function line(v, max, n, tail) {
    var s = C.str(v, max);
    s = s && !/https?:\/\/|www\./i.test(s) ? s.replace(tail || /$^/, '') : null;
    return s && n && s.length > n ? s.slice(0, n - 1).replace(/\s+\S*$/, '') + '…' : s;
  }
  function model(raw) {
    var h = raw && typeof raw === 'object' && C.handle(raw.handle);
    if (!h) return null;
    var pr = raw.profile && typeof raw.profile === 'object' ? raw.profile : {};
    var m = { name: line(pr.display_name, 60) || line(pr.first_name, 30) || h, handle: h, plat: (C.domain(raw.platform) || 'onlyfans.com').split('.')[0] };
    var x = fromHits(raw, PANELS.x.hosts, X_AT, X_NOT), r = fromHits(raw, PANELS.reddit.hosts, R_SUB), mm = megaMeta(raw);
    if (x) { m.xat = '@' + x.cap; m.xtext = line(x.hit.title, 300, 90, /\s*\/\s*(X|Twitter)$/); }
    if (r) { m.sub = 'r/' + r.cap; m.rtitle = line(r.hit.title, 300, 110, /\s*(:\s*r\/\w+|[-|]\s*Reddit)$/i); }
    if (mm) { m.mtitle = line(mm.mg.title, 200, 70); m.mimg = mm.img; m.mvid = mm.vid; m.mmeta = mm.meta; }
    else { var mh = fromHits(raw, PANELS.mega.hosts, /^(\/)/); if (mh) m.mtitle = line(mh.hit.title, 200, 70, /\s*[-|]\s*MEGA$/i); }
    var top = E.rankHosts(raw).filter(function (o) { return !notLeak(o.domain); })[0];   // the most-seen other host
    m.host = top ? top.domain : null;
    m.thumbs = thumbsOf(raw);
    return m;
  }
  window.LeakScanRemovals = { model: model };

  var root = document.getElementById('removals');
  if (!root) return;

  // the removed layer repeats the live post's chrome (header, text, actions): written once in the live layer, copied
  // where the markup says <span data-rm-copy="<selector in the live layer>">
  each(root.querySelectorAll('[data-rm-copy]'), function (slot) {
    var src = slot.closest('.rm-stage').querySelector('.rm-live ' + slot.getAttribute('data-rm-copy'));
    if (src) slot.parentNode.replaceChild(src.cloneNode(true), slot);
  });

  // ---------- compare: --p = edge position in % (LIVE = all live, GONE = all removed) ----------
  var LIVE = 100, GONE = 0, HALF = 50, END = 5, STEP = 10, PAGE = 25, INTENT_PX = 8;
  function set(card, p, anim) {
    p = Math.max(GONE, Math.min(LIVE, Math.round(p)));
    var stage = card.querySelector('.rm-stage'), h = card.querySelector('.rm-handle'), b = card.querySelector('.rm-btn'), gone = p <= HALF;
    stage.classList.toggle('rm-anim', !!anim);
    stage.style.setProperty('--p', p);
    stage.setAttribute('data-end', p === LIVE ? 'idle' : p >= LIVE - END ? 'r' : p <= GONE + END ? 'l' : '');   // CSS keeps the knob in
    card.classList.toggle('is-removed', gone);
    h.setAttribute('aria-valuenow', p);
    h.setAttribute('aria-valuetext', p === LIVE ? 'Leak live' : p === GONE ? 'Removed' : p + '% leak, ' + (LIVE - p) + '% removed');
    b.setAttribute('aria-pressed', String(gone));
    b.textContent = gone ? 'Show again' : 'Show removal';
  }
  var now = function (card) { return +card.querySelector('.rm-handle').getAttribute('aria-valuenow'); };

  // ---------- ambient sweep: glide (CSS transition, --rm-t 1-2 s) to a random 15-85, hold 1-3 s, repeat ----------
  // Timers only, no per-frame JS. Runs while the card is on screen (IntersectionObserver) and the tab is visible.
  // reduced motion: no sweep at all; switched on mid-visit: the next step is skipped (edges stay put)
  var mq = window.matchMedia ? matchMedia('(prefers-reduced-motion: reduce)') : null;
  var still = !window.IntersectionObserver || !mq || mq.matches;
  var sweeps = [], io = null;
  var rnd = function (a, b) { return a + Math.random() * (b - a); }, FIRST = 6000;
  function step(c) {
    c.t = 0;
    if (c.dead || !c.seen || document.hidden || mq.matches) return;
    var p = now(c.card), to, dur = Math.round(rnd(1000, 2000));
    do { to = Math.round(rnd(15, 85)); } while (Math.abs(to - p) < 15);   // a visible move every time
    c.stage.style.setProperty('--rm-t', dur + 'ms');
    set(c.card, to, true);
    c.t = setTimeout(function () { step(c); }, dur + rnd(1000, 3000));
  }
  function wake(c, wait) { if (!c.t && !c.dead && c.seen && !document.hidden) c.t = setTimeout(function () { step(c); }, wait); }
  function stop(c) {   // the user's input from here on: transitions back to the .7s default
    if (c.dead) return;
    c.dead = true;
    clearTimeout(c.t);
    c.stage.style.removeProperty('--rm-t');
    if (io) io.unobserve(c.card);
  }
  if (!still) {
    io = new IntersectionObserver(function (en) {
      en.forEach(function (e) {
        var c = sweeps.filter(function (x) { return x.card === e.target; })[0];
        c.seen = e.isIntersecting;
        // first time on screen: 6 s of the still leak before the first glide (time to read it); later visits sooner
        if (c.seen) { wake(c, c.met ? rnd(300, 1500) : FIRST); c.met = true; } else { clearTimeout(c.t); c.t = 0; }
      });
    });
    document.addEventListener('visibilitychange', function () {
      sweeps.forEach(function (c) { if (document.hidden) { clearTimeout(c.t); c.t = 0; } else wake(c, rnd(300, 1500)); });
    });
  }

  // one stage, four platform tabs (Mega / X / Reddit / Leak sites): every panel stays in the DOM, the others [hidden];
  // a hidden panel is off screen for the IntersectionObserver, so its sweep waits until its tab is picked
  E.tablist(root);

  each(root.querySelectorAll('.rm-card'), function (card, i) {
    var stage = card.querySelector('.rm-stage'), h = card.querySelector('.rm-handle'), drag = null;
    var c = sweeps[i] = { card: card, stage: stage, t: 0, seen: false, dead: still };
    // a press (pointer or key) stops the sweep before its click: no glide may flip Remove / Show again under the finger
    each(['pointerdown', 'keydown'], function (t) { card.querySelector('.rm-btn').addEventListener(t, function () { stop(c); }); });
    card.querySelector('.rm-btn').addEventListener('click', function () { stop(c); set(card, now(card) <= HALF ? LIVE : GONE, true); });
    var at = function (e) { var r = stage.getBoundingClientRect(); return (e.clientX - r.left) / r.width * 100; };
    var start = function (e) {
      drag.on = true;
      try { stage.setPointerCapture(e.pointerId); } catch (x) { /* ignore */ }
      set(card, at(e), false);
      if (e.pointerType !== 'touch') h.focus({ preventScroll: true });
    };
    // a press on the knob drags at once; anywhere else only once the pointer moves sideways (INTENT_PX, more x than y)
    stage.addEventListener('pointerdown', function (e) {
      if (e.button !== 0) return;
      stop(c);   // a tap too: the sweep never moves an edge she touched
      drag = { id: e.pointerId, x: e.clientX, y: e.clientY, on: false };
      if (e.target.closest && e.target.closest('.rm-knob')) start(e);
    });
    stage.addEventListener('pointermove', function (e) {
      if (!drag || drag.id !== e.pointerId) return;
      if (!drag.on) {
        var dx = Math.abs(e.clientX - drag.x), dy = Math.abs(e.clientY - drag.y);
        if (dx > INTENT_PX && dx > dy) start(e);
        else if (dy > INTENT_PX) drag = null;   // a vertical swipe: the page scrolls (touch-action: pan-y)
        return;
      }
      set(card, at(e), false);
    });
    var end = function (e) { if (drag && drag.id === e.pointerId) drag = null; };
    stage.addEventListener('pointerup', end);
    stage.addEventListener('pointercancel', end);
    h.addEventListener('keydown', function (e) {
      var p = now(card), k = e.key, n = k === 'ArrowLeft' || k === 'ArrowDown' ? p - STEP : k === 'ArrowRight' || k === 'ArrowUp' ? p + STEP
        : k === 'PageDown' ? p - PAGE : k === 'PageUp' ? p + PAGE : k === 'Home' ? GONE : k === 'End' ? LIVE : null;
      if (n === null) return;
      e.preventDefault();
      stop(c);
      set(card, n, false);
    });
    set(card, LIVE, false);
    if (io) io.observe(card);
  });
  // Reveal / Blur: the [data-reveal] button in this [data-reveal-scope] section (one handler, js/scan-engine.js)

  // the demo (as in the markup), kept so a second result / no data puts it back
  var cards = Array.prototype.map.call(root.querySelectorAll('.rm-card'), function (card) {
    return { el: card, panel: PANELS[card.getAttribute('data-rm')],
      texts: Array.prototype.map.call(card.querySelectorAll('[data-rm-k]'), function (el) { return [el, el.textContent]; }),
      imgs: Array.prototype.map.call(card.querySelectorAll('.rm-img'), function (im) { return [im, im.getAttribute('src')]; }) };
  });
  function render(raw) {
    var h = raw && C.handle(raw.handle), pr = h && raw.profile && typeof raw.profile === 'object' ? raw.profile : {};
    var who = h && { handle: h, name: safe(C.str(pr.display_name, 60)) || safe(C.str(pr.first_name, 30)) || h };
    // her Google thumbs go round her panels' image slots in page order; one that dies leaves its tile empty
    var pics = h ? thumbsOf(raw) : [], n = 0;
    cards.forEach(function (c) {
      var v = who && c.panel ? c.panel.fill(raw, who) : null;
      c.texts.forEach(function (t) {
        var el = t[0], s = v ? v[el.getAttribute('data-rm-k')] : t[1];
        el.hidden = !s;
        if (s && el.textContent !== s) el.textContent = s;
      });
      c.imgs.forEach(function (t) {   // the tile goes with its photo: no empty grey box, never a demo face beside her
        var im = t[0], tile = im.parentNode, src = v ? pics.length ? pics[n++ % pics.length] : null : t[1];
        tile.hidden = !src;
        if (!src || im.getAttribute('src') === src) return;
        im.referrerPolicy = 'no-referrer';
        im.setAttribute('src', src);
        if (v) E.watchThumb(im, function () { if (im.getAttribute('src') === src) tile.hidden = true; });
      });
      c.el.setAttribute('data-rm-for', v ? 'scan' : 'demo');
    });
    root.setAttribute('data-rm-for', who ? h : '');
  }

  var scanned = false;
  document.addEventListener('leakscan:result', function (e) { scanned = true; render(e.detail); });   // an in-page scan
  var slug = E.currentSlug();
  if (slug && window.fetch) E.fetchResult(slug).then(function (r) { if (!scanned) render(r); }, function () { /* the demo */ });
})();
