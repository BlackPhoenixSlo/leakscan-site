// Free scan page: runs the scan on Jaka's scan server and renders the report. Plain ES2017, no tracking, no third
// parties. Transport, API host and message links live in js/scan-engine.js (shared with the landing hero).
(function () {
  'use strict';
  var E = window.LeakScanEngine;
  var REPORT_BASE = E.REPORT_BASE, PLATFORMS = E.PLATFORMS, cleanHandle = E.cleanHandle, thumb = E.thumb, setMessages = E.setMessages;
  var MAX_THUMBS = 30;
  var G_COLORS = ['#4285f4', '#ea4335', '#fbbc05', '#4285f4', '#34a853', '#ea4335'];

  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  var show = function (id, on) { $(id).hidden = !on; };
  var plural = function (n, one, many) { return n === 1 ? one : many; };
  var num = function (n) { return Number(n || 0).toLocaleString('en-US'); };

  // ---------- input ----------
  function safeUrl(u) { return typeof u === 'string' && /^https?:\/\//i.test(u) ? u : null; }
  function host(u) {
    try { return new URL(u).hostname.replace(/^www\./, ''); } catch (e) { return ''; }
  }

  // ---------- state ----------
  var state = { handle: '', platform: 'onlyfans.com', social: null, data: null, tab: 'all', device: 'phone', revealed: false,
    more: { all: 10, images: 12 }, retry: null };
  state.device = window.matchMedia('(min-width: 720px)').matches ? 'computer' : 'phone';

  function setTitle(kicker, title, lead) {
    $('scan-kicker').textContent = kicker;
    $('scan-title').textContent = title;
    $('scan-lead').textContent = lead;
  }
  function hideAll() {
    ['scan-form', 'form-error', 'progress', 'error', 'summary', 'empty', 'report', 'scan-aliases'].forEach(function (id) { show(id, false); });
  }

  // ---------- message links ----------
  function who() { return E.who(state.handle, state.platform); }

  // ---------- form ----------
  function showForm(message) {
    hideAll();
    setTitle('Free leak scan', 'Free leak scan', 'See what Google shows for your handle: pages, images and videos, and every leak link the scan finds.');
    var f = $('scan-form');
    f.hidden = false;
    if (message) { $('form-error').textContent = message; show('form-error', true); f.elements.h.focus(); }
  }
  $('scan-form').addEventListener('submit', function (e) {
    var f = e.target;
    if (!cleanHandle(f.elements.h.value)) {
      e.preventDefault();
      showForm('That doesn’t look like a handle. Use letters, numbers, dots, dashes or underscores, like yourhandle.');
    } else if (E.cleanSocial(f.elements.ig.value) === false) {
      e.preventDefault();
      showForm(SOCIAL_BAD);
      f.elements.ig.focus();
    }
  });

  var SOCIAL_BAD = 'That Instagram or X username doesn’t look right. Paste the profile link or type the name, like yourname.';

  // ---------- errors ----------
  var ERRORS = {
    rate_limited: ['You’ve reached the free scan limit for now', 'To keep the scan free, the server limits how many scans one connection can run. Try again in a little while, or message me your handle and I’ll run it for you.', false],
    busy: ['The scanner is busy right now', 'Other scans are running at the moment. Try again in a minute, or message me your handle and I’ll run it for you.', true],
    failed: ['The scan didn’t finish', '', true],
    network: ['Couldn’t reach the scan server', 'Check your connection and try again. If it keeps happening, message me your handle and I’ll run the scan for you.', true],
    not_found: ['This report link doesn’t work', 'The report may have been removed, or the link is incomplete. Run a new scan, or message me and I’ll help.', false]
  };
  function showError(kind, detail) {
    hideAll();
    var e = ERRORS[kind] || ERRORS.failed;
    setTitle('Free leak scan', state.handle ? '@' + state.handle : 'Free leak scan', state.handle ? 'Scan on ' + (PLATFORMS[state.platform] || state.platform) : '');
    $('error').dataset.kind = kind;
    $('error-title').textContent = e[0];
    $('error-text').textContent = kind === 'failed'
      ? (detail ? detail + '. ' : '') + 'Try again in a minute, or message me your handle and I’ll run it for you.'
      : e[1];
    show('retry', e[2] && !!state.retry);
    var t = state.handle ? 'Hi Jaka, the free scan didn’t work for me. My handle: ' + who()
      : 'Hi Jaka, I’d like the free Google scan. My creator name / handles: ';
    setMessages($('error'), t, 'Free Google scan', 'Hi Jaka,\n\n' + t + '\n\nThanks!');
    show('error', true);
    if (kind === 'not_found') { $('scan-form').hidden = false; }
  }
  $('retry').addEventListener('click', function () { if (state.retry) state.retry(); });
  // ---------- scan + reopen ----------
  function startScan() {
    hideAll();
    state.retry = startScan;
    var name = PLATFORMS[state.platform];
    setTitle('Free leak scan', 'Scanning Google for @' + state.handle,
      'I’m checking what Google has indexed for your ' + name + ' handle: pages, images and videos.');
    $('progress-log').textContent = '';
    $('progress-stage').textContent = 'Starting the scan…';
    setBar(3);
    show('progress', true);
    E.runScan({ platform: state.platform, handle: state.handle, social: state.social, onProgress: addProgress,
      onResult: function (result) { setBar(100); report(result, true); },
      onError: function (e) {
        if (e.kind === 'bad_handle') showForm('The scan server didn’t accept that handle. Check it and try again.');
        else showError(e.kind, e.detail);
      } });
  }
  function setBar(p) {
    var b = $('progress-bar');
    b.setAttribute('aria-valuenow', String(Math.round(p)));
    b.firstElementChild.style.width = p + '%';
  }
  function addProgress(text) {
    var p = E.progressInfo(text);
    if (p.pct != null) setBar(p.pct);
    $('progress-stage').textContent = p.stage;
    var log = $('progress-log');
    var li = document.createElement('li');
    li.textContent = text;
    log.appendChild(li);
    while (log.children.length > 6) log.removeChild(log.firstChild);
  }
  function reopen(slug) {
    hideAll();
    state.retry = function () { reopen(slug); };
    setTitle('Free scan report', 'Loading the report…', '');
    E.fetchResult(slug).then(function (r) { report(r, false); }, function (e) { showError(e.kind || 'network', e.detail); });
  }

  // ---------- report ----------
  function normalize(r) {
    var hits = Array.isArray(r.hits) ? r.hits.filter(function (h) { return h && safeUrl(h.url); }) : [];
    var results = Array.isArray(r.results) ? r.results.filter(function (x) { return x && safeUrl(x.link); }).slice(0, 80) : [];
    results.forEach(function (x) { x.domain = x.domain || host(x.link); });
    hits.forEach(function (h) { h.domain = h.domain || host(h.url); });
    var d = {
      slug: String(r.slug || ''), handle: String(r.handle || state.handle || ''), platform: r.platform || state.platform,
      hit_count: +r.hit_count || hits.length, domain_count: +r.domain_count || 0, google_total: +r.google_total || 0,
      images: Array.isArray(r.images) ? r.images : [], hits: hits, results: results
    };
    d.status = r.status || (d.hit_count || results.length ? 'complete' : 'empty');
    var al = r.aliases && typeof r.aliases === 'object' && Array.isArray(r.aliases.discovered) ? r.aliases.discovered : [];
    d.discovered = al.slice(0, 4).filter(function (a) { return typeof a === 'string' && E.HANDLE_RE.test(a) && a !== d.handle; });
    return d;
  }
  function report(raw, fresh) {
    var d = state.data = normalize(raw);
    state.handle = d.handle;
    state.platform = PLATFORMS[d.platform] ? d.platform : state.platform;
    if (d.slug && history.replaceState) history.replaceState(null, '', '?r=' + encodeURIComponent(d.slug));
    hideAll();
    var name = PLATFORMS[state.platform] || state.platform;
    var empty = d.status === 'empty';
    setTitle('Free scan report', '@' + d.handle,
      empty ? 'Scan of what Google shows for your ' + name + ' handle.'
        : 'Copies found on ' + d.domain_count + ' ' + plural(d.domain_count, 'site', 'sites') + '. Here is what Google shows for your ' + name + ' handle.');
    document.title = '@' + d.handle + ' · Free scan report · Abolita';
    $('scan-aliases').textContent = d.discovered.length ? 'Also found as ' + d.discovered.map(function (a) { return '@' + a; }).join(', ') : '';
    show('scan-aliases', d.discovered.length > 0);
    $('summary').querySelector('[data-stat=domains]').textContent = num(d.domain_count);
    $('summary').querySelector('[data-label=domains]').textContent = plural(d.domain_count, 'site with copies found', 'sites with copies found');
    $('summary').querySelector('[data-stat=pages]').textContent = num(d.hit_count);
    $('summary').querySelector('[data-label=pages]').textContent = plural(d.hit_count, 'indexed page', 'indexed pages');
    $('summary').querySelector('[data-stat=google]').textContent = '~' + num(d.google_total);
    show('summary', true);
    show('empty', empty);
    ['google', 'sites', 'links'].forEach(function (id) { show(id, !empty); });

    E.sendReport($('send'), d.slug, d.handle, state.platform);
    $('deep-link').href = 'https://jackbase.me/scan?p=' + encodeURIComponent(state.platform) + '&h=' + encodeURIComponent(d.handle) + '&l=deep&go=1';
    $('g-note').textContent = 'Rendered from Google’s index for @' + d.handle + '. Not a live screenshot.';
    var r = encodeURIComponent(d.slug);
    $('after-link').href = '../?r=' + r + '#website';
    $('demo-link').href = '../showcase/?r=' + r;
    E.remember(raw, d.slug, d.handle, state.platform);
    mediaStatus(raw.profile && typeof raw.profile === 'object' ? d.slug : null);
    show('report', true);
    if (!empty) { renderGoogle(); renderSites(); renderLinks(); }
    if (fresh) $('scan-title').focus({ preventScroll: true });
  }

  // Demo-site photos arrive after the scan: js/personalize.js polls /api/media/<slug>; this line mirrors it.
  var mediaToken = 0;
  function mediaStatus(slug) {
    var el = $('after-media'), tok = ++mediaToken;
    el.hidden = true;
    if (!slug || !window.LeakScanPersonalize) return;
    window.LeakScanPersonalize.pollMedia(slug, function (imgs, phase) {
      if (tok !== mediaToken) return;
      var ready = phase === 'ready' || (phase !== 'pending' && imgs.length > 0);
      el.textContent = ready ? 'Photos ready' : 'Gathering photos for your demo site…';
      el.dataset.phase = ready ? 'ready' : phase;
      el.hidden = !ready && phase !== 'pending';
    });
  }

  // ---------- "What Google shows" ----------
  function fav(dom, cls) { return E.fav(dom, cls).outerHTML; }
  function siteName(dom) { var b = dom.split('.')[0] || dom; return b.charAt(0).toUpperCase() + b.slice(1); }
  function crumbs(u) {
    try {
      var x = new URL(u), segs = x.pathname.split('/').filter(Boolean).slice(0, 3);
      return x.protocol + '//' + x.hostname + (segs.length ? ' › ' + segs.map(decodeURIComponent).join(' › ') : '');
    } catch (e) { return u; }
  }
  function gLogo() {
    return '<span class="g-logo" aria-hidden="true">' + 'Google'.split('').map(function (c, i) {
      return '<span style="color:' + G_COLORS[i] + '">' + c + '</span>';
    }).join('') + '</span>';
  }
  function imageItems(d) { return E.imageItems(d.images, d.results, thumb, MAX_THUMBS); }
  function img(u, alt) {
    return '<span class="g-img"><img src="' + esc(thumb(u)) + '" alt="' + esc(alt || '') + '" loading="lazy" decoding="async" referrerpolicy="no-referrer"></span>';
  }
  function a(u, cls, inner) {
    return '<a class="' + cls + '" href="' + esc(u) + '" target="_blank" rel="noopener noreferrer nofollow">' + inner + '</a>';
  }
  // "open ↗" on hover / focus; on touch screens a small ↗ that is always there (css: .g-go)
  var GO = '<span class="g-go" aria-hidden="true"><span class="g-go-w">open </span>↗</span>';
  // the pill rides on the title's last word (never alone on a line); a long last word (a bare URL) wraps as before
  function titled(t) {
    t = esc(String(t).trim());
    var i = t.lastIndexOf(' '), w = t.slice(i + 1);
    return w.length > 24 ? t + GO : t.slice(0, i + 1) + '<span class="g-nw">' + w + GO + '</span>';
  }
  function more(kind, label, left) {
    return left > 0 ? '<button type="button" class="g-more" data-more="' + kind + '">' + esc(label) + '</button>' : '';
  }

  function panelAll(d, phone) {
    var pages = d.results.filter(function (r) { return r.kind !== 'video'; });
    var imgs = imageItems(d).slice(0, phone ? 4 : 6);
    var h = phone ? '' : '<p class="g-stats">About ' + num(d.google_total) + ' results</p>';
    if (imgs.length) {
      h += '<div class="g-pack"><p class="g-pack-h">Images</p><div class="g-pack-row">' +
        imgs.map(function (it) {
          return '<button type="button" class="g-pack-b" data-goto="images" aria-label="Show image results">' + img(it.src, '') + '</button>';
        }).join('') +
        '</div><button type="button" class="g-more g-more-sm" data-goto="images">Show more images</button></div>';
    }
    if (!pages.length) return h + '<p class="g-empty">No web results indexed for this handle.</p>';
    var n = Math.min(state.more.all, pages.length);
    h += pages.slice(0, n).map(function (r) {
      return '<div class="g-r"><div class="g-src">' + fav(r.domain) + '<div class="g-src-t"><span class="g-site">' + esc(siteName(r.domain)) +
        '</span><span class="g-cite">' + esc(crumbs(r.link)) + '</span></div></div>' +
        a(r.link, 'g-title', titled(r.title || r.link)) + (r.snippet ? '<p class="g-snip">' + esc(r.snippet) + '</p>' : '') + '</div>';
    }).join('');
    return h + more('all', 'More results', pages.length - n);
  }
  function panelImages(d, phone) {
    var items = imageItems(d);
    if (!items.length) return '<p class="g-empty">No image results indexed for this handle.</p>';
    var n = phone ? Math.min(state.more.images, items.length) : items.length;
    var h = '<div class="g-safe" aria-hidden="true"><span>SafeSearch off: what anyone searching your handle sees</span></div>';
    h += '<div class="g-grid">' + items.slice(0, n).map(function (it) {
      // an image no result has: same caption shape, credited to Google Images (nothing to open: this is the report)
      var cap = it.domain ? '<span class="g-ct">' + esc(it.title || it.domain) + '</span><span class="g-cs">' + fav(it.domain, 'g-fav-s') + esc(it.domain) + '</span>'
        : '<span class="g-ct">Image result</span><span class="g-cs">' + fav('google.com', 'g-fav-s') + 'Google Images</span>';
      var tile = img(it.src, it.title || 'Image result');
      return '<figure class="g-tile">' + (it.link ? a(it.link, 'g-tile-a', tile + GO) : tile) + '<figcaption>' + cap + '</figcaption></figure>';
    }).join('') + '</div>';
    return h + more('images', 'Show more images', items.length - n);
  }
  function panelVideos(d) {
    var vids = d.results.filter(function (r) { return r.kind === 'video'; });
    if (!vids.length) return '<p class="g-empty">No video results indexed for this handle</p>';
    return vids.map(function (r) {
      var t = r.thumb && thumb(r.thumb) ? img(r.thumb, r.title) : '<span class="g-img g-img-none"></span>';
      return '<div class="g-v">' + a(r.link, 'g-vthumb', t + '<span class="g-play" aria-hidden="true"></span>' + GO) +
        '<div class="g-vbody">' + a(r.link, 'g-title', titled(r.title || r.link)) +
        '<span class="g-cite">' + fav(r.domain, 'g-fav-s') + esc(r.domain) + esc(crumbs(r.link).replace(/^https?:\/\/[^ ]+/, '')) + '</span>' +
        (r.snippet ? '<p class="g-snip">' + esc(r.snippet) + '</p>' : '') + '</div></div>';
    }).join('');
  }
  var TABS = [['all', 'All'], ['images', 'Images'], ['videos', 'Videos']];
  function tabRow() {
    var deco = function (t) { return '<span class="g-tab-deco" aria-hidden="true">' + t + '</span>'; };
    return '<div class="g-tabs" role="tablist" aria-label="Google result type">' + deco('AI Mode') + TABS.map(function (t) {
      var on = state.tab === t[0];
      return '<button type="button" role="tab" class="g-tab" id="g-tab-' + t[0] + '" data-tab="' + t[0] + '" aria-selected="' + on +
        '" aria-controls="g-panel" tabindex="' + (on ? 0 : -1) + '">' + t[1] + '</button>';
    }).join('') + deco('Short videos') + deco('Forums') + deco('More ▾') + '</div>';
  }
  function renderGoogle(focusTab) {
    var d = state.data, phone = state.device === 'phone';
    var q = d.handle + ' leaks';
    var panel = state.tab === 'images' ? panelImages(d, phone) : state.tab === 'videos' ? panelVideos(d) : panelAll(d, phone);
    var body = '<div class="g-panel g-panel-' + state.tab + '" role="tabpanel" id="g-panel" aria-labelledby="g-tab-' + state.tab + '">' + panel + '</div>';
    var search = '<div class="g-search" aria-hidden="true"><svg class="icon"><use href="#i-search"/></svg><span>' + esc(q) + '</span></div>';
    var h;
    if (phone) {
      h = '<div class="frame-phone" data-device="phone"><div class="ph-screen g-dark g-' + state.tab + '">' +
        '<div class="ph-status" aria-hidden="true"><span>9:41</span><span class="ph-icons"><i class="ph-sig"></i><i class="ph-wifi"></i><i class="ph-bat"></i></span></div>' +
        '<div class="gm-head" aria-hidden="true"><span class="gm-burger"><i></i><i></i><i></i></span>' + gLogo() + '<span class="g-av"></span></div>' +
        search + tabRow() + body + '<div class="ph-home" aria-hidden="true"></div></div></div>';
    } else {
      var path = 'google.com/search?q=' + encodeURIComponent(d.handle).replace(/%20/g, '+') + '+leaks' +
        (state.tab === 'images' ? '&udm=2' : state.tab === 'videos' ? '&tbm=vid' : '');
      h = '<div class="cw-scale"><div class="frame-computer" data-device="computer">' +
        '<div class="bw-bar" aria-hidden="true"><span class="dots"><i></i><i></i><i></i></span><span class="bw-url">' + esc(path) + '</span></div>' +
        '<div class="g-dark gd g-' + state.tab + '"><div class="gd-top" aria-hidden="true">' + gLogo() + search +
        '<span class="gd-apps"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span><span class="g-av"></span></div>' +
        tabRow() + body + '</div></div></div>';
    }
    var stage = $('g-stage');
    stage.className = 'g-stage' + (state.revealed ? ' revealed' : '');
    stage.innerHTML = h;
    // an image tile whose thumb fails or loads blank (hotlink-blocked) leaves the grid / pack (no empty square); other
    // thumbs (video stills, icons) fall back to their grey box
    stage.querySelectorAll('img').forEach(function (im) {
      var drop = function () {
        var t = im.closest('.g-tile, .g-pack-b');
        if (t) t.remove(); else { im.parentNode.classList.add('g-img-none'); im.remove(); }
      };
      im.addEventListener('error', drop, { once: true });
      im.addEventListener('load', function () { if (im.naturalWidth < 16 || im.naturalHeight < 16) drop(); }, { once: true });
    });
    if (!phone) fitComputer(); else if ($('g-hint')) $('g-hint').removeAttribute('data-small');
    if (focusTab) { var b = $('g-tab-' + state.tab); if (b) b.focus(); }
  }
  var ro = null;
  function fitComputer() {
    var wrap = document.querySelector('.cw-scale'), frame = wrap && wrap.firstElementChild;
    if (!frame) return;
    var fit = function () {
      if (!wrap.isConnected) return;   // replaced by the next render (ResizeObserver still reports it, at 0 px)
      var s = Math.min(1, wrap.clientWidth / frame.offsetWidth), hint = $('g-hint');
      frame.style.transform = s < 1 ? 'scale(' + s + ')' : '';
      if (hint) hint.toggleAttribute('data-small', s < 0.6);   // tabs / tiles below a usable tap size: point to the Phone view
      wrap.style.height = Math.ceil(frame.offsetHeight * s) + 'px';
    };
    fit();
    if (ro) ro.disconnect();
    if (window.ResizeObserver) { ro = new ResizeObserver(fit); ro.observe(wrap); ro.observe(frame); }
  }
  window.addEventListener('resize', function () { if (state.device === 'computer' && state.data) fitComputer(); });

  $('g-stage').addEventListener('click', function (e) {
    var t = e.target.closest('[data-tab],[data-more],[data-goto]');
    if (!t) return;
    if (t.dataset.tab) { state.tab = t.dataset.tab; renderGoogle(true); }
    else if (t.dataset.goto) { state.tab = t.dataset.goto; renderGoogle(true); }
    else {
      var k = t.dataset.more;
      state.more[k] += k === 'all' ? 10 : 18;
      renderGoogle(false);
      var nb = document.querySelector('[data-more="' + k + '"]') || $('g-tab-' + state.tab);
      if (nb) nb.focus({ preventScroll: true });
    }
  });
  $('g-stage').addEventListener('keydown', function (e) {
    var t = e.target.closest('[role=tab]');
    if (!t || ['ArrowLeft', 'ArrowRight', 'Home', 'End'].indexOf(e.key) < 0) return;
    e.preventDefault();
    var i = TABS.map(function (x) { return x[0]; }).indexOf(state.tab);
    i = e.key === 'Home' ? 0 : e.key === 'End' ? TABS.length - 1 : (i + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length;
    state.tab = TABS[i][0];
    renderGoogle(true);
  });
  document.addEventListener('click', function (e) {   // "Switch to Phone" in the hint = the Phone toggle
    var b = e.target.closest && e.target.closest('[data-device-go]'), r = b && document.querySelector('#device input[value="' + b.getAttribute('data-device-go') + '"]');
    if (r && !r.checked) { r.checked = true; r.dispatchEvent(new Event('change')); r.focus(); }
  });
  document.querySelectorAll('#device input').forEach(function (r) {
    r.checked = r.value === state.device;
    r.addEventListener('change', function () { if (r.checked) { state.device = r.value; state.more = { all: 10, images: 12 }; renderGoogle(false); } });
  });
  $('reveal').addEventListener('click', function () {
    state.revealed = !state.revealed;
    var b = $('reveal');
    b.setAttribute('aria-pressed', String(state.revealed));
    b.querySelector('span').textContent = state.revealed ? 'Blur images' : 'Reveal images';
    $('g-stage').classList.toggle('revealed', state.revealed);
  });

  // ---------- per-site breakdown + all links ----------
  function groups(d) {
    var by = {}, order = [];
    var add = function (dom, url, occ) {
      if (!dom) return;
      if (!by[dom]) { by[dom] = { domain: dom, links: [], seen: {}, occ: 0, top: null, topOcc: -1 }; order.push(dom); }
      var g = by[dom];
      g.occ += occ || 0;
      if ((occ || 0) > g.topOcc) { g.top = url; g.topOcc = occ || 0; }
      if (!g.seen[url]) { g.seen[url] = 1; g.links.push(url); }
    };
    d.hits.forEach(function (h) { add(h.domain, h.url, +h.occurrences || 1); });
    d.results.forEach(function (r) { add(r.domain, r.link, 0); });
    return order.map(function (k) { return by[k]; }).sort(function (x, y) {
      return y.links.length - x.links.length || y.occ - x.occ;
    });
  }
  function renderSites() {
    $('sites-body').innerHTML = groups(state.data).map(function (g) {
      return '<tr><th scope="row">' + fav(g.domain, 'g-fav-s') + esc(g.domain) + '</th><td data-label="Links">' + g.links.length +
        '</td><td class="top-link">' + a(g.top, 'mono', esc(g.top.replace(/^https?:\/\/(www\.)?/, ''))) + '</td></tr>';
    }).join('');
  }
  function renderLinks() {
    $('links-list').innerHTML = groups(state.data).map(function (g) {
      return '<details><summary><span>' + fav(g.domain, 'g-fav-s') + esc(g.domain) + '</span><span class="count">' + g.links.length + ' ' +
        plural(g.links.length, 'link', 'links') + '</span></summary><ul>' + g.links.map(function (u) {
        return '<li>' + a(u, 'mono', esc(u)) + '</li>';
      }).join('') + '</ul></details>';
    }).join('');
  }
  function linksText() {
    var d = state.data, out = ['Abolita free scan report: ' + who(), 'Report: ' + REPORT_BASE + d.slug,
      d.domain_count + ' sites, ' + d.hit_count + ' indexed pages, Google index ~' + num(d.google_total), ''];
    groups(d).forEach(function (g) { out.push(g.domain + ' (' + g.links.length + ')'); out = out.concat(g.links); out.push(''); });
    return out.join('\n');
  }
  function status(t) { var s = $('copy-status'); s.textContent = t; setTimeout(function () { s.textContent = ''; }, 4000); }
  $('copy-all').addEventListener('click', function () {
    var text = linksText();
    var fallback = function () {
      var ta = document.createElement('textarea');
      ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      ta.remove();
      status(ok ? 'Copied' : 'Copy failed. Use Download .txt instead.');
    };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(function () { status('Copied'); }, fallback);
    else fallback();
  });
  $('download').addEventListener('click', function () {
    var url = URL.createObjectURL(new Blob([linksText()], { type: 'text/plain' }));
    var dl = document.createElement('a');
    dl.href = url; dl.download = 'leakscan-' + state.data.handle + '.txt';
    document.body.appendChild(dl); dl.click(); dl.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    status('Downloaded');
  });

  // ---------- boot ----------
  $('scan-title').setAttribute('tabindex', '-1');
  var qs = new URLSearchParams(location.search);
  var slug = qs.get('r'), p = qs.get('p'), rawH = qs.get('h'), rawS = qs.get('ig') || qs.get('x') || '';
  state.platform = PLATFORMS[p] ? p : 'onlyfans.com';
  if (slug && /^[A-Za-z0-9_-]{4,64}$/.test(slug)) { reopen(slug); return; }
  if (slug) { showError('not_found'); return; }
  if (rawH == null) { showForm(); return; }
  var h = cleanHandle(rawH);
  $('scan-form').elements.h.value = rawH;
  $('scan-form').elements.ig.value = rawS;
  if (!h) { showForm('That doesn’t look like a handle. Use letters, numbers, dots, dashes or underscores, like yourhandle.'); return; }
  state.social = E.cleanSocial(rawS, qs.get('ig') ? 'instagram' : 'x');
  if (state.social === false) { showForm(SOCIAL_BAD); return; }
  state.handle = h;
  startScan();
})();
