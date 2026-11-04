// Landing hero: the free-scan form runs the scan right here (js/scan-engine.js) instead of opening scan/. The hero card
// becomes the live report, the "Free scan report" illustration shows the real counts, and js/personalize.js
// re-personalizes the phones / showcase / demo. Without JS the form still opens scan/. A slug from ?r= (else
// localStorage, same order as personalize.js) re-renders the hero card on load. Every API value is validated;
// rendering is textContent / createElement only. Own elements only (never personalize's data-p slots).
(function () {
  'use strict';
  var E = window.LeakScanEngine, form = document.getElementById('scan'), card = document.querySelector('.report-card');
  var ill = document.querySelector('.scan-report');
  if (!E || !form || !card || !window.fetch) return;
  var DOMAIN_RE = /^[a-z0-9-]+(\.[a-z0-9-]+)+$/, HANDLE_RE = /^[A-Za-z0-9._-]{1,60}$/;
  var GSTATIC_RE = /^https:\/\/[a-z0-9-]+\.gstatic\.com\/[^\s"'<>\\]*$/;
  var ROWS = 5, SITES = 5;
  var btn = form.querySelector('button[type=submit]'), btnText = btn && btn.lastChild, btnLabel = btnText && btnText.nodeValue;
  var token = 0, busy = false, live = null, msg = null, saved = null;
  var P = function () { return window.LeakScanPersonalize; };
  var reduce = function () { return !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches); };
  var plural = function (n, one, many) { return n + ' ' + (n === 1 ? one : many); };

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
  // raw API result → {slug, handle, platform, rows: [{url, domain, title, badge}], sites: [{domain, n, thumb}], profile}
  function model(raw, fb) {
    if (!raw || typeof raw !== 'object') return null;
    var slug = typeof raw.slug === 'string' && E.SLUG_RE.test(raw.slug) ? raw.slug : null;
    if (!slug) return null;
    var m = { slug: slug, handle: typeof raw.handle === 'string' && HANDLE_RE.test(raw.handle) ? raw.handle : fb.handle,
      platform: E.PLATFORMS[raw.platform] ? raw.platform : fb.platform, rows: [], sites: [],
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
      m.rows.push({ url: x.href, domain: d, title: str(title, 200), badge: badge });
      if (!by[d]) { by[d] = { domain: d, n: 0, thumb: null }; m.sites.push(by[d]); }
      by[d].n++;
      if (!by[d].thumb && typeof thumb === 'string' && thumb.length <= 600 && GSTATIC_RE.test(thumb)) by[d].thumb = thumb;
    };
    // Badges only say what the data says: live:true → Live, a Google result → Indexed, anything else → Found.
    (Array.isArray(raw.hits) ? raw.hits : []).slice(0, 1000).forEach(function (h) {
      if (h) add(h.url, h.domain, h.title, h.live === true ? 'Live' : 'Found');
    });
    (Array.isArray(raw.results) ? raw.results : []).slice(0, 200).forEach(function (r) {
      if (r) add(r.link, r.domain, r.title, 'Indexed', r.thumb);
    });
    m.sites.sort(function (a, b) { return b.n - a.n; });
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
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    if (busy) return;
    var h = E.cleanHandle(form.elements.h.value), social = E.cleanSocial(form.elements.ig.value);
    if (!h) return formMsg('That handle doesn’t look right. Use letters, numbers, dots, dashes or underscores, like yourhandle.');
    if (social === false) return formMsg('That Instagram or X username doesn’t look right. Paste the profile link or type the name, like yourname.', 'ig');
    formMsg('');
    scan(h, 'onlyfans.com', social);
  });

  // ---------- hero card: the live report ----------
  function heroReset() {
    if (live) { live.remove(); live = null; }
    card.classList.remove('is-live');
    card.removeAttribute('aria-busy');
    if (saved) { card.setAttribute('role', saved.role); card.setAttribute('aria-label', saved.label); }
  }
  function heroOpen(handle, platform) {
    heroReset();
    if (!saved) saved = { role: card.getAttribute('role'), label: card.getAttribute('aria-label') };
    card.removeAttribute('role');
    card.removeAttribute('aria-label');
    card.classList.add('is-live');
    live = make('div', 'live', [
      make('div', 'report-head', [
        make('div', '', [make('p', 'report-kicker live-kicker', ['Free scan · ' + E.PLATFORMS[platform]]),
          make('p', 'report-title live-title', ['@' + handle], { tabindex: '-1' }), make('p', 'live-socials', [], { hidden: '' }),
          make('p', 'live-aliases', [], { hidden: '' })]),
        make('span', 'chip chip-live live-count', [], { hidden: '' })]),
      make('p', 'live-status', [], { role: 'status' }),
      make('div', 'live-bar', [make('i')], { 'aria-hidden': 'true' }),
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
  function heroResult(m) {
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
    count.textContent = plural(n, 'link found', 'links found');
    count.className = 'chip live-count ' + (n ? 'chip-live' : 'chip-dead');
    count.hidden = false;
    body.textContent = '';
    if (!n) {
      q('.live-status').textContent = '';
      body.appendChild(make('p', 'live-empty', [make('strong', '', ['No leaks found for @' + m.handle + ' right now.']),
        'Google shows no leak links for this handle at the moment. Send me the report and I’ll check by hand.']));
    } else {
      q('.live-status').textContent = 'On ' + plural(m.sites.length, 'site', 'sites') + '. Every link is in the full report.';
      body.appendChild(make('ul', 'report-rows live-rows', m.rows.slice(0, ROWS).map(function (r) {
        var path = r.url.replace(/^https?:\/\/(www\.)?/, '');
        return make('li', '', [
          make('a', 'live-link', [make('span', 'live-dom', [r.domain]), make('span', 'live-ttl', [r.title || path])],
            { href: r.url, target: '_blank', rel: 'noopener noreferrer nofollow' }),
          make('span', 'chip live-badge ' + (r.badge === 'Live' ? 'chip-live' : 'chip-soft'), [r.badge])]);
      })));
      if (n > ROWS) body.appendChild(make('p', 'live-more', ['+ ' + (n - ROWS) + ' more in the full report']));
    }
    var send = msgLinks();
    body.appendChild(make('div', 'live-actions', [
      make('a', 'btn btn-primary btn-sm live-open', ['Open full report'], { href: 'scan/?r=' + encodeURIComponent(m.slug) }),
      make('p', 'live-send-h', ['Send me the report']), send,
      make('p', 'live-media', [], { hidden: '' })]));
    E.sendReport(send, m.slug, m.handle, m.platform);
    mediaStatus(m);
  }
  var ERR = {
    rate_limited: ['The scanner is busy right now.', 'Try again in a minute, or message me your handle and I’ll run it for you.'],
    busy: ['The scanner is busy right now.', 'Try again in a minute, or message me your handle and I’ll run it for you.'],
    network: ['Couldn’t reach the scan server.', 'Check your connection and try again, or message me your handle and I’ll run it for you.'],
    failed: ['The scan didn’t finish.', 'Try again in a minute, or message me your handle and I’ll run it for you.']
  };
  function heroError(kind, handle, platform) {
    var e = ERR[kind] || ERR.failed, body = q('.live-body'), send = msgLinks();
    card.removeAttribute('aria-busy');
    q('.live-status').textContent = '';
    q('.live-bar').hidden = true;
    body.textContent = '';
    body.appendChild(make('div', 'live-error', [make('p', '', [make('strong', '', [e[0]]), ' ' + e[1]], { role: 'alert' }), send]));
    var t = 'Hi Jaka, the free scan didn’t work for me. My handle: ' + E.who(handle, platform);
    E.setMessages(send, t, 'Free Google scan', 'Hi Jaka,\n\n' + t + '\n\nThanks!');
    live.setAttribute('data-error', kind);
  }

  // Demo-site photos arrive after the scan (personalize.js polls /api/media/<slug>); this line mirrors scan/'s.
  var mediaTok = 0;
  function mediaStatus(m) {
    var el = q('.live-media'), tok = ++mediaTok;
    if (!el || !m.profile || !P()) return;
    P().pollMedia(m.slug, function (imgs, phase) {
      if (tok !== mediaTok || !el.isConnected) return;
      var ready = phase === 'ready' || (phase !== 'pending' && imgs.length > 0);
      el.textContent = '';
      el.appendChild(ready ? make('a', '', ['Photos ready: see your demo site'], { href: '#showcase' })
        : document.createTextNode('Gathering photos for your demo site…'));
      el.setAttribute('data-phase', ready ? 'ready' : phase);
      el.hidden = !ready && phase !== 'pending';
    });
  }

  // ---------- "Free scan report" illustration: real counts + domains ----------
  var illSaved = null;
  function illReset() {
    if (!ill || !illSaved) return;
    ill.classList.remove('is-live');
    Array.prototype.forEach.call(document.querySelectorAll('[data-live]'), function (el) { el.remove(); });
    ill.setAttribute('aria-label', illSaved.label);
    if (illSaved.cap) illSaved.cap.el.textContent = illSaved.cap.text;
    if (illSaved.url) illSaved.url.el.textContent = illSaved.url.text;
  }
  function illResult(m) {
    if (!ill) return;
    var fig = ill.closest('figure'), cap = fig && fig.querySelector('figcaption'), bar = fig && fig.querySelector('.url');
    if (!illSaved) illSaved = { label: ill.getAttribute('aria-label'), cap: cap && { el: cap, text: cap.textContent },
      url: bar && { el: bar, text: bar.textContent } };
    illReset();
    var n = m.rows.length, head = ill.querySelector('.report-head'), rows = ill.querySelector('.report-rows');
    ill.classList.add('is-live');
    ill.setAttribute('aria-label', 'Your free scan report for @' + m.handle + ': ' + plural(n, 'link', 'links') + ' found on ' +
      plural(m.sites.length, 'site', 'sites') + '.');
    head.appendChild(make('span', 'chip ' + (n ? 'chip-live' : 'chip-dead'), [plural(n, 'link found', 'links found')], { 'data-live': 'scan-count' }));
    var list = make('ul', 'report-rows live-rows', [], { 'aria-hidden': 'true', 'data-live': 'scan-rows' });
    (n ? m.sites.slice(0, SITES) : [null]).forEach(function (s, i) {
      var th = make('span', 'thumb t' + (i + 1));
      var src = s && s.thumb && E.thumb(s.thumb);
      if (src) {
        var img = make('img', 'p-img', [], { src: src, alt: '', width: '40', height: '40', loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer' });
        img.addEventListener('error', function () { img.remove(); }, { once: true });
        th.appendChild(img);
      }
      list.appendChild(make('li', '', s ? [th, make('span', 'row-url', [s.domain]), make('span', 'chip chip-soft', [plural(s.n, 'link', 'links')])]
        : [th, make('span', 'row-url', ['Nothing found for @' + m.handle + ' right now']), make('span', 'chip chip-dead', ['0 links'])]));
    });
    rows.parentNode.insertBefore(list, rows.nextSibling);
    if (cap) {
      cap.textContent = 'From your scan of @' + m.handle + '. ';
      cap.appendChild(make('a', '', ['Open the full report'], { href: 'scan/?r=' + encodeURIComponent(m.slug), 'data-live': 'scan-link' }));
      cap.appendChild(document.createTextNode(', send me its link and I remove one page free.'));
    }
    if (bar) bar.textContent = 'blackphoenixslo.github.io/leakscan-site/scan/?r=' + m.slug;
  }

  // ---------- scan ----------
  function bring() {
    var r = card.getBoundingClientRect(), top = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
    if (r.top >= top && r.bottom <= window.innerHeight) return;
    window.scrollTo({ top: Math.max(0, window.pageYOffset + r.top - top), behavior: reduce() ? 'auto' : 'smooth' });
  }
  function settle() {
    setBusy(false);
    var t = q('.live-title');
    if (t) t.focus({ preventScroll: true });
    bring();
  }
  function scan(handle, platform, social) {
    var tok = ++token;
    mediaTok++;
    setBusy(true);
    illReset();
    heroOpen(handle, platform).setAttribute('data-handle', handle);
    card.setAttribute('aria-busy', 'true');
    q('.live-status').textContent = 'Starting the scan…';
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
        heroResult(m);
        illResult(m);
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
    E.fetchResult(slug).then(function (raw) {
      var m = tok0 === token && model(raw, {});
      if (!m || m.slug !== slug) return;
      heroOpen(m.handle, m.platform).setAttribute('data-handle', m.handle);
      heroResult(m);
      illResult(m);
    }, function () { /* unknown / unreachable: the page keeps its illustration */ });
  }
})();
