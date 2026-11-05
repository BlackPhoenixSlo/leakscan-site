// #removals "Where I remove from": four mock panels (Mega, X, Reddit, a leak site), each a live leak vs. its removed
// state. Remove / Show again animates the compare edge; the handle (drag anywhere on the stage, arrow keys on the
// handle) moves it: left of it = the live leak, right = removed. Own file so it merges next to other work.
// Personalized from the scan result the page already fetches (?r=<slug> or the last scan: js/scan-engine.js
// fetchResult, one request shared with the hero card), and again after an in-page scan (wraps LeakScanPersonalize.apply).
// textContent only; leak URLs are read for their host / subreddit / poster, never rendered or linked.
// model() is defined before the #removals check and exposed as LeakScanRemovals.model (the video page has no #removals).
(function () {
  'use strict';
  // ---------- personalization ----------
  var HANDLE_RE = /^[A-Za-z0-9._-]{1,60}$/, SLUG_RE = /^[A-Za-z0-9_-]{4,64}$/, GSTATIC_RE = /^https:\/\/[a-z0-9-]+\.gstatic\.com\/[^\s"'<>\\]*$/;
  var NOT_LEAK = /(^|\.)(x|twitter|reddit|redd|mega|instagram|tiktok|onlyfans|fansly|patreon|youtube|threads|twitch|google|facebook)\.(com|net|tv|it|nz|io)$/;
  function str(v, max) {
    if (typeof v !== 'string') return null;
    var s = v.replace(/[\u0000-\u001f\u007f\u200b-\u200f\u2028-\u202e]/g, ' ').replace(/\s+/g, ' ').trim();
    return s && s.length <= max && !/[<>{}]|javascript:|data:|https?:\/\/|www\./i.test(s) ? s : null;
  }
  var cut = function (s, n) { return s && s.length > n ? s.slice(0, n - 1).replace(/\s+\S*$/, '') + '\u2026' : s; };
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
  function dom(v) {
    var d = typeof v === 'string' ? v.trim().toLowerCase().replace(/^www\./, '') : '';
    return d.length <= 80 && /^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(d) ? d : null;
  }
  function path(u) {
    try { var x = new URL(u); return /^https?:$/.test(x.protocol) ? x.pathname : ''; } catch (e) { return ''; }
  }
  function model(raw) {
    if (!raw || typeof raw !== 'object') return null;
    var h = typeof raw.handle === 'string' ? raw.handle.trim().replace(/^@/, '') : '';
    if (!HANDLE_RE.test(h)) return null;
    var pr = raw.profile && typeof raw.profile === 'object' ? raw.profile : {};
    var name = str(pr.display_name, 60) || str(pr.first_name, 30) || h;
    var plat = (dom(raw.platform) || 'onlyfans.com').split('.')[0];
    var hits = (Array.isArray(raw.hits) ? raw.hits : []).slice(0, 1000).filter(function (x) { return x && dom(x.domain); });
    var on = function (re) { return hits.filter(function (x) { return re.test(dom(x.domain)); }); };
    var m = { name: name, handle: h, plat: plat };
    // X: the post's text + poster (first path segment) from an x.com / twitter.com hit
    var xh = on(/(^|\.)(x|twitter)\.com$/)[0];
    var xp = xh && /^\/([A-Za-z0-9_]{1,15})(\/|$)/.exec(path(xh.url));
    if (xp && !/^(i|search|hashtag|home|explore)$/i.test(xp[1])) m.xat = '@' + xp[1];
    if (xh) m.xtext = cut(str(xh.title, 300) && str(xh.title, 300).replace(/\s*\/\s*(X|Twitter)$/, ''), 90);
    // Reddit: subreddit from the URL, title from the hit
    var rh = on(/(^|\.)reddit\.com$/)[0];
    var rs = rh && /^\/r\/([A-Za-z0-9_]{2,21})\//.exec(path(rh.url));
    if (rs) m.sub = 'r/' + rs[1];
    if (rh) m.rtitle = cut(str(rh.title, 300) && str(rh.title, 300).replace(/\s*(:\s*r\/\w+|[-|]\s*Reddit)$/i, ''), 110);
    // Mega: the backend's top-level mega[] (always there, [] = none: title, size in bytes, images, videos, age ISO UTC; its url /
    // host are an aggregator share page, never shown); else a mega.nz hit's title
    var mg = (Array.isArray(raw.mega) ? raw.mega : []).filter(function (x) { return x && typeof x === 'object'; })[0];
    if (mg) {
      m.mtitle = cut(str(mg.title, 200), 70);
      m.mimg = num(mg.images); m.mvid = num(mg.videos);
      m.mmeta = [bytes(mg.size), m.mimg !== null ? m.mimg + ' images' : null, m.mvid !== null ? m.mvid + ' videos' : null, ago(mg.age)]
        .filter(Boolean).join(' · ') || null;
    } else {
      var mh = on(/(^|\.)mega\.(nz|io)$/)[0];
      if (mh) m.mtitle = cut(str(mh.title, 200) && str(mh.title, 200).replace(/\s*[-|]\s*MEGA$/i, ''), 70);
    }
    // custom leak site: the most-seen other host
    var occ = {};
    hits.forEach(function (x) {
      var d = dom(x.domain);
      if (!NOT_LEAK.test(d)) occ[d] = (occ[d] || 0) + (typeof x.occurrences === 'number' && x.occurrences > 0 ? Math.min(x.occurrences, 1e6) : 1);
    });
    m.host = Object.keys(occ).sort(function (a, b) { return occ[b] - occ[a]; })[0] || null;
    var E = window.LeakScanEngine;
    m.thumbs = E && E.thumb ? (Array.isArray(raw.images) ? raw.images : []).filter(function (u) {
      return typeof u === 'string' && u.length <= 600 && GSTATIC_RE.test(u);
    }).slice(0, 10).map(E.thumb).filter(Boolean) : [];
    return m;
  }

  window.LeakScanRemovals = { model: model };   // site/js/video-overlays.js reuses the same validation

  var root = document.getElementById('removals');
  if (!root) return;
  var each = function (list, fn) { Array.prototype.forEach.call(list, fn); };

  // ---------- compare: --p = edge position in % (100 = all live, 0 = all removed) ----------
  function set(card, p, anim) {
    p = Math.max(0, Math.min(100, Math.round(p)));
    var stage = card.querySelector('.rm-stage'), h = card.querySelector('.rm-handle'), b = card.querySelector('.rm-btn'), gone = p <= 50;
    stage.classList.toggle('rm-anim', !!anim);
    stage.style.setProperty('--p', p);
    stage.setAttribute('data-end', p >= 95 ? 'r' : p <= 5 ? 'l' : '');
    card.classList.toggle('is-removed', gone);
    h.setAttribute('aria-valuenow', p);
    h.setAttribute('aria-valuetext', p === 100 ? 'Leak live' : p === 0 ? 'Removed' : p + '% leak, ' + (100 - p) + '% removed');
    b.setAttribute('aria-pressed', String(gone));
    b.textContent = gone ? 'Show again' : 'Remove';
  }
  var now = function (card) { return +card.querySelector('.rm-handle').getAttribute('aria-valuenow'); };
  each(root.querySelectorAll('.rm-card'), function (card) {
    var stage = card.querySelector('.rm-stage'), h = card.querySelector('.rm-handle'), drag = null;
    card.querySelector('.rm-btn').addEventListener('click', function () { set(card, now(card) <= 50 ? 100 : 0, true); });
    var at = function (e) { var r = stage.getBoundingClientRect(); return (e.clientX - r.left) / r.width * 100; };
    stage.addEventListener('pointerdown', function (e) {
      if (e.button !== 0) return;
      drag = e.pointerId;
      try { stage.setPointerCapture(e.pointerId); } catch (x) { /* ignore */ }
      set(card, at(e), false);
      if (e.pointerType !== 'touch') h.focus({ preventScroll: true });
    });
    stage.addEventListener('pointermove', function (e) { if (drag === e.pointerId) set(card, at(e), false); });
    var end = function (e) { if (drag === e.pointerId) drag = null; };
    stage.addEventListener('pointerup', end);
    stage.addEventListener('pointercancel', end);   // a vertical swipe (touch-action: pan-y) scrolls the page instead
    h.addEventListener('keydown', function (e) {
      var p = now(card), k = e.key, n = k === 'ArrowLeft' || k === 'ArrowDown' ? p - 10 : k === 'ArrowRight' || k === 'ArrowUp' ? p + 10
        : k === 'PageDown' ? p - 25 : k === 'PageUp' ? p + 25 : k === 'Home' ? 0 : k === 'End' ? 100 : null;
      if (n === null) return;
      e.preventDefault();
      set(card, n, false);
    });
    set(card, 100, false);
  });
  var rev = root.querySelector('.rm-reveal');
  if (rev) rev.addEventListener('click', function () {
    var on = rev.getAttribute('aria-pressed') !== 'true';
    rev.setAttribute('aria-pressed', String(on));
    root.classList.toggle('revealed', on);
    rev.lastChild.textContent = on ? 'Blur images' : 'Reveal images';
  });

  // defaults (the demo creator) kept so a second result / no data puts them back
  var DEF = {}, IMGS = root.querySelectorAll('.rm-img'), DEF_IMG = [];
  each(root.querySelectorAll('[data-rm-k]'), function (el) { DEF[el.getAttribute('data-rm-k')] = el.textContent; });
  each(IMGS, function (im) { DEF_IMG.push(im.getAttribute('src')); });
  function render(m) {
    var v = {
      name: m.name,
      'mega-title': m.mtitle || m.handle + ' \u2013 pack', 'mega-meta': m.mmeta || DEF['mega-meta'],
      'mega-img': (m.mimg != null ? m.mimg : 369) + ' files', 'mega-vid': (m.mvid != null ? m.mvid : 1069) + ' files',
      'x-at': m.xat || DEF['x-at'], 'x-name': m.xat ? m.xat.slice(1) : DEF['x-name'], 'x-av': m.xat ? m.xat.charAt(1).toUpperCase() : DEF['x-av'],
      'x-l1': m.xtext || m.name + ' leaked', 'x-l2': m.xtext ? '' : m.name + ' ' + m.plat,
      sub: m.sub || 'r/' + (m.handle.replace(/[^A-Za-z0-9_]/g, '').slice(0, 14) || 'creator') + '_leaks',
      'rd-title': m.rtitle || m.name + ' full pack, link in comments',
      host: m.host || DEF.host, album: m.name + ' \u2013 album'
    };
    each(root.querySelectorAll('[data-rm-k]'), function (el) {
      var k = el.getAttribute('data-rm-k');
      if (v.hasOwnProperty(k) && el.textContent !== v[k]) el.textContent = v[k];
    });
    each(IMGS, function (im, i) {
      var src = m.thumbs.length ? m.thumbs[i % m.thumbs.length] : DEF_IMG[i];
      if (im.getAttribute('src') === src) return;
      if (m.thumbs.length) {
        im.referrerPolicy = 'no-referrer';
        im.addEventListener('error', function () { if (im.getAttribute('src') === src) im.setAttribute('src', DEF_IMG[i]); }, { once: true });
      }
      im.setAttribute('src', src);
    });
    root.setAttribute('data-rm-for', m.handle);
  }
  function apply(raw) { var m = model(raw); if (m) render(m); }

  var E = window.LeakScanEngine, P = window.LeakScanPersonalize;
  if (P && typeof P.apply === 'function') {   // an in-page scan re-personalizes the page through this
    var orig = P.apply;
    P.apply = function (r) { var ok = orig.apply(this, arguments); if (ok) apply(r); return ok; };
  }
  var slug = null, mr = /[?&]r=([^&#]*)/.exec(location.search);
  if (mr) { try { slug = decodeURIComponent(mr[1]); } catch (e) { slug = null; } }
  else { try { slug = (JSON.parse(localStorage.getItem('leakscan.last') || 'null') || {}).slug; } catch (e) { slug = null; } }
  if (E && E.fetchResult && typeof slug === 'string' && SLUG_RE.test(slug)) E.fetchResult(slug).then(apply, function () { /* defaults */ });
})();
