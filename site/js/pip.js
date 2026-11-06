// Floating mini player of site/video/ (picture-in-picture style). Off unless ?pip=1, or the script tag has
// data-pip-auto="r" and the page URL has ?r=<slug> (the scan report: the video personalizes itself with that scan).
// ?pip=0 = off. Same-origin iframe of ../video/ (?r= / ?name= passed through) in embed form: this script injects a style
// into it (no name bar, no player UI: the stage fills the frame) and drives its <video> (starts muted, tap = unmute,
// then play / pause). The iframe is created only after the page's load, then the first scroll / pointer / key or idle; the player is fixed, so
// it never moves the page. Drag (pointer events, touch too) → nearest corner; fling / drag past the left or right edge
// → tucked off-screen, a tab with a chevron stays at that edge (tap / drag it = back). Esc (focus inside) tucks. Kept
// clear of the sticky header / report nav (top), the hero Scan now button, the phone CTA bar, Ask-AI launcher and
// report Reveal pill (moved to the nearest free slot above / below them).
// State (corner, tucked side, closed) in sessionStorage 'leakscan.pip'.
(function () {
  'use strict';
  var me = document.currentScript, q = new URLSearchParams(location.search), KEY = 'leakscan.pip';
  if (!me || q.get('pip') === '0' || !('PointerEvent' in window)) return;
  var forced = q.get('pip') === '1', auto = me.getAttribute('data-pip-auto') === 'r';
  if (!forced && !auto) return;
  var VIDEO = new URL('../video/', me.src);
  var TOP = ['.site-header', '.rnav'], AVOID = ['#scan button[type=submit]', '.mobile-cta', '.askai-launcher', '.ph-reveal'];
  var EMBED = '.vo{--nb-h:0px}.vo-page{min-height:0;display:block}.vo-stage{width:100vw}.vo-nb,.vo-ui,.vo-wait{display:none!important}';
  var SVG = function (d) { return '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">' + d + '</svg>'; };
  var I = { x: SVG('<path d="M18 6 6 18M6 6l12 12"/>'), exp: SVG('<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>'),
    off: SVG('<path d="M11 5 6 9H2v6h4l5 4zM22 9l-6 6M16 9l6 6"/>'), on: SVG('<path d="M11 5 6 9H2v6h4l5 4zM15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14"/>'),
    play: SVG('<path d="M7 4v16l13-8z" fill="currentColor"/>'), l: SVG('<path d="m9 6 6 6-6 6"/>'), r: SVG('<path d="m15 6-6 6 6 6"/>') };
  var S = { c: 'br', t: '', x: 0 };
  try { var s0 = JSON.parse(sessionStorage.getItem(KEY) || 'null'); if (s0 && /^[tb][lr]$/.test(s0.c)) S = { c: s0.c, t: /^[lr]$/.test(s0.t) ? s0.t : '', x: s0.x ? 1 : 0 }; } catch (e) { /* defaults */ }
  if (S.x) return;
  var save = function () { try { sessionStorage.setItem(KEY, JSON.stringify(S)); } catch (e) { /* private mode */ } };
  var pip, tab, frame, video = null, wasPlaying = true, mounted = false, pos = { x: 0, y: 0 };

  function slug() { var r = new URLSearchParams(location.search).get('r'); return r && /^[A-Za-z0-9_-]{1,64}$/.test(r) ? r : ''; }
  function src(t) {
    var u = new URL(VIDEO), r = slug(), n = q.get('name');
    if (r) u.searchParams.set('r', r);
    if (n) u.searchParams.set('name', n);
    if (t) u.searchParams.set('t', String(t));
    return u.href;
  }
  function vis(el) { var r = el.getBoundingClientRect(); return r.width && r.height && getComputedStyle(el).visibility !== 'hidden' ? r : null; }
  function target() {   // corner, kept under the sticky header / nav and off the obstacles (nearest free slot above / below)
    var w = pip.offsetWidth, h = pip.offsetHeight, vw = document.documentElement.clientWidth, vh = innerHeight;
    var m = innerWidth < 720 ? 12 : 24, x = S.c[1] === 'l' ? m : vw - w - m, top = m, bot = vh - h - m;
    TOP.forEach(function (s) { document.querySelectorAll(s).forEach(function (el) { var r = vis(el); if (r && r.top < 140 && r.bottom > 0) top = Math.max(top, r.bottom + 8); }); });
    var base = S.c[0] === 't' ? top : bot, y = base, rs = [];
    AVOID.forEach(function (s) { document.querySelectorAll(s).forEach(function (el) { var r = vis(el); if (r && r.right > x && r.left < x + w && r.bottom > 0 && r.top < vh) rs.push(r); }); });
    for (var i = 0; i < 4; i++) {
      var hit = rs.filter(function (r) { return r.top - 8 < y + h && r.bottom + 8 > y; })[0];
      if (!hit) break;
      var c = [hit.top - 8 - h, hit.bottom + 8].filter(function (v) { return v >= top && v <= bot; });
      if (!c.length) break;
      y = c.sort(function (a, b) { return Math.abs(a - base) - Math.abs(b - base); })[0];
    }
    y = Math.max(top, Math.min(y, bot));
    if (S.t) x = S.t === 'l' ? -w - 8 : vw + 8;
    return { x: x, y: y, w: w, h: h, vw: vw };
  }
  function move(x, y) { pos.x = x; pos.y = y; pip.style.setProperty('--x', Math.round(x) + 'px'); pip.style.setProperty('--y', Math.round(y) + 'px'); }
  function place() {
    if (!pip || pip.classList.contains('drag')) return;
    var t = target();
    move(t.x, t.y);
    pip.classList.toggle('tucked', !!S.t);
    if (S.t) pip.setAttribute('inert', ''); else pip.removeAttribute('inert');
    tab.hidden = !S.t;
    if (S.t) { tab.setAttribute('data-side', S.t); tab.innerHTML = I[S.t]; tab.style.setProperty('--ty', Math.round(t.y + t.h / 2 - 32) + 'px'); }
  }
  var raf = 0, late = 0;   // + once more after the scroll settles: the phone CTA bar / launcher slide in after it
  function soon() { if (!raf) raf = requestAnimationFrame(function () { raf = 0; place(); }); clearTimeout(late); late = setTimeout(place, 350); }

  function sync() {
    if (!video) return;
    pip.classList.toggle('muted', video.muted);
    pip.classList.toggle('paused', video.paused && !S.t);
    snd.innerHTML = (video.muted ? I.off + '<span>Tap to unmute</span>' : I.on);
    snd.setAttribute('aria-label', video.muted ? 'Unmute video' : 'Mute video');
  }
  function play() { if (video) { var p = video.play(); if (p && p.catch) p.catch(sync); } }
  function tap() {
    if (!video) return;
    if (video.muted) { video.muted = false; play(); }
    else if (video.paused) play(); else video.pause();
    sync();
  }
  function tuck(side) {
    if (video) { wasPlaying = !video.paused; video.pause(); }
    S.t = side; save(); place(); sync();
  }
  function untuck() {
    S.t = ''; save(); place();
    if (video && wasPlaying) play();
    sync();
  }
  function close() {
    S.x = 1; save();
    pip.remove(); tab.remove();
    removeEventListener('scroll', soon); removeEventListener('resize', soon);
  }

  // ---------- drag: corners, fling / past the edge = tuck ----------
  var drag = null;
  function down(e) {
    if (e.button > 0) return;
    drag = { id: e.pointerId, sx: e.clientX, sy: e.clientY, x0: pos.x, y0: pos.y, moved: false, pts: [[e.timeStamp, e.clientX, e.clientY]] };
    try { hit.setPointerCapture(e.pointerId); } catch (x) { /* synthetic pointer */ }
  }
  function over(e) {
    if (!drag || e.pointerId !== drag.id) return;
    var dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
    if (!drag.moved && Math.abs(dx) + Math.abs(dy) < 8) return;
    drag.moved = true; pip.classList.add('drag');
    move(drag.x0 + dx, drag.y0 + dy);
    drag.pts.push([e.timeStamp, e.clientX, e.clientY]);
    while (drag.pts.length > 2 && e.timeStamp - drag.pts[0][0] > 100) drag.pts.shift();
  }
  function up(e) {
    if (!drag || e.pointerId !== drag.id) return;
    var d = drag; drag = null;
    pip.classList.remove('drag');
    if (!d.moved) { tap(); return; }
    var a = d.pts[0], b = d.pts[d.pts.length - 1], dt = Math.max(16, b[0] - a[0]);
    var held = e.timeStamp - b[0] > 90, vx = held ? 0 : (b[1] - a[1]) / dt, vy = held ? 0 : (b[2] - a[2]) / dt, w = pip.offsetWidth, h = pip.offsetHeight, vw = document.documentElement.clientWidth;
    var px = pos.x + vx * 250, py = pos.y + vy * 250;   // where a fling would carry it
    if (px < -w * 0.4) return tuck('l');
    if (px + w > vw + w * 0.4) return tuck('r');
    S.c = (py + h / 2 < innerHeight / 2 ? 't' : 'b') + (px + w / 2 < vw / 2 ? 'l' : 'r');
    save(); place();
  }

  // ---------- the tab: tap or drag inward = back ----------
  var tdrag = null, tmoved = false;
  function tabDown(e) { tdrag = { id: e.pointerId, sx: e.clientX }; tmoved = false; try { tab.setPointerCapture(e.pointerId); } catch (x) { /* synthetic pointer */ } }
  function tabUp(e) {
    if (!tdrag || e.pointerId !== tdrag.id) return;
    var dx = e.clientX - tdrag.sx; tdrag = null;
    if ((S.t === 'l' && dx > 16) || (S.t === 'r' && dx < -16)) { tmoved = true; setTimeout(function () { tmoved = false; }, 400); untuck(); }
  }

  var hit, snd, exp, xb;
  function mount() {
    if (mounted) return;
    if (!forced && !slug()) return;   // the report page before its result: wait (the URL gets ?r= once it renders)
    mounted = true;
    ['scroll', 'pointerdown', 'keydown'].forEach(function (ev) { removeEventListener(ev, mount, true); });
    pip = document.createElement('div');
    pip.className = 'pip';
    pip.setAttribute('role', 'region');
    pip.setAttribute('aria-label', "Jack's video");
    pip.innerHTML = '<button class="pip-snd" type="button"></button><a class="pip-exp" aria-label="Open the full video">' + I.exp +
      '</a><button class="pip-x" type="button" aria-label="Close video">' + I.x + '</button><span class="pip-play" aria-hidden="true">' + I.play + '</span>';
    frame = document.createElement('iframe');
    frame.title = "Jack's video";
    frame.setAttribute('tabindex', '-1');
    frame.setAttribute('inert', '');
    frame.setAttribute('allow', 'autoplay');
    hit = document.createElement('div');
    hit.className = 'pip-hit';
    pip.insertBefore(hit, pip.firstChild);
    pip.insertBefore(frame, hit);
    snd = pip.querySelector('.pip-snd'); exp = pip.querySelector('.pip-exp'); xb = pip.querySelector('.pip-x');
    exp.href = src();
    tab = document.createElement('button');
    tab.type = 'button';
    tab.className = 'pip-tab';
    tab.hidden = true;
    tab.setAttribute('aria-label', "Show Jack's video");
    document.body.appendChild(pip);
    document.body.appendChild(tab);
    place();

    hit.addEventListener('pointerdown', down);
    hit.addEventListener('pointermove', over);
    hit.addEventListener('pointerup', up);
    hit.addEventListener('pointercancel', function () { drag = null; pip.classList.remove('drag'); place(); });
    snd.addEventListener('click', function () { if (video) { video.muted = !video.muted; if (!video.muted) play(); sync(); } });
    xb.addEventListener('click', close);
    exp.addEventListener('click', function () { exp.href = src(video ? Math.floor(video.currentTime) : 0); });
    tab.addEventListener('pointerdown', tabDown);
    tab.addEventListener('pointerup', tabUp);
    tab.addEventListener('click', function () { if (tmoved) { tmoved = false; return; } untuck(); var f = snd; if (f) setTimeout(function () { f.focus(); }, 0); });
    pip.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      tuck(S.c[1]);
      tab.focus();
    });
    addEventListener('scroll', soon, { passive: true });
    addEventListener('resize', soon);

    var shown = false;
    function show() { if (shown) return; shown = true; place(); pip.classList.add('on'); sync(); }
    frame.addEventListener('load', function () {
      try {
        var d = frame.contentDocument, st = d.createElement('style');
        st.textContent = EMBED;
        d.head.appendChild(st);
        video = d.querySelector('.vo-video');
      } catch (e) { video = null; }
      if (video) {
        video.muted = true;
        video.controls = false;
        ['play', 'pause', 'volumechange'].forEach(function (ev) { video.addEventListener(ev, sync); });
        if (!S.t) play();
      }
      show();
    });
    setTimeout(show, 6000);
    frame.src = src();
  }
  function arm() {
    ['scroll', 'pointerdown', 'keydown'].forEach(function (ev) { addEventListener(ev, mount, { capture: true, passive: true }); });
    var idle = window.requestIdleCallback || function (f) { return setTimeout(f, 2500); };
    idle(mount, { timeout: 4000 });
  }
  if (document.readyState === 'complete') arm(); else addEventListener('load', arm);
})();
