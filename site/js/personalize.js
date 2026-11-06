// After a free scan, fills the landing mockups ("Your website", showcase frame) and the demo site (showcase/) with the
// scanned creator's data. Plain ES5-ish, no deps, no third parties (only the scan API host). Needs js/scan-engine.js,
// loaded before it on every page: API host, validators (E.clean), the current slug, thumb liveness, the result fetch.
// Slug: E.currentSlug() = ?r=<slug>, else localStorage['leakscan.last'].slug (written by scan-engine.js remember()), else
// nothing: the page keeps its defaults. One GET <API>/api/scan-result/<slug> per page (E.fetchResult, shared with the
// hero card; sessionStorage cache, 8s timeout); any failure = defaults. A scan run on this page re-applies (the
// `leakscan:result` event). Rendering uses textContent / createElement only, never innerHTML.
(function () {
  'use strict';
  var E = window.LeakScanEngine;
  if (!E) return;
  var API = E.API, SCAN_API = E.SCAN_API, C = E.clean, make = E.make, NEW_TAB = E.NEW_TAB;
  // CACHE: per-slug models in sessionStorage; r2 = models built since aggregator rows are dropped (older ones may hold them)
  var CACHE = 'leakscan.r2.', MEDIA = 'leakscan.media.';
  var PLAT = {
    instagram: ['Instagram', 'instagram.com'], tiktok: ['TikTok', 'tiktok.com'], youtube: ['YouTube', 'youtube.com'],
    patreon: ['Patreon', 'patreon.com'], onlyfans: ['OnlyFans', 'onlyfans.com'], fansly: ['Fansly', 'fansly.com'],
    x: ['X', 'x.com', 'twitter.com'], threads: ['Threads', 'threads.net'], twitch: ['Twitch', 'twitch.tv']
  };
  // Before-phone rows: same phrasing as the static mockup, name swapped in. Never the leak pages' own titles.
  var LEAK_TITLES = ['{n}: full gallery', '{n}: all photos and videos', '{n} videos (new)', '{n} forum thread'];

  var each = function (list, fn) { Array.prototype.forEach.call(list, fn); };
  var $$ = function (sel, root) { return (root || document).querySelectorAll(sel); };
  function hide(el) { if (el) { el.style.display = 'none'; el.setAttribute('data-p-off', ''); } }
  function text(el, s) { if (el) el.textContent = s; }

  // ---------- validation (E.clean: str / handle / domain / thumbOk; here only what the profile adds) ----------
  function platKey(v) {
    if (typeof v !== 'string') return null;
    var k = v.trim().toLowerCase().replace(/^www\./, '').replace(/\.(com|net|tv)$/, '');
    if (k === 'twitter') k = 'x';
    return PLAT.hasOwnProperty(k) ? k : null;
  }
  function accountUrl(u, key) {
    if (typeof u !== 'string' || u.length > 200) return null;
    var x;
    try { x = new URL(u); } catch (e) { return null; }
    if (x.protocol !== 'https:' || x.username || x.password || x.port) return null;
    var h = x.hostname.toLowerCase();
    return PLAT[key].slice(1).some(function (d) { return E.under(h, d); }) ? x.href : null;
  }
  // follower count for prose: 2 significant figures ("12,000", "1.2 million"); < 100 or not a number = unknown
  function people(n) {
    if (typeof n !== 'number' || !isFinite(n) || n < 100) return null;
    if (n >= 1e6) return Math.round(n / 1e5) / 10 + ' million';
    var k = Math.pow(10, String(Math.round(n)).length - 2);
    return (Math.round(n / k) * k).toLocaleString('en-US');
  }
  function cleanProfile(p) {
    if (!p || typeof p !== 'object') return null;
    var o = {
      display_name: C.str(p.display_name, 60), first_name: C.str(p.first_name, 30), username: C.handle(p.username),
      tagline: C.str(p.tagline, 120), profession: C.str(p.profession, 60), location: C.str(p.location, 60),
      bio: C.str(p.bio, 700), about_short: C.str(p.about_short, 320), site_domain: C.domain(p.site_domain),
      avatar: p.avatar === true, followers: people(p.followers), accounts: []
    };
    var seen = {};
    (Array.isArray(p.accounts) ? p.accounts : []).slice(0, 12).forEach(function (a) {
      var k = a && platKey(a.platform), h = a && C.handle(a.handle);
      if (!k || !h || seen[k]) return;
      seen[k] = 1;
      o.accounts.push({ key: k, handle: h, url: accountUrl(a.url, k) });
    });
    o.name = o.display_name || o.first_name || o.username;
    if (!o.name) return null;
    o.first = o.first_name || o.name.split(' ')[0];
    return o;
  }
  // r: an API result → {slug, handle, platform, leaks: top 4 leak hosts (E.rankHosts), urls: {host:
  // its most-seen page}, images: 3 Google thumbs, profile, socials, found} or null
  function clean(r, slug) {
    if (!r || typeof r !== 'object') return null;
    var h = C.handle(r.handle);
    if (!h) return null;
    var ranked = E.rankHosts(r).slice(0, 4), top = {};
    ranked.forEach(function (x) { if (x.url) top[x.domain] = x.url; }); // the phone's row for this site opens its most-seen page
    var images = (Array.isArray(r.images) ? r.images : []).filter(C.thumbOk);
    // socials: the Instagram / X names she typed next to the scan (echoed by the API); they win over profile guesses
    var so = r.socials && typeof r.socials === 'object' ? r.socials : {}, socials = {};
    if (C.handle(so.instagram)) socials.instagram = C.handle(so.instagram);
    if (C.handle(so.x)) socials.x = C.handle(so.x);
    // found: her other accounts read off leak pages (alias enrichment); only fill platforms nothing else knows
    var al = r.aliases && typeof r.aliases === 'object' ? r.aliases : {}, found = [], fseen = {};
    (Array.isArray(al.socials) ? al.socials : []).slice(0, 12).forEach(function (a) {
      var k = a && platKey(a.platform), fh = a && C.handle(a.handle);
      if (!k || !fh || fseen[k]) return;
      fseen[k] = 1;
      found.push({ key: k, handle: fh, url: accountUrl(a.url, k) });
    });
    return { slug: slug, handle: h, platform: platKey(r.platform), leaks: ranked.map(function (x) { return x.domain; }), urls: top,
      images: images.slice(0, 3), profile: cleanProfile(r.profile), socials: socials, found: found };
  }

  // ---------- data ----------
  function load(slug, cb) {
    try {
      var c = JSON.parse(sessionStorage.getItem(CACHE + slug) || 'null');
      // A result without a profile may get one shortly (generated after the scan): re-ask after a minute.
      if (c && c.m && (c.m.profile || Date.now() - c.ts < 60000)) return cb(c.m);
    } catch (e) { /* ignore */ }
    if (!window.fetch) return;
    var late = false, timer = setTimeout(function () { late = true; }, 8000);
    E.fetchResult(slug).then(function (j) {   // the hero card's request on the landing: one per page
      clearTimeout(timer);
      var m = late ? null : clean(j, slug);
      if (!m) return;
      try { sessionStorage.setItem(CACHE + slug, JSON.stringify({ ts: Date.now(), m: m })); } catch (e) { /* ignore */ }
      cb(m);
    }, function () { clearTimeout(timer); });
  }

  // ---------- demo photos: they arrive after the scan, so poll ----------
  // GET <API>/api/media/<slug> every 3s for up to 90s; stop on "ready" / "none" / a second 404 (or network error).
  // cb(images, phase) on every answer; phase = 'pending' (still polling) | 'ready' (photos to show: the API says ready, or
  // it ended with some) | 'none' | 'stopped' (no photos coming). Only API-hosted media srcs pass:
  // "/api/media/<slug>/<file>", relative or absolute on the API origin, this page's origin or SCAN_API (the backend
  // emits its public origin, which differs from the page host on the VPS). The emitted origin is dropped: photos always
  // load from API + path.
  var MEDIA_RE = new RegExp('^(?:' + [API, location.origin, SCAN_API].filter(Boolean).map(function (o) {
    return o.replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&');
  }).join('|') + ')?(\\/api\\/media\\/[A-Za-z0-9_-]{4,64}\\/[A-Za-z0-9_-]{1,40}\\.(?:jpe?g|png|webp))$');
  function cleanMedia(j) {
    return (j && Array.isArray(j.images) ? j.images : []).slice(0, 12).filter(function (it) {
      return it && typeof it.src === 'string' && it.src.length <= 300 && MEDIA_RE.test(it.src);
    }).map(function (it) { return { src: API + MEDIA_RE.exec(it.src)[1] }; });
  }
  function pollMedia(slug, done) {
    if (!C.slug(slug) || !window.fetch) return;
    var cb = function (imgs, phase) { done(imgs, phase !== 'pending' && imgs.length ? 'ready' : phase); };
    try {
      var c = JSON.parse(sessionStorage.getItem(MEDIA + slug) || 'null');
      if (c && c.phase) return cb(c.images, c.phase);
    } catch (e) { /* ignore */ }
    var t0 = Date.now(), misses = 0, imgs = [];
    var next = function (phase) {
      if (phase === 'ready' || phase === 'none') {
        try { sessionStorage.setItem(MEDIA + slug, JSON.stringify({ phase: phase, images: imgs })); } catch (e) { /* ignore */ }
      }
      if (phase === 'pending' && Date.now() - t0 < 90000) { setTimeout(tick, 3000); return; }
      if (phase === 'pending') cb(imgs, 'stopped');
    };
    var miss = function () {
      misses++;
      if (misses >= 2 || Date.now() - t0 >= 90000) cb(imgs, 'stopped'); else setTimeout(tick, 3000);
    };
    var tick = function () {
      fetch(API + '/api/media/' + encodeURIComponent(slug), { credentials: 'omit' }).then(function (res) {
        if (!res.ok) throw new Error('http ' + res.status);
        return res.json();
      }).then(function (j) {
        var phase = j && (j.status === 'ready' || j.status === 'none') ? j.status : 'pending';
        imgs = cleanMedia(j);
        cb(imgs, phase);
        next(phase);
      }, miss);
    };
    tick();
  }

  // ---------- the shared dictionary ----------
  function dict(m) {
    var p = m.profile || {}, acc = {};
    (p.accounts || []).forEach(function (a) { acc[a.key] = a; });
    if (m.platform && !acc[m.platform]) acc[m.platform] = { key: m.platform, handle: m.handle, url: null };
    (m.found || []).forEach(function (a) { if (!acc[a.key]) acc[a.key] = a; });
    var so = m.socials || {};
    ['instagram', 'x'].forEach(function (k) { // keep the profile's link only when it is the same account
      if (so[k]) acc[k] = { key: k, handle: so[k], url: acc[k] && acc[k].handle.toLowerCase() === so[k].toLowerCase() ? acc[k].url : null };
    });
    var main = (p.accounts && p.accounts[0]) || (m.platform && acc[m.platform]);
    var base = (p.username || m.handle).toLowerCase().replace(/[^a-z0-9-]/g, '') || 'yourname';
    return {
      name: p.name || m.handle, first: p.first || m.handle, handle: p.username || m.handle,
      tagline: p.tagline, profession: p.profession, location: p.location, bio: p.bio, about_short: p.about_short,
      followers: p.followers,
      site: p.site_domain || base + '.com', accounts_n: p.accounts && p.accounts.length ? String(p.accounts.length) : null,
      main_platform: main ? PLAT[main.key][0] : null,
      ig: acc.instagram && acc.instagram.handle, tiktok: acc.tiktok && acc.tiktok.handle, acc: acc
    };
  }
  // "{key}" = value, "{Key}" = value with a capital first letter, "{a|b}" = first non-empty; "{key}." drops the value's own
  // trailing full stop.
  // "[ ... ]" = optional part, dropped when a key inside is empty; an empty key outside one fails the template (null).
  function fill(tpl, d) {
    var sub = function (s) {
      var miss = false;
      var out = s.replace(/\{([\w|]+)\}/g, function (all, keys, at) {
        var v = null, dot = s.charAt(at + all.length) === '.'; // the template adds its own full stop
        keys.split('|').some(function (k) {
          var low = k.charAt(0).toLowerCase() + k.slice(1), x = typeof d[low] === 'string' ? d[low] : null;
          if (x && dot) x = x.replace(/\.$/, '');
          if (x && k !== low) x = x.charAt(0).toUpperCase() + x.slice(1);
          v = x;
          return !!x;
        });
        if (!v) miss = true;
        return v || '';
      });
      return miss ? null : out;
    };
    var out = sub(tpl.replace(/\[([^\]]*)\]/g, function (_, seg) { return sub(seg) || ''; }));
    return out && out.trim() ? out.trim() : null;
  }
  function templates(d) {
    each($$('[data-p-tpl]'), function (el) {
      var t = fill(el.getAttribute('data-p-tpl'), d);
      if (t) text(el, t); else hide(el.closest('[data-p-unit]') || el);
    });
    each($$('[data-p-alt]'), function (el) { el.setAttribute('alt', fill(el.getAttribute('data-p-alt'), d) || ''); });
  }

  // ---------- landing: "Your website" phones, showcase frame, hero line ----------
  // Idempotent: every top-level [data-p] slot is put back to its pristine markup (deep clone taken before the first
  // fill; no innerHTML) and then filled, so apply() can run again with another result.
  var SNAP = null;
  function pristine() {
    var tops = Array.prototype.filter.call($$('[data-p]'), function (el) { return !el.parentElement.closest('[data-p]'); });
    if (!SNAP) { SNAP = tops.map(function (el) { return [el, el.cloneNode(true)]; }); return; }
    SNAP.forEach(function (p) {
      var el = p[0], s = p[1], i;
      for (i = el.attributes.length - 1; i >= 0; i--) if (!s.hasAttribute(el.attributes[i].name)) el.removeAttribute(el.attributes[i].name);
      for (i = 0; i < s.attributes.length; i++) {
        if (el.getAttribute('data-p') === 'demo' && /^(src|href)$/.test(s.attributes[i].name)) continue; // set below; no double load
        if (el.getAttribute(s.attributes[i].name) !== s.attributes[i].value) el.setAttribute(s.attributes[i].name, s.attributes[i].value);
      }
      el.textContent = '';
      each(s.cloneNode(true).childNodes, function (c) { el.appendChild(c.cloneNode(true)); });
    });
  }
  function landing(m) {
    pristine();
    var d = dict(m), name = d.name, q = function (k) { return document.querySelector('[data-p="' + k + '"]'); };
    var row = function (k, site, title) {
      each($$('[data-p="' + k + '"]'), function (r) {
        if (site == null) return hide(r);
        if (site) text(r.querySelector('.m-site'), site);
        if (title) text(r.querySelector('.m-title'), title);
        var f = site && /^(leak-\d|gone)$/.test(k) && r.querySelector('.fav');
        if (f) { // a letter avatar per leak site, like the hero card's rows
          f.textContent = site.charAt(0).toUpperCase();
          f.classList.add('fav-l');
          f.style.background = E.favColor(site);
        }
      });
    };
    each($$('[data-p="search"], [data-p="name"]'), function (el) { text(el, name); });
    each($$('[data-p="site"]'), function (el) { text(el, d.site); });
    if (m.leaks.length) {
      LEAK_TITLES.forEach(function (t, i) { row('leak-' + (i + 1), m.leaks[i] || null, t.replace('{n}', name)); });
      row('gone', m.leaks[0]);
    } // no leak domains: the leak rows stay the generic illustration
    each($$('[data-p="thumbs"] .thumb'), function (span, i) {
      var u = m.images[i];
      if (!u) return;
      var img = make('img', 'p-img', [], { src: E.thumb(u), alt: '', width: '60', height: '60',
        loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer' });
      E.watchThumb(img, function () { img.remove(); });   // dead / blank: the illustration's gradient stays
      span.appendChild(img);
    });
    row('ig', d.ig ? '' : null, d.ig ? name + ' (@' + d.ig + ')' : '');
    row('tt', d.tiktok ? '' : null, d.tiktok ? '@' + d.tiktok : '');
    row('own', d.site, name + ': Official site');
    row('blog', d.site + ' \u203a blog');
    phones(m, d);
    if (m.profile) {
      text(q('site-url'), d.site);
      text(q('demo-intro'), 'A preview built from your scan: your name and links, your photos as they arrive. Scroll around inside it. The real one we make together.');
    }
    // Hero "Weekly report" card + "Free scan report" illustration: only the handle for now. Their rows / "N links
    // found" pill are marked (report-row-*, scan-row-*, scan-count) but stay the illustration: no invented statuses.
    each($$('[data-p="report-handle"], [data-p="scan-handle"]'), function (el) { text(el, '@' + m.handle); });
    var demo = 'showcase/?r=' + encodeURIComponent(m.slug);
    each($$('[data-p="demo"]'), function (el) {
      var k = el.tagName === 'IFRAME' ? 'src' : 'href';
      if (el.getAttribute(k) !== demo) el.setAttribute(k, demo);
      if (k === 'src') keepSlug(el);
    });

    // phone sticky bar: "Free scan" → "DM me on Telegram", prefilled like #contact's Telegram channel with her report link
    // (E.reportUrl, absolute) + handle. Set again on every apply(); Reset reloads = the original bar.
    var bar = document.querySelector('.mobile-cta');
    if (bar) {
      bar.setAttribute('href', 'https://t.me/jakabasej?text=' + encodeURIComponent('Hi Jaka, I ran the free scan. My report link and handle: ' + E.reportUrl(m.slug) + ' @' + m.handle));
      bar.querySelector('use').setAttribute('href', '#i-send');
      bar.lastChild.textContent = 'DM me on Telegram';
    }

    var line = q('scanned');
    if (line) {
      var reset = make('button', 'linkish', ['Reset page'], { type: 'button' });
      reset.addEventListener('click', function () {
        E.forget();
        try { sessionStorage.removeItem(CACHE + m.slug); } catch (e) { /* ignore */ }
        location.href = location.pathname;
      });
      line.textContent = '';
      // one line in the note's slot (CSS): the handle shortens before anything wraps
      [ make('span', null, ['Scanned ', make('strong', null, ['@' + m.handle])]), ' \u00b7 ',
        make('a', null, ['Your report'], { href: E.reportUrl(m.slug) }), ' \u00b7 ', reset
      ].forEach(function (c) { line.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
      line.hidden = false;
    }
  }

  // Before / after phones: after a scan every row of their All tab is a real link (leak rows → her leak pages,
  // Instagram / TikTok → her accounts, her site / blog → the demo site above, Removed → pricing) and the label drops
  // "Illustration:". The phones are labelled groups either way (their All / Images / Videos tabs are real buttons).
  var PHONES = null;
  function phones(m, d) {
    var ba = document.querySelector('.ba');
    if (!ba) return;
    if (!PHONES) PHONES = Array.prototype.map.call($$('.phone', ba), function (ph) { return [ph, ph.getAttribute('aria-label')]; });
    PHONES.forEach(function (p) { p[0].setAttribute('aria-label', p[1]); }); // back to the illustration first (apply() can run again)
    ba.classList.remove('is-live');
    var hint = document.querySelector('.ba-hint');
    if (hint) hint.remove();
    var urls = m.urls || {}, acc = function (k) { return d.acc[k] && d.acc[k].url; };
    var to = {
      own: '#showcase', blog: '#showcase', gone: '#pricing', ig: acc('instagram'), tt: acc('tiktok'),
      'leak-1': urls[m.leaks[0]], 'leak-2': urls[m.leaks[1]], 'leak-3': urls[m.leaks[2]], 'leak-4': urls[m.leaks[3]]
    };
    var n = 0;
    each($$('[data-p]', ba), function (r) {
      var k = r.getAttribute('data-p'), href = to[k];
      if (!href || !r.classList.contains('m-result') || r.hasAttribute('data-p-off')) return;
      var out = href.charAt(0) !== '#', site = r.querySelector('.m-site'), title = r.querySelector('.m-title');
      var label = [site && site.textContent, title && title.textContent].filter(Boolean).join(': ') + (out ? ' (opens in a new tab)' : '');
      var a = make('a', 'm-link', [], Object.assign({ href: href, 'aria-label': label }, out ? NEW_TAB : {}));
      while (r.firstChild) a.appendChild(r.firstChild);
      a.appendChild(make('span', 'm-go', ['\u2197'], { 'aria-hidden': 'true' }));
      r.appendChild(a);
      r.classList.add('is-link');
      n++;
    });
    if (!n) return;
    PHONES.forEach(function (p) {
      p[0].setAttribute('aria-label', p[1].replace(/^Illustration: /, '').replace(/^./, function (c) { return c.toUpperCase(); }));
    });
    ba.classList.add('is-live');
    if (!document.querySelector('.ba-hint')) ba.parentNode.insertBefore(make('p', 'ba-hint', ['Tap a result to open it']), ba.nextSibling);
  }

  // ---------- demo site ----------
  // With a profile, every content block that is not marked data-p / data-p-tpl / data-p-keep / data-p-unit /
  // data-p-show is hidden: Orla's facts and pottery prose never show next to someone else's name.
  var BLOCKS = 'p,li,h1,h2,h3,h4,h5,h6,blockquote,figure,picture,img,table,dl,ol,ul,.btn,.chip,.notice,.facts-row,' +
    '.fact-item,.social-card,.link-btn,.blog-card,.post-meta';
  var MARK = '[data-p],[data-p-tpl],[data-p-keep],[data-p-unit],[data-p-show],[data-p-media-only]';
  var SKIP = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEMPLATE: 1, NAV: 1, svg: 1 };

  function ownText(el) {
    for (var n = el.firstChild; n; n = n.nextSibling) if (n.nodeType === 3 && n.nodeValue.trim()) return true;
    return false;
  }
  function strong(s) { return make('strong', null, [s]); }
  var builders = {
    eyebrow: function (el, d) {
      var t = [d.profession && d.profession.charAt(0).toUpperCase() + d.profession.slice(1), d.location].filter(Boolean).join(' \u00b7 ');
      if (t) text(el, t); else hide(el);
    },
    welcome: function (el, d) {
      var kids = ['This is the official website of ', strong(d.name)];
      if (d.tagline) kids.push(', ' + d.tagline.replace(/\.$/, ''));
      if (d.ig) kids.push(', known as ', strong('@' + d.ig), ' on Instagram');
      if (d.tiktok) kids.push(d.ig ? ' and as ' : ', known as ', strong('@' + d.tiktok), ' on TikTok');
      kids.push('.');
      if (d.location) kids.push(' ' + d.first + ' is based in ', strong(d.location), '.');
      el.textContent = '';
      kids.forEach(function (c) { el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    },
    'links-bio': function (el, d) {
      var t = [d.profession && d.profession.charAt(0).toUpperCase() + d.profession.slice(1), d.location].filter(Boolean).join(' \u00b7 ');
      el.textContent = '';
      if (t) { el.appendChild(document.createTextNode(t)); el.appendChild(make('br')); }
      el.appendChild(document.createTextNode('These are my only accounts.'));
    },
    links: function (el, d) {
      var n = 0;
      el.textContent = '';
      Object.keys(d.acc).forEach(function (k) {
        var a = d.acc[k];
        if (!a.url) return;
        var icon = document.querySelector('.link-btn[id^="' + k + '-"] svg');
        var btn = make('a', 'link-btn' + (n ? '' : ' link-btn--featured'),
          [make('span', 'link-btn__label', [PLAT[k][0] + ' \u2014 @' + a.handle])], Object.assign({ id: 'p-' + k, href: a.url }, NEW_TAB));
        if (icon) btn.insertBefore(icon.cloneNode(true), btn.firstChild);
        el.appendChild(btn);
        n++;
      });
      if (!n) hide(el);
    },
    social: function (el, d) {
      each($$('a.social-icon', el), function (a) {
        var k = ((a.getAttribute('href') || '').split('#')[1] || '').split('-')[0], acc = d.acc[k];
        if (!acc || !acc.url) return hide(a);
        a.setAttribute('href', 'links.html#p-' + k);
        a.setAttribute('aria-label', d.name + ' on ' + PLAT[k][0]);
      });
    },
    avatar: function (el, d, m) {
      if (!m.profile.avatar) return;
      var orig = el.getAttribute('src');
      el.addEventListener('error', function () { el.setAttribute('src', orig); }, { once: true });
      el.removeAttribute('srcset');
      el.setAttribute('src', API + '/api/avatar/' + encodeURIComponent(m.slug));
      el.setAttribute('alt', d.name);
    }
  };

  function showEl(el) { if (el) { el.style.display = ''; el.removeAttribute('data-p-off'); } }
  // "<name>, photo n of N": N = photos arrived so far; every swapped photo is re-labelled when more arrive
  function photoLabel(img, d, total) {
    var n = +img.getAttribute('data-p-media') + 1, t = d.name + ', photo ' + n + ' of ' + Math.max(total, n);
    img.setAttribute('alt', t);
    var unit = img.closest('[data-p-media-only]'), b = unit && unit.querySelector('button[aria-label]');
    if (b) b.setAttribute('aria-label', 'View larger: ' + t);
  }
  function swapImg(img, src, d, total) {
    img.setAttribute('data-p-src', src);
    var pre = new Image();
    pre.onload = function () {
      if (img.getAttribute('data-p-src') !== src) return;
      var pic = img.parentNode;
      if (pic && pic.tagName === 'PICTURE') each($$('source', pic), function (x) { x.remove(); });
      // fixed box: keep the placeholder's aspect ratio, crop the photo into it
      if (img.getAttribute('width')) img.style.aspectRatio = img.getAttribute('width') + ' / ' + img.getAttribute('height');
      img.style.objectFit = 'cover';
      // her photo, focal point unknown: faces sit in the upper part of most photos (a portrait is cropped hardest)
      img.style.objectPosition = pre.naturalHeight > pre.naturalWidth ? 'center 20%' : 'center 30%';
      img.classList.add('p-fade');
      img.style.opacity = '0';
      img.removeAttribute('srcset');
      img.setAttribute('src', src);
      photoLabel(img, d, total());
      var unit = img.closest('[data-p-media-only]');
      if (unit) {
        showEl(unit);
        showEl(unit.closest('[data-p-gallery]'));
      }
      requestAnimationFrame(function () { requestAnimationFrame(function () { img.style.opacity = ''; }); });
    };
    pre.src = src;
  }
  function media(m, d) {
    var slots = $$('img[data-p-media]');
    if (!slots.length) return;
    var total = 0, count = function () { return total; };
    pollMedia(m.slug, function (imgs) {
      var was = total;
      total = Math.min(imgs.length, slots.length);
      each(slots, function (img) {
        var it = imgs[+img.getAttribute('data-p-media')];
        if (it && img.getAttribute('data-p-src') !== it.src) swapImg(img, it.src, d, count);
        else if (total !== was && img.classList.contains('p-fade')) photoLabel(img, d, total);
      });
    });
  }

  function demo(m) {
    if (!m.profile) return slugLinks(m.slug); // scan only: the demo stays the fictional creator, its links keep the slug
    var d = dict(m);
    each($$('[data-p]'), function (el) {
      var b = builders[el.getAttribute('data-p')];
      if (b) b(el, d, m);
    });
    templates(d);
    each($$('[data-p-show]'), function (el) { if (!el.hasAttribute('data-p-off')) el.hidden = false; });
    each(document.body.children, function (top) {
      if (SKIP[top.tagName] || top.matches('.demo-ribbon, .lightbox, .skip-link')) return;
      each([top].concat(Array.prototype.slice.call($$('*', top))), function (el) {
        if (SKIP[el.tagName] || el.closest('svg, script, style')) return;
        if (!(el.matches(BLOCKS) || ownText(el))) return;
        if (el.closest(MARK) || el.querySelector(MARK)) return;
        hide(el);
      });
      each([top].concat(Array.prototype.slice.call($$('section, header', top))), function (s) {
        if (s.matches('section, header') && !s.innerText.trim() && !s.querySelector('img:not([data-p-off])')) hide(s);
      });
    });
    // photos-only blocks (galleries) stay hidden until their photo arrives
    each($$('[data-p-media-only], [data-p-gallery]'), hide);
    media(m, d);
    var t = fill(document.body.getAttribute('data-p-title') || '', d);
    if (t) document.title = t;
    slugLinks(m.slug);
    document.documentElement.classList.add('p-on');
  }
  // keep the slug on every internal link so navigating inside the demo (and the landing iframe) stays on her scan
  function slugLinks(slug) {
    each($$('a[href]'), function (a) {
      var raw = a.getAttribute('href');
      if (!raw || raw.charAt(0) === '#' || /^[a-z][a-z0-9+.-]*:/i.test(raw)) return;
      var u;
      try { u = new URL(raw, location.href); } catch (e) { return; }
      if (u.origin !== location.origin) return;
      u.searchParams.set('r', slug);
      a.setAttribute('href', u.href);
    });
  }

  // A lazy iframe's deferred first load (showcase/) can commit after the src change above and win: Chrome left the demo
  // un-personalized in ~1 of 16 desktop loads (measured). So until the iframe has loaded a page with ?r=, a load without
  // it is sent on to its src; from the first ?r= load on, the listener is gone: whatever the visitor does inside the
  // demo is never undone (once its scan result is in, scan-only too, its links carry ?r=: slugLinks()).
  function keepSlug(f) {
    if (f.keepSlug) return;
    f.keepSlug = true;
    var onLoad = function () {
      try {
        if (/[?&]r=/.test(f.contentWindow.location.search)) f.removeEventListener('load', onLoad);
        else f.contentWindow.location.replace(new URL(f.getAttribute('src'), location.href).href);
      } catch (e) { f.removeEventListener('load', onLoad); /* not same-origin: leave it */ }
    };
    f.addEventListener('load', onLoad);
  }

  // ---------- wiring ----------
  // apply(result): personalize from an in-memory scan result, no reload; a scan run on this page reaches it through the
  // leakscan:result event (scan-engine.js). applySlug(slug): fetch + personalize (?r= / last scan). Both are internal;
  // the only export is pollMedia(slug, cb), the demo-photo poller. Safe to run repeatedly.
  var isDemo = document.body.hasAttribute('data-p-demo'), shown = null;
  function render(m) {
    if (!isDemo) return landing(m);
    if (!shown) { shown = m.slug; return demo(m); }
    // the demo's whitelist hiding is one-way: a different creator = reload with her slug (model already cached)
    if (shown !== m.slug) location.replace(location.pathname + '?r=' + encodeURIComponent(m.slug));
  }
  function apply(result) {
    var slug = result ? C.slug(result.slug) : null;
    var m = slug && clean(result, slug);
    if (!m) return false;
    try { sessionStorage.setItem(CACHE + slug, JSON.stringify({ ts: Date.now(), m: m })); } catch (e) { /* ignore */ }
    render(m);
    return true;
  }
  function applySlug(slug) {
    if (!C.slug(slug)) return false;
    load(slug, render);
    return true;
  }
  window.LeakScanPersonalize = { pollMedia: pollMedia };   // the scan page's / hero card's photo status

  if (!document.querySelector('[data-p]') && !isDemo) return; // e.g. scan/: poller only
  document.addEventListener('leakscan:result', function (e) { apply(e.detail); });   // a scan run on this page (scan-engine.js)
  var slug = E.currentSlug();
  if (slug) applySlug(slug);
})();
