// site/video/: overlay prefabs (Google, Google Images, X, Reddit, Mega) on the right half (Jack is on the left), driven by the face video's currentTime. Cues are the
// data-cue-live / -removed / -out seconds on each .vo-pf (site/video/CUES.md, SCRIPT.md). draw(t) is a pure function of t (no CSS
// transitions), so seeking, ?t= and frame-by-frame capture (tools/video/render_prefabs.py) all show the exact frame.
// URL: ?name=<1-40 letters/digits/space . - _> (else the shared scan result: ?r= or the last scan, like #removals)
//      ?t=<sec> seek · ?sfx=0 no sound · ?prefab=google|google-images|x|reddit|mega&state=live|removed&bg=green|none: one prefab, no video
//      (?prefab=cta-steps&state=step1|step2|step3: the generic end card's 3 steps, 8 s, no form: the 6th CapCut clip).
// Two modes (html[data-vo-mode]): "named" (?name= or a scan result: her texts, the name spoken, "for <name>" pill, the
// jack-named.mp4 take if the server has it) and "generic" (texts say "Your name", default blurred thumbs, no speech, at
// data-cue-cta (default data-cue-say) the "Type your name" card = cta-steps: 3 steps on an 8 s loop, type your name → run the
// free scan → rewatch this video with YOUR content, kept looping after the video ends; its form reloads the page with ?name=).
// Player UI (.vo-ui): full screen = the stage (Fullscreen API, + landscape lock on Android), else (iPhone) a CSS "theater":
// the stage fixed + rotated 90deg (Esc / X / back closes); touch devices: no native controls, own play bar, a tap on the
// stage plays / pauses, "Rotate for full size" hint after the first tap.
// Each prefab: live cue = pops in from the right (0.45 s, scale .6 → 1.08 → 1) + kinetic word card; removed cue = the
// snap: 0.25 s shake + flash + "GONE." word card, then the compare wipe (0.95 s; .vo-roll counters roll down meanwhile),
// "Removed" stamp slams in (scale 2 → 1, 0.2 s) + a 12-piece confetti burst; slides out (0.4 s, gone at the out cue).
// google-images taps "Images" at data-cue-tap (default live + 0.6) and shows the image grid 0.3 s later.
// prefers-reduced-motion: css/video.css drops the shake / scale / particles / wipe for plain fades (same custom properties).
// Sound (web page only, never in ?prefab= renders): WebAudio-synthesized pop at live, whoosh + thud at removed, only while
// playing after the user's play gesture, low volume.
// Keys: space = play / pause, Esc closes the theater. textContent only; requests: the scan-result read (js/scan-engine.js) and, named only, a HEAD
// for jack-named.mp4 (same folder).
(function () {
  'use strict';
  var root = document.getElementById('vo');
  if (!root) return;
  var IN = 0.45, OUT = 0.4, SHAKE = 0.25, WIPE = 0.95, STAMP = 0.2, BURST = 0.6, KW = 0.6, SLIDE = 160;   // seconds; px
  var TAP = 0.6, SWAP = 0.3;                // google-images: tap at data-cue-tap (default live + 0.6), grid 0.3 s later
  var GENERIC = 'Your name', NAMED_TAKE = 'jack-named.mp4';
  // cta-steps: step windows (s into its 8 s loop), the name it types (or what the viewer typed in the form), the count it rolls to
  var STEPS = [[0, 2.6], [2.6, 5.3], [5.3, 8]], CYCLE = 8, DEMO = 'Orla Brennick', LEAKS = 37;
  var SOLO_CTA = { end: 8, step1: 2.2, step2: 3.9, step3: 7.2 };   // ?prefab=cta-steps: clip length, state= stills
  // ?prefab= timeline = the CapCut clip: in 0-0.45, snap at 2.4, wipe 2.65-3.6, stamp 3.6, out 5.6-6; state=live / removed = these stills
  var SOLO = { wipe: 2.4, end: 6, live: 1.6, removed: 5.4 };
  var q = new URLSearchParams(location.search), solo = q.get('prefab');
  var video = root.querySelector('.vo-video'), over = root.querySelector('.vo-over'), stage = root.querySelector('.vo-stage');
  var forEl = root.querySelector('.vo-for'), ctaEl = root.querySelector('.vo-cta'), forc = null, ctac = null, who = null, shift = 0, endT = Infinity;
  var num = function (el, k) { var v = el.getAttribute(k); return v === null ? NaN : parseFloat(v); };
  var pfs = Array.prototype.map.call(root.querySelectorAll('.vo-pf[data-prefab][data-cue-live]'), function (el) {
    var c = { el: el, id: el.getAttribute('data-prefab'), l0: num(el, 'data-cue-live'), r0: num(el, 'data-cue-removed'), o0: num(el, 'data-cue-out'),
      t0: num(el, 'data-cue-tap'), rolls: el.querySelectorAll('.vo-roll') };
    var burst = document.createElement('span');   // 12 confetti pieces, deterministic spread over the stamp
    burst.className = 'vo-burst';
    for (var i = 0; i < 12; i++) {
      var p = document.createElement('i'), ang = -Math.PI * (0.08 + 0.84 * i / 11), d = 90 + (i * 37) % 70;
      p.style.cssText = '--cx:' + (Math.cos(ang) * d).toFixed(1) + ';--cy:' + (Math.sin(ang) * d).toFixed(1) + ';--cr:' + ((i % 2 ? 1 : -1) * (200 + i * 23)) +
        ';--c:' + ['#ffd400', '#ff3b5c', '#23c483', '#2f80ff'][i % 4] + (i % 3 ? '' : ';border-radius:50%');
      burst.appendChild(p);
    }
    el.appendChild(burst);
    return c;
  });
  function retime() {   // the cues of the take that plays (shift = data-cue-named-shift while jack-named.mp4 plays)
    pfs.forEach(function (c) { c.live = c.l0 + shift; c.removed = c.r0 + shift; c.out = c.o0 + shift; c.tap = (isFinite(c.t0) ? c.t0 : c.l0 + TAP) + shift; });
  }
  retime();

  var clamp = function (x) { return x < 0 ? 0 : x > 1 ? 1 : x; };
  var ease = function (x) { return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
  var back = function (x) { var c = 1.2, d = x - 1; return 1 + (c + 1) * d * d * d + c * d * d; };   // ease-out with a slight overshoot
  var pop = function (a) { return a < 0.6 ? 0.6 + 0.48 * (1 - Math.pow(1 - a / 0.6, 2)) : 1.08 - 0.08 * ease((a - 0.6) / 0.4); };   // .6 → 1.08 → 1
  var kwPop = function (k) {   // the kinetic word card: [scale, opacity] at k = 0..1 of its 0.6 s
    if (k < 0 || k >= 1) return [1, 0];
    return [k < 0.2 ? 0.4 + 4 * k : k < 0.35 ? 1.2 - (k - 0.2) / 0.75 : 1, k < 0.1 ? k * 10 : k > 0.8 ? (1 - k) * 5 : 1];
  };
  var ROLL = /(\d[\d,]*(?:\.\d+)?)(\s*(?:[KMGT]B|videos?|images?|files?|results?)\b)/g;
  function rolled(src, to, w) {   // every "<n> <unit>" in src rolled from n to `to` over w = 0..1
    if (w <= 0) return src;
    return src.replace(ROLL, function (m, n, unit) {
      var v = parseFloat(n.replace(/,/g, '')), d = (n.split('.')[1] || '').length, x = w >= 1 ? to : to + (v - to) * (1 - w);
      var s = d && w < 1 ? x.toFixed(d) : String(Math.round(x));
      return (n.indexOf(',') >= 0 ? s.replace(/\B(?=(\d{3})+(?!\d))/g, ',') : s) + unit;
    });
  }
  var bump = function (k) { return k > 0 && k < 1 ? Math.sin(Math.PI * k) : 0; };
  var setText = function (el, s) { if (el && el.textContent !== s) el.textContent = s; };
  function demoName() {   // what step 1 types: the form's name once the viewer typed a valid one, else the demo name
    var inp = ctaEl && ctaEl.querySelector('input'), v = inp ? inp.value.replace(/\s+/g, ' ').trim() : '';
    return v && NAME_RE.test(v) ? v : DEMO;
  }
  function steps(c, t) {   // cta-steps at t: u = seconds into its loop (from the card's live cue, = the clip's 0 s)
    var box = c.steps, u = Math.max(0, t - c.live) % CYCLE, name = demoName(), bs = box.style;
    Array.prototype.forEach.call(box.querySelectorAll('.vo-step'), function (el, i) {
      var a = u - STEPS[i][0], d = STEPS[i][1] - STEPS[i][0], on = a >= 0 && a < d;
      el.style.setProperty('--so', (on ? Math.min(clamp(a / 0.15), clamp((d - a) / 0.2)) : 0).toFixed(3));
      el.style.setProperty('--ss', (on ? pop(clamp(a / 0.35)) : 1).toFixed(4));
      var dot = c.dots[i];
      if (dot) dot.style.setProperty('--d', on ? '1' : '.3');
    });
    var n = Math.round(clamp((u - 0.35) / 1.4) * name.length), p = 1 - Math.pow(1 - clamp((u - 2.8) / 1.8), 2), f = clamp((u - 6.1) / 0.3);
    setText(box.querySelector('.vo-mi-t'), name.slice(0, n));
    bs.setProperty('--caret', u < STEPS[0][1] && (n < name.length || Math.floor(u * 2.5) % 2 === 0) ? '1' : '0');
    bs.setProperty('--press', bump((u - 2.0) / 0.3).toFixed(3));
    bs.setProperty('--bar', p.toFixed(3));
    setText(box.querySelector('.vo-mc-n'), String(Math.round(LEAKS * p)));
    bs.setProperty('--cp', (1 + 0.25 * bump((u - 4.6) / 0.4)).toFixed(3));
    bs.setProperty('--fl', ((f < 0.5 ? f : f - 1) * 180).toFixed(1));   // 0 → 90deg, swap the text, -90 → 0
    setText(box.querySelector('.vo-mini-n'), f >= 0.5 ? name : GENERIC);
    bs.setProperty('--fp', (1 + 0.3 * bump((u - 6.4) / 0.4)).toFixed(3));
    bs.setProperty('--mp', clamp((u - 5.3) / 2.7).toFixed(3));
  }
  var cueAt = function (k) { return num(stage, k); };
  var sayStart = function () { return cueAt('data-cue-say-start'); };
  var sayEnd = function () { return Math.min(cueAt('data-cue-say') + shift, endT); };   // or when the video ends, if that comes first
  var ctaAt = function () { var c = cueAt('data-cue-cta'); return Math.min(isFinite(c) ? c : cueAt('data-cue-say'), endT); };
  function draw(t) {
    var cards = pfs;
    if (!root.classList.contains('vo-solo')) {
      if (forc) { var s0 = sayStart(), s1 = sayEnd(); forc.live = isFinite(s0) && t < s1 ? s0 : s1; forc.out = forc.live + 2; cards = cards.concat([forc]); }
      if (ctac) { ctac.live = ctaAt(); cards = cards.concat([ctac]); }
    }
    cards.forEach(function (c) {
      var a = clamp((t - c.live) / IN), b = clamp((t - (c.out - OUT)) / OUT), o = Math.min(clamp(a * 1.5), 1 - b);
      var k = (t - c.removed) / SHAKE, sh = k >= 0 && k < 1 ? 1 - k : 0, r = t - c.removed - SHAKE;
      var w = ease(clamp(r / WIPE)), s = clamp((r - WIPE) / STAMP), bu = clamp((r - WIPE - STAMP) / BURST), st = c.el.style;
      Array.prototype.forEach.call(c.rolls || [], function (el) {
        if (el.__src == null) el.__src = el.textContent;
        var txt = rolled(el.__src, parseFloat(el.getAttribute('data-roll-to')) || 0, w);
        if (el.textContent !== txt) el.textContent = txt;
      });
      if (!(o > 0)) { c.el.setAttribute('data-off', ''); return; }
      c.el.removeAttribute('data-off');
      var kl = kwPop((t - c.live) / KW), kg = kwPop((t - c.removed) / KW);
      st.setProperty('--o', o.toFixed(3));
      st.setProperty('--x', ((1 - back(a)) * SLIDE + b * b * 70 + (sh && sh * 13 * Math.sin(k * 29))).toFixed(2));   // + the snap shake
      st.setProperty('--y', (b * b * 110 + (sh && sh * 8 * Math.cos(k * 37))).toFixed(2));
      st.setProperty('--rot', (sh && sh * 1.6 * Math.sin(k * 23)).toFixed(3));
      st.setProperty('--sc', pop(a).toFixed(4));
      st.setProperty('--f', (sh * sh * 0.85).toFixed(3));
      st.setProperty('--tap', clamp((t - c.tap) / 0.4).toFixed(3));
      st.setProperty('--g', ease(clamp((t - c.tap - SWAP) / 0.3)).toFixed(3));
      st.setProperty('--p', (100 - w * 100).toFixed(2));
      st.setProperty('--w', w.toFixed(3));
      st.setProperty('--h', Math.min(1, 6 * Math.min(w, 1 - w)).toFixed(3));
      st.setProperty('--s', (s * s).toFixed(3));   // ease-in: the stamp slams
      st.setProperty('--b', (1 - Math.pow(1 - bu, 2)).toFixed(3));
      st.setProperty('--bo', (bu > 0 && bu < 1 ? 1 - bu * bu : 0).toFixed(3));
      st.setProperty('--kls', kl[0].toFixed(3));
      st.setProperty('--klo', kl[1].toFixed(3));
      st.setProperty('--kgs', kg[0].toFixed(3));
      st.setProperty('--kgo', kg[1].toFixed(3));
      if (c.steps) steps(c, t);
    });
    document.documentElement.setAttribute('data-vo-t', t.toFixed(2));
  }
  function fit() { root.querySelector('.vo-box').style.setProperty('--k', (over.clientWidth / 640).toFixed(4)); }
  fit();
  if (window.ResizeObserver) new ResizeObserver(fit).observe(over); else window.addEventListener('resize', fit);

  // ---------- personalization: values for the [data-vo] slots ----------
  var NAME_RE = /^[\p{L}\p{N} ._-]{1,40}$/u;
  function fill(v) {
    Array.prototype.forEach.call(root.querySelectorAll('[data-vo]'), function (el) {
      var k = el.getAttribute('data-vo');
      if (typeof v[k] !== 'string') return;
      if (el.classList.contains('vo-roll')) el.__src = v[k];
      if (el.textContent !== v[k]) el.textContent = v[k];
    });
  }
  function values(m) {   // m = LeakScanRemovals.model(result) + mine(result), or {name} from ?name= / the generic "Your name"
    var name = m.name, h = (m.handle || name).toLowerCase().replace(/[^a-z0-9_.]/g, '') || 'creator';
    var v = { name: name, site: m.site || (h.replace(/[^a-z0-9-]/g, '') || 'creator') + '.com', ig: m.ig || h, tt: m.tt || m.ig || h, 'mega-title': m.mtitle || name + ' – pack', 'x-l1': m.xtext || name + ' leaked', 'x-l2': m.xtext ? '' : name + ' ' + (m.plat || 'onlyfans'),
      sub: m.sub || 'r/' + (h.replace(/\./g, '').slice(0, 14) || 'creator') + '_leaks', 'rd-title': m.rtitle || name + ' full pack, link in comments' };
    if (m.xat) { v['x-at'] = m.xat; v['x-name'] = m.xat.slice(1); v['x-av'] = m.xat.charAt(1).toUpperCase(); }
    if (m.mmeta) { v['mega-meta'] = m.mmeta; var gb = /\d[\d.,]*\s*[KMGT]B/.exec(m.mmeta); if (gb) v['mega-gb'] = gb[0]; }
    if (m.mvid != null) v['mega-vid'] = m.mvid + ' files';
    if (m.mimg != null) v['mega-img'] = m.mimg + ' files';
    if (m.host) v.host = m.host;
    return v;
  }
  // her own site + accounts from the raw result, the way personalize.js dict() reads them (it is not loaded here)
  var HANDLE = /^[A-Za-z0-9_.]{1,30}$/, DOMAIN = /^(?=.{4,60}$)[a-z0-9-]+(\.[a-z0-9-]+)+$/;
  function mine(raw) {
    var pr = raw.profile && typeof raw.profile === 'object' ? raw.profile : {}, so = raw.socials && typeof raw.socials === 'object' ? raw.socials : {};
    var ok = function (x) { x = typeof x === 'string' ? x.trim().replace(/^@/, '') : ''; return HANDLE.test(x) ? x : null; };
    var acc = function (k) {
      var a = (Array.isArray(pr.accounts) ? pr.accounts : []).filter(function (a) {
        return a && typeof a.platform === 'string' && a.platform.toLowerCase().replace(/^www\./, '').split('.')[0] === k && ok(a.handle);
      })[0];
      return a ? ok(a.handle) : null;
    };
    var plat = typeof raw.platform === 'string' ? raw.platform.toLowerCase().replace(/^www\./, '').split('.')[0] : '';
    var sd = typeof pr.site_domain === 'string' ? pr.site_domain.trim().toLowerCase() : '', base = ok(pr.username) || ok(raw.handle) || '';
    base = base.toLowerCase().replace(/[^a-z0-9-]/g, '');
    return { site: DOMAIN.test(sd) ? sd : base ? base + '.com' : null,
      ig: ok(so.instagram) || acc('instagram') || (plat === 'instagram' ? ok(raw.handle) : null), tt: acc('tiktok') || (plat === 'tiktok' ? ok(raw.handle) : null) };
  }
  // the scan's thumbs into every .rm-img, cycled, same as js/removals.js render(); a failed one falls back to its default
  function thumbs(list) {
    if (!list || !list.length) return;
    Array.prototype.forEach.call(root.querySelectorAll('.rm-img'), function (im, i) {
      var def = im.getAttribute('src'), src = list[i % list.length];
      im.referrerPolicy = 'no-referrer';
      im.addEventListener('error', function () { if (im.getAttribute('src') === src) im.setAttribute('src', def); }, { once: true });
      im.setAttribute('src', src);
    });
  }
  var seekTo = null;   // the pending ?t= (played-take seconds)
  function namedTake() {   // named mode: play jack-named.mp4 when the server has it (HEAD), else keep jack.mp4
    if (solo !== null || !video || !window.fetch || !video.canPlayType('video/mp4')) return;
    fetch(NAMED_TAKE, { method: 'HEAD', cache: 'no-store' }).then(function (r) {
      if (!r.ok || !/^video\//.test(r.headers.get('content-type') || '') || who === null) return;
      var at = video.readyState >= 1 ? video.currentTime : seekTo || 0, go = !video.paused;
      Array.prototype.forEach.call(video.querySelectorAll('source'), function (s) { s.remove(); });
      shift = num(stage, 'data-cue-named-shift') || 0;
      retime();
      video.addEventListener('loadedmetadata', function () { video.currentTime = at; if (go) video.play().catch(function () {}); }, { once: true });
      video.src = NAMED_TAKE;
      video.load();
      root.setAttribute('data-vo-take', 'named');
      draw(at);
    }, function () { /* keep jack.mp4 */ });
  }
  function mode(m) { document.documentElement.setAttribute('data-vo-mode', m); }
  function personal(n) {
    who = n;
    mode('named');
    ctac = null;   // cta-steps: generic only
    pfs = pfs.filter(function (c) { return c.el !== ctaEl; });
    if (ctaEl) ctaEl.setAttribute('data-off', '');
    if (forEl) forc = { el: forEl, removed: Infinity, tap: Infinity };
    namedTake();
  }
  mode('generic');
  fill(values({ name: GENERIC }));
  if (ctaEl) ctac = { el: ctaEl, id: 'cta-steps', out: Infinity, removed: Infinity, tap: Infinity, steps: ctaEl.querySelector('.vo-steps'),
    dots: ctaEl.querySelectorAll('.vo-dots i') };
  var name = q.get('name');
  name = name === null ? null : name.replace(/\s+/g, ' ').trim();
  if (name && NAME_RE.test(name)) { fill(values({ name: name })); personal(name); }
  else {   // the shared scan result, same slug rule as js/removals.js (?r= → last scan → none = generic)
    var E = window.LeakScanEngine, R = window.LeakScanRemovals, slug = q.get('r');
    if (slug === null) { try { slug = (JSON.parse(localStorage.getItem('leakscan.last') || 'null') || {}).slug; } catch (e) { slug = null; } }
    if (E && E.fetchResult && R && typeof slug === 'string' && E.SLUG_RE.test(slug)) {
      E.fetchResult(slug).then(function (raw) {
        var m = R.model(raw);
        if (m) { var o = mine(raw); m.site = o.site; m.ig = o.ig; m.tt = o.tt; fill(values(m)); thumbs(m.thumbs); personal(m.name); if (solo === null && video) draw(video.currentTime); }
      }, function () { /* generic */ });
    }
  }
  // the generic end card's form: same page with ?name= (validated as above), nothing else carried over
  var form = ctaEl && ctaEl.querySelector('form');
  if (form) form.addEventListener('submit', function (e) {
    e.preventDefault();
    var inp = form.querySelector('input'), n = inp.value.replace(/\s+/g, ' ').trim();
    inp.setCustomValidity(NAME_RE.test(n) ? '' : 'Use 1-40 letters, digits, spaces or . - _');
    if (!inp.reportValidity()) return;
    location.assign(location.pathname + '?name=' + encodeURIComponent(n));
  });
  if (form) form.querySelector('input').addEventListener('input', function (e) { e.target.setCustomValidity(''); });

  // ---------- clock ----------
  var api = { prefabs: pfs.map(function (c) { return c.id; }).concat(ctac ? [ctac.id] : []), SOLO: SOLO, SOLO_CTA: SOLO_CTA, draw: draw };
  var bg = q.get('bg');
  if (bg === 'green' || bg === 'none') document.documentElement.classList.add(bg === 'green' ? 'vo-green' : 'vo-clear');
  if (solo !== null) {
    var one = pfs.concat(ctac ? [ctac] : []).filter(function (c) { return c.id === solo; })[0] || pfs[0], cfg = one === ctac ? SOLO_CTA : SOLO;
    pfs.forEach(function (c) { if (c !== one) c.el.remove(); });
    [forEl, one === ctac ? one.el.querySelector('form') : ctaEl, root.querySelector('.vo-ui')].forEach(function (el) { if (el) el.remove(); });
    pfs = [one];
    if (one === ctac) { ctac = null; one.live = 0; } else { one.live = 0; one.removed = SOLO.wipe; one.out = SOLO.end; one.tap = TAP; }
    root.classList.add('vo-solo');
    if (video) { video.pause(); video.removeAttribute('src'); video.remove(); }
    var state = q.get('state'), at = state && /^(live|removed|step[123])$/.test(state) ? cfg[state] : undefined, t0 = null, held = null;
    // seek(t) stops the clock and draws exactly t (the frame renderer calls it once per frame)
    api.seek = function (t) { held = t; draw(t); };
    if (typeof at === 'number') api.seek(at);
    else {
      var tick = function (now) {
        if (held !== null) return;
        if (t0 === null) t0 = now;
        var t = Math.min(cfg.end, (now - t0) / 1000);
        draw(t);
        if (t < cfg.end) requestAnimationFrame(tick);
      };
      draw(0);
      requestAnimationFrame(tick);
    }
    window.VideoOverlays = api;
    return;
  }
  var gesture = function () { return !navigator.userActivation || navigator.userActivation.hasBeenActive; };

  // ---------- the name, spoken (named only): data-cue-say-start and data-cue-say, each once per playback ----------
  var says = [{ at: sayStart, done: false }, { at: sayEnd, done: false }], ducked = null, SPEECH = 'speechSynthesis' in window;
  function unduck() { if (ducked !== null) { video.volume = ducked; ducked = null; } }
  function hush() { if (SPEECH && ducked !== null) window.speechSynthesis.cancel(); unduck(); }
  function speak(t) {   // from the play loop / ended only, so never before the user's play gesture
    if (!who || !SPEECH || !gesture()) return;
    says.forEach(function (s) {
      var at = s.at();
      if (s.done || !isFinite(at) || t < at || t > at + 2 || ducked !== null) return;
      s.done = true;
      var u = new SpeechSynthesisUtterance(who);
      u.lang = document.documentElement.lang || 'en';
      u.rate = 0.95;
      u.onend = u.onerror = unduck;
      ducked = video.volume;
      video.volume = Math.min(ducked, 0.25);
      window.speechSynthesis.speak(u);
    });
  }

  // ---------- sound effects (synthesized, no files): pop at live, whoosh + thud at removed ----------
  var AC = window.AudioContext || window.webkitAudioContext, SFX = q.get('sfx') !== '0' && !!AC, actx = null, lastT = null, VOL = 0.14;
  function audio() {
    if (!SFX) return null;
    if (!actx) { try { actx = new AC(); } catch (e) { SFX = false; return null; } }
    if (actx.state === 'suspended') actx.resume().catch(function () {});
    return actx;
  }
  function tone(ac, f0, f1, at, dur, vol) {
    var o = ac.createOscillator(), g = ac.createGain();
    o.type = 'sine';
    o.frequency.setValueAtTime(f0, at);
    o.frequency.exponentialRampToValueAtTime(f1, at + dur);
    g.gain.setValueAtTime(vol * VOL, at);
    g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
    o.connect(g).connect(ac.destination);
    o.start(at);
    o.stop(at + dur + 0.02);
  }
  function whoosh(ac, at) {
    var n = Math.round(ac.sampleRate * 0.3), buf = ac.createBuffer(1, n, ac.sampleRate), d = buf.getChannelData(0), seed = 7;
    for (var i = 0; i < n; i++) { seed = (seed * 16807) % 2147483647; d[i] = seed / 1073741823.5 - 1; }
    var src = ac.createBufferSource(), f = ac.createBiquadFilter(), g = ac.createGain();
    src.buffer = buf;
    f.type = 'bandpass';
    f.Q.value = 0.9;
    f.frequency.setValueAtTime(350, at);
    f.frequency.exponentialRampToValueAtTime(2600, at + 0.2);
    g.gain.setValueAtTime(0.0001, at);
    g.gain.exponentialRampToValueAtTime(0.8 * VOL, at + 0.12);
    g.gain.exponentialRampToValueAtTime(0.0001, at + 0.3);
    src.connect(f).connect(g).connect(ac.destination);
    src.start(at);
  }
  var SOUND = { pop: function (ac) { tone(ac, 900, 300, ac.currentTime, 0.12, 1); },
    snap: function (ac) { var t = ac.currentTime; whoosh(ac, t); tone(ac, 150, 45, t + 0.22, 0.3, 1.4); } };
  function sounds(t) {   // a cue crossed during continuous playback (not by a seek)
    var p = lastT;
    lastT = t;
    if (p === null || !(t > p) || t - p > 0.5 || !SFX || !gesture()) return;
    pfs.forEach(function (c) {
      ['live', 'removed'].forEach(function (k) {
        var ac = p < c[k] && c[k] <= t && audio();
        if (ac) SOUND[k === 'live' ? 'pop' : 'snap'](ac);
      });
    });
  }

  var post = null;   // the post-roll clock: after the take ends, cta-steps keeps looping (the take may end ~2 s after its cue)
  function postroll(now) { if (post === null || !video.ended || !ctac) { post = null; return; } draw(video.currentTime + (now - post) / 1000); requestAnimationFrame(postroll); }
  video.addEventListener('play', function () { post = null; if (gesture()) audio(); lastT = video.currentTime; });
  video.addEventListener('pause', function () { if (!video.ended) hush(); });
  video.addEventListener('seeking', function () {
    hush();
    lastT = null;
    post = null;
    endT = Infinity;
    says.forEach(function (s) { if (video.currentTime < s.at()) s.done = false; });
  });
  video.addEventListener('ended', function () {
    endT = video.currentTime - IN; draw(video.currentTime); speak(video.currentTime);
    if (ctac && post === null) { post = performance.now(); requestAnimationFrame(postroll); }
  });   // a say / card cue past the end: now, fully popped in

  var looping = false;
  function loop() { var t = video.currentTime; draw(t); speak(t); sounds(t); sync(); if (!video.paused && !video.ended) requestAnimationFrame(loop); else looping = false; }
  function kick() { if (!looping) { looping = true; requestAnimationFrame(loop); } }
  video.addEventListener('play', kick);
  ['seeked', 'timeupdate', 'loadeddata', 'pause'].forEach(function (ev) { video.addEventListener(ev, function () { draw(video.currentTime); }); });
  api.seek = function (t) { video.currentTime = t; draw(t); };
  var t = parseFloat(q.get('t'));
  if (isFinite(t) && t >= 0 && t <= 3600) {
    seekTo = t;
    draw(t);
    var go = function () { video.currentTime = t; };
    if (video.readyState >= 1) go(); else video.addEventListener('loadedmetadata', go, { once: true });
  } else draw(0);
  // ---------- player UI: full screen / theater, touch play bar, hint ----------
  var html = document.documentElement, ui = root.querySelector('.vo-ui'), fsBtn = ui && ui.querySelector('.vo-fs'), hintBtn = ui && ui.querySelector('.vo-hint');
  var pp = ui && ui.querySelector('.vo-pp'), seekEl = ui && ui.querySelector('.vo-seek'), touch = !!(window.matchMedia && matchMedia('(pointer: coarse)').matches);
  var pushed = false, hintT = null, dragging = false, started = false, full = function () { return html.getAttribute('data-vo-full'); };
  if (touch) { html.setAttribute('data-vo-touch', ''); video.controls = false; }
  function sync() {
    if (!video.paused && !video.ended) html.setAttribute('data-vo-playing', ''); else html.removeAttribute('data-vo-playing');
    if (pp) pp.setAttribute('aria-label', video.paused ? 'Play' : 'Pause');
    if (seekEl && !dragging && video.duration) seekEl.value = String(Math.round(video.currentTime / video.duration * 1000));
    if (fsBtn) fsBtn.setAttribute('aria-label', full() ? 'Close full screen' : 'Full screen');
  }
  function hint(on) { clearTimeout(hintT); if (on) { html.setAttribute('data-vo-hint', ''); hintT = setTimeout(hint, 6000, false); } else html.removeAttribute('data-vo-hint'); }
  function theater(on, popped) {
    if (on) { html.setAttribute('data-vo-full', 'theater'); history.pushState({ voTheater: 1 }, ''); pushed = true; }
    else if (full() === 'theater') { html.removeAttribute('data-vo-full'); if (pushed && !popped) history.back(); pushed = false; }
    sync();
  }
  function enter() {
    hint(false);
    if (stage.requestFullscreen && document.fullscreenEnabled) {
      stage.requestFullscreen({ navigationUI: 'hide' }).then(function () {
        var o = screen.orientation;
        if (o && o.lock) o.lock('landscape').catch(function () { /* desktop: no lock */ });
      }, function () { theater(true); });
    } else if (stage.webkitRequestFullscreen && document.webkitFullscreenEnabled) stage.webkitRequestFullscreen();
    else theater(true);   // iPhone Safari: no element full screen
  }
  function leave() {
    if (full() === 'theater') theater(false);
    else if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(function () {});
    else if (document.webkitFullscreenElement && document.webkitExitFullscreen) document.webkitExitFullscreen();
  }
  function onFs() {
    if ((document.fullscreenElement || document.webkitFullscreenElement) === stage) html.setAttribute('data-vo-full', 'fs');
    else if (full() === 'fs') { html.removeAttribute('data-vo-full'); try { screen.orientation.unlock(); } catch (e) { /* none */ } }
    sync();
  }
  function toggle() {
    if (!video.paused && !video.ended) { video.pause(); return; }
    video.play().catch(function () {});
    if (!started && touch && !full()) hint(true);
    started = true;
  }
  var own = function (f) { return function (e) { e.stopPropagation(); f(); }; };
  if (fsBtn) fsBtn.addEventListener('click', own(function () { if (full()) leave(); else enter(); }));
  if (hintBtn) hintBtn.addEventListener('click', own(enter));
  if (pp) pp.addEventListener('click', own(toggle));
  if (seekEl) {
    seekEl.addEventListener('pointerdown', function () { dragging = true; });
    ['pointerup', 'pointercancel', 'change'].forEach(function (ev) { seekEl.addEventListener(ev, function () { dragging = false; }); });
    seekEl.addEventListener('input', function () { if (video.duration) video.currentTime = seekEl.value / 1000 * video.duration; });
  }
  stage.addEventListener('click', function (e) {   // touch: a tap on the stage plays / pauses (not on the controls / the form)
    if (touch && !e.target.closest('button, input, form, a, .vo-ctl')) toggle();
  });
  document.addEventListener('fullscreenchange', onFs);
  document.addEventListener('webkitfullscreenchange', onFs);
  window.addEventListener('popstate', function () { theater(false, true); });
  if (form) form.querySelector('input').addEventListener('focus', function () { theater(false); });   // the keyboard comes up upright
  ['play', 'pause', 'ended', 'seeked', 'timeupdate', 'loadedmetadata'].forEach(function (ev) { video.addEventListener(ev, sync); });
  sync();
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && full() === 'theater') { theater(false); return; }
    if (e.key !== ' ' || e.target === video || /^(BUTTON|INPUT|TEXTAREA|SELECT|A)$/.test(e.target.tagName)) return;
    e.preventDefault();
    if (video.paused) video.play().catch(function () { /* autoplay policy: needs a click first */ }); else video.pause();
  });
  window.VideoOverlays = api;
})();
