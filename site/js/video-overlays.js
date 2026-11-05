// site/video/: overlay prefabs (Google, X, Reddit, Mega) driven by the face video's currentTime. Cues are the
// data-cue-live / -removed / -out seconds on each .vo-pf (site/video/CUES.md). draw(t) is a pure function of t (no CSS
// transitions), so seeking, ?t= and frame-by-frame capture (tools/video/render_prefabs.py) all show the exact frame.
// URL: ?name=<1-40 letters/digits/space . - _> (else the shared scan result: ?r= or the last scan, like #removals)
//      ?t=<sec> seek · ?prefab=google|x|reddit|mega&state=live|removed&bg=green|none: one prefab, no video.
// Keys: space = play / pause. textContent only; no requests except the scan-result read (js/scan-engine.js).
(function () {
  'use strict';
  var root = document.getElementById('vo');
  if (!root) return;
  var IN = 0.45, OUT = 0.35, WIPE = 1.2, STAMP = 0.35;          // seconds: fade in, fade out, compare wipe, stamp pop
  var SOLO = { live: -IN, removed: 2.4, end: 6 };                // ?prefab= timeline: fully in at 0 (CapCut adds fades), wipe at 2.4, hold to 6
  var q = new URLSearchParams(location.search);
  var video = root.querySelector('.vo-video'), over = root.querySelector('.vo-over');
  var pfs = Array.prototype.map.call(root.querySelectorAll('.vo-pf'), function (el) {
    return { el: el, id: el.getAttribute('data-prefab'), live: +el.getAttribute('data-cue-live'),
      removed: +el.getAttribute('data-cue-removed'), out: +el.getAttribute('data-cue-out') };
  });

  var clamp = function (x) { return x < 0 ? 0 : x > 1 ? 1 : x; };
  var ease = function (x) { return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
  function draw(t) {
    pfs.forEach(function (c) {
      var inn = clamp((t - c.live) / IN), o = Math.min(inn, 1 - clamp((t - (c.out - OUT)) / OUT));
      var w = ease(clamp((t - c.removed) / WIPE)), s = ease(clamp((t - c.removed - WIPE) / STAMP)), st = c.el.style;
      if (o <= 0) { c.el.setAttribute('data-off', ''); return; }
      c.el.removeAttribute('data-off');
      st.setProperty('--o', o.toFixed(3));
      st.setProperty('--y', ((1 - ease(inn)) * 24).toFixed(2));
      st.setProperty('--p', (100 - w * 100).toFixed(2));
      st.setProperty('--w', w.toFixed(3));
      st.setProperty('--h', Math.min(1, 6 * Math.min(w, 1 - w)).toFixed(3));
      st.setProperty('--s', s.toFixed(3));
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
  var name = q.get('name');
  name = name === null ? null : name.replace(/\s+/g, ' ').trim();
  if (name && NAME_RE.test(name)) fill(values({ name: name }));
  else {   // the shared scan result, same slug rule as js/removals.js (?r= → last scan → none = demo defaults)
    var E = window.LeakScanEngine, R = window.LeakScanRemovals, slug = q.get('r');
    if (slug === null) { try { slug = (JSON.parse(localStorage.getItem('leakscan.last') || 'null') || {}).slug; } catch (e) { slug = null; } }
    if (E && E.fetchResult && R && typeof slug === 'string' && E.SLUG_RE.test(slug)) {
      E.fetchResult(slug).then(function (raw) { var m = R.model(raw); if (m) fill(values(m)); }, function () { /* defaults */ });
    }
  }

  // ---------- clock ----------
  var solo = q.get('prefab'), api = { prefabs: pfs.map(function (c) { return c.id; }), SOLO: SOLO, draw: draw };
  var bg = q.get('bg');
  if (bg === 'green' || bg === 'none') document.documentElement.classList.add(bg === 'green' ? 'vo-green' : 'vo-clear');
  if (solo !== null) {
    var one = pfs.filter(function (c) { return c.id === solo; })[0] || pfs[0];
    pfs.forEach(function (c) { if (c !== one) c.el.remove(); });
    pfs = [one];
    one.live = SOLO.live; one.removed = SOLO.removed; one.out = Infinity;
    root.classList.add('vo-solo');
    if (video) { video.pause(); video.removeAttribute('src'); video.remove(); }
    var state = q.get('state'), t0 = null, held = null;
    // seek(t) stops the clock and draws exactly t (the frame renderer calls it once per frame)
    api.seek = function (t) { held = t; draw(t); };
    if (state === 'live') api.seek(0);
    else if (state === 'removed') api.seek(SOLO.end);
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
  var looping = false;
  function loop() { draw(video.currentTime); if (!video.paused && !video.ended) requestAnimationFrame(loop); else looping = false; }
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
