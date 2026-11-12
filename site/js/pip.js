// Mini player of site/video/ (picture-in-picture style). The script tag says where it is on by default:
//   data-pip-auto="dock" (landing): fixed top-right; on a wide screen docked on the hero card while that spot is fully in view;
//   data-pip-auto="r" (scan report): fixed top-right, once the URL has ?r=<slug> (the video personalizes itself with that scan).
//   data-pip-auto="float" (faq / removals / compare / privacy / imprint: Google Ads lands there too): fixed top-right at once (last scan or generic video).
// ?pip=1 forces it on, ?pip=0 off. Same-origin iframe of ../video/ (?r= / ?name= passed through) in embed form: this script
// injects a style into it (no name bar, no player UI: the stage fills the picture) and drives its <video> (starts muted).
// On screen at once: a phone's first paint already has a tiny still on the home spot (.pip-still, an inline script at the top of
// the page; replaced here in one task, and its image stays under the poster until that is in). Mounted when this deferred
// script runs (before DOMContentLoaded), the box shows with a poster frame = the take's first frame
// (video/jack-poster.webp by fetch(): it does not hold the page's load event) and the iframe starts at the page's load event
// (an iframe started before it holds it, its images too; load is ~1 s on Fast 4G), shown over the poster once its video has
// a frame. FCP / LCP measured unchanged. Fixed, out of the flow: CLS 0.
// Placement (Jack's iPhone): position fixed, top-anchored. The home spot = top-right under the sticky header / report nav,
// min(320px, 45vw) (computer: min(640px, 45vw)); computed ONCE per width from where the scan inputs / Scan now / "Scanned @…" line / CTA bar / Ask-AI
// launcher / Reveal pill sit at scrollY 0: if it would cover them it gets smaller (>= 168 px) rather than lower (moved below
// them only if even that covers them). Never re-placed by a scroll (so it stays put while the page scrolls under it); a
// width / orientation change recomputes it; a height-only change (iOS URL bar, visualViewport resize) moves nothing unless
// the box would leave the screen (keep()). The viewport meta has no viewport-fit=cover: no safe-area insets to add.
// Bar under the picture (40 px targets): play / pause, sound, expand / minimize (+ expanded: floating mini, bottom-right); the close X (40 px) on the picture's
// top-right corner. X = hidden behind a tab at the top-right corner (the home spot's top, right edge; fixed, so it stays
// there while scrolling); the tab = back to the same spot (home, dropped, or docked). Never gone, never a new page / tab.
// Expanded (YouTube style, .big, not kept): a tap on the picture, the expand button or (phone) Play on the mini = sound on, full width (phone) or
// min(960px, 70vw) centred, fixed right under the sticky header; the page keeps scrolling under it (no lock, nothing over
// the rest). There a tap on the picture = play / pause; drag it down (follows the finger: translate + scale toward the mini
// spot; released past 30% or flung down = mini, else snaps back), the chevron button or Esc = back to the mini player.
// Expanded, wide (>= 1024 px): a scan card (OnlyFans + Instagram / X, Scan now) on the player's right (scanCard()); narrower: the page
// pushed down by the player's height (.pip-push spacer under the header: the title never covered). X while expanded: 1 s (0.5 s down to the floating spot, 0.5 s off the right).
// 360p mini, 720p expanded (phones, < 720 px wide; a computer's mini is 476-640 px, 720p all along): src() adds ?mini=1, video/index.html then
// plays jack-360.*. That <video> stays the master for the clock, the sound (iPhone: unmute only inside the tap) and the overlays; expanding adds
// a muted 720p <video> (.pip-hd) over it, under the overlays (no request before that), seeked ahead, revealed once it plays within 0.15 s of the
// master and kept there (hdTick); hidden the moment it stalls or falls behind, so the still-playing mini shows through: never a freeze, maybe no HD.
// Minimized / closed = the layer dropped, its download stopped (a re-expand starts again, off the HTTP cache). The master paused by nothing here (iOS as
// the second video starts? unproven) = the same, the master played again, no 720p for the rest of this page view.
// Docked (>= 720 px wide only, and only while that whole spot is on screen under the header): absolute, 2 x 55% of the card's
// width, over the card's lower right and poking out of its bottom-right corner (it may cover the card's rows, never the scan
// inputs / Scan now / "Scanned" line: else the home spot); re-placed on scroll / when the card changes (in-page scan → report card). Drag (pointer
// events, touch too): it stays where it is dropped (kept on-screen, under the header, above the phone toolbar); fling /
// drag past the left, right or bottom edge → tucked off-screen, a tab with a chevron beside where it went (tap / drag inward
// = back); Esc (focus inside) tucks. Resize: the top-left corner grip (drag, arrow keys) or a pinch, 16:9, 168 px .. 60%
// (phone 90%) of the screen width. A drag / resize / fling ends docking for this page view; size and spot are kept. Paused
// while off-screen / hidden. Nothing stored: every page load (reload, new page) starts on the home spot at default size.
(function () {
  'use strict';
  var me = document.currentScript, q = new URLSearchParams(location.search);
  if (!me || q.get('pip') === '0' || !('PointerEvent' in window) || !('IntersectionObserver' in window)) return;
  var auto = me.getAttribute('data-pip-auto') || '', forced = q.get('pip') === '1';
  if (!forced && !auto) return;
  var VIDEO = new URL('../video/', me.src);
  var TOP = ['.site-header', '.rnav'], AVOID = ['#scan input', '#scan button[type=submit]', '[data-p=scanned]', '.mobile-cta', '.askai-launcher', '.ph-reveal'];
  var EMBED = '.vo{--nb-h:0px}.vo-page{min-height:0;display:block}.vo-stage{width:100vw}.vo-nb,.vo-ui,.vo-wait{display:none!important}.pip-hd{opacity:0;z-index:1}.pip-hd.on{opacity:1}';
  var SVG = function (d, c) { return '<svg' + (c ? ' class="' + c + '"' : '') + ' viewBox="0 0 24 24" aria-hidden="true" focusable="false">' + d + '</svg>'; };
  var I = { x: SVG('<path d="M18 6 6 18M6 6l12 12"/>'), exp: SVG('<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>'),
    off: SVG('<path d="M11 5 6 9H2v6h4l5 4zM22 9l-6 6M16 9l6 6"/>'), on: SVG('<path d="M11 5 6 9H2v6h4l5 4zM15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14"/>'),
    pp: SVG('<path d="M7 4v16l13-8z" fill="currentColor"/>', 'pip-i-play') + SVG('<path d="M8 5v14M16 5v14"/>', 'pip-i-pause'),
    dn: SVG('<path d="m6 9 6 6 6-6"/>'), fl: SVG('<rect x="2" y="4" width="20" height="16" rx="2"/><rect x="12" y="12" width="7" height="5" rx="1" fill="currentColor"/>'), rs: SVG('<path d="M5 15V5h10"/>'), l: SVG('<path d="m9 6 6 6-6 6"/>'), r: SVG('<path d="m15 6-6 6 6 6"/>') };
  var S = { p: null, w: 0, t: '', u: 0, c: 0 };   // this page view only: spot, size, tucked side, closed by X, moved
  var pip, pic, tab, frame, snd, pp, exp, xb, grip, video = null, wasPlaying = true, offPaused = false, mounted = false, pos = { x: 0, y: 0 };
  var card = null, mode = '', big = false, home = null, closing = 0, sc = null, push = null, pushH = 0, backAt = 0;   // closing: X's drop timer; sc: the scan card; push: the phone spacer

  function slug() { var r = new URLSearchParams(location.search).get('r'); return r && /^[A-Za-z0-9_-]{1,64}$/.test(r) ? r : ''; }
  function src() {
    var u = new URL(VIDEO), r = slug(), n = q.get('name');
    if (r) u.searchParams.set('r', r);
    if (n) u.searchParams.set('name', n);
    if (innerWidth < 720) u.searchParams.set('mini', '1');   // a phone's mini plays the 360p files
    return u.href;
  }
  function vis(el) { var r = el.getBoundingClientRect(); return r.width && r.height && getComputedStyle(el).visibility !== 'hidden' ? r : null; }
  function vw() { return document.documentElement.clientWidth; }
  function vh() { return window.visualViewport ? Math.min(innerHeight, visualViewport.height) : innerHeight; }
  function bot() { return innerWidth < 720 && matchMedia('(pointer: coarse)').matches ? 88 : 8; }   // touch phone: Safari's bottom toolbar

  // ---------- docked: over the hero card's lower right, poking out of its bottom-right corner ----------
  function dockAt() {   // → viewport rect {x, y, w} or null (it would cover the form)
    var r = card && card.getBoundingClientRect();
    if (!r || !r.width) return null;
    var w0 = r.width * DOCK, h0 = w0 * 9 / 16 + BAR, w = Math.round(w0 * 2), h = Math.round(w * 9 / 16) + BAR, W = vw();
    var s = { x: Math.max(12, Math.min(r.right + w0 * 0.3 - w, W - w - 12)), y: r.bottom + h0 * 0.3 - h };   // 2x, grown up-left from #79's corner
    var form = [];   // it may cover the card's own rows (Jack, 2026-11-06), never the scan form
    AVOID.slice(0, 3).forEach(function (q) { document.querySelectorAll(q).forEach(function (el) { var b = vis(el); if (b) form.push(b); }); });
    return form.some(function (b) { return b.right > s.x - 4 && b.left < s.x + w + 4 && b.bottom > s.y - 4 && b.top < s.y + h + 4; }) ? null : { x: s.x, y: s.y, w: w };
  }
  var DOCK = 0.55, BAR = 40, MIN = 168;   // docked width = 2 x 55% of the card; bar = 4 x 40 px buttons (+ 8 px padding = MIN)
  function lim(w) {   // 16:9 + bar, MIN .. 60% (phone 90%) of the width, and it fits the screen's height
    var W = vw(), max = Math.min(W * (innerWidth < 720 ? 0.9 : 0.6), (vh() - topInset() - 8 - BAR) * 16 / 9);
    return Math.round(Math.max(MIN, Math.min(w, max)));
  }
  function hdr() {   // bottom of the sticky header / report nav (0 if none at the top)
    var b = 0;
    TOP.forEach(function (s) { document.querySelectorAll(s).forEach(function (el) { var r = vis(el); if (r && r.top < 140 && r.bottom > 0) b = Math.max(b, r.bottom); }); });
    return b;
  }
  function topInset() { var h = hdr(); return Math.max(innerWidth < 720 ? 12 : 24, h ? h + 8 : 0); }
  var CARD = 320, GAP = 16;   // the scan card beside the expanded player (wide screens)
  function side() { return vw() >= 1024; }
  function bigAt() {   // expanded: full width (phone) / min(960, 70vw) centred, right under the header; wide: + the scan card on its right
    var W = vw(), ph = innerWidth < 720, t = Math.round(hdr()) + (ph ? 0 : 12), c = side() ? CARD + GAP : 0;
    var w = Math.round(ph ? W : Math.min(960, W * 0.7, W - 48 - c, (innerHeight - t - 16 - BAR) * 16 / 9));
    return { x: Math.round((W - w - c) / 2), y: t, w: w };
  }
  function miniAt() {   // where minimize lands (viewport): the dock spot, else the floating spot
    var d = docking() ? dockAt() : null;
    if (d && inView(d)) return d;
    var w = homeAt().w, f = floatAt(w, w * 9 / 16 + BAR);
    return { x: f.x, y: f.y, w: w };
  }
  function keep(x, y, w, h) {   // fully on-screen, under the header, above the phone's toolbar
    return [Math.max(8, Math.min(x, vw() - w - 8)), Math.max(topInset(), Math.min(y, vh() - h - bot()))];
  }
  function docking() { return auto === 'dock' && card && !S.u && !S.t && !closing && innerWidth >= 720; }
  function inView(d) {   // a dock spot is used only on a wide screen and while all of it is on screen under the header
    return innerWidth >= 720 && d.y >= topInset() && d.y + Math.round(d.w * 9 / 16) + BAR <= vh() - 8;
  }

  // ---------- floating: corner, kept under the sticky header / nav and off the obstacles ----------
  function homeAt() {   // the default spot {x, y, w}: computed once per width (never per scroll: a top-anchored box stays put)
    var W = vw(), ph = innerWidth < 720, w = S.w ? lim(S.w) : Math.round(Math.min(ph ? 320 : 640, innerWidth * 0.45)), k = W + ':' + w;   // computer: 2x (Jack)
    if (home && home.k === k) return home; var sy = scrollY;
    var top = topInset(), m = ph ? 12 : 24, rs = [];
    AVOID.forEach(function (s) { document.querySelectorAll(s).forEach(function (el) {   // where they are at scrollY 0 (fixed ones: where they are)
      var r = vis(el); if (!r || r.right <= W - w - m) return;
      var y0 = getComputedStyle(el).position === 'fixed' ? r.top : r.top + sy;
      if (y0 < vh()) rs.push({ top: y0, bottom: y0 + r.height });
    }); });
    var fit = function (y, w) { return !rs.some(function (r) { return r.top - 8 < y + w * 9 / 16 + BAR && r.bottom + 8 > y; }); };
    if (!S.w) while (w > MIN && !fit(top, w)) w = Math.max(MIN, w - 8);   // at the top, under the header: smaller rather than lower
    var y = top;
    if (!fit(top, w)) {   // even the smallest covers the form: just below what it covers (still on screen)
      var low = vh() - w * 9 / 16 - BAR - bot(), c = rs.map(function (r) { return r.bottom + 8; }).filter(function (v) { return v <= low && fit(v, w); }).sort(function (a, b) { return a - b; });
      if (c.length) y = c[0];
    }
    home = { k: k, x: W - w - m, y: y, w: w };
    return home;
  }
  function floatAt(w, h) {   // the user's spot, else the home spot top-right (for a w x h box); kept on-screen, under the header
    var W = vw(), o = homeAt(), k = S.p ? keep(S.p[0], S.p[1], w, h) : keep(W - w - (innerWidth < 720 ? 12 : 24), o.y, w, h);
    return { x: S.t ? (S.t === 'l' ? -w - 8 : W + 8) : k[0], y: k[1] };
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
    if (d && !inView(d)) d = null;
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
      pip.style.setProperty('--w', homeAt().w + 'px');   // the user's size, else the default (smaller if the form is near the top)
      var t = floatAt(pip.offsetWidth, pip.offsetHeight);
      move(t.x, t.y);
    }
    pip.setAttribute('data-mode', mode);
    aside();
    exp.innerHTML = big ? I.dn : I.exp;
    exp.setAttribute('aria-label', big ? 'Minimize video' : 'Expand video');
    exp.setAttribute('aria-expanded', big ? 'true' : 'false');
    pip.classList.toggle('tucked', !!S.t);
    if (S.t) pip.setAttribute('inert', ''); else pip.removeAttribute('inert');
    tab.hidden = !S.t;
    if (S.t) {   // X: at the top-right corner (the home spot's top); a fling: beside where it went
      var ty = S.c ? keep(0, homeAt().y, 0, 64)[1] : pos.y + pip.offsetHeight / 2 - 32;
      tab.setAttribute('data-side', S.t); tab.innerHTML = I[S.t]; tab.style.setProperty('--ty', Math.round(ty) + 'px');
    }
  }
  function aside() {   // expanded: the scan card on the player's right (wide), else (phone / tablet) the page pushed down under it
    var on = big && !closing && !S.t, b = on && bigAt(), wide = on && side(), h = on && !wide ? Math.round(b.w * 9 / 16) + BAR : 0;
    sc.classList.toggle('on', !!wide);
    if (wide) { sc.style.setProperty('--x', (b.x + b.w + GAP) + 'px'); sc.style.setProperty('--y', b.y + 'px'); }
    if (wide) sc.removeAttribute('inert'); else sc.setAttribute('inert', '');
    if (push && h !== pushH) {   // un-pushed while scrolled: scrolled back by as much, so what's on screen doesn't jump up
      var up = !h && scrollY > 0 ? Math.min(pushH, scrollY) : 0, to = scrollY - up;   // absolute: a short page clamps scrollY as it shrinks
      if (up) push.style.transition = 'none';
      push.style.height = h + 'px'; pushH = h;
      if (up) { scrollTo({ top: to, behavior: 'instant' }); void push.offsetHeight; push.style.transition = ''; }
    }
    // no scroll anchoring while pushed / un-pushing (Chrome would undo the push, or double the scroll-back): back on a frame later
    if (h) document.documentElement.style.overflowAnchor = 'none';
    else if (document.documentElement.style.overflowAnchor) requestAnimationFrame(function () { requestAnimationFrame(function () { if (!pushH) document.documentElement.style.overflowAnchor = ''; }); });
  }
  var raf = 0;   // scroll (desktop dock in / out), card / viewport resize: re-placed once per frame
  function soon() { if (!raf) raf = requestAnimationFrame(function () { raf = 0; place(); }); }

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
  // ---------- 720p over the 360p mini while expanded (header comment). Every 50 ms while big: the master's clock leads, hd follows ----------
  var hd = null, hdTimer = 0, hdAt = -1, hdTries = 0, hdOff = false;
  function hdGo() { if (!hdTimer && !hdOff && video && /-360\./.test(video.currentSrc)) hdTimer = setInterval(hdTick, 50); }
  function hdStop() { clearInterval(hdTimer); hdTimer = 0; }
  function hdHide() { hd.classList.remove('on'); }
  function hdDrop() {   // minimized, or the master starving / paused by the browser: stop the download (a re-expand starts again)
    if (!hd) return;
    hdStop();
    hd.pause(); hd.removeAttribute('src'); hd.load(); hd.remove(); hd = null; hdAt = -1; hdTries = 0;
  }
  function hdMake() {   // first expand, once the master can play: same container, so no <source> list; after the master: querySelector still finds that
    var d = video.ownerDocument;
    hd = d.createElement('video');
    hd.className = 'vo-video pip-hd';
    hd.muted = true; hd.setAttribute('muted', '');
    hd.playsInline = true; hd.setAttribute('playsinline', '');
    hd.disablePictureInPicture = true; hd.setAttribute('disablepictureinpicture', ''); hd.setAttribute('disableremoteplayback', '');
    hd.setAttribute('aria-hidden', 'true'); hd.setAttribute('tabindex', '-1');
    hd.preload = 'auto';
    hd.src = video.currentSrc.replace('-360.', '.');
    video.parentNode.insertBefore(hd, video.nextSibling);
  }
  function hdSeek(t) {   // t, else ahead of the master (1, 2, 4, 8 s: it waits there until the master arrives; never past the end: stays on the mini)
    var at = t != null ? t : video.currentTime + Math.min(8, Math.pow(2, hdTries++));
    if (at > video.duration - 0.2) return;
    if (!hd.paused) hd.pause();
    hdAt = at; hd.currentTime = at;
  }
  function hdTick() {
    if (!big) { hdStop(); hdDrop(); return; }   // minimized / closed: the mini plays on
    if (!hd) { if (video.readyState >= 3) hdMake(); return; }
    if (hd.readyState < 1) return;
    var m = video.currentTime, d = m - hd.currentTime, lag = Math.abs(d);
    if (lag > 0.15) hdHide();
    if (video.paused || video.ended) {   // follows it, frame for frame
      if (!hd.paused) { hd.pause(); hdAt = hd.currentTime; }   // play again = from here
      if (lag > 0.04 && !hd.seeking) hdSeek(m);
      return;
    }
    if (hd.paused) {   // waiting at hdAt: late (or the master jumped back, a replay) = further ahead
      var ready = !hd.seeking && hd.readyState >= 3;
      if (m > hdAt + (ready ? 0.15 : 0) || hdAt - m > 9) return hdSeek();
      if (ready && m >= hdAt - 0.02) {
        hd.playbackRate = 1;
        var p = hd.play();
        if (p && p.catch) p.catch(function (e) { if (e.name === 'NotAllowedError') hdDrop(); });
      }
      return;
    }
    if (lag > 0.5) return hdSeek();
    if (hd.readyState < 3) return hdHide();
    var r = lag < 0.03 ? 1 : lag < 0.15 ? (d > 0 ? 1.03 : 0.97) : (d > 0 ? 1.1 : 0.9);
    if (hd.playbackRate !== r) hd.playbackRate = r;
    if (lag <= 0.15 && !hd.classList.contains('on')) { hd.classList.add('on'); hdTries = 0; }
  }
  function expand() {
    if (big || S.t || closing) return;
    big = true;
    flip(place);
    if (video) { video.muted = false; play(); }
    hdGo();
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
    S.t = side; S.c = 0; S.u = 1; place(); sync();
  }
  function untuck() {
    if (closing) { clearTimeout(closing); closing = 0; pip.classList.remove('closing'); }
    S.t = ''; S.c = 0; backAt = Date.now(); place();
    if (video && wasPlaying) play();
    sync();
  }
  function close() {   // X: hidden behind a tab at the top-right corner (never gone); the tab = back to the same spot / dock.
    // Animated, 1 s from expanded: 0.5 s down to the floating spot (never the dock), then 0.5 s off the right edge; from the mini: just the slide
    if (closing || S.t || Date.now() - backAt < 500) return;   // the tab's tap: its click lands where the X comes back
    if (video) { wasPlaying = !video.paused; video.pause(); }
    pip.classList.add('closing');
    var off = function () {
      S.t = 'r'; S.c = 1; place(); sync();
      tab.focus();
      closing = setTimeout(function () { closing = 0; pip.classList.remove('closing'); }, 500);
    };
    if (!big && mode !== 'dock') return off();
    big = false; pip.classList.remove('drag');
    closing = setTimeout(off, 500);
    flip(place); sync();
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
    S.p = k; S.w = w; S.u = 1; place();
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
    var side = px < -w * 0.4 ? 'l' : px + w > W + w * 0.4 ? 'r' : '', down = !side && py + h > vh() + h * 0.4;   // past a side / the bottom
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
    // a tap counts here too: WebKit (iPhone) sends no click for it once the page is scrolled (the pointer was captured)
    if (Math.abs(dx) <= 16 || (S.t === 'l' && dx > 16) || (S.t === 'r' && dx < -16)) {
      tmoved = true; setTimeout(function () { tmoved = false; }, 400); untuck(); setTimeout(function () { snd.focus(); }, 0);
    }
  }

  // ---------- the scan card (expanded, wide screens): OnlyFans + Instagram / X, Scan now. The landing = its own hero form
  // (in-page scan, then the mini so the live report shows; the video turns hers when it lands); elsewhere = GET <site>/?scan=&ig= (the landing runs it in the hero) ----------
  function scanCard() {
    sc = document.createElement('form');
    sc.className = 'pip-card'; sc.method = 'get'; sc.action = new URL('../', me.src).href;
    sc.setAttribute('aria-label', 'Free scan'); sc.setAttribute('inert', '');
    sc.innerHTML = '<p class="pip-card-k">Free scan</p><p class="pip-card-t">Type your name <span>→ get YOUR video</span></p>' +
      '<label class="pip-card-f"><span aria-hidden="true">onlyfans.com/</span><input name="scan" type="text" maxlength="200" autocomplete="off" autocapitalize="none" spellcheck="false" required placeholder="username" aria-label="OnlyFans username"></label>' +
      '<label class="pip-card-f"><span aria-hidden="true">@</span><input name="ig" type="text" maxlength="200" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="Instagram or X (optional)" aria-label="Instagram or X username (optional)"></label>' +
      '<button type="submit">Scan now</button><p class="pip-card-n">Free. No account. You see every link it finds.</p>';
    sc.addEventListener('submit', function (e) {
      var f = auto === 'dock' && document.getElementById('scan');
      if (!f || !f.requestSubmit || !f.elements.h) return;   // not the landing: GET it
      e.preventDefault();
      f.elements.h.value = sc.elements.scan.value; f.elements.ig.value = sc.elements.ig.value; f.elements.ig.removeAttribute('data-net');
      minimize();
      f.requestSubmit();
    });
    document.body.appendChild(sc);
  }

  function mount() {
    if (mounted) return;
    if (auto === 'r' && !forced && !slug()) return;   // the report page before its result: wait (the URL gets ?r= once it renders)
    mounted = true;
    ['scroll', 'pointerdown', 'keydown'].forEach(function (ev) { removeEventListener(ev, mount, true); });
    card = auto === 'dock' ? document.querySelector('.hero .report-card') : null;
    pip = document.createElement('div');
    pip.className = 'pip';
    pip.setAttribute('role', 'region');
    pip.setAttribute('aria-label', "Jack's video");
    pip.innerHTML = '<div class="pip-pic"><div class="pip-hit"></div><div class="pip-rs" role="button" tabindex="0" aria-label="Resize video (arrow keys)">' + I.rs +
      '</div><button class="pip-x" type="button" aria-label="Close video">' + I.x + '</button></div><div class="pip-bar"><button class="pip-pp" type="button">' + I.pp +
      '</button><button class="pip-snd" type="button"></button><i></i><button class="pip-exp" type="button"></button><button class="pip-fl" type="button" aria-label="Floating player">' + I.fl + '</button></div>';
    pic = pip.querySelector('.pip-pic');
    // the poster by fetch(), shown from a blob: a CSS / <img> load would hold the page's load event (and a later load event
    // lets the landing's own report thumbs hold it seconds more: measured 1.0 s -> 5.0 s with a stored scan)
    var still = document.querySelector('.pip-still'), lq = still ? still.style.backgroundImage : '';
    if (lq) pic.style.backgroundImage = lq;
    fetch(new URL('jack-poster.webp', VIDEO)).then(function (r) { return r.ok ? r.blob() : null; })
      .then(function (b) { if (b) pic.style.backgroundImage = 'url(' + URL.createObjectURL(b) + ')' + (lq && ',' + lq); }).catch(function () {});   // the still under it until its bytes decode: no black frame
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
    scanCard();
    var sh = document.querySelector('.site-header');
    if (sh) { push = document.createElement('div'); push.className = 'pip-push'; push.setAttribute('aria-hidden', 'true'); sh.parentNode.insertBefore(push, sh.nextSibling); }
    if (card && 'ResizeObserver' in window) new ResizeObserver(soon).observe(card);
    if (window.visualViewport) visualViewport.addEventListener('resize', soon);   // height only (URL bar): the box stays (keep() clamps)
    pip.classList.add('on');   // the box + poster at once
    place();
    if (still) still.remove();

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
    pp.addEventListener('click', function () {
      if (!big && innerWidth < 720 && (!video || video.paused)) return expand();   // phone: Play = the expanded player, sound on
      if (!video) return;
      if (video.paused) play(); else video.pause(); sync();
    });
    xb.addEventListener('click', close);
    exp.addEventListener('click', function () { if (big) minimize(); else expand(); });
    pip.querySelector('.pip-fl').addEventListener('click', function () { S.u = 1; minimize(); });   // the floating mini (top-right, follows the scroll), never the dock
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
    addEventListener('scroll', place, { passive: true });   // in the scroll event (before the frame paints): dock in / out, no frame late
    addEventListener('resize', soon);

    var shown = false;
    function show() { if (shown) return; shown = true; pip.classList.add('live'); place(); sync(); }   // the iframe over the poster
    function hook() {   // the iframe's <video>, as soon as its DOM has it (its load event waits for every image of the page)
      if (video) return true;
      var d, v;
      try { d = frame.contentDocument; v = d && d.URL !== 'about:blank' && d.querySelector('.vo-video'); } catch (e) { v = null; }
      if (!v) return false;
      var st = d.createElement('style');
      st.textContent = EMBED;
      (d.head || d.documentElement).appendChild(st);
      video = v;
      video.muted = true;
      video.controls = false;
      video.disablePictureInPicture = true;
      video.setAttribute('disablepictureinpicture', '');
      video.setAttribute('disableremoteplayback', '');
      ['play', 'pause', 'volumechange'].forEach(function (ev) { video.addEventListener(ev, sync); });
      video.addEventListener('waiting', function () { if (!video.seeking) hdDrop(); });
      var mine = false, pause = video.pause;   // every script's pause (button, tap, tuck, X, off-screen, the overlays') comes through here, a browser's own doesn't
      video.pause = function () { if (!video.paused) mine = true; pause.call(video); };
      video.addEventListener('pause', function () {
        if (mine) { mine = false; return; }
        if (hd && big && !video.ended && !document.hidden) { hdOff = true; hdDrop(); play(); }
      });
      if (video.readyState >= 2) show(); else video.addEventListener('loadeddata', show, { once: true });
      if (!S.t && !offPaused) play();
      if (big) hdGo();
      sync();
      return true;
    }
    var poll = setInterval(function () { if (hook()) clearInterval(poll); }, 50);
    var go = function () {   // at the page's load event (an iframe started before it holds it: its images too)
      frame.addEventListener('load', function () { clearInterval(poll); if (!hook()) show(); });   // not the initial about:blank's
      frame.src = src();
    };
    if (document.readyState === 'complete') go(); else addEventListener('load', go, { once: true });
    setTimeout(show, 8000);
    new IntersectionObserver(function (en) {   // off-screen = paused (and back on when it returns)
      var seen = en[0].isIntersecting;
      if (!video || S.t) return;
      if (!seen && !video.paused) { offPaused = true; video.pause(); }
      else if (seen && offPaused) { offPaused = false; play(); }
    }, { rootMargin: '200px' }).observe(pip);
  }
  // as soon as this deferred script runs (DOM parsed, CSS in); the report page before its result waits for the URL's ?r=
  mount();
  if (!mounted) {   // the report page: once its result is in (the URL has ?r= then)
    ['scroll', 'pointerdown', 'keydown'].forEach(function (ev) { addEventListener(ev, mount, { capture: true, passive: true }); });
    document.addEventListener('leakscan:result', function () { setTimeout(mount, 0); });
  }
})();
