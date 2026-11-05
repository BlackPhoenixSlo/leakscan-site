// site/video/: overlay prefabs (Google, Google Images, X, Reddit, Mega) in the bottom-right corner, driven by the face video's currentTime. Cues are the
// data-cue-live / -removed / -out seconds on each .vo-pf (site/video/CUES.md). draw(t) is a pure function of t (no CSS
// transitions), so seeking, ?t= and frame-by-frame capture (tools/video/render_prefabs.py) all show the exact frame.
// URL: ?name=<1-40 letters/digits/space . - _> (else the shared scan result: ?r= or the last scan, like #removals)
//      ?t=<sec> seek · ?prefab=google|google-images|x|reddit|mega&state=live|removed&bg=green|none: one prefab, no video.
// Each prefab: slides in from the right (live cue, 0.4 s, slight overshoot), wipe to removed (removed cue, 1.2 s) +
// "Removed" stamp, slides out down / right (0.4 s, gone at the out cue). google-images also taps "Images" 0.6 s after
// live and swaps the results for the image grid by live + 1.2 s (derived from live: no extra cue).
// Scan result (?r= / last scan): texts AND the .rm-img photos (its thumbs via /api/thumb, blurred by removals.css), as #removals.
// data-cue-say on .vo-stage: with a personalized name (?name= / scan result, never the default) the browser says it once
// per playback (speechSynthesis, after the user's play gesture; video ducked to 0.25 meanwhile; cancelled on pause / seek)
// and a "for <name>" pill slides into the same corner for 2 s (also reads where there is no voice).
// Keys: space = play / pause. textContent only; no requests except the scan-result read (js/scan-engine.js).
(function () {
  'use strict';
  var root = document.getElementById('vo');
  if (!root) return;
  var IN = 0.4, OUT = 0.4, WIPE = 1.2, STAMP = 0.35, SLIDE = 160;   // seconds: slide in, slide out, compare wipe, stamp pop; px
  var TAP = 0.6, SWAP = 0.9;                                          // google-images: tap at live + 0.6 (0.4 s), grid at live + 0.9 (0.3 s)
  // ?prefab= timeline = the CapCut clip: in 0-0.4, wipe at 2.4, stamp 3.6, out 5.6-6; state=live / removed = these stills
  var SOLO = { wipe: 2.4, end: 6, live: 1.6, removed: 5.4 };
  var q = new URLSearchParams(location.search);
  var video = root.querySelector('.vo-video'), over = root.querySelector('.vo-over'), stage = root.querySelector('.vo-stage');
  var forEl = root.querySelector('.vo-for'), forc = null, who = null;   // the "for <name>" pill; who = the personalized name
  var pfs = Array.prototype.map.call(root.querySelectorAll('.vo-pf[data-prefab]'), function (el) {
    return { el: el, id: el.getAttribute('data-prefab'), live: +el.getAttribute('data-cue-live'),
      removed: +el.getAttribute('data-cue-removed'), out: +el.getAttribute('data-cue-out') };
  });

  var clamp = function (x) { return x < 0 ? 0 : x > 1 ? 1 : x; };
  var ease = function (x) { return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
  var back = function (x) { var c = 1.2, d = x - 1; return 1 + (c + 1) * d * d * d + c * d * d; };   // ease-out with a slight overshoot
  var sayAt = function () { return parseFloat(stage.getAttribute('data-cue-say')); };   // read live: CUES.md retimes it
  function draw(t) {
    if (forc && !root.classList.contains('vo-solo')) { forc.live = sayAt(); forc.out = forc.live + 2; }
    pfs.concat(forc && isFinite(forc.live) && !root.classList.contains('vo-solo') ? [forc] : []).forEach(function (c) {
      var a = clamp((t - c.live) / IN), b = clamp((t - (c.out - OUT)) / OUT), o = Math.min(clamp(a * 1.5), 1 - b);
      var w = ease(clamp((t - c.removed) / WIPE)), s = ease(clamp((t - c.removed - WIPE) / STAMP)), st = c.el.style;
      if (o <= 0) { c.el.setAttribute('data-off', ''); return; }
      c.el.removeAttribute('data-off');
      st.setProperty('--o', o.toFixed(3));
      st.setProperty('--x', ((1 - back(a)) * SLIDE + b * b * 70).toFixed(2));
      st.setProperty('--y', (b * b * 110).toFixed(2));
      st.setProperty('--tap', clamp((t - c.live - TAP) / 0.4).toFixed(3));
      st.setProperty('--g', ease(clamp((t - c.live - SWAP) / 0.3)).toFixed(3));
      st.setProperty('--p', (100 - w * 100).toFixed(2));
      st.setProperty('--w', w.toFixed(3));
      st.setProperty('--h', Math.min(1, 6 * Math.min(w, 1 - w)).toFixed(3));
      st.setProperty('--s', s.toFixed(3));
    });
    document.documentElement.setAttribute('data-vo-t', t.toFixed(2));
  }
  function fit() { root.querySelector('.vo-box').style.setProperty('--k', (over.clientWidth / 520).toFixed(4)); }
  fit();
  if (window.ResizeObserver) new ResizeObserver(fit).observe(over); else window.addEventListener('resize', fit);

  // ---------- personalization: values for the [data-vo] slots ----------
  var NAME_RE = /^[\p{L}\p{N} ._-]{1,40}$/u;
  function fill(v) {
    Array.prototype.forEach.call(root.querySelectorAll('[data-vo]'), function (el) {
      var k = el.getAttribute('data-vo');
      if (typeof v[k] === 'string' && el.textContent !== v[k]) el.textContent = v[k];
    });
  }
  function values(m) {   // m = LeakScanRemovals.model(result), or {name} from ?name=
    var name = m.name, h = (m.handle || name).toLowerCase().replace(/[^a-z0-9_.]/g, '') || 'creator';
    var v = { name: name, handle: h, 'mega-title': m.mtitle || name + ' \u2013 pack', 'x-l1': m.xtext || name + ' leaked', 'x-l2': m.xtext ? '' : name + ' ' + (m.plat || 'onlyfans'),
      sub: m.sub || 'r/' + (h.replace(/\./g, '').slice(0, 14) || 'creator') + '_leaks', 'rd-title': m.rtitle || name + ' full pack, link in comments' };
    if (m.xat) { v['x-at'] = m.xat; v['x-name'] = m.xat.slice(1); v['x-av'] = m.xat.charAt(1).toUpperCase(); }
    if (m.mmeta) v['mega-meta'] = m.mmeta;
    if (m.mvid != null) v['mega-vid'] = m.mvid + ' files';
    if (m.mimg != null) v['mega-img'] = m.mimg + ' files';
    if (m.host) v.host = m.host;
    return v;
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
  function personal(n) { who = n; if (forEl) forc = { el: forEl, removed: Infinity }; }
  var name = q.get('name');
  name = name === null ? null : name.replace(/\s+/g, ' ').trim();
  if (name && NAME_RE.test(name)) { fill(values({ name: name })); personal(name); }
  else {   // the shared scan result, same slug rule as js/removals.js (?r= → last scan → none = demo defaults)
    var E = window.LeakScanEngine, R = window.LeakScanRemovals, slug = q.get('r');
    if (slug === null) { try { slug = (JSON.parse(localStorage.getItem('leakscan.last') || 'null') || {}).slug; } catch (e) { slug = null; } }
    if (E && E.fetchResult && R && typeof slug === 'string' && E.SLUG_RE.test(slug)) {
      E.fetchResult(slug).then(function (raw) { var m = R.model(raw); if (m) { fill(values(m)); thumbs(m.thumbs); personal(m.name); } }, function () { /* defaults */ });
    }
  }

  // ---------- clock ----------
  var solo = q.get('prefab'), api = { prefabs: pfs.map(function (c) { return c.id; }), SOLO: SOLO, draw: draw };
  var bg = q.get('bg');
  if (bg === 'green' || bg === 'none') document.documentElement.classList.add(bg === 'green' ? 'vo-green' : 'vo-clear');
  if (solo !== null) {
    var one = pfs.filter(function (c) { return c.id === solo; })[0] || pfs[0];
    pfs.forEach(function (c) { if (c !== one) c.el.remove(); });
    if (forEl) forEl.remove();
    pfs = [one];
    one.live = 0; one.removed = SOLO.wipe; one.out = SOLO.end;
    root.classList.add('vo-solo');
    if (video) { video.pause(); video.removeAttribute('src'); video.remove(); }
    var state = q.get('state'), t0 = null, held = null;
    // seek(t) stops the clock and draws exactly t (the frame renderer calls it once per frame)
    api.seek = function (t) { held = t; draw(t); };
    if (state === 'live') api.seek(SOLO.live);
    else if (state === 'removed') api.seek(SOLO.removed);
    else {
      var tick = function (now) {
        if (held !== null) return;
        if (t0 === null) t0 = now;
        var t = Math.min(SOLO.end, (now - t0) / 1000);
        draw(t);
        if (t < SOLO.end) requestAnimationFrame(tick);
      };
      draw(0);
      requestAnimationFrame(tick);
    }
    window.VideoOverlays = api;
    return;
  }
  // ---------- the name, spoken (data-cue-say) ----------
  var said = false, ducked = null, SPEECH = 'speechSynthesis' in window;
  function unduck() { if (ducked !== null) { video.volume = ducked; ducked = null; } }
  function hush() { if (SPEECH && ducked !== null) window.speechSynthesis.cancel(); unduck(); }
  function speak(t) {   // from the play loop only, so never before the user's play gesture
    var at = sayAt();
    if (said || !who || !SPEECH || !isFinite(at) || t < at || t > at + 2) return;
    if (navigator.userActivation && !navigator.userActivation.hasBeenActive) return;
    said = true;
    var u = new SpeechSynthesisUtterance(who);
    u.lang = document.documentElement.lang || 'en';
    u.rate = 0.95;
    u.onend = u.onerror = unduck;
    ducked = video.volume;
    video.volume = Math.min(ducked, 0.25);
    window.speechSynthesis.speak(u);
  }
  video.addEventListener('pause', function () { if (!video.ended) hush(); });
  video.addEventListener('seeking', function () { hush(); if (video.currentTime < sayAt()) said = false; });

  var looping = false;
  function loop() { draw(video.currentTime); speak(video.currentTime); if (!video.paused && !video.ended) requestAnimationFrame(loop); else looping = false; }
  function kick() { if (!looping) { looping = true; requestAnimationFrame(loop); } }
  video.addEventListener('play', kick);
  ['seeked', 'timeupdate', 'loadeddata', 'pause'].forEach(function (ev) { video.addEventListener(ev, function () { draw(video.currentTime); }); });
  api.seek = function (t) { video.currentTime = t; draw(t); };
  var t = parseFloat(q.get('t'));
  if (isFinite(t) && t >= 0 && t <= 3600) {
    draw(t);
    var go = function () { video.currentTime = t; };
    if (video.readyState >= 1) go(); else video.addEventListener('loadedmetadata', go, { once: true });
  } else draw(0);
  document.addEventListener('keydown', function (e) {
    if (e.key !== ' ' || e.target === video || /^(BUTTON|INPUT|TEXTAREA|SELECT|A)$/.test(e.target.tagName)) return;
    e.preventDefault();
    if (video.paused) video.play().catch(function () { /* autoplay policy: needs a click first */ }); else video.pause();
  });
  window.VideoOverlays = api;
})();
