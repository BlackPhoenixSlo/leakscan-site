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
    mark('leakscan:report-start');
    var d = state.data = normalize(raw);
    state.handle = d.handle;
    state.platform = PLATFORMS[d.platform] ? d.platform : state.platform;
    if (d.slug && history.replaceState) history.replaceState(null, '', '?r=' + encodeURIComponent(d.slug));
    hideAll();
    var lead = $('scan-lead');   // the report header is a new view: a fresh lead node, so its new text is not a layout shift
    lead.replaceWith(lead.cloneNode(false));
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
    ['rnav', 'google', 'sites'].forEach(function (id) { show(id, !empty); });
    $('rnav-who').textContent = '@' + d.handle;

    E.sendReport($('send'), d.slug, d.handle, state.platform);
    $('deep-link').href = 'https://jackbase.me/scan?p=' + encodeURIComponent(state.platform) + '&h=' + encodeURIComponent(d.handle) + '&l=deep&go=1';
    $('g-note').textContent = 'Rendered from Google’s index for @' + d.handle + '. Not a live screenshot.';
    var r = encodeURIComponent(d.slug);
    $('after-link').href = '../?r=' + r + '#website';
    $('demo-link').href = '../showcase/?r=' + r;
    E.remember(raw, d.slug, d.handle, state.platform);
    mediaStatus(raw.profile && typeof raw.profile === 'object' ? d.slug : null);
    show('report', true);
    if (!empty) { renderGoogle(); renderSites(); $('rnav-n').textContent = num(lx.groups.length); }
    if (fresh) $('scan-title').focus({ preventScroll: true });
    navCurrent();
    painted();
  }

  // Render timing for tools/scan_e2e.py: leakscan:report = result event (js/scan-engine.js) or report start → the
  // first frame after the report is built. Local performance entries only; nothing leaves the page.
  function mark(n) { if (window.performance && performance.mark) performance.mark(n); }
  function painted() {
    requestAnimationFrame(function () {
      setTimeout(function () {
        if (!window.performance || !performance.measure) return;
        var from = performance.getEntriesByName('leakscan:result').length ? 'leakscan:result' : 'leakscan:report-start';
        try { performance.measure('leakscan:report', from); } catch (e) { /* marks cleared */ }
      }, 0);
    });
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
      h = '<div class="ph-track"><div class="frame-phone" data-device="phone"><div class="ph-screen g-dark g-' + state.tab + '">' +
        '<div class="ph-status" aria-hidden="true"><span>9:41</span><span class="ph-icons"><i class="ph-sig"></i><i class="ph-wifi"></i><i class="ph-bat"></i></span></div>' +
        '<div class="ph-scroll"><div class="ph-page"><div class="gm-head" aria-hidden="true"><span class="gm-burger"><i></i><i></i><i></i></span>' + gLogo() + '<span class="g-av"></span></div>' +
        search + tabRow() + body + '</div></div><span class="ph-fade" aria-hidden="true"></span>' + revealPill() + '<div class="ph-home" aria-hidden="true"></div></div></div></div>';
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
    if (focusTab) { var b = $('g-tab-' + state.tab); if (b) b.focus({ preventScroll: true }); }
    pinPhone();
  }

  // ---------- the phone frame stays put while its screen scrolls ----------
  // .ph-track is as tall as the frame + the overflow of its Google page; the frame is sticky inside it (css), so page
  // scroll moves the screen 1:1 (.ph-scroll, overflow hidden, scrollTop set here) and, at its end, carries on to the
  // sites below. Short screens (css: frame not sticky) scroll the screen by itself. A scroll of the screen itself (focus,
  // find in page) moves the page to match. A new tab starts at its top.
  var pin = null, pinTab = null, pinRo = null;
  function pinPhone() {
    var track = document.querySelector('.ph-track'), reset = pinTab !== state.tab;
    if (pinRo) { pinRo.disconnect(); pinRo = null; }
    pin = track && { track: track, frame: track.firstElementChild, scr: track.querySelector('.ph-scroll'), set: -1 };
    pinTab = pin ? state.tab : null;
    if (!pin) return;
    pin.scr.addEventListener('scroll', onScreenScroll, { passive: true });
    measurePin();
    var off = pin.track.getBoundingClientRect().top - pin.top;   // < 0: scrolled into / past the phone
    if (reset && pin.on && off < 0) window.scrollTo({ top: window.pageYOffset + off, behavior: 'instant' });
    if (window.ResizeObserver) { pinRo = new ResizeObserver(measurePin); pinRo.observe(pin.scr.firstElementChild); pinRo.observe(pin.frame); }
  }
  function measurePin() {
    if (!pin || !pin.track.isConnected) return;
    var cs = getComputedStyle(pin.frame);
    pin.on = cs.position === 'sticky';
    pin.top = parseFloat(cs.top) || 0;
    pin.max = Math.max(0, pin.scr.scrollHeight - pin.scr.clientHeight);
    pin.track.style.height = pin.on ? pin.frame.offsetHeight + pin.max + 'px' : '';
    syncPin();
  }
  function pinWant() { return Math.min(pin.max, Math.max(0, pin.top - pin.track.getBoundingClientRect().top)); }
  function pinEnd() { pin.frame.classList.toggle('ph-end', pin.scr.scrollTop >= pin.scr.scrollHeight - pin.scr.clientHeight - 4); }
  function syncPin() {
    if (!pin || !pin.on) { if (pin) pinEnd(); return; }
    var p = Math.round(Math.min(pinWant(), pin.scr.scrollHeight - pin.scr.clientHeight));
    if (Math.abs(pin.scr.scrollTop - p) >= 1) { pin.scr.scrollTop = p; pin.set = pin.scr.scrollTop; }
    pinEnd();
  }
  function onScreenScroll() {
    if (!pin) return;
    var t = pin.scr.scrollTop;
    if (pin.on && Math.abs(t - pin.set) > 2) {   // not ours: bring the page along
      var d = t - pinWant();
      pin.set = t;
      if (Math.abs(d) > 2) window.scrollTo({ top: window.pageYOffset + d, behavior: 'instant' });
    }
    pinEnd();
  }
  window.addEventListener('scroll', syncPin, { passive: true });
  window.addEventListener('resize', measurePin);
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
  // Reveal / Blur: the button above the frame + the same switch on the pinned phone (the one above scrolls away)
  function revealPill() {
    return '<button type="button" class="ph-reveal" data-reveal aria-pressed="' + state.revealed + '"><svg class="icon" aria-hidden="true"><use href="#' +
      (state.revealed ? 'i-eye-off' : 'i-eye') + '"/></svg><span>' + (state.revealed ? 'Blur images' : 'Reveal images') + '</span></button>';
  }
  $('g-stage').addEventListener('click', function (e) {
    var b = e.target.closest('[data-reveal]');
    if (!b) return;
    $('reveal').click();
    var nb = $('g-stage').querySelector('[data-reveal]');
    if (nb) nb.focus({ preventScroll: true });
  });
  $('reveal').addEventListener('click', function () {
    state.revealed = !state.revealed;
    var b = $('reveal'), p = $('g-stage').querySelector('[data-reveal]');
    b.setAttribute('aria-pressed', String(state.revealed));
    b.querySelector('.rv-t').textContent = state.revealed ? 'Blur' : 'Reveal';
    if (p) p.outerHTML = revealPill();
    $('g-stage').classList.toggle('revealed', state.revealed);
  });

  // ---------- "Where the copies are": every site and link, built only as far as it is looked at ----------
  // 1000 links on 100 sites must not mean 1000 rows on load: SITES_STEP sites first (then MORE_SITES per click), a
  // site's links only once it is opened (LINKS_STEP, then MORE_LINKS per click), one filter over domains + URLs.
  // Copy / .txt always carry everything. Built with elements + textContent only.
  var SITES_STEP = 10, MORE_SITES = 25, LINKS_STEP = 10, MORE_LINKS = 50, AUTO_OPEN = 1;
  var lx = { groups: [], view: [], q: '', shown: 0, timer: 0 };
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
    return order.map(function (k) {   // the top link first, then the order the scan found them in
      var g = by[k];
      g.links = [g.top].concat(g.links.filter(function (u) { return u !== g.top; }));
      return g;
    }).sort(function (x, y) { return y.links.length - x.links.length || y.occ - x.occ; });
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  // a link shown without scheme + its site, which is the row heading (another host of the site keeps its name)
  function shortUrl(u, dom) {
    var s = u.replace(/^https?:\/\//i, ''), i = s.search(/[\/?#]/), h = i < 0 ? s : s.slice(0, i), rest = i < 0 ? '' : s.slice(i);
    h = h.replace(/^www\./i, '');
    return (h.toLowerCase() === dom ? '' : h) + (rest && rest !== '/' ? rest : (h.toLowerCase() === dom ? '/' : ''));
  }
  function marked(parent, text, q) {   // text with the first match of q in <mark>
    var i = q ? text.toLowerCase().indexOf(q) : -1;
    if (i < 0) { parent.textContent = text; return parent; }
    parent.append(text.slice(0, i), el('mark', '', text.slice(i, i + q.length)), text.slice(i + q.length));
    return parent;
  }
  function renderSites() {
    lx.groups = groups(state.data);
    lx.q = '';
    $('lx-q').value = '';
    var n = lx.groups.length, links = lx.groups.reduce(function (t, g) { return t + g.links.length; }, 0);
    lx.max = lx.groups.length ? lx.groups[0].links.length : 1;
    var seen = {}, found = 0;   // the summary counts the scan's pages; the list also holds Google results that are not among them
    state.data.hits.forEach(function (h) { if (!seen[h.url]) { seen[h.url] = 1; found++; } });
    $('lx-sub').textContent = num(n) + ' ' + plural(n, 'site', 'sites') + ' · ' + num(links) + ' ' + plural(links, 'link', 'links') +
      (found && links > found ? ' (' + num(found) + ' indexed pages + ' + num(links - found) + ' more Google results)' : '') + (n > 1 ? ' · most copies first' : '');
    $('lx-q').closest('.lx-tools').hidden = links < 8;   // nothing to filter on a short report
    filterSites();
  }
  function filterSites() {
    var q = lx.q;
    lx.view = !q ? lx.groups.map(function (g) { return { g: g, links: g.links }; }) : lx.groups.reduce(function (out, g) {
      if (g.domain.indexOf(q) >= 0) out.push({ g: g, links: g.links });
      else {
        var m = g.links.filter(function (u) { return u.toLowerCase().indexOf(q) >= 0; });
        if (m.length) out.push({ g: g, links: m, inside: true });
      }
      return out;
    }, []);
    $('lx-list').textContent = '';
    lx.shown = 0;
    showSites(SITES_STEP);
    var v = lx.view, nl = v.reduce(function (t, it) { return t + it.links.length; }, 0);
    $('lx-status').textContent = !q ? '' : v.length ? num(v.length) + ' ' + plural(v.length, 'site', 'sites') + ' · ' + num(nl) + ' ' +
      plural(nl, 'link matches', 'links match') + ' “' + q + '”' : 'No site or link contains “' + q + '”.';
  }
  function showSites(n) {
    var v = lx.view, to = Math.min(v.length, lx.shown + n), frag = document.createDocumentFragment();
    for (var i = lx.shown; i < to; i++) frag.appendChild(siteRow(v[i], i < AUTO_OPEN && v[i].inside));
    $('lx-list').appendChild(frag);
    lx.shown = to;
    var left = v.length - to, b = $('lx-more');
    b.hidden = left <= 0;
    b.textContent = 'Show ' + Math.min(MORE_SITES, left) + ' more ' + plural(Math.min(MORE_SITES, left), 'site', 'sites') + ' · ' + num(left) + ' left';
  }
  function siteRow(it, open) {
    var g = it.g, li = el('li', 'lx-site'), det = el('details'), sum = el('summary', 'lx-sum'), q = lx.q;
    var name = el('span', 'lx-dom');
    name.append(E.fav(g.domain, 'g-fav-s'), marked(el('span', 'lx-name'), g.domain, q));
    var cnt = el('span', 'lx-n');
    cnt.append(el('b', '', num(it.links.length)), ' ' + (it.inside ? 'of ' + num(g.links.length) + ' ' : '') + plural(g.links.length, 'link', 'links'));
    var bar = el('span', 'lx-bar');
    bar.setAttribute('aria-hidden', 'true');
    bar.appendChild(el('i')).style.width = Math.max(2, Math.round(100 * g.links.length / lx.max)) + '%';
    sum.append(name, cnt, marked(el('span', 'lx-top mono'), shortUrl(it.links[0], g.domain), it.inside ? q : ''), bar);
    det.appendChild(sum);
    det.addEventListener('toggle', function () {
      if (det.open && !det.querySelector('.lx-links')) { var ul = el('ul', 'lx-links'); det.appendChild(ul); showLinks(det, it, LINKS_STEP); }
      else if (!det.open) det.querySelectorAll('.lx-links, .lx-lmore').forEach(function (x) { x.remove(); });   // closed = gone from the DOM
    });
    li.appendChild(det);
    if (open) det.open = true;
    return li;
  }
  function showLinks(det, it, n) {
    var ul = det.querySelector('.lx-links'), from = ul.children.length, to = Math.min(it.links.length, from + n), frag = document.createDocumentFragment();
    for (var i = from; i < to; i++) {
      var u = it.links[i], a = el('a', 'lx-a mono');
      a.href = u; a.target = '_blank'; a.rel = 'noopener noreferrer nofollow'; a.title = u;
      marked(a, shortUrl(u, it.g.domain), lx.q);
      frag.appendChild(el('li')).appendChild(a);
    }
    ul.appendChild(frag);
    var left = it.links.length - to, mb = det.querySelector('.lx-lmore');
    if (left <= 0) { if (mb) mb.remove(); return; }
    if (!mb) {
      mb = el('button', 'lx-lmore');
      mb.type = 'button';
      mb.addEventListener('click', function () {   // keyboard: carry on at the first new link (the button may be gone now)
        var had = document.activeElement === mb, first = det.querySelector('.lx-links').children.length;
        showLinks(det, it, MORE_LINKS);
        var nx = det.querySelector('.lx-links').children[first];
        if (had && nx) nx.firstChild.focus({ preventScroll: true });
      });
      det.appendChild(mb);
    }
    mb.textContent = 'Show ' + Math.min(MORE_LINKS, left) + ' more of ' + num(it.links.length) + ' on ' + it.g.domain;
  }
  $('lx-more').addEventListener('click', function () {
    var had = document.activeElement === $('lx-more'), nx = lx.shown;
    showSites(MORE_SITES);
    nx = $('lx-list').children[nx];   // keyboard: carry on at the first new site (the button may be gone now)
    if (had && nx) nx.querySelector('summary').focus({ preventScroll: true });
  });
  $('lx-q').addEventListener('input', function () {
    clearTimeout(lx.timer);
    lx.timer = setTimeout(function () {
      var q = $('lx-q').value.trim().toLowerCase();
      if (q !== lx.q) { lx.q = q; filterSites(); }
    }, 120);
  });
  $('lx-q').addEventListener('keydown', function (e) { if (e.key === 'Enter') e.preventDefault(); });
  function linksText() {
    var d = state.data, out = ['Abolita free scan report: ' + who(), 'Report: ' + REPORT_BASE + d.slug,
      d.domain_count + ' sites, ' + d.hit_count + ' indexed pages, Google index ~' + num(d.google_total), ''];
    lx.groups.forEach(function (g) { out.push(g.domain + ' (' + g.links.length + ')'); out = out.concat(g.links); out.push(''); });
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

  // ---------- section nav: current = the last section whose top has passed the middle of the screen (none above) ----------
  var navRaf = 0;
  function navCurrent() {
    navRaf = 0;
    var cur = null;
    ['google', 'sites', 'send'].forEach(function (id) { var e = $(id); if (!e.hidden && e.getBoundingClientRect().top < innerHeight / 2) cur = id; });
    document.querySelectorAll('.rnav-a').forEach(function (a) {
      if (a.getAttribute('data-sec') === cur) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current');
    });
  }
  window.addEventListener('scroll', function () { if (!navRaf && !$('report').hidden) navRaf = requestAnimationFrame(navCurrent); }, { passive: true });

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
