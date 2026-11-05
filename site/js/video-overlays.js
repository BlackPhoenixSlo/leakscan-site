// site/video/: overlay prefabs (Google, Google Images, X, Reddit, Mega) on the right half (Jack is on the left), driven by the face video's currentTime. Cues are the
// data-cue-live / -removed / -out seconds on each .vo-pf (site/video/CUES.md, SCRIPT.md). draw(t) is a pure function of t (no CSS
// transitions), so seeking, ?t= and frame-by-frame capture (tools/video/render_prefabs.py) all show the exact frame.
// URL: ?name=<1-40 letters/digits/space . - _> (else the shared scan result: ?r= or the last scan, like #removals)
//      ?t=<sec> seek · ?sfx=0 no sound · ?prefab=google|google-images|x|reddit|mega&state=live|removed&bg=green|none: one prefab, no video
//      (?prefab=cta-steps&state=step1|step2|step3: the generic end card's phone take, 10 s, no form: the 6th CapCut clip).
// Two modes (html[data-vo-mode]): "named" (?name= or a scan result: her texts, the name spoken, "for <name>" pill: 2 s at
// data-cue-say-start, from data-cue-say on it stays to the end + after it; the jack-named.mp4 take if the server has it) and
// "generic" (texts say "Your name", default blurred thumbs, no speech, at data-cue-cta (default data-cue-say) the "Type your
// name" card = cta-steps: a phone replica of the landing, one 10 s take: the camera zooms onto the onlyfans.com/ field,
// types "Jaka Basej" as a handle (or the viewer's typed name), "Scan now" → the scan card "Searching Google, step N of 9…"
// → the report "87 links found" + tabs + placeholder rows → "Rewatch this video with YOUR content" + the name flip, kept
// looping after the video ends). Name bar (.vo-nb, under the stage; full screen / theater: the .vo-nb-pill opens it) + the end
// card's form = rebuild(): in place, no reload, no interstitial: pop, named mode + texts, ?name= via history.replaceState,
// the take (jack-named.mp4 if the server has it) restarts from 0, playing (the submit is the gesture). Reset = generic again.
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
  // cta-steps: one 10 s take (s into its loop) in a phone replica of the landing: the hero, the camera zooms onto the
  // onlyfans.com/ field, types the name as a handle (DEMO, or what the viewer typed in the form), "Scan now"; the scan card
  // ("Searching <place>, step N of 9…", js/scan-engine.js progressInfo); the report card (LEAKS links rolling, tabs, rows)
  // + "Rewatch this video with YOUR content" with the name flip. SCENES = [in, out] per scene (0.2 s fades; the hero fades
  // back in over the loop's last 0.2 s)
  var CYCLE = 10, DEMO = 'Jaka Basej', LEAKS = 87, NSTEP = 9, SCENES = [[0, 4.1], [4.1, 6.8], [6.8, 9.8]];
  var WHERE = ['Google', 'Google Images', 'X', 'Reddit', 'Mega'];
  var SOLO_CTA = { end: 10, step1: 3.05, step2: 5.6, step3: 9.65 };   // ?prefab=cta-steps: clip length, state= stills
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
  function demoName() {   // what the hero types: the form's name once the viewer typed a valid one, else the demo name
    var inp = ctaEl && ctaEl.querySelector('input'), v = inp ? inp.value.replace(/\s+/g, ' ').trim() : '';
    return v && NAME_RE.test(v) ? v : DEMO;
  }
  var handle = function (n) { return n.toLowerCase().replace(/[^\p{L}\p{N}._]/gu, '') || 'creator'; };   // "Jaka Basej" → jakabasej
  var RM = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)');
  function lay(el, pg) {   // el's layout box in its page's px (offsets up to the .vo-pg, untransformed)
    var x = 0, y = 0, w = el.offsetWidth, h = el.offsetHeight;
    for (; el && el !== pg; el = el.offsetParent) { x += el.offsetLeft; y += el.offsetTop; }
    return { x: x, y: y, w: w, h: h };
  }
  function camera(pg, keys, u) {   // keys: [s, [focus x, focus y, scale]] eased between; reduced motion = cuts at the midpoints
    var i = 0, f;
    while (i < keys.length - 1 && u >= keys[i + 1][0]) i++;
    if (i === keys.length - 1 || u < keys[0][0]) f = keys[u < keys[0][0] ? 0 : i][1];
    else {
      var a = keys[i], b = keys[i + 1], w = clamp((u - a[0]) / (b[0] - a[0]));
      w = RM && RM.matches ? (w < 0.5 ? 0 : 1) : ease(w);
      f = [0, 1, 2].map(function (k) { return a[1][k] + (b[1][k] - a[1][k]) * w; });
    }
    var sc = pg.parentNode.parentNode, W = sc.clientWidth, H = sc.clientHeight, T = f[2], pw = pg.offsetWidth * T, ph = pg.offsetHeight * T;
    var x = pw <= W ? (W - pw) / 2 : Math.min(0, Math.max(W - pw, W / 2 - f[0] * T)), y = Math.min(0, Math.max(Math.min(0, H - ph), H / 2 - f[1] * T));
    pg.style.setProperty('--cx', x.toFixed(1));
    pg.style.setProperty('--cy', y.toFixed(1));
    pg.style.setProperty('--cz', T.toFixed(4));
  }
  function steps(c, t) {   // cta-steps at t: u = seconds into its loop (from the card's live cue, = the clip's 0 s)
    var box = c.steps, u = Math.max(0, t - c.live) % CYCLE, name = demoName(), h = handle(name), bs = box.style, q1 = function (s) { return box.querySelector(s); };
    var sc = box.querySelectorAll('.vo-step'), pgs = box.querySelectorAll('.vo-pg'), W = q1('.vo-scr').clientWidth, T0 = W / 390;
    Array.prototype.forEach.call(sc, function (el, i) {
      var a = u - SCENES[i][0], d = SCENES[i][1] - SCENES[i][0], o = i === 0 && u >= SCENES[2][1] ? clamp((u - SCENES[2][1]) / 0.2) : a >= 0 && a < d + 0.2 ? Math.min(i ? clamp(a / 0.2) : 1, clamp((d + 0.2 - a) / 0.2)) : 0;
      el.style.setProperty('--so', o.toFixed(3));
    });
    // 1 the hero: rest → zoom onto the field (caret kept in view) → type → pull back to "Scan now" → press
    var n = Math.round(clamp((u - 1.4) / 1.6) * h.length), typed = h.slice(0, n), pg = pgs[0], fld = lay(q1('.vo-mi'), pg);
    setText(q1('.vo-mi-t'), typed);
    var car = lay(q1('.vo-mi-c'), pg), btn = lay(q1('.vo-mbtn'), pg), TZ = 2.25, vw = W / TZ;
    var rest = [195, 0, T0], field = [Math.max(fld.x + vw / 2 - 10, car.x + 34 - vw / 2), fld.y + fld.h / 2, TZ], press = [195, (fld.y + btn.y + btn.h) / 2, T0];
    camera(pg, u >= SCENES[2][1] ? [[0, rest]] : [[0.6, rest], [1.4, field], [3.1, field], [3.5, press]], u);
    bs.setProperty('--foc', u > 1.2 && u < 3.6 ? '1' : '0');
    bs.setProperty('--caret', u > 1.2 && u < 3.5 && (n < h.length || Math.floor(u * 2.5) % 2 === 0) ? '1' : '0');
    bs.setProperty('--press', bump((u - 3.55) / 0.4).toFixed(3));
    // 2 the scan card: "Searching <place>, step N of 9…", the bar, shimmering skeleton rows
    var p = 1 - Math.pow(1 - clamp((u - 4.4) / 2.2), 2), k = Math.max(1, Math.ceil(p * NSTEP));
    Array.prototype.forEach.call(box.querySelectorAll('.vo-at'), function (el) { setText(el, '@' + h); });
    var card = lay(pgs[1].querySelector('.vo-card'), pgs[1]), top = function (T) { return [card.x - 6 + W / T / 2, card.y - 8 + q1('.vo-scr').clientHeight / T / 2, T]; };
    camera(pgs[1], [[4.1, top(1.3)], [6.8, top(1.42)]], u);
    setText(q1('.vo-ms'), p >= 1 ? 'Done: ' + NSTEP + ' of ' + NSTEP + ' steps' : 'Searching ' + WHERE[Math.min(WHERE.length - 1, Math.floor(p * WHERE.length))] + ', step ' + k + ' of ' + NSTEP + '…');
    bs.setProperty('--bar', p.toFixed(3));
    bs.setProperty('--shim', (1 - (u * 0.8) % 1).toFixed(3));
    // 3 the report card: zoom onto "N links found" while it rolls to LEAKS, pull back over the tabs + rows; the end toast + flip
    var chip = lay(q1('.vo-mc'), pgs[2]), m = Math.round(LEAKS * (1 - Math.pow(1 - clamp((u - 7.2) / 0.75), 3))), f = clamp((u - 9.05) / 0.25);
    camera(pgs[2], [[7, top(1.42)], [7.5, [chip.x + chip.w / 2, chip.y + chip.h / 2 - 16, 2.4]], [8.1, [chip.x + chip.w / 2, chip.y + chip.h / 2 - 16, 2.4]], [8.6, top(0.8)]], u);
    setText(q1('.vo-mc-n'), String(m));
    setText(q1('.vo-mc-u'), m === 1 ? ' link found' : ' links found');
    bs.setProperty('--cp', (1 + 0.2 * bump((u - 7.95) / 0.3)).toFixed(3));
    var ttl = [' full set', ' PPV pack', '', ' video bundle', ' photo set'];
    Array.prototype.forEach.call(box.querySelectorAll('.vo-row'), function (el, i) {
      setText(el.querySelector('.vo-ttl'), i === 2 ? 'Search results for ' + h : h + ttl[i]);
      el.style.setProperty('--ro', (u < 7 ? 1 : clamp((u - 8.15 - i * 0.08) / 0.2)).toFixed(3));
    });
    var eo = u < SCENES[2][1] ? clamp((u - 8.75) / 0.3) : clamp((SCENES[2][1] + 0.2 - u) / 0.2);
    bs.setProperty('--eo', eo.toFixed(3));
    bs.setProperty('--es', (0.9 + 0.1 * back(clamp((u - 8.75) / 0.35))).toFixed(4));
    bs.setProperty('--fl', ((f < 0.5 ? f : f - 1) * 180).toFixed(1));   // 0 → 90deg, swap the text, -90 → 0
    setText(q1('.vo-mini-n'), f >= 0.5 ? name : GENERIC);
    bs.setProperty('--fp', (1 + 0.3 * bump((u - 9.3) / 0.3)).toFixed(3));
  }
  var cueAt = function (k) { return num(stage, k); };
  var sayStart = function () { return cueAt('data-cue-say-start'); };
  var sayEnd = function () { return Math.min(cueAt('data-cue-say') + shift, endT); };   // or when the video ends, if that comes first
  var ctaAt = function () { var c = cueAt('data-cue-cta'); return Math.min(isFinite(c) ? c : cueAt('data-cue-say'), endT); };
  function draw(t) {
    var cards = pfs;
    if (!root.classList.contains('vo-solo')) {
      if (forc) {   // 2 s at the start cue; from the end cue on it stays (the name at the end, also after the take ends)
        var s0 = sayStart(), s1 = sayEnd(), early = isFinite(s0) && t < s1;
        forc.live = early ? s0 : s1; forc.out = early ? s0 + 2 : Infinity; cards = cards.concat([forc]);
      }
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
  var seekTo = null, probe = null, noop = function () {};   // the pending ?t= (played-take seconds); the jack-named.mp4 HEAD
  var sources = video ? Array.prototype.slice.call(video.querySelectorAll('source')) : [];   // jack.mp4 / .webm, for Reset
  function named() {   // does the server have jack-named.mp4? (HEAD, once, named mode only) → Promise<bool>
    if (!probe) probe = solo !== null || !video || !window.fetch || !video.canPlayType('video/mp4') ? Promise.resolve(false)
      : fetch(NAMED_TAKE, { method: 'HEAD', cache: 'no-store' }).then(function (r) { return r.ok && /^video\//.test(r.headers.get('content-type') || ''); }, function () { return false; });
    return probe;
  }
  function take(on, at, go) {   // play jack-named.mp4 (on) or jack.mp4 (its <source>s) from `at`, playing if go
    if (on !== (root.getAttribute('data-vo-take') === 'named')) {
      if (on) { sources.forEach(function (s) { s.remove(); }); video.src = NAMED_TAKE; root.setAttribute('data-vo-take', 'named'); }
      else { video.removeAttribute('src'); sources.forEach(function (s) { video.appendChild(s); }); root.removeAttribute('data-vo-take'); }
      shift = on ? num(stage, 'data-cue-named-shift') || 0 : 0;
      retime();
      video.addEventListener('loadedmetadata', function () { video.currentTime = at; if (go) video.play().catch(noop); }, { once: true });
      video.load();
    } else { video.currentTime = at; if (go) video.play().catch(noop); }
    draw(at);
  }
  function mode(m) { document.documentElement.setAttribute('data-vo-mode', m); }
  var nb = root.querySelector('.vo-nb');
  function personal(n) {
    who = n;
    mode('named');
    ctac = null;   // cta-steps: generic only
    pfs = pfs.filter(function (c) { return c.el !== ctaEl; });
    if (ctaEl) ctaEl.setAttribute('data-off', '');
    if (forEl) forc = { el: forEl, removed: Infinity, tap: Infinity };
    if (nb) { nb.removeAttribute('data-edit'); setText(nb.querySelector('.vo-nb-n'), n); }
  }
  function generic() {   // back to "Your name": the end card, no pill, no speech
    who = null;
    mode('generic');
    forc = null;
    if (forEl) forEl.setAttribute('data-off', '');
    if (ctaEl) ctac = { el: ctaEl, id: 'cta-steps', out: Infinity, removed: Infinity, tap: Infinity, steps: ctaEl.querySelector('.vo-steps') };
    if (nb) nb.removeAttribute('data-edit');
  }
  // the page's own texts / photos, so a rebuild or Reset starts from them (not from a scan's)
  var slots = root.querySelectorAll('[data-vo]'), imgs = root.querySelectorAll('.rm-img');
  Array.prototype.forEach.call(slots, function (el) { el.__def = el.textContent; });
  Array.prototype.forEach.call(imgs, function (im) { im.__def = im.getAttribute('src'); });
  function apply(v) {
    Array.prototype.forEach.call(slots, function (el) { el.textContent = el.__def; if (el.classList.contains('vo-roll')) el.__src = el.__def; });
    Array.prototype.forEach.call(imgs, function (im) { if (im.getAttribute('src') !== im.__def) im.setAttribute('src', im.__def); });
    fill(v);
  }
  apply(values({ name: GENERIC }));
  generic();
  var name = q.get('name');
  name = name === null ? null : name.replace(/\s+/g, ' ').trim();
  if (name && NAME_RE.test(name)) {
    fill(values({ name: name }));
    personal(name);
    named().then(function (ok) { if (ok && who !== null) take(true, video.readyState >= 1 ? video.currentTime : seekTo || 0, !video.paused); });
  }
  else {   // the shared scan result, same slug rule as js/removals.js (?r= → last scan → none = generic)
    var E = window.LeakScanEngine, R = window.LeakScanRemovals, slug = q.get('r');
    if (slug === null) { try { slug = (JSON.parse(localStorage.getItem('leakscan.last') || 'null') || {}).slug; } catch (e) { slug = null; } }
    if (E && E.fetchResult && R && typeof slug === 'string' && E.SLUG_RE.test(slug)) {
      E.fetchResult(slug).then(function (raw) {
        var m = R.model(raw);
        if (!m || who !== null) return;   // (a name typed in meanwhile wins)
        var o = mine(raw); m.site = o.site; m.ig = o.ig; m.tt = o.tt; fill(values(m)); thumbs(m.thumbs); personal(m.name);
        if (solo === null && video) {
          draw(video.currentTime);
          named().then(function (ok) { if (ok && who === m.name) take(true, video.readyState >= 1 ? video.currentTime : seekTo || 0, !video.paused); });
        }
      }, function () { /* generic */ });
    }
  }
  var form = ctaEl && ctaEl.querySelector('form'), nbForm = nb && nb.querySelector('form');

  // ---------- clock ----------
  var api = { prefabs: pfs.map(function (c) { return c.id; }).concat(ctac ? [ctac.id] : []), SOLO: SOLO, SOLO_CTA: SOLO_CTA, draw: draw };
  var bg = q.get('bg');
  if (bg === 'green' || bg === 'none') document.documentElement.classList.add(bg === 'green' ? 'vo-green' : 'vo-clear');
  if (solo !== null) {
    var one = pfs.concat(ctac ? [ctac] : []).filter(function (c) { return c.id === solo; })[0] || pfs[0], cfg = one === ctac ? SOLO_CTA : SOLO;
    pfs.forEach(function (c) { if (c !== one) c.el.remove(); });
    [forEl, one === ctac ? one.el.querySelector('form') : ctaEl, root.querySelector('.vo-ui'), nb].forEach(function (el) { if (el) el.remove(); });
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
  // ---------- the name: bar + end card form → rebuild() in place; Change / Reset; the full screen pill ----------
  var BAD = 'Use 1-40 letters, digits, spaces or . - _', gen = 0;
  var nbInp = nbForm && nbForm.querySelector('input'), nbErr = nb && nb.querySelector('.vo-nb-err'), nbPill = ui && ui.querySelector('.vo-nb-pill');
  function restart() { says.forEach(function (s) { s.done = false; }); endT = Infinity; post = null; lastT = null; }
  function rebuild(n) {   // generic (or another name) → named for n, in place, at once; called from a submit = a user gesture
    var g = ++gen, ac = audio();
    if (ac) SOUND.pop(ac);
    apply(values({ name: n }));
    personal(n);
    history.replaceState(history.state, '', location.pathname + '?name=' + encodeURIComponent(n));
    restart();
    take(root.getAttribute('data-vo-take') === 'named', 0, true);   // now, inside the gesture (iOS)
    named().then(function (ok) { if (ok && g === gen && who === n && root.getAttribute('data-vo-take') !== 'named') { restart(); take(true, 0, true); } });
  }
  function reset() {
    gen++;
    apply(values({ name: GENERIC }));
    generic();
    if (nbInp) nbInp.value = '';
    history.replaceState(history.state, '', location.pathname);
    restart();
    take(false, 0, true);
  }
  function onName(f, err) {   // the bar (inline message) and the end card's form (the browser's bubble) share the submit
    if (!f) return;
    var inp = f.querySelector('input'), say = function (m) { inp.setCustomValidity(m); inp.setAttribute('aria-invalid', m ? 'true' : 'false'); if (err) { err.textContent = m; err.hidden = !m; } };
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var n = inp.value.replace(/\s+/g, ' ').trim();
      if (!NAME_RE.test(n)) { say(BAD); if (err) inp.focus(); else inp.reportValidity(); return; }
      say('');
      inp.blur();
      rebuild(n);
    });
    inp.addEventListener('input', function () { say(''); });
    inp.addEventListener('focus', function () { theater(false); html.setAttribute('data-vo-nb-seen', ''); });   // the keyboard comes up upright
  }
  onName(nbForm, nbErr);
  onName(form, null);
  var edit = function () { if (!nb) return; if (who) { nb.setAttribute('data-edit', ''); nbInp.value = who; } nbInp.focus(); nbInp.select(); };
  if (nb) nb.querySelector('.vo-nb-chg').addEventListener('click', edit);
  if (nb) nb.querySelector('.vo-nb-rst').addEventListener('click', reset);
  if (nbPill) nbPill.addEventListener('click', own(function () { leave(); setTimeout(edit, 60); }));
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
