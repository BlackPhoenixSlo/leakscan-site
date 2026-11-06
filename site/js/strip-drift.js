// Landing hero: the film strip of what Google Images shows drifts by itself (js/inline-scan.js builds the strip and calls
// LeakScanDrift.start). One strip at a time.
(function () {
  'use strict';
  // ~4 s after the result shows, if the visitor does nothing, the strip scrolls itself slowly (rAF, ping-pong, a pause
  // at each end). Hover / focus pauses it; a tap, click, wheel or key on the strip stops it for good; any page activity
  // before it starts restarts the wait. Only while the strip is on screen, its tab is showing and the page is visible.
  // Never under prefers-reduced-motion. While it moves, the inner track slides with translate3d (sub-pixel, on the
  // compositor: smooth at 24 px/s); whenever it pauses or stops, the position goes back into the scroller's scrollLeft,
  // so swipe, arrows and focus carry on from there. Nothing else moves, the card never changes size.
  var DRIFT_WAIT = 4000, DRIFT_SPEED = 24, DRIFT_HOLD = 1400, drifter = null;
  var reduce = function () { return !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches); };
  // box → {hover, seen}: hover / focus inside it, its strip on screen. Bound once per box (a Play restart reuses them).
  var boxes = new WeakMap();
  function watch(box, strip) {
    var st = boxes.get(box);
    if (st) return st;
    st = { hover: false, seen: !window.IntersectionObserver };
    var pause = function (on) { return function () { st.hover = on; }; };
    box.addEventListener('mouseenter', pause(true));
    box.addEventListener('mouseleave', pause(false));
    box.addEventListener('focusin', pause(true));
    box.addEventListener('focusout', pause(false));
    if (window.IntersectionObserver) new IntersectionObserver(function (es) { st.seen = es[es.length - 1].isIntersecting; }).observe(strip);
    boxes.set(box, st);
    return st;
  }
  // start(box, strip, panel, now, onMove): drift `strip` (inside `box`, on tab panel `panel`); now = no idle wait first;
  // onMove(x) on every drifted frame (the strip's scrollLeft stays put while it moves: see x()).
  function drift(box, strip, panel, now, onMove) {
    if (drifter) drifter.stop();
    drifter = null;
    if (reduce() || !window.requestAnimationFrame) return;
    var btn = box.querySelector('.live-strip-pause');
    var auto = function (on) {
      box.setAttribute('data-auto', on ? 'on' : 'off');
      if (btn) { btn.setAttribute('aria-label', on ? 'Pause slideshow' : 'Play slideshow'); btn.title = btn.getAttribute('aria-label'); }
    };
    var d = { box: box, dead: false, armed: false, raf: 0, timer: 0 }, st = watch(box, strip);
    if (now) st.hover = false;   // Play: a deliberate restart, though pointer / focus are still on its button
    var track = strip.firstElementChild, pos = 0, dir = 1, hold = 0, t0 = 0, max = 0, moving = false;
    var lift = function () {   // scrollLeft → transform (same frame: no visual jump)
      moving = true;
      pos = strip.scrollLeft;
      strip.scrollLeft = 0;
      track.style.transform = 'translate3d(' + -pos + 'px, 0, 0)';
    };
    var settle = function () {   // transform → scrollLeft
      if (!moving) return;
      moving = false;
      track.style.transform = '';
      strip.scrollLeft = pos;
    };
    d.strip = strip;
    d.x = function () { return moving ? pos : strip.scrollLeft; };
    d.stop = function () {
      settle();
      d.dead = true;
      clearTimeout(d.timer);
      if (d.raf) cancelAnimationFrame(d.raf);
      strip.removeAttribute('data-drift');
      auto(false);
      if (drifter === d) drifter = null;
    };
    var frame = function (t) {
      d.raf = 0;
      if (d.dead || !strip.isConnected) return d.stop();
      var dt = t0 ? Math.min(64, t - t0) : 0;
      t0 = t;
      if (!moving) max = strip.scrollWidth - strip.clientWidth;
      if (max > 1 && st.seen && !st.hover && !panel.hidden && !document.hidden) {
        if (!moving) lift();
        if (hold > 0) hold -= dt;
        else {
          pos += dir * DRIFT_SPEED * dt / 1000;
          if (dir > 0 && pos >= max) { pos = max; dir = -1; hold = DRIFT_HOLD; } else if (dir < 0 && pos <= 0) { pos = 0; dir = 1; hold = DRIFT_HOLD; }
          track.style.transform = 'translate3d(' + (-pos).toFixed(2) + 'px, 0, 0)';
          if (onMove) onMove(pos);
        }
      } else settle();
      d.raf = requestAnimationFrame(frame);
    };
    d.start = function () {
      if (d.dead || d.armed) return;
      d.armed = true;
      strip.setAttribute('data-drift', 'on');
      d.raf = requestAnimationFrame(frame);
    };
    d.wait = function () { clearTimeout(d.timer); if (!d.armed && !d.dead) d.timer = setTimeout(d.start, DRIFT_WAIT); };
    drifter = d;
    auto(true);   // the Stop / Play button (hidden under reduced motion: no data-auto at all)
    if (now) d.start(); else d.wait();
  }
  ['pointerdown', 'keydown', 'wheel', 'touchstart'].forEach(function (k) {
    document.addEventListener(k, function (e) {
      var d = drifter;
      if (!d || d.dead || (e.target.closest && e.target.closest('.live-strip-pause'))) return;   // the button decides itself
      if (d.box.contains(e.target)) d.stop(); else if (!d.armed) d.wait();
    }, { capture: true, passive: true });
  });
  window.LeakScanDrift = {
    start: drift,
    stop: function () { if (drifter) drifter.stop(); },
    // the running strip's scroll position, or null when `strip` is not the one drifting
    x: function (strip) { return drifter && drifter.strip === strip ? drifter.x() : null; },
    owns: function (box) { return !!drifter && drifter.box === box; }
  };
})();
