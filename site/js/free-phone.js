// #free: one phone, Google for her handle. After a scan its All / Images / Videos tabs show her real results
// (js/inline-scan.js calls LeakScanFreePhone.render / reset); no scan or nothing found = the illustration stays.
// The screen has a fixed height: each tab scrolls inside it, shows twice its illustration's count, "Show more" adds as
// many again.
(function () {
  'use strict';
  var E = window.LeakScanEngine, phone = document.querySelector('.phone-free');
  if (!E || !phone) return;
  var make = E.make, pager = E.pager;
  var panel = function (k) { return document.getElementById('panel-free-' + k); };
  var fits = function (k, sel, dflt) { var p = panel(k); return (p && p.querySelectorAll('.m-illus ' + sel).length) || dflt; };
  var ROWS = 2 * fits('all', '.m-result', 4), TILES = 2 * fits('images', '.gi-card', 9), VIDEOS = 2 * fits('videos', '.m-video', 3);
  var saved = null, pics = null;

  function reset() {
    if (pics) { pics.close(); pics = null; }
    if (!saved) return;
    phone.classList.remove('is-live', 'revealed');
    Array.prototype.forEach.call(phone.querySelectorAll('[data-live]'), function (el) { el.remove(); });
    phone.setAttribute('aria-label', saved.label);
    if (saved.send) saved.send.setAttribute('href', saved.href);
  }
  // a result row like the before / after phones': letter avatar, site, title; the whole row opens it (new tab)
  function row(cls, url, dom, title, lead) {
    return make('div', cls + ' is-link', [make('a', 'm-link', [lead, make('div', '', [make('span', 'm-site', [dom]), make('span', 'm-title', [title])]),
      make('span', 'm-go', ['↗'], { 'aria-hidden': 'true' })], Object.assign({ href: url, 'aria-label': dom + ': ' + title + ' (opens in a new tab)' }, E.NEW_TAB))]);
  }
  var titleOf = function (t, url) { return t || url.replace(/^https?:\/\/(www\.)?/, ''); };
  // a plain list (All, Videos): its next items appended, mk(item) each
  var list = function (box, items, mk) { return function (n) { items.slice(box.children.length, n).forEach(function (it) { box.appendChild(mk(it)); }); }; };
  // m: E.reportModel(...); the images are its own E.gallery (thumb verdicts are shared page-wide: one dies, it leaves all):
  // every image, video stills too (last), so its count is where "Show more" ends
  function render(m) {
    var send = document.querySelector('[data-free-send]');
    if (!saved) saved = { label: phone.getAttribute('aria-label'), send: send, href: send && send.getAttribute('href') };
    reset();
    // "Send me the report" → Telegram with her report link (the other channels are in the hero card)
    if (send) send.setAttribute('href', E.reportLinks(m.slug, m.handle, m.platform).tg);
    if (!m.rows.length || !panel('all') || !panel('images') || !panel('videos')) return;   // the phone stays the illustration
    phone.classList.add('is-live');
    phone.setAttribute('aria-label', 'Google results for @' + m.handle);
    var put = function (k, kids) { panel(k).appendChild(make('div', '', kids, { 'data-live': 'free-' + k })); };
    var rows = make('div'), more = pager(rows, ROWS, list(rows, m.rows, function (r) {
      var f = make('span', 'fav fav-l', [r.domain.charAt(0).toUpperCase()], { 'aria-hidden': 'true' });
      f.style.background = E.favColor(r.domain);
      return row('m-result bad', r.url, r.domain, titleOf(r.title, r.url), f);
    }), function (n) { return n < m.rows.length; });
    put('all', [rows, more.el]);
    var empty = function (what) { return [make('p', 'm-empty', [m.expired ? 'This scan’s ' + what + ' results have expired.' : 'No ' + what + ' results for @' + m.handle + ' right now.'])]; };
    pics = E.gallery(m.images, m.slug);
    if (pics.count().alive) {
      var n = make('span', 'm-n'), box = make('div', 'm-grid'), tile = pics.tile(true);
      // view() again on its box = a new max; a dead tile leaves and the next takes its slot, so "more" = more alive
      var gm = pager(box, TILES, function (k) { pics.view(box, k, tile); }, function (k) { return pics.count().alive > k; });
      put('images', [make('div', 'm-head', [n, E.revealButton(phone)]), box, gm.el]);
      pics.onCount(function (c) { n.textContent = c.text + (c.text === '1' ? ' image' : ' images'); gm.sync(); });
    } else put('images', empty('image'));
    var vids = make('div'), vm = m.videos.length && pager(vids, VIDEOS, list(vids, m.videos, function (v) {
      var img = v.thumb && make('img', 'gi-img', [], { alt: '', loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer' });
      // a dead still / no person photo (a site logo): the grey 16:9 box with its play mark stays, the row too. Shown
      // only once its verdict passed (E.photo), from that load's cached copy (E.put)
      if (img) {
        img.addEventListener('error', function () { img.remove(); }, { once: true });
        E.photo(v.thumb, function (ok) { if (ok) E.put(img, v.thumb); else img.remove(); });
      }
      return row('m-video bad', v.link, v.domain, titleOf(v.title, v.link), make('span', 'm-vthumb', [img, make('span', 'm-play', [], { 'aria-hidden': 'true' })]));
    }), function (k) { return k < m.videos.length; });
    put('videos', vm ? [make('div', 'm-head', [make('span', 'm-n', [m.videos.length + ' ' + E.plural(m.videos.length, 'video', 'videos')]), E.revealButton(phone)]),
      vids, vm.el] : empty('video'));
  }
  window.LeakScanFreePhone = { render: render, reset: reset };
})();
