// #free: one phone, Google for her handle. After a scan its All / Images / Videos tabs show her real results
// (js/inline-scan.js calls LeakScanFreePhone.render / reset); no scan or nothing found = the illustration stays.
// Each tab shows as many live items as its illustration has (the screen has a fixed height).
(function () {
  'use strict';
  var E = window.LeakScanEngine, phone = document.querySelector('.phone-free');
  if (!E || !phone) return;
  var make = E.make;
  var panel = function (k) { return document.getElementById('panel-free-' + k); };
  var fits = function (k, sel, dflt) { var p = panel(k); return (p && p.querySelectorAll('.m-illus ' + sel).length) || dflt; };
  var ROWS = fits('all', '.m-result', 4), TILES = fits('images', '.gi-card', 9), VIDEOS = fits('videos', '.m-video', 3);
  var saved = null, pics = null, grid = null;

  function reset() {
    if (pics) { pics.close(); grid.close(); pics = grid = null; }
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
  // m: E.reportModel(...); the images are its own E.gallery (thumb verdicts are shared page-wide: one dies, it leaves all)
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
    put('all', m.rows.slice(0, ROWS).map(function (r) {
      var f = make('span', 'fav fav-l', [r.domain.charAt(0).toUpperCase()], { 'aria-hidden': 'true' });
      f.style.background = E.favColor(r.domain);
      return row('m-result bad', r.url, r.domain, titleOf(r.title, r.url), f);
    }));
    var empty = function (what) { return [make('p', 'm-empty', ['No ' + what + ' results for @' + m.handle + ' right now.'])]; };
    pics = E.gallery(m.images, m.slug);   // the count: every image
    var inVids = {};   // a still its Videos tab already shows stays out of the Images grid
    m.videos.slice(0, VIDEOS).forEach(function (v) { if (v.thumb) inVids[v.thumb] = 1; });
    grid = E.gallery(m.images.filter(function (it) { return !inVids[it.src]; }), m.slug);
    if (pics.count().alive) {
      var n = make('span', 'm-n');
      put('images', [make('div', 'm-head', [n, E.revealButton(phone)]), grid.view(make('div', 'm-grid'), TILES, grid.tile(true))]);
      pics.onCount(function (c) { n.textContent = c.text + (c.text === '1' ? ' image' : ' images'); });
    } else put('images', empty('image'));
    put('videos', m.videos.length ? [make('div', 'm-head', [make('span', 'm-n', [m.videos.length + ' ' + E.plural(m.videos.length, 'video', 'videos')]), E.revealButton(phone)])]
      .concat(m.videos.slice(0, VIDEOS).map(function (v) {
        var img = v.thumb && make('img', 'gi-img', [], { alt: '', loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer' });
        // a dead still / no person photo (a site logo): the grey 16:9 box with its play mark stays, the row too. Shown
        // only once its verdict passed (E.photo), from that load's cached copy (E.put)
        if (img) {
          img.addEventListener('error', function () { img.remove(); }, { once: true });
          E.photo(v.thumb, function (ok) { if (ok) E.put(img, v.thumb); else img.remove(); });
        }
        return row('m-video bad', v.link, v.domain, titleOf(v.title, v.link), make('span', 'm-vthumb', [img, make('span', 'm-play', [], { 'aria-hidden': 'true' })]));
      })) : empty('video'));
  }
  window.LeakScanFreePhone = { render: render, reset: reset };
})();
