// Mini player of site/video/ (picture-in-picture style). The script tag says where it is on by default:
//   data-pip-auto="dock" (landing): docked on the hero card (below), floating once the hero is out of view;
//   data-pip-auto="r" (scan report): floating, when the URL has ?r=<slug> (the video personalizes itself with that scan).
// ?pip=1 forces it on, ?pip=0 off. Same-origin iframe of ../video/ (?r= / ?name= passed through) in embed form: this script
// injects a style into it (no name bar, no player UI: the stage fills the picture) and drives its <video> (starts muted).
// Bar under the picture (40 px targets): play / pause, sound, expand / minimize, close. Never a new page / tab.
// Expanded (YouTube style, .big, not kept): a tap on the picture or the expand button = sound on, full width (phone) or
// min(960px, 70vw) centred, fixed right under the sticky header; the page keeps scrolling under it (no lock, nothing over
// the rest). There a tap on the picture = play / pause; drag it down (follows the finger: translate + scale toward the mini
// spot; released past 30% or flung down = mini, else snaps back), the chevron button or Esc = back to the mini player.
// Docked: absolute (scrolls with the page), ~44% of the card's width, hanging off its bottom-right corner (<= 25% of the
// card, never over a link / button / input: else just outside that corner, else floating); re-placed when the card
// changes (in-page scan → report card). Floating: fixed, by default bottom-right at min(320px, 45vw), under the sticky header
// / report nav and off the hero Scan now button, phone CTA bar, Ask-AI launcher, report Reveal pill. Drag (pointer events,
// touch too): it stays where it is dropped (kept on-screen, under the header); fling / drag past the left, right or bottom
// edge → tucked off-screen, a tab with a chevron at the side (tap / drag inward = back); Esc (focus inside) tucks. Resize:
// the top-left corner grip (drag, arrow keys) or a pinch, 16:9, 168 px .. 60% (phone 90%) of the screen width. A drag / resize /
// tuck ends docking for the session; size and spot are kept. Created after the page's load + first
// scroll / pointer / key or idle; the iframe loads once the player is near the screen; paused while off-screen.
// State (spot, size, tucked side, moved, closed) in sessionStorage 'leakscan.pip'.
(function () {
  'use strict';
  var me = document.currentScript, q = new URLSearchParams(location.search), KEY = 'leakscan.pip';
  if (!me || q.get('pip') === '0' || !('PointerEvent' in window) || !('IntersectionObserver' in window)) return;
  var auto = me.getAttribute('data-pip-auto') || '', forced = q.get('pip') === '1';
  if (!forced && !auto) return;
  var VIDEO = new URL('../video/', me.src);
  var TOP = ['.site-header', '.rnav'], AVOID = ['#scan button[type=submit]', '.mobile-cta', '.askai-launcher', '.ph-reveal'];
  var LIVE = 'a[href], button, input, select, textarea, summary, label, [role="tab"], [role="button"], [tabindex]:not([tabindex="-1"])';
  var EMBED = '.vo{--nb-h:0px}.vo-page{min-height:0;display:block}.vo-stage{width:100vw}.vo-nb,.vo-ui,.vo-wait{display:none!important}';
  var SVG = function (d, c) { return '<svg' + (c ? ' class="' + c + '"' : '') + ' viewBox="0 0 24 24" aria-hidden="true" focusable="false">' + d + '</svg>'; };
  var I = { x: SVG('<path d="M18 6 6 18M6 6l12 12"/>'), exp: SVG('<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>'),
    off: SVG('<path d="M11 5 6 9H2v6h4l5 4zM22 9l-6 6M16 9l6 6"/>'), on: SVG('<path d="M11 5 6 9H2v6h4l5 4zM15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14"/>'),
    pp: SVG('<path d="M7 4v16l13-8z" fill="currentColor"/>', 'pip-i-play') + SVG('<path d="M8 5v14M16 5v14"/>', 'pip-i-pause'),
    dn: SVG('<path d="m6 9 6 6 6-6"/>'), rs: SVG('<path d="M5 15V5h10"/>'), l: SVG('<path d="m9 6 6 6-6 6"/>'), r: SVG('<path d="m15 6-6 6 6 6"/>') };
  var S = { p: null, w: 0, t: '', u: 0, x: 0 }, num = function (v) { return typeof v === 'number' && isFinite(v) ? v : 0; };
  try {
    var s0 = JSON.parse(sessionStorage.getItem(KEY) || 'null');
    if (s0) S = { p: Array.isArray(s0.p) ? [num(s0.p[0]), num(s0.p[1])] : null, w: num(s0.w), t: /^[lr]$/.test(s0.t) ? s0.t : '', u: s0.u ? 1 : 0, x: s0.x ? 1 : 0 };
  } catch (e) { /* defaults */ }
  if (S.x) return;
  var save = function () { try { sessionStorage.setItem(KEY, JSON.stringify(S)); } catch (e) { /* private mode */ } };
  var pip, pic, tab, frame, snd, pp, exp, xb, grip, video = null, wasPlaying = true, offPaused = false, mounted = false, pos = { x: 0, y: 0 };
  var card = null, hero = null, heroIn = false, mode = '', big = false;

  function slug() { var r = new URLSearchParams(location.search).get('r'); return r && /^[A-Za-z0-9_-]{1,64}$/.test(r) ? r : ''; }
  function src() {
    var u = new URL(VIDEO), r = slug(), n = q.get('name');
    if (r) u.searchParams.set('r', r);
    if (n) u.searchParams.set('name', n);
    return u.href;
  }
  function vis(el) { var r = el.getBoundingClientRect(); return r.width && r.height && getComputedStyle(el).visibility !== 'hidden' ? r : null; }
  function vw() { return document.documentElement.clientWidth; }

  // ---------- docked: off the hero card's bottom-right corner ----------
  function dockAt() {   // → viewport rect {x, y, w} or null (no safe spot)
    var r = card && card.getBoundingClientRect();
    if (!r || !r.width) return null;
    var w = Math.round(r.width * DOCK), h = Math.round(w * 9 / 16) + BAR, W = vw();
    var fit = function (x) { return Math.max(12, Math.min(x, W - w - 12)); };
    var spots = [{ x: fit(r.right - w * 0.7), y: r.bottom - h * 0.7 }, { x: fit(r.right - w), y: r.bottom + 10 }];
    var live = [].filter.call(document.querySelectorAll(LIVE), function (el) {
      if (pip.contains(el) || tab.contains(el) || el.closest('.askai-launcher, .mobile-cta')) return false;   // fixed ones: they sit above the docked player (z)
      return !!vis(el);
    }).map(function (el) { return el.getBoundingClientRect(); });
    for (var i = 0; i < spots.length; i++) {
      var s = spots[i], ix = Math.max(0, Math.min(s.x + w, r.right) - Math.max(s.x, r.left)), iy = Math.max(0, Math.min(s.y + h, r.bottom) - Math.max(s.y, r.top));
      if (ix * iy > 0.25 * r.width * r.height) continue;
      var hit = live.some(function (b) { return b.right > s.x - 4 && b.left < s.x + w + 4 && b.bottom > s.y - 4 && b.top < s.y + h + 4; });
      if (!hit) return { x: s.x, y: s.y, w: w };
    }
    return null;
  }
  var DOCK = 0.55, BAR = 40, MIN = 168;   // docked width = 55% of the card; bar = 4 x 40 px buttons (+ 8 px padding = MIN)
  function lim(w) {   // 16:9 + bar, MIN .. 60% (phone 90%) of the width, and it fits the screen's height
    var W = vw(), max = Math.min(W * (innerWidth < 720 ? 0.9 : 0.6), (innerHeight - topInset() - 8 - BAR) * 16 / 9);
    return Math.round(Math.max(MIN, Math.min(w, max)));
  }
  function hdr() {   // bottom of the sticky header / report nav (0 if none at the top)
    var b = 0;
    TOP.forEach(function (s) { document.querySelectorAll(s).forEach(function (el) { var r = vis(el); if (r && r.top < 140 && r.bottom > 0) b = Math.max(b, r.bottom); }); });
    return b;
  }
  function topInset() { var h = hdr(); return Math.max(innerWidth < 720 ? 12 : 24, h ? h + 8 : 0); }
  function bigAt() {   // expanded: full width (phone) / min(960, 70vw) centred, right under the header
    var W = vw(), ph = innerWidth < 720, t = Math.round(hdr()) + (ph ? 0 : 12);
    var w = Math.round(ph ? W : Math.min(960, W * 0.7, (innerHeight - t - 16 - BAR) * 16 / 9));
    return { x: Math.round((W - w) / 2), y: t, w: w };
  }
  function miniAt() {   // where minimize lands (viewport): the dock spot, else the floating spot
    var d = docking() ? dockAt() : null;
    if (d) return d;
    var w = S.w ? lim(S.w) : Math.min(320, innerWidth * 0.45), f = floatAt(w, w * 9 / 16 + BAR);
    return { x: f.x, y: f.y, w: w };
  }
  function keep(x, y, w, h) {   // fully on-screen, under the header
    return [Math.max(8, Math.min(x, vw() - w - 8)), Math.max(topInset(), Math.min(y, innerHeight - h - 8))];
  }
  function docking() { return auto === 'dock' && card && heroIn && !S.u && !S.t; }

  // ---------- floating: corner, kept under the sticky header / nav and off the obstacles ----------
  function floatAt(w, h) {   // the user's spot, else bottom-right, off the obstacles (for a w x h box)
    var W = vw(), vh = innerHeight, x, y;
    if (S.p) { var k = keep(S.p[0], S.p[1], w, h); x = k[0]; y = k[1]; }
    else {
      var m = innerWidth < 720 ? 12 : 24, top = topInset(), bot = vh - h - m, rs = [];
      x = W - w - m; y = bot;
      AVOID.forEach(function (s) { document.querySelectorAll(s).forEach(function (el) { var r = vis(el); if (r && r.right > x && r.left < x + w && r.bottom > 0 && r.top < vh) rs.push(r); }); });
      for (var i = 0; i < 4; i++) {
        var hit = rs.filter(function (r) { return r.top - 8 < y + h && r.bottom + 8 > y; })[0];
        if (!hit) break;
        var c = [hit.top - 8 - h, hit.bottom + 8].filter(function (v) { return v >= top && v <= bot; });
        if (!c.length) break;
        y = c.sort(function (a, b) { return Math.abs(a - bot) - Math.abs(b - bot); })[0];
      }
      y = Math.max(top, Math.min(y, bot));
    }
    if (S.t) x = S.t === 'l' ? -w - 8 : W + 8;
    return { x: x, y: y };
  }
  function move(x, y) { pos.x = x; pos.y = y; pip.style.setProperty('--x', Math.round(x) + 'px'); pip.style.setProperty('--y', Math.round(y) + 'px'); }
  function setMode(m) {
    if (m === mode) return;
    var fade = mode && mode !== 'big' && m !== 'big';   // dock <-> float: fade in; to / from big: flip() animates
    mode = m;
    pip.classList.add('swap');
    pip.classList.toggle('docked', m === 'dock');
    pip.classList.toggle('big', m === 'big');
    if (fade) { pip.classList.remove('pop'); void pip.offsetWidth; pip.classList.add('pop'); }
    requestAnimationFrame(function () { requestAnimationFrame(function () { pip.classList.remove('swap'); }); });
  }
  function place() {
    if (!pip || pip.classList.contains('drag')) return;
    var d = big ? null : docking() ? dockAt() : null;
    if (big) {
      setMode('big');
      var b = bigAt();
      pip.style.setProperty('--w', b.w + 'px');
      move(b.x, b.y);
    } else if (d) {
      setMode('dock');
      pip.style.setProperty('--w', d.w + 'px');
      move(d.x + scrollX, d.y + scrollY);
    } else {
      setMode('float');
      if (S.w) pip.style.setProperty('--w', lim(S.w) + 'px'); else pip.style.removeProperty('--w');
      var t = floatAt(pip.offsetWidth, pip.offsetHeight);
      move(t.x, t.y);
    }
    pip.setAttribute('data-mode', mode);
    exp.innerHTML = big ? I.dn : I.exp;
    exp.setAttribute('aria-label', big ? 'Minimize video' : 'Expand video');
    exp.setAttribute('aria-expanded', big ? 'true' : 'false');
    pip.classList.toggle('tucked', !!S.t);
    if (S.t) pip.setAttribute('inert', ''); else pip.removeAttribute('inert');
    tab.hidden = !S.t;
    if (S.t) { tab.setAttribute('data-side', S.t); tab.innerHTML = I[S.t]; tab.style.setProperty('--ty', Math.round(pos.y + pip.offsetHeight / 2 - 32) + 'px'); }
  }
  var raf = 0, late = 0;   // + once more after the scroll settles: the phone CTA bar / launcher slide in after it
  function soon() { if (!raf) raf = requestAnimationFrame(function () { raf = 0; place(); }); clearTimeout(late); late = setTimeout(place, 350); }

  function sync() {
    if (!video) return;
    pip.classList.toggle('muted', video.muted);
    pip.classList.toggle('paused', video.paused);
    snd.innerHTML = video.muted ? I.off : I.on;
    snd.setAttribute('aria-label', video.muted ? 'Turn the sound on' : 'Mute');
    pp.setAttribute('aria-label', video.paused ? 'Play' : 'Pause');
  }
  function play() { if (video) { var p = video.play(); if (p && p.catch) p.catch(sync); } }
  function tap() {   // on the picture: mini = expand; expanded = sound on, then play / pause
    if (!big) return expand();
    if (!video) return;
    if (video.muted) { video.muted = false; play(); }
    else if (video.paused) play(); else video.pause();
    sync();
  }
  function flip(fn) {   // change the layout, then animate from the old box (translate + scale, transform only)
    var a = pip.getBoundingClientRect();
    pip.style.setProperty('--s', '1');
    fn();
    var b = pip.getBoundingClientRect(), x = pos.x, y = pos.y, o = mode === 'dock';
    if (!b.width) return;
    pip.classList.add('swap');
    pip.style.setProperty('--s', String(a.width / b.width));
    move(a.left + (o ? scrollX : 0), a.top + (o ? scrollY : 0));
    void pip.offsetWidth;
    pip.classList.remove('swap');
    pip.style.setProperty('--s', '1');
    move(x, y);
  }
  function expand() {
    if (big || S.t) return;
    big = true;
    flip(place);
    if (video) { video.muted = false; play(); }
    sync();
  }
  function minimize() {
    if (!big) return;
    big = false;
    pip.classList.remove('drag');
    flip(place);
    sync();
  }
  function tuck(side) {
    if (video) { wasPlaying = !video.paused; video.pause(); }
    if (mode === 'dock' || !S.p) { var r = pip.getBoundingClientRect(); S.p = keep(r.left, r.top, r.width, r.height); S.w = Math.round(r.width); }
    S.t = side; S.u = 1; save(); place(); sync();
  }
  function untuck() {
    S.t = ''; save(); place();
    if (video && wasPlaying) play();
    sync();
  }
  function close() {
    S.x = 1; save();
    if (video) video.pause();
    pip.remove(); tab.remove();
    removeEventListener('scroll', soon); removeEventListener('resize', soon);
  }

  // ---------- drag: free drop, fling / past the edge = tuck; pinch / grip = resize (any of them ends docking);
  // expanded: only a pull down (toward the mini spot) ----------
  var drag = null, pts = {}, pinch = null, rsz = null;
  function toFloat() {   // fixed from here, same spot and size on screen
    var r = pip.getBoundingClientRect();
    pip.classList.add('drag');
    setMode('float');
    pip.style.setProperty('--w', Math.round(r.width) + 'px');
    move(r.left, r.top);
    return r;
  }
  function settle() {   // the user's spot / size from now on
    pip.classList.remove('drag');
    var w = pip.offsetWidth, k = keep(pos.x, pos.y, w, pip.offsetHeight);
    S.p = k; S.w = w; S.u = 1; save(); place();
  }
  function setW(w, ax, ay) {   // resize keeping the point (ax, ay) in [0..1] of the box where it is
    var r = pip.getBoundingClientRect(), nw = lim(w), nh = Math.round(nw * 9 / 16) + BAR;
    pip.style.setProperty('--w', nw + 'px');
    move(r.left + (r.width - nw) * ax, r.top + (r.height - nh) * ay);
  }
  function dist() { var a = Object.keys(pts).map(function (k) { return pts[k]; }); return Math.hypot(a[0][0] - a[1][0], a[0][1] - a[1][1]); }
  function down(e) {
    if (e.button > 0) return;
    if (e.target.closest('.pip-rs')) {   // the grip: anchored at the opposite (bottom-right) corner
      e.preventDefault();
      var r0 = toFloat();
      rsz = { id: e.pointerId, sx: e.clientX, sy: e.clientY, w0: r0.width };
      try { grip.setPointerCapture(e.pointerId); } catch (x) { /* synthetic pointer */ }
      return;
    }
    if (e.target.closest('button, a')) return;
    pts[e.pointerId] = [e.clientX, e.clientY];
    if (Object.keys(pts).length === 2 && !big) {   // pinch
      drag = null;
      var r = toFloat();
      pinch = { d0: dist() || 1, w0: r.width };
      return;
    }
    if (drag) return;
    drag = { id: e.pointerId, big: big, pic: !!e.target.closest('.pip-pic'), sx: e.clientX, sy: e.clientY, moved: false, pts: [[e.timeStamp, e.clientX, e.clientY]] };
    try { pip.setPointerCapture(e.pointerId); } catch (x) { /* synthetic pointer */ }
  }
  function over(e) {
    if (rsz && e.pointerId === rsz.id) {
      var dx = rsz.sx - e.clientX, dy = (rsz.sy - e.clientY) * 16 / 9;
      setW(rsz.w0 + (Math.abs(dx) > Math.abs(dy) ? dx : dy), 1, 1);
      return;
    }
    if (pts[e.pointerId]) pts[e.pointerId] = [e.clientX, e.clientY];
    if (pinch && Object.keys(pts).length === 2) { setW(pinch.w0 * dist() / pinch.d0, 0.5, 0.5); return; }
    if (!drag || e.pointerId !== drag.id) return;
    var mx = e.clientX - drag.sx, my = e.clientY - drag.sy;
    if (drag.big) { pull(e, my); return; }
    if (!drag.moved) {
      if (Math.abs(mx) + Math.abs(my) < 8) return;
      drag.moved = true;
      var r = toFloat();
      drag.x0 = r.left; drag.y0 = r.top;
    }
    move(drag.x0 + mx, drag.y0 + my);
    drag.pts.push([e.timeStamp, e.clientX, e.clientY]);
    while (drag.pts.length > 2 && e.timeStamp - drag.pts[0][0] > 100) drag.pts.shift();
  }
  function pull(e, my) {   // expanded, dragged down: follows the finger from the big box toward the mini one
    if (!drag.moved) {
      if (Math.abs(e.clientX - drag.sx) + Math.abs(my) < 8) return;
      drag.moved = true;
      pip.classList.add('drag');
      drag.b = bigAt(); drag.t = miniAt();
    }
    var b = drag.b, t = drag.t, p = Math.max(0, Math.min(1, my / Math.max(120, t.y - b.y)));
    drag.p = p;
    pip.style.setProperty('--s', String(1 + (t.w / b.w - 1) * p));
    move(b.x + (t.x - b.x) * p, b.y + (t.y - b.y) * p);
    drag.pts.push([e.timeStamp, e.clientX, e.clientY]);
    while (drag.pts.length > 2 && e.timeStamp - drag.pts[0][0] > 100) drag.pts.shift();
  }
  function up(e) {
    delete pts[e.pointerId];
    if (rsz && e.pointerId === rsz.id) { rsz = null; settle(); return; }
    if (pinch) { if (!Object.keys(pts).length) { pinch = null; settle(); } return; }
    if (!drag || e.pointerId !== drag.id) return;
    var d = drag; drag = null;
    if (!d.moved) { if (d.pic) tap(); return; }
    var a = d.pts[0], b = d.pts[d.pts.length - 1], dt = Math.max(16, b[0] - a[0]), held = e.timeStamp - b[0] > 90;
    var vx = held ? 0 : (b[1] - a[1]) / dt, vy = held ? 0 : (b[2] - a[2]) / dt, w = pip.offsetWidth, h = pip.offsetHeight, W = vw();
    if (d.big) {   // past 30% of the way or flung down = mini, else back up
      if (d.p > 0.3 || vy > 0.5) return minimize();
      pip.classList.remove('drag'); pip.style.setProperty('--s', '1'); place();
      return;
    }
    var px = pos.x + vx * 250, py = pos.y + vy * 250;   // where a fling would carry it
    var side = px < -w * 0.4 ? 'l' : px + w > W + w * 0.4 ? 'r' : '', down = !side && py + h > innerHeight + h * 0.4;   // past a side / the bottom
    if (down) side = pos.x + w / 2 < W / 2 ? 'l' : 'r';
    if (side) {
      pip.classList.remove('drag');
      S.p = keep(d.x0, down ? d.y0 : pos.y, w, h); S.w = w;   // back where the fling started
      return tuck(side);
    }
    settle();
  }
  function cancel(e) {
    delete pts[e.pointerId];
    var d = drag; drag = null; rsz = null; pinch = null;
    if (!pip.classList.contains('drag')) return;
    if (d && d.big) { pip.classList.remove('drag'); pip.style.setProperty('--s', '1'); place(); } else settle();
  }

  // ---------- the tab: tap or drag inward = back ----------
  var tdrag = null, tmoved = false;
  function tabDown(e) { tdrag = { id: e.pointerId, sx: e.clientX }; tmoved = false; try { tab.setPointerCapture(e.pointerId); } catch (x) { /* synthetic pointer */ } }
  function tabUp(e) {
    if (!tdrag || e.pointerId !== tdrag.id) return;
    var dx = e.clientX - tdrag.sx; tdrag = null;
    if ((S.t === 'l' && dx > 16) || (S.t === 'r' && dx < -16)) { tmoved = true; setTimeout(function () { tmoved = false; }, 400); untuck(); }
  }

  function mount() {
    if (mounted) return;
    if (auto === 'r' && !forced && !slug()) return;   // the report page before its result: wait (the URL gets ?r= once it renders)
    mounted = true;
    ['scroll', 'pointerdown', 'keydown'].forEach(function (ev) { removeEventListener(ev, mount, true); });
    card = auto === 'dock' ? document.querySelector('.hero .report-card') : null;
    hero = card && card.closest('.hero');
    pip = document.createElement('div');
    pip.className = 'pip';
    pip.setAttribute('role', 'region');
    pip.setAttribute('aria-label', "Jack's video");
    pip.innerHTML = '<div class="pip-pic"><div class="pip-hit"></div><div class="pip-rs" role="button" tabindex="0" aria-label="Resize video (arrow keys)">' + I.rs +
      '</div></div><div class="pip-bar"><button class="pip-pp" type="button">' + I.pp +
      '</button><button class="pip-snd" type="button"></button><i></i><button class="pip-exp" type="button"></button><button class="pip-x" type="button" aria-label="Close video">' + I.x + '</button></div>';
    pic = pip.querySelector('.pip-pic');
    frame = document.createElement('iframe');
    frame.title = "Jack's video";
    frame.setAttribute('tabindex', '-1');
    frame.setAttribute('inert', '');
    frame.setAttribute('allow', 'autoplay');
    pic.insertBefore(frame, pic.firstChild);
    grip = pip.querySelector('.pip-rs'); snd = pip.querySelector('.pip-snd'); pp = pip.querySelector('.pip-pp'); exp = pip.querySelector('.pip-exp'); xb = pip.querySelector('.pip-x');
    snd.innerHTML = I.off; snd.setAttribute('aria-label', 'Turn the sound on'); pp.setAttribute('aria-label', 'Pause');
    pip.classList.add('muted');
    tab = document.createElement('button');
    tab.type = 'button';
    tab.className = 'pip-tab';
    tab.hidden = true;
    tab.setAttribute('aria-label', "Show Jack's video");
    document.body.appendChild(pip);
    document.body.appendChild(tab);
    if (hero) {
      var hb = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--header-h')) || 64;
      heroIn = hero.getBoundingClientRect().bottom > hb;
      new IntersectionObserver(function (en) { heroIn = en[0].isIntersecting; place(); }, { rootMargin: -hb + 'px 0px 0px 0px' }).observe(hero);
      if ('ResizeObserver' in window) new ResizeObserver(soon).observe(card);
    }
    place();

    pip.addEventListener('pointerdown', down);
    pip.addEventListener('pointermove', over);
    pip.addEventListener('pointerup', up);
    pip.addEventListener('pointercancel', cancel);
    grip.addEventListener('click', function (e) { e.preventDefault(); });
    grip.addEventListener('keydown', function (e) {
      var k = { ArrowUp: 1.1, ArrowRight: 1.1, ArrowDown: 1 / 1.1, ArrowLeft: 1 / 1.1 }[e.key];
      if (!k) return;
      e.preventDefault();
      toFloat(); setW(pip.offsetWidth * k, 1, 1); settle();
    });
    snd.addEventListener('click', function () { if (video) { video.muted = !video.muted; if (!video.muted) play(); sync(); } });
    pp.addEventListener('click', function () { if (!video) return; if (video.paused) play(); else video.pause(); sync(); });
    xb.addEventListener('click', close);
    exp.addEventListener('click', function () { if (big) minimize(); else expand(); });
    tab.addEventListener('pointerdown', tabDown);
    tab.addEventListener('pointerup', tabUp);
    tab.addEventListener('click', function () { if (tmoved) { tmoved = false; return; } untuck(); setTimeout(function () { snd.focus(); }, 0); });
    pip.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      if (big) return minimize();
      tuck(pos.x + pip.offsetWidth / 2 < vw() / 2 ? 'l' : 'r');
      tab.focus();
    });
    addEventListener('scroll', soon, { passive: true });
    addEventListener('resize', soon);

    var shown = false;
    function show() { if (shown) return; shown = true; pip.classList.add('on'); place(); sync(); }
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
        video.disablePictureInPicture = true;
        video.setAttribute('disablepictureinpicture', '');
        video.setAttribute('disableremoteplayback', '');
        ['play', 'pause', 'volumechange'].forEach(function (ev) { video.addEventListener(ev, sync); });
        if (!S.t && !offPaused) play();
      }
      show();
    });
    // the iframe loads once the player is near the screen; off-screen = paused (and back on when it returns)
    new IntersectionObserver(function (en) {
      var inView = en[0].isIntersecting;
      if (inView && !frame.src) { frame.src = src(); setTimeout(show, 6000); }
      if (!video || S.t) return;
      if (!inView && !video.paused) { offPaused = true; video.pause(); }
      else if (inView && offPaused) { offPaused = false; play(); }
    }, { rootMargin: '200px' }).observe(pip);
  }
  function arm() {
    ['scroll', 'pointerdown', 'keydown'].forEach(function (ev) { addEventListener(ev, mount, { capture: true, passive: true }); });
    var idle = window.requestIdleCallback || function (f) { return setTimeout(f, 2500); };
    idle(mount, { timeout: 4000 });
  }
  if (document.readyState === 'complete') arm(); else addEventListener('load', arm);
})();
