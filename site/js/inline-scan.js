// Landing hero: the free-scan form runs the scan right here (js/scan-engine.js) instead of opening scan/. The hero card
// becomes the live report (Links / Images / Sites tabs + a film strip of what Google Images shows), the #free band's
// mini Google Images frame shows her real image results, and js/personalize.js re-personalizes the phones / showcase /
// demo. Without JS the form still opens scan/. A slug from ?r= (else localStorage, same order as personalize.js)
// re-renders the hero card on load. Every API value is validated; rendering is textContent / createElement only. Own
// elements only (never personalize's data-p slots).
(function () {
  'use strict';
  var E = window.LeakScanEngine, form = document.getElementById('scan'), card = document.querySelector('.report-card');
  var band = document.querySelector('.gmini');
  if (!E || !form || !card || !window.fetch) return;
  var DOMAIN_RE = /^[a-z0-9-]+(\.[a-z0-9-]+)+$/, HANDLE_RE = /^[A-Za-z0-9._-]{1,60}$/;
  var GSTATIC_RE = /^https:\/\/[a-z0-9-]+\.gstatic\.com\/[^\s"'<>\\]*$/;
  var ROWS = 5, MAX_SITES = 12, STRIP = 24, BAND = 10, MAX_IMAGES = 60;
  var btn = form.querySelector('button[type=submit]'), btnText = btn && btn.lastChild, btnLabel = btnText && btnText.nodeValue;
  var token = 0, busy = false, live = null, msg = null, saved = null;
  var P = function () { return window.LeakScanPersonalize; };
  var reduce = function () { return !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches); };
  var plural = function (n, one, many) { return n + ' ' + (n === 1 ? one : many); };

  function icon(id) {
    var NS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(NS, 'svg'), use = document.createElementNS(NS, 'use');
    svg.setAttribute('class', 'icon');
    svg.setAttribute('aria-hidden', 'true');
    use.setAttribute('href', '#' + id);
    svg.appendChild(use);
    return svg;
  }
  var NEW_TAB = { target: '_blank', rel: 'noopener noreferrer nofollow' };
  var ext = function (attrs) { return Object.assign({}, NEW_TAB, attrs); };
  function make(tag, cls, kids, attrs) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    for (var k in attrs || {}) if (attrs.hasOwnProperty(k)) el.setAttribute(k, attrs[k]);
    (kids || []).forEach(function (c) { if (c != null) el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return el;
  }

  // ---------- validation ----------
  function str(v, max) {
    if (typeof v !== 'string') return null;
    var s = v.replace(/[\u0000-\u001f\u007f\u200b-\u200f\u2028-\u202e]/g, ' ').replace(/\s+/g, ' ').trim();
    return s && s.length <= max && !/[<>{}]|javascript:|data:/i.test(s) ? s : null;
  }
  function domain(v) {
    if (typeof v !== 'string') return null;
    var d = v.trim().toLowerCase().replace(/^www\./, '');
    return d.length <= 80 && DOMAIN_RE.test(d) ? d : null;
  }
  function link(u) {
    if (typeof u !== 'string' || u.length > 600 || !/^https?:\/\/[^\s"'<>\\]+$/i.test(u)) return null;
    try { var x = new URL(u); return x.username || x.password ? null : x; } catch (e) { return null; }
  }
  var okThumb = function (u) { return typeof u === 'string' && u.length <= 600 && GSTATIC_RE.test(u); };
  // raw API result → {slug, handle, platform, rows: [{url, domain, title, badge, thumb}], sites: [{domain, n, thumb, url}],
  // images: [{src, title, domain, link}] (images[] + results' thumbs, deduped; link '' = no result has it), profile}
  function model(raw, fb) {
    if (!raw || typeof raw !== 'object') return null;
    var slug = typeof raw.slug === 'string' && E.SLUG_RE.test(raw.slug) ? raw.slug : null;
    if (!slug) return null;
    var m = { slug: slug, handle: typeof raw.handle === 'string' && HANDLE_RE.test(raw.handle) ? raw.handle : fb.handle,
      platform: E.PLATFORMS[raw.platform] ? raw.platform : fb.platform, rows: [], sites: [], images: [],
      profile: !!(raw.profile && typeof raw.profile === 'object'), socials: {}, discovered: [] };
    if (!m.handle) return null;
    var so = raw.socials && typeof raw.socials === 'object' ? raw.socials : {};
    ['instagram', 'x'].forEach(function (k) {
      if (typeof so[k] === 'string' && HANDLE_RE.test(so[k].replace(/^@/, ''))) m.socials[k] = so[k].replace(/^@/, '');
    });
    var al = raw.aliases && typeof raw.aliases === 'object' && Array.isArray(raw.aliases.discovered) ? raw.aliases.discovered : [];
    m.discovered = al.slice(0, 4).filter(function (a) { return typeof a === 'string' && HANDLE_RE.test(a) && a !== m.handle; });
    // backend that doesn't echo socials yet: show what she typed (fresh scan only)
    if (!m.socials.instagram && !m.socials.x && fb.social) m.socials[fb.social.net] = fb.social.handle;
    var seen = {}, by = {};
    var add = function (u, d, title, badge, thumb) {
      var x = link(u);
      if (!x || seen[x.href]) return;
      d = domain(d) || domain(x.hostname);
      if (!d) return;
      seen[x.href] = 1;
      thumb = okThumb(thumb) ? thumb : null;
      m.rows.push({ url: x.href, domain: d, title: str(title, 200), badge: badge, thumb: thumb });
      if (!by[d]) { by[d] = { domain: d, n: 0, thumb: null, url: x.href }; m.sites.push(by[d]); }
      by[d].n++;
      if (!by[d].thumb && thumb) by[d].thumb = thumb;
    };
    var res = [];
    // Badges only say what the data says: live:true → Live, a Google result → Indexed, anything else → Found.
    (Array.isArray(raw.hits) ? raw.hits : []).slice(0, 1000).forEach(function (h) {
      if (h) add(h.url, h.domain, h.title, h.live === true ? 'Live' : 'Found');
    });
    (Array.isArray(raw.results) ? raw.results : []).slice(0, 200).forEach(function (r) {
      if (!r) return;
      add(r.link, r.domain, r.title, 'Indexed', r.thumb);
      var x = link(r.link), d = x && (domain(r.domain) || domain(x.hostname));
      if (d) res.push({ link: x.href, domain: d, title: str(r.title, 200), thumb: okThumb(r.thumb) ? r.thumb : null });
    });
    m.sites.sort(function (a, b) { return b.n - a.n; });
    var imgs = E.imageItems((Array.isArray(raw.images) ? raw.images : []).slice(0, 200), res, okThumb, MAX_IMAGES);
    // the ones that open a page first: the strip / grid / band lead with tiles that go somewhere
    m.images = imgs.filter(function (it) { return it.link; }).concat(imgs.filter(function (it) { return !it.link; }));
    return m;
  }

  // ---------- form ----------
  function setBusy(on) {
    busy = on;
    form.setAttribute('aria-busy', String(on));
    if (btn) btn.disabled = on;
    if (btnText && btnText.nodeType === 3) btnText.nodeValue = on ? 'Scanning…' : btnLabel;
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
    var h = form.elements.h, ig = form.elements.ig, c = E.cleanHandle(h.value), so = E.cleanSocial(ig.value, ig.getAttribute('data-net'));
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
    var h = E.cleanHandle(form.elements.h.value), social = E.cleanSocial(form.elements.ig.value, form.elements.ig.getAttribute('data-net'));
    if (!h) return formMsg('That handle doesn’t look right. Use letters, numbers, dots, dashes or underscores, like yourhandle.');
    if (social === false) return formMsg('That Instagram or X username doesn’t look right. Paste the profile link or type the name, like yourname.', 'ig');
    formMsg('');
    scan(h, 'onlyfans.com', social);
  });

  // ---------- hero card: the live report ----------
  function heroReset() {
    if (drifter) drifter.stop();
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
    ]);
    card.appendChild(live);
    return live;
  }
  var q = function (sel) { return live && live.querySelector(sel); };
  function progress(text) {
    var p = E.progressInfo(text);
    q('.live-status').textContent = p.stage;
    if (p.pct != null) q('.live-bar i').style.width = p.pct + '%';
  }
  function msgLinks(scope) {
    return make('p', 'live-send', [
      make('a', 'btn btn-ghost btn-sm', ['Telegram'], { 'data-msg': 'tg' }),
      make('a', 'btn btn-ghost btn-sm', ['WhatsApp'], { 'data-msg': 'wa' }),
      make('a', 'btn btn-ghost btn-sm', ['Email'], { 'data-msg': 'mail' })]);
  }
  // ---------- image tiles (hero strip + Images tab + #free band) ----------
  // Blurred until Reveal; ↗ on hover / focus (always on touch screens). A tile links to the result that has that image
  // (new tab); an image no result has links to the full report.
  function tile(it, slug, cap) {
    var img = make('img', 'gi-img', [], { src: E.thumb(it.src), alt: '', loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer' });
    var box = make('span', 'gi-box gi-wait', [img, make('span', 'gi-go', [icon(it.link ? 'i-external-link' : 'i-arrow-right')])]);
    img.addEventListener('load', function () { box.classList.remove('gi-wait'); }, { once: true });   // fades in (CSS)
    img.addEventListener('error', function () { img.remove(); box.classList.remove('gi-wait'); box.classList.add('gi-none'); }, { once: true });
    var label = it.link ? 'Image on ' + it.domain + (it.title ? ': ' + it.title : '') + ' (opens in a new tab)' : 'Image result: see it in the full report';
    return make('a', 'gi-card', [box, cap ? make('span', 'gi-cap', [E.fav(it.domain || 'google.com', 'gi-fav'), make('span', 'gi-cap-t', [it.domain || 'Google Images'])]) : null],
      it.link ? ext({ href: it.link, 'aria-label': label, title: it.domain }) : { href: 'scan/?r=' + encodeURIComponent(slug), 'aria-label': label });
  }
  function revealBtn(scope) {
    var b = make('button', 'live-reveal', [icon('i-eye'), make('span', '', ['Reveal images'])], { type: 'button', 'aria-pressed': 'false' });
    b.addEventListener('click', function () {
      var on = !scope.classList.contains('revealed');
      scope.classList.toggle('revealed', on);
      Array.prototype.forEach.call(scope.querySelectorAll('.live-reveal'), function (x) {
        x.setAttribute('aria-pressed', String(on));
        x.lastChild.textContent = on ? 'Blur images' : 'Reveal images';
      });
    });
    return b;
  }
  function rowLink(url, dom, thumbSrc, text, chip, label) {
    var ico = E.fav(dom, 'live-ico', thumbSrc ? E.thumb(thumbSrc) : null);
    if (!thumbSrc) { ico.style.background = ''; ico.classList.add('fav-none'); }   // same neutral letter as a failed thumb
    return make('a', 'live-link', [ico, make('span', 'live-txt', text), chip,
      make('span', 'live-go', [icon('i-external-link')])], ext({ href: url, 'aria-label': label }));
  }

  // ---------- film strip drift ----------
  // ~4 s after the result shows, if the visitor does nothing, the strip scrolls itself slowly (rAF, ping-pong, a pause
  // at each end). Hover / focus pauses it; a tap, click, wheel or key on the strip stops it for good; any page activity
  // before it starts restarts the wait. Only while the strip is on screen, its tab is showing and the page is visible.
  // Never under prefers-reduced-motion. While it moves, the inner track slides with translate3d (sub-pixel, on the
  // compositor: smooth at 24 px/s); whenever it pauses or stops, the position goes back into the scroller's scrollLeft,
  // so swipe, arrows and focus carry on from there. Nothing else moves, the card never changes size.
  var DRIFT_WAIT = 4000, DRIFT_SPEED = 24, DRIFT_HOLD = 1400, drifter = null;
  function stripEdges(box, x, max) {
    var p = box.querySelector('.live-strip-prev'), n = box.querySelector('.live-strip-next');
    if (p) p.disabled = x <= 1;
    if (n) n.disabled = x >= max - 1;
  }
  function drift(box, strip, panel, now) {
    if (drifter) drifter.stop();
    drifter = null;
    if (reduce() || !window.requestAnimationFrame) return;
    var btn = box.querySelector('.live-strip-pause');
    var auto = function (on) {
      box.setAttribute('data-auto', on ? 'on' : 'off');
      if (btn) { btn.setAttribute('aria-label', on ? 'Pause slideshow' : 'Play slideshow'); btn.title = btn.getAttribute('aria-label'); }
    };
    var d = { box: box, dead: false, armed: false, hover: false, seen: !window.IntersectionObserver, raf: 0, timer: 0 };
    var track = strip.firstElementChild, pos = 0, dir = 1, hold = 0, t0 = 0, io = null, max = 0, moving = false;
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
      if (io) io.disconnect();
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
      if (max > 1 && d.seen && !d.hover && panel.classList.contains('on') && !document.hidden) {
        if (!moving) lift();
        if (hold > 0) hold -= dt;
        else {
          pos += dir * DRIFT_SPEED * dt / 1000;
          if (dir > 0 && pos >= max) { pos = max; dir = -1; hold = DRIFT_HOLD; } else if (dir < 0 && pos <= 0) { pos = 0; dir = 1; hold = DRIFT_HOLD; }
          track.style.transform = 'translate3d(' + (-pos).toFixed(2) + 'px, 0, 0)';
          stripEdges(box, pos, max);
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
    var pause = function (on) { return function () { d.hover = on; }; };
    box.addEventListener('mouseenter', pause(true));
    box.addEventListener('mouseleave', pause(false));
    box.addEventListener('focusin', pause(true));
    box.addEventListener('focusout', pause(false));
    if (window.IntersectionObserver) {
      io = new IntersectionObserver(function (es) { d.seen = es[es.length - 1].isIntersecting; });
      io.observe(strip);
    }
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
    var n = m.rows.length, body = q('.live-body'), slugQ = encodeURIComponent(m.slug);
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
    count.textContent = plural(n, 'link found', 'links found');
    count.className = 'chip live-count ' + (n ? 'chip-live' : 'chip-dead');
    count.hidden = false;
    var top = q('.live-open-top');
    top.href = 'scan/?r=' + slugQ;
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
        return make('li', '', [rowLink(r.url, r.domain, r.thumb || thumbs[r.domain],
          [make('span', 'live-dom', [r.domain]), make('span', 'live-ttl', [r.title || path])],
          make('span', 'chip live-badge ' + (r.badge === 'Live' ? 'chip-live' : 'chip-soft'), [r.badge]),
          r.domain + ': ' + (r.title || path) + ' (' + r.badge + ', opens in a new tab)')]);
      }))]);
      if (n > ROWS) links.appendChild(make('p', 'live-more', ['+ ' + (n - ROWS) + ' more in the full report']));
      var tabs = [['links', 'Links', n, links]], strip = null, sbox = null;
      if (m.images.length) {
        strip = make('div', 'live-strip', [make('div', 'live-strip-track', m.images.slice(0, STRIP).map(function (it) { return tile(it, m.slug); }))],
          { role: 'group', 'aria-label': 'Google Images results for @' + m.handle });
        var nav = function (dir) {
          var b = make('button', 'live-strip-nav live-strip-' + (dir < 0 ? 'prev' : 'next'), [icon(dir < 0 ? 'i-arrow-right' : 'i-arrow-right')],
            { type: 'button', 'aria-label': dir < 0 ? 'Scroll images back' : 'Scroll images forward', tabindex: '-1' });
          b.addEventListener('click', function () { strip.scrollBy({ left: dir * strip.clientWidth * 0.8, behavior: reduce() ? 'auto' : 'smooth' }); });
          return b;
        };
        var pauseB = make('button', 'live-strip-pause', [icon('i-pause'), icon('i-play')], { type: 'button' });
        pauseB.addEventListener('click', function () {   // a deliberate choice: Pause ends it, Play starts it now (no wait)
          if (drifter && drifter.box === sbox) drifter.stop(); else drift(sbox, strip, links, true);
        });
        sbox = make('div', 'live-strip-box', [
          make('div', 'live-strip-head', [make('p', 'live-strip-h', ['What Google Images shows for @' + m.handle]),
            make('span', 'live-strip-tools', [pauseB, revealBtn(live)])]),
          make('div', 'live-strip-wrap', [strip, nav(-1), nav(1)])]);
        links.appendChild(sbox);
        // Images: a grid of the first ones
        var GRID = window.matchMedia && matchMedia('(max-width: 559px)').matches ? 12 : 16;   // phone 3×4, else 4×4: fills the Links panel's height
        var more = m.images.length - GRID, grid = make('div', 'live-panel', [
          make('div', 'live-imgs-head', [make('p', '', [plural(m.images.length, 'image', 'images') + ' on Google Images']), revealBtn(live)]),
          make('div', 'live-grid', m.images.slice(0, GRID).map(function (it) { return tile(it, m.slug); })),
          more > 0 ? make('a', 'live-more live-more-a', ['+ ' + more + ' more in the full report'], { href: 'scan/?r=' + slugQ }) : null]);
        tabs.push(['images', 'Images', m.images.length, grid]);
      }
      // Sites: per site, its first link
      var sites = make('div', 'live-panel live-panel-sites', [make('ul', 'report-rows live-sites', m.sites.slice(0, MAX_SITES).map(function (s) {
        return make('li', '', [rowLink(s.url, s.domain, s.thumb, [make('span', 'live-dom', [s.domain]),
          make('span', 'live-ttl', [s.url.replace(/^https?:\/\/(www\.)?/, '')])],
          make('span', 'chip chip-soft', [plural(s.n, 'link', 'links')]), s.domain + ': ' + plural(s.n, 'link', 'links') + ' (opens its first link in a new tab)')]);
      }))]);
      sites.appendChild(make('a', 'live-more live-more-a', [], { href: 'scan/?r=' + slugQ }));
      tabs.push(['sites', 'Sites', m.sites.length, sites]);
      body.appendChild(tabBar(tabs));
      body.appendChild(make('div', 'live-panels', tabs.map(function (t) { return t[3]; })));
      fitSites(sites, m.sites.length);
      if (strip) {
        var edges = function () {
          if (!(drifter && drifter.strip === strip && drifter.x() !== strip.scrollLeft)) stripEdges(sbox, strip.scrollLeft, strip.scrollWidth - strip.clientWidth);
        };
        strip.addEventListener('scroll', edges, { passive: true });
        requestAnimationFrame(edges);
        drift(sbox, strip, links);
      } else if (drifter) drifter.stop();
    }
    var send = msgLinks();
    body.appendChild(make('div', 'live-actions', [
      make('a', 'btn btn-primary btn-sm live-open', ['Open full report'], { href: 'scan/?r=' + slugQ }),
      make('p', 'live-send-h', ['Send me the report']), send,
      make('p', 'live-media', [], { hidden: '' })]));
    E.sendReport(send, m.slug, m.handle, m.platform);
    mediaStatus(m);
    if (ease) grow(h0);
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
        more.textContent = '+ ' + left + ' more ' + (left === 1 ? 'site' : 'sites') + ' in the full report';
      }
    };
    fit();
    if (window.ResizeObserver) new ResizeObserver(fit).observe(panel);
  }
  // [[key, label, count, panel]] → a tablist; the panels share one grid cell, so switching never moves anything else.
  function tabBar(tabs) {
    var bar = make('div', 'live-tabs', [], { role: 'tablist', 'aria-label': 'Report' });
    var pick = function (i, focus) {
      tabs.forEach(function (t, j) {
        var b = bar.children[j], on = i === j;
        b.setAttribute('aria-selected', String(on));
        b.tabIndex = on ? 0 : -1;
        t[3].classList.toggle('on', on);
        if (on) t[3].removeAttribute('aria-hidden'); else t[3].setAttribute('aria-hidden', 'true');
        if (on && focus) b.focus();
      });
    };
    tabs.forEach(function (t, i) {
      var b = make('button', 'live-tab', [t[1], make('span', 'live-tab-n', [String(t[2])])],
        { type: 'button', role: 'tab', id: 'lt-' + t[0], 'aria-controls': 'lp-' + t[0], 'data-tab': t[0] });
      t[3].id = 'lp-' + t[0];
      t[3].setAttribute('role', 'tabpanel');
      t[3].setAttribute('aria-labelledby', 'lt-' + t[0]);
      b.addEventListener('click', function () { pick(i, false); });
      b.addEventListener('keydown', function (e) {
        var k = ['ArrowLeft', 'ArrowRight', 'Home', 'End'].indexOf(e.key);
        if (k < 0) return;
        e.preventDefault();
        pick(k === 2 ? 0 : k === 3 ? tabs.length - 1 : (i + (k ? 1 : tabs.length - 1)) % tabs.length, true);
      });
      bar.appendChild(b);
    });
    pick(0, false);
    return bar;
  }
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
      var ready = phase === 'ready' || (phase !== 'pending' && imgs.length > 0);
      el.textContent = '';
      el.appendChild(ready ? make('a', '', ['Photos ready: see your demo site'], { href: '#showcase' })
        : document.createTextNode('Gathering photos for your demo site…'));
      el.setAttribute('data-phase', ready ? 'ready' : phase);
      el.style.visibility = !ready && phase !== 'pending' ? 'hidden' : '';   // keep the slot: no late shrink
    });
  }

  // ---------- #free band: the mini Google Images frame shows her real image results ----------
  var bandSaved = null;
  function bandReset() {
    if (!band || !bandSaved) return;
    band.classList.remove('is-live', 'revealed');
    Array.prototype.forEach.call(document.querySelectorAll('[data-live]'), function (el) { el.remove(); });
    band.setAttribute('role', 'img');
    band.setAttribute('aria-label', bandSaved.label);
    if (bandSaved.send) bandSaved.send.setAttribute('href', bandSaved.href);
  }
  function bandResult(m) {
    if (!band) return;
    var send = document.querySelector('[data-free-send]');
    if (!bandSaved) bandSaved = { label: band.getAttribute('aria-label'), send: send, href: send && send.getAttribute('href') };
    bandReset();
    // "Send me the report" → Telegram with her report link (the other channels are in the hero card)
    if (send) {
      var s = make('span', '', [make('a', '', [], { 'data-msg': 'tg' })]);
      E.sendReport(s, m.slug, m.handle, m.platform);
      send.setAttribute('href', s.firstChild.getAttribute('href'));
    }
    if (!m.images.length) return; // nothing on Google Images: the frame stays the illustration
    band.classList.add('is-live');
    band.removeAttribute('role');
    band.setAttribute('aria-label', 'What Google Images shows for @' + m.handle);
    band.querySelector('.gmini-top').appendChild(make('span', 'gmini-tools', [
      make('span', 'gmini-n', [plural(m.images.length, 'image', 'images')]), revealBtn(band)], { 'data-live': 'band-tools' }));
    var grid = band.querySelector('.gmini-grid');
    grid.parentNode.insertBefore(make('div', 'gmini-grid live-grid', m.images.slice(0, BAND).map(function (it) { return tile(it, m.slug, true); }),
      { 'data-live': 'band-grid' }), grid.nextSibling);
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
    bandReset();
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
        var m = model(raw, { handle: handle, platform: platform, social: social });
        if (!m) { heroError('failed', handle, platform); return settle(); }
        if (history.replaceState) history.replaceState(null, '', location.pathname + '?r=' + encodeURIComponent(m.slug) + location.hash);
        E.remember(raw, m.slug, m.handle, m.platform);
        if (P()) P().apply(raw.socials ? raw : Object.assign({}, raw, { socials: m.socials }));
        heroResult(m, true);
        bandResult(m);
        settle();
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

  // ---------- boot: a known slug re-renders the hero card (personalize.js does the rest itself) ----------
  var slug = null, mr = /[?&]r=([^&#]*)/.exec(location.search);
  if (mr) { try { slug = decodeURIComponent(mr[1]); } catch (e) { slug = null; } }
  else { try { slug = (JSON.parse(localStorage.getItem('leakscan.last') || 'null') || {}).slug; } catch (e) { slug = null; } }
  if (typeof slug === 'string' && E.SLUG_RE.test(slug)) {
    var tok0 = token;
    asked = Date.now();
    E.fetchResult(slug).then(function (raw) {
      var m = tok0 === token && model(raw, {});
      if (!m || m.slug !== slug) return;
      heroOpen(m.handle, m.platform).setAttribute('data-handle', m.handle);
      heroResult(m);
      bandResult(m);
      // A shared report link (?r=, no #section) opened where the card sits below the fold (phones: under the hero
      // text): bring it up, unless she already scrolled / typed. A restored scroll position or a #link is left alone.
      if (mr && !location.hash && card.getBoundingClientRect().top >= window.innerHeight) bring();
    }, function () { /* unknown / unreachable: the page keeps its illustration */ });
  }
})();
