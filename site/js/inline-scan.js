// Landing hero: the free-scan form runs the scan right here (js/scan-engine.js) instead of opening scan/. The hero card
// becomes the live report (Links / Images / Sites tabs + a film strip of what Google Images shows: js/strip-drift.js),
// the #free phone shows her real results (js/free-phone.js), and the `leakscan:result` event lets js/personalize.js and
// js/removals.js re-personalize the rest. Without JS the form still opens scan/. The page's report (E.currentSlug():
// ?r=, else the last scan) re-renders the hero card on load. Every API value is validated (E.reportModel); rendering is
// textContent / createElement only. Own elements only (never personalize's data-p slots).
(function () {
  'use strict';
  var E = window.LeakScanEngine, form = document.getElementById('scan'), card = document.querySelector('.report-card');
  if (!E || !form || !card || !window.fetch) return;
  var D = window.LeakScanDrift, F = window.LeakScanFreePhone, make = E.make, icon = E.icon;
  var ROWS = 5, MAX_SITES = 12, STRIP = 24, GRID_ROWS = 4;
  var btn = form.querySelector('button[type=submit]'), btnText = btn && btn.querySelector('.btn-t'), btnLabel = btnText && btnText.textContent;
  var token = 0, busy = false, live = null, msg = null, saved = null, pics = null;
  var P = function () { return window.LeakScanPersonalize; };
  var reduce = function () { return !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches); };
  var ext = function (attrs) { return Object.assign({}, E.NEW_TAB, attrs); };

  // ---------- form ----------
  function setBusy(on) {
    busy = on;
    form.setAttribute('aria-busy', String(on));
    if (btn) btn.disabled = on;
    if (btnText) btnText.textContent = on ? 'Scanning…' : btnLabel;
  }
  function formMsg(text, field) {
    if (!msg) { msg = make('p', 'inline-msg', [], { role: 'alert' }); form.parentNode.insertBefore(msg, form.nextSibling); }
    msg.textContent = text || '';
    msg.hidden = !text;
    if (text) form.elements[field || 'h'].focus();
  }
  form.noValidate = true; // own messages below, same rules as scan/
  // A pasted profile URL / @name becomes the bare handle in the field (on blur and on submit), so the field never shows
  // "onlyfans.com/https://…". An x.com link keeps its network on the field (data-net).
  function tidy() {
    var h = form.elements.h, ig = form.elements.ig, c = E.clean.handleInput(h.value), so = E.clean.social(ig.value, ig.getAttribute('data-net'));
    if (c && c !== h.value) h.value = c;
    if (so && so.handle !== ig.value) { ig.value = so.handle; if (so.net === 'x') ig.setAttribute('data-net', 'x'); }
  }
  form.elements.h.addEventListener('change', tidy);
  form.elements.ig.addEventListener('change', tidy);
  form.elements.ig.addEventListener('input', function () { form.elements.ig.removeAttribute('data-net'); });
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    if (busy) return;
    tidy();
    var h = E.clean.handleInput(form.elements.h.value), social = E.clean.social(form.elements.ig.value, form.elements.ig.getAttribute('data-net'));
    if (!h) return formMsg('That handle doesn’t look right. Use letters, numbers, dots, dashes or underscores, like yourhandle.');
    if (social === false) return formMsg('That Instagram or X username doesn’t look right. Paste the profile link or type the name, like yourname.', 'ig');
    formMsg('');
    scan(h, 'onlyfans.com', social);
  });

  // ---------- hero card: the live report ----------
  function heroReset() {
    if (D) D.stop();
    if (pics) { pics.close(); pics = null; }
    if (live) { live.remove(); live = null; }
    card.classList.remove('is-live');
    card.style.minHeight = '';
    card.removeAttribute('aria-busy');
    if (saved) { card.setAttribute('role', saved.role); card.setAttribute('aria-label', saved.label); }
  }
  function heroOpen(handle, platform) {
    heroReset();
    if (!saved) saved = { role: card.getAttribute('role'), label: card.getAttribute('aria-label') };
    card.style.minHeight = card.offsetHeight + 'px';   // never shorter than the illustration: no collapse while scanning
    card.removeAttribute('role');
    card.removeAttribute('aria-label');
    card.classList.add('is-live');
    live = make('div', 'live', [
      make('div', 'report-head', [
        make('div', '', [make('p', 'report-kicker live-kicker', ['Free scan · ' + E.PLATFORMS[platform]]),
          make('p', 'report-title live-title', ['@' + handle], { tabindex: '-1' }), make('p', 'live-socials', [], { hidden: '' }),
          make('p', 'live-aliases', [], { hidden: '' })]),
        make('div', 'live-head-end', [make('span', 'chip chip-live live-count', [], { hidden: '' }),
          make('a', 'live-open-top', ['Open full report ', make('span', '', ['→'], { 'aria-hidden': 'true' })], { hidden: '' })])]),
      make('p', 'live-status', [], { role: 'status' }),
      make('div', 'live-bar', [make('i')], { 'aria-hidden': 'true' }),
      // placeholder tabs, rows, image strip and actions while scanning, about the result's height (CSS hides them once
      // the card is no longer aria-busy): the card grows at the click, not when the result lands
      make('div', 'live-skel', [make('span', 'live-skel-tabs', [make('b'), make('b'), make('b')])]
        .concat([0, 1, 2, 3, 4].map(function () { return make('span', 'live-skel-row', [make('i'), make('b')]); }))
        .concat([make('span', 'live-skel-strip', [make('b'), make('span', '', [make('i'), make('i'), make('i'), make('i')])]),
          make('span', 'live-skel-act', [make('b'), make('b')])]), { 'aria-hidden': 'true' }),
      make('div', 'live-body')
    ], { 'data-reveal-scope': '' });
    card.appendChild(live);
    return live;
  }
  var q = function (sel) { return live && live.querySelector(sel); };
  function progress(text) {
    var p = E.progressInfo(text);
    q('.live-status').textContent = p.stage;
    if (p.pct != null) q('.live-bar i').style.width = p.pct + '%';
  }
  function msgLinks() {
    return make('p', 'live-send', [
      make('a', 'btn btn-ghost btn-sm', ['Telegram'], { 'data-msg': 'tg' }),
      make('a', 'btn btn-ghost btn-sm', ['WhatsApp'], { 'data-msg': 'wa' }),
      make('a', 'btn btn-ghost btn-sm', ['Email'], { 'data-msg': 'mail' })]);
  }
  // A row's icon: its thumb only once it passed the people check (E.photo: the image views' one verdict per thumb), else
  // the first person photo from the same site (another row's thumb, an image whose result is on that domain), else the
  // neutral letter (as a row with no thumb). Never another site's photo; a neutral tile until decided (no logo flashes).
  function rowIco(m, dom, src) {
    var ico = E.fav(dom, 'live-ico', null), seen = {};
    ico.style.background = '';
    var cands = [src].concat(m.rows.map(function (r) { return r.domain === dom && r.thumb; }), m.images.map(function (it) { return it.domain === dom && it.src; }))
      .filter(function (u) { return u && !seen[u] && (seen[u] = 1); });
    ico.classList.add(cands.length ? 'fav-wait' : 'fav-none');
    (function next(i) {
      if (i >= cands.length) { if (cands.length) { ico.classList.remove('fav-wait'); ico.classList.add('fav-none'); } return; }
      E.photo(cands[i], function (ok) {
        if (!ok) return next(i + 1);
        var im = make('img', '', [], { alt: '', loading: 'lazy', referrerpolicy: 'no-referrer', 'data-src': cands[i] });   // no decoding=async: as E.fav (an async-decoded row thumb stayed an empty slot)
        E.put(im, cands[i]);   // the passing load's cached copy: no second request
        im.addEventListener('load', function () { ico.classList.remove('fav-wait'); }, { once: true });
        im.addEventListener('error', function () { im.remove(); ico.classList.remove('fav-wait'); ico.classList.add('fav-none'); }, { once: true });
        ico.appendChild(im);
      });
    })(0);
    return ico;
  }
  function rowLink(m, url, dom, thumbSrc, text, chip, label) {
    var ico = rowIco(m, dom, thumbSrc);
    return make('a', 'live-link', [ico, make('span', 'live-txt', text), chip,
      make('span', 'live-go', [icon('i-external-link')])], ext({ href: url, 'aria-label': label }));
  }

  // ---------- hero card: the live report ----------
  // The card eases from the scanning height to the result's (no one-frame snap). Not on a page load, not under reduced motion.
  function grow(h0) {
    var h1 = card.offsetHeight;
    if (reduce() || !card.animate || Math.abs(h1 - h0) < 2) return;
    card.classList.add('is-growing');
    var a = card.animate([{ height: h0 + 'px' }, { height: h1 + 'px' }], { duration: 320, easing: 'cubic-bezier(.2, .7, .2, 1)' });
    a.onfinish = a.oncancel = function () { card.classList.remove('is-growing'); };
  }
  function heroResult(m, ease) {
    var h0 = card.offsetHeight;   // the visible height, mid-ease if the scan was quick: stop that ease, lay out for real
    if (card.getAnimations) card.getAnimations().forEach(function (a) { a.cancel(); });
    if (!live || live.getAttribute('data-handle') !== m.handle) heroOpen(m.handle, m.platform);
    var n = m.rows.length, body = q('.live-body');
    live.setAttribute('data-slug', m.slug);
    card.removeAttribute('aria-busy');
    q('.live-kicker').textContent = 'Free scan report · ' + E.PLATFORMS[m.platform];
    q('.live-title').textContent = '@' + m.handle;
    var soc = [['instagram', 'Instagram'], ['x', 'X']].filter(function (k) { return m.socials[k[0]]; })
      .map(function (k) { return k[1] + ' @' + m.socials[k[0]]; });
    q('.live-socials').textContent = soc.join(' · ');
    q('.live-socials').hidden = !soc.length;
    q('.live-aliases').textContent = m.discovered.length ? 'Also found as ' + m.discovered.map(function (a) { return '@' + a; }).join(', ') : '';
    q('.live-aliases').hidden = !m.discovered.length;
    q('.live-bar').hidden = true;
    var count = q('.live-count');
    count.textContent = n + ' ' + E.plural(n, 'link found', 'links found');
    count.className = 'chip live-count ' + (n ? 'chip-live' : 'chip-dead');
    count.hidden = false;
    var top = q('.live-open-top');
    top.href = E.reportUrl(m.slug);
    top.hidden = false;
    body.textContent = '';
    if (!n) {
      q('.live-status').textContent = '';
      body.appendChild(make('p', 'live-empty', [make('strong', '', ['No leaks found for @' + m.handle + ' right now.']),
        'Google shows no leak links for this handle at the moment. Send me the report and I’ll check by hand.']));
    } else {
      q('.live-status').textContent = ''; // the tab counts say it now
      var thumbs = {};
      m.sites.forEach(function (s) { thumbs[s.domain] = s.thumb; });
      // Links: the first rows (whole row = link) + the strip of what Google Images shows
      var links = make('div', 'live-panel', [make('ul', 'report-rows live-rows', m.rows.slice(0, ROWS).map(function (r) {
        var path = r.url.replace(/^https?:\/\/(www\.)?/, '');
        return make('li', '', [rowLink(m, r.url, r.domain, r.thumb || thumbs[r.domain],
          [make('span', 'live-dom', [r.domain]), make('span', 'live-ttl', [r.title || path])],
          make('span', 'chip live-badge ' + (r.badge === 'Live' ? 'chip-live' : 'chip-soft'), [r.badge]),
          r.domain + ': ' + (r.title || path) + ' (' + r.badge + ', opens in a new tab)')]);
      }))]);
      if (n > ROWS) links.appendChild(make('p', 'live-more', ['+ ' + (n - ROWS) + ' more in the full report']));
      var tabs = [['links', 'Links', n, links]], strip = null;
      pics = E.gallery(m.images, m.slug);
      if (pics.count().alive) {
        strip = heroStrip(m, pics, links);
        links.appendChild(strip.box);
        // Images: a grid of the first ones
        // rows x columns from CSS (--live-grid-rows / --live-grid-cols: phone 4 x 3, 4 x 4, the wide docket 2 x 8): fills the Links panel's height
        var cs = getComputedStyle(document.documentElement), GRID = (parseInt(cs.getPropertyValue('--live-grid-rows'), 10) || GRID_ROWS) * (parseInt(cs.getPropertyValue('--live-grid-cols'), 10) || 4);
        var imgsN = make('p'), imgsMore = make('a', 'live-more live-more-a', [], { href: E.reportUrl(m.slug) }), grid = make('div', 'live-panel', [
          make('div', 'live-imgs-head', [imgsN, E.revealButton(live)]), pics.view(make('div', 'live-grid'), GRID, pics.tile()), imgsMore]);
        tabs.push(['images', 'Images', pics.count().text, grid]);
      }
      // Sites: per site, its first link
      var sites = make('div', 'live-panel live-panel-sites', [make('ul', 'report-rows live-sites', m.sites.slice(0, MAX_SITES).map(function (s) {
        return make('li', '', [rowLink(m, s.url, s.domain, s.thumb, [make('span', 'live-dom', [s.domain]),
          make('span', 'live-ttl', [s.url.replace(/^https?:\/\/(www\.)?/, '')])],
          make('span', 'chip chip-soft', [s.n + ' ' + E.plural(s.n, 'link', 'links')]), s.domain + ': ' + s.n + ' ' + E.plural(s.n, 'link', 'links') + ' (opens its first link in a new tab)')]);
      }))]);
      sites.appendChild(make('a', 'live-more live-more-a', [], { href: E.reportUrl(m.slug) }));
      tabs.push(['sites', 'Sites', m.sites.length, sites]);
      body.appendChild(tabBar(tabs));
      body.appendChild(make('div', 'live-panels', tabs.map(function (t) { return t[3]; })));
      if (strip) {   // the counts say what shows (E.gallery: "24+" until every image is checked, never more)
        var tabN = body.querySelector('#tab-report-images .live-tab-n'), counts = function (c) {
          var sure = c.ok === c.alive;
          imgsN.textContent = c.text + (c.text === '1' ? ' image' : ' images') + ' on Google Images';
          imgsMore.textContent = sure ? '+ ' + (c.ok - GRID) + ' more in the full report' : 'More in the full report';
          imgsMore.hidden = c.alive <= GRID;
          tabN.textContent = c.text;
        };
        pics.onCount(counts);
      }
      fitSites(sites, m.sites.length);
      if (strip) strip.start(); else if (D) D.stop();
    }
    var send = msgLinks();
    body.appendChild(make('div', 'live-actions', [
      make('a', 'btn btn-primary btn-sm live-open', ['Open full report'], { href: E.reportUrl(m.slug) }),
      make('p', 'live-send-h', ['Send me the report']), send,
      make('p', 'live-media', [], { hidden: '' })]));
    E.sendReport(send, m.slug, m.handle, m.platform);
    mediaStatus(m);
    if (ease) grow(h0);
  }
  // The Links panel's strip of what Google Images shows (pics.view): the idle drift (js/strip-drift.js), ← / → nav (off at
  // the ends), Pause / Play, Reveal; hidden once no image is left. → {box, start()}: start() once the card is laid out.
  function heroStrip(m, pics, links) {
    var strip = make('div', 'live-strip', [pics.view(make('div', 'live-strip-track'), STRIP, pics.tile())],
      { role: 'group', 'aria-label': 'Google Images results for @' + m.handle }), sbox;
    var edges = function (x) {   // the nav buttons: back off at the start, forward off at the end
      var max = strip.scrollWidth - strip.clientWidth;
      sbox.querySelector('.live-strip-prev').disabled = x <= 1;
      sbox.querySelector('.live-strip-next').disabled = x >= max - 1;
    };
    var nav = function (dir) {
      var b = make('button', 'live-strip-nav live-strip-' + (dir < 0 ? 'prev' : 'next'), [icon('i-arrow-right')],   // CSS turns the back one round
        { type: 'button', 'aria-label': dir < 0 ? 'Scroll images back' : 'Scroll images forward', tabindex: '-1' });
      b.addEventListener('click', function () { strip.scrollBy({ left: dir * strip.clientWidth * 0.8, behavior: reduce() ? 'auto' : 'smooth' }); });
      return b;
    };
    var pauseB = make('button', 'live-strip-pause', [icon('i-pause', 'ic-pause'), icon('i-play', 'ic-play')], { type: 'button' });
    pauseB.addEventListener('click', function () {   // a deliberate choice: Pause ends it, Play starts it now (no wait)
      if (!D) return;
      if (D.owns(sbox)) D.stop(); else D.start(sbox, strip, links, true, edges);
    });
    sbox = make('div', 'live-strip-box', [
      make('div', 'live-strip-head', [make('p', 'live-strip-h', ['What Google Images shows for @' + m.handle]),
        make('span', 'live-strip-tools', [pauseB, E.revealButton(live)])]),
      make('div', 'live-strip-wrap', [strip, nav(-1), nav(1)])]);
    pics.onCount(function (c) { sbox.hidden = !c.alive; });
    return { box: sbox, start: function () {
      strip.addEventListener('scroll', function () {   // scrolled by hand or by the drift (its moves leave scrollLeft alone: D.x)
        var x = D ? D.x(strip) : null;
        if (x === null || x === strip.scrollLeft) edges(strip.scrollLeft);
      }, { passive: true });
      requestAnimationFrame(function () { edges(strip.scrollLeft); });
      if (D) D.start(sbox, strip, links, false, edges);
    } };
  }
  // The Sites panel takes no height of its own (CSS: contain size): the card is as tall as the other panels give it.
  // Its list shows the sites that fit whole in that height (up to 12) and "+N more sites" sits at its foot; re-fitted
  // whenever the panel's box changes (fonts, the Pause button appearing, a resize). No empty band, never a taller card.
  function fitSites(panel, total) {
    var list = panel.firstChild, more = panel.querySelector('.live-more'), rows = list.children;
    var fit = function () {
      if (!panel.isConnected) return;
      Array.prototype.forEach.call(rows, function (li) { li.hidden = false; });
      var bottom = list.offsetTop + list.clientHeight + 0.5, shown = 0;   // layout boxes: the rows' entry nudge doesn't count
      Array.prototype.forEach.call(rows, function (li) {
        if (li.offsetTop + li.offsetHeight > bottom) li.hidden = true; else shown++;
      });
      var left = total - shown;
      if (more) {
        more.hidden = left <= 0;
        more.textContent = '+ ' + left + ' more ' + E.plural(left, 'site', 'sites') + ' in the full report';
      }
    };
    fit();
    if (window.ResizeObserver) new ResizeObserver(fit).observe(panel);
  }
  // [[key, label, count, panel]] → a tablist (E.tablist on the card handles click / keys); the panels share one grid
  // cell and a hidden one keeps its place (CSS), so switching never moves anything else.
  function tabBar(tabs) {
    return make('div', 'live-tabs', tabs.map(function (t, i) {
      t[3].id = 'panel-report-' + t[0];
      t[3].setAttribute('role', 'tabpanel');
      t[3].setAttribute('aria-labelledby', 'tab-report-' + t[0]);
      t[3].hidden = i > 0;
      return make('button', 'live-tab', [t[1], make('span', 'live-tab-n', [String(t[2])])],
        { type: 'button', role: 'tab', id: 'tab-report-' + t[0], 'aria-controls': 'panel-report-' + t[0], 'data-tab': t[0],
          'aria-selected': String(!i), tabindex: i ? '-1' : '0' });
    }), { role: 'tablist', 'aria-label': 'Report' });
  }
  E.tablist(card);
  var ERR = {
    rate_limited: ['The scanner is busy right now.', 'Try again in a minute, or message me your handle and I’ll run it for you.'],
    busy: ['The scanner is busy right now.', 'Try again in a minute, or message me your handle and I’ll run it for you.'],
    network: ['Couldn’t reach the scan server.', 'Check your connection and try again, or message me your handle and I’ll run it for you.'],
    failed: ['The scan didn’t finish.', 'Try again in a minute, or message me your handle and I’ll run it for you.']
  };
  function heroError(kind, handle, platform) {
    var e = ERR[kind] || ERR.failed, body = q('.live-body'), send = msgLinks(), h0 = card.offsetHeight;
    if (card.getAnimations) card.getAnimations().forEach(function (a) { a.cancel(); });
    card.removeAttribute('aria-busy');
    q('.live-status').textContent = '';
    q('.live-bar').hidden = true;
    body.textContent = '';
    body.appendChild(make('div', 'live-error', [make('p', '', [make('strong', '', [e[0]]), ' ' + e[1]], { role: 'alert' }), send]));
    var t = 'Hi Jaka, the free scan didn’t work for me. My handle: ' + E.who(handle, platform);
    E.setMessages(send, t, 'Free Google scan', 'Hi Jaka,\n\n' + t + '\n\nThanks!');
    live.setAttribute('data-error', kind);
    grow(h0);
  }

  // Demo-site photos arrive after the scan (personalize.js polls /api/media/<slug>); this line mirrors scan/'s.
  var mediaTok = 0;
  function mediaStatus(m) {
    var el = q('.live-media'), tok = ++mediaTok;
    if (!el || !m.profile || !P()) return;
    // its line is there from the first frame (the card eases to its final height once, nothing pops in later)
    el.textContent = 'Gathering photos for your demo site…';
    el.setAttribute('data-phase', 'pending');
    el.hidden = false;
    P().pollMedia(m.slug, function (imgs, phase) {
      if (tok !== mediaTok || !el.isConnected) return;
      var ready = phase === 'ready';
      el.textContent = '';
      el.appendChild(ready ? make('a', '', ['Photos ready: see your demo site'], { href: '#showcase' })
        : document.createTextNode('Gathering photos for your demo site…'));
      el.setAttribute('data-phase', phase);
      el.style.visibility = !ready && phase !== 'pending' ? 'hidden' : '';   // keep the slot: no late shrink
    });
  }

  // ---------- scan ----------
  // Brings the card into view once its height ease ends: its top under the header (never under it), and if the report
  // runs past the fold, as far as its "Send me the report" buttons allow without that. Never after the visitor has
  // scrolled / swiped / typed since pressing Scan.
  var asked = 0, intent = 0;
  ['wheel', 'touchstart', 'keydown'].forEach(function (t) { window.addEventListener(t, function () { intent = Date.now(); }, { passive: true }); });
  function bring() {
    var run = card.getAnimations && card.getAnimations().filter(function (a) { return a.playState === 'running'; })[0];
    if (run && run.finished) { run.finished.then(bring, function () {}); return; }
    if (intent > asked) return;
    var r = card.getBoundingClientRect(), top = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
    var y = window.pageYOffset, to = r.top >= top && r.bottom <= window.innerHeight ? y : y + r.top - top;
    var send = !card.hasAttribute('aria-busy') && q('.live-send');
    if (send) {   // never past the card's top edge: it stays whole under the sticky nav
      var want = y + send.getBoundingClientRect().bottom + 16 - window.innerHeight;
      if (want > to) to = Math.min(want, y + r.top - top);
    }
    if (Math.abs(to - y) > 2) window.scrollTo({ top: Math.max(0, to), behavior: reduce() ? 'auto' : 'smooth' });
  }
  function settle() {
    setBusy(false);
    var t = q('.live-title');
    if (t) t.focus({ preventScroll: true });
    bring();
  }
  function scan(handle, platform, social) {
    var tok = ++token;
    asked = Date.now();
    mediaTok++;
    setBusy(true);
    if (F) F.reset();
    var h0 = card.offsetHeight;
    heroOpen(handle, platform).setAttribute('data-handle', handle);
    card.setAttribute('aria-busy', 'true');
    q('.live-status').textContent = 'Starting the scan…';
    grow(h0);
    bring();
    E.runScan({ platform: platform, handle: handle, social: social,
      onProgress: function (t) { if (tok === token) progress(t); },
      onResult: function (raw) {
        if (tok !== token) return;
        var m = E.reportModel(raw, { handle: handle, platform: platform });
        if (!m) { heroError('failed', handle, platform); return settle(); }
        if (history.replaceState) history.replaceState(null, '', location.pathname + '?r=' + encodeURIComponent(m.slug) + location.hash);
        E.remember(raw, m.slug, m.handle, m.platform);
        heroResult(m, true);
        if (F) F.render(m);
        settle();   // then the engine's leakscan:result event re-personalizes the rest of the page
      },
      onError: function (e) {
        if (tok !== token) return;
        if (e.kind === 'bad_handle') {
          heroReset();
          setBusy(false);
          return formMsg('That handle doesn’t look right. Check it and try again.');
        }
        heroError(e.kind, handle, platform);
        settle();
      } });
  }

  // ---------- boot: the page's report re-renders the hero card (personalize.js / removals.js do the rest themselves) ----------
  var slug = E.currentSlug(), shared = /[?&]r=/.test(location.search);
  if (slug) {
    var tok0 = token;
    asked = Date.now();
    E.fetchResult(slug).then(function (raw) {
      var m = tok0 === token && E.reportModel(raw, {});
      if (!m || m.slug !== slug) return;
      heroOpen(m.handle, m.platform).setAttribute('data-handle', m.handle);
      heroResult(m);
      if (F) F.render(m);
      // A shared report link (?r=, no #section) opened where the card sits below the fold (phones: below mid-screen,
      // under the hero text and the form): bring it up, unless she already scrolled / typed. A restored scroll position
      // or a #link is left alone.
      if (shared && !location.hash && card.getBoundingClientRect().top >= window.innerHeight * (window.innerWidth < 720 ? 0.5 : 1)) bring();
    }, function () { /* unknown / unreachable: the page keeps its illustration */ });
  }
})();
