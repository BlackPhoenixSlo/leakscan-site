// Shared by every page that runs or shows a scan (landing, scan/, showcase/): API host, transport, the validators every
// API value goes through, the current slug, thumb liveness, tablists, Reveal, the hero's report model and image tiles.
// Plain ES2017. This file: no tracking, no third parties (ads: js/analytics.js). The API host is set in ONE place below: same origin, except on
// *.github.io (the VPS API host); <body data-api="..."> overrides it (tools/scan_stub.py does that).
(function () {
  'use strict';
  var SCAN_API = 'https://scan.srv1395798.hstgr.cloud';   // the scan server's public origin (also serves this site on the VPS)
  var API = (document.body.dataset.api || (location.hostname.slice(-9) === 'github.io' ? SCAN_API : '')).replace(/\/+$/, ''); // '' = same origin (VPS)
  // Shareable report link on the host serving this page (GitHub Pages, the VPS, later abolita.com): js/ -> ../scan/.
  var REPORT_BASE = new URL('../scan/?r=', document.currentScript.src).href;
  var PLATFORMS = { 'onlyfans.com': 'OnlyFans', 'instagram.com': 'Instagram', 'fansly.com': 'Fansly', 'tiktok.com': 'TikTok', 'patreon.com': 'Patreon' };
  var HANDLE_RE = /^[A-Za-z0-9._-]{1,60}$/, SLUG_RE = /^[A-Za-z0-9_-]{4,64}$/, DOMAIN_RE = /^[a-z0-9-]+(\.[a-z0-9-]+)+$/;
  var GSTATIC_RE = /^https:\/\/[a-z0-9-]+\.gstatic\.com\/[^\s"'<>\\]*$/;
  var LAST = 'leakscan.last';   // {slug, handle, platform, name, ts}: the last scan in this browser (remember())

  // ---------- validators: every API value goes through one of these before it is rendered ----------
  var clean = {
    // free text → one line, <= max chars, nothing markup- or script-like; else null
    str: function (v, max) {
      if (typeof v !== 'string') return null;
      var s = v.replace(/[\u0000-\u001f\u007f\u200b-\u200f\u2028-\u202e]/g, ' ').replace(/\s+/g, ' ').trim();
      return s && s.length <= max && !/[<>{}]|javascript:|data:/i.test(s) ? s : null;
    },
    handle: function (v) {
      if (typeof v !== 'string') return null;
      var h = v.trim().replace(/^@+/, '');
      return HANDLE_RE.test(h) ? h : null;
    },
    domain: function (v) {
      if (typeof v !== 'string') return null;
      var d = v.trim().toLowerCase().replace(/^www\./, '');
      return d.length <= 80 && DOMAIN_RE.test(d) ? d : null;
    },
    // an http(s) link without credentials → URL, else null
    link: function (u) {
      if (typeof u !== 'string' || u.length > 600 || !/^https?:\/\/[^\s"'<>\\]+$/i.test(u)) return null;
      try { var x = new URL(u); return x.username || x.password ? null : x; } catch (e) { return null; }
    },
    // a Google thumb we may proxy through /api/thumb
    thumbOk: function (u) { return typeof u === 'string' && u.length <= 600 && GSTATIC_RE.test(u); },
    slug: function (v) { return typeof v === 'string' && SLUG_RE.test(v) ? v : null; }
  };
  // The report this page is about: ?r=<slug> (an invalid one = none), else the last scan in this browser, else null.
  function currentSlug() {
    var m = /[?&]r=([^&#]*)/.exec(location.search);
    if (m) { try { return clean.slug(decodeURIComponent(m[1])); } catch (e) { return null; } }
    try { return clean.slug((JSON.parse(localStorage.getItem(LAST) || 'null') || {}).slug); } catch (e) { return null; }
  }
  var under = function (h, d) { return !!h && (h === d || h.slice(-d.length - 1) === '.' + d); };
  var hostOf = function (u) { var x = clean.link(u); return x ? x.hostname.toLowerCase().replace(/^www\./, '') : null; };
  // mega[] items are aggregator share pages: their host / via never show up anywhere, not as a hit / result row nor as
  // such a result's thumb. The API drops those rows and results itself, and the images[] it took from those results
  // (app/public_app.py scan_end; off_row for scans stored before). This guard, on every result entering the page
  // (runScan, fetchResult), is only the fallback for an API from before that (GitHub Pages deploys site/ apart from the
  // VPS API): it drops the rows and results (a result's own thumb goes with it) and recounts the rows such an API
  // counted; an images[] entry that API took from a dropped result stays (a bare thumb url names no host).
  // Suffix-aware: s.leakshaven.com is leakshaven.com.
  function withoutAggregators(raw) {
    var agg = [];
    (raw && Array.isArray(raw.mega) ? raw.mega : []).forEach(function (x) {
      if (x && typeof x === 'object') [x.host, x.via].forEach(function (h) { var d = clean.domain(h); if (d) agg.push(d); });
    });
    if (!agg.length) return raw;
    var keep = function (row, u) {
      var hs = row && typeof row === 'object' ? [clean.domain(row.domain), hostOf(u)] : [];
      return !hs.some(function (h) { return agg.some(function (a) { return under(h, a); }); });
    };
    var out = Object.assign({}, raw);
    if (Array.isArray(raw.results)) out.results = raw.results.filter(function (r) { return keep(r, r && r.link); });
    if (Array.isArray(raw.hits)) {
      out.hits = raw.hits.filter(function (h) { return keep(h, h && h.url); });
      if (out.hits.length < raw.hits.length) {   // an API from before: its counts included them
        var ds = {};
        out.hits.forEach(function (h) { if (h && h.domain) ds[h.domain] = 1; });
        out.hit_count = out.hits.length;
        out.domain_count = Object.keys(ds).length;
      }
    }
    return out;
  }
  function onHost(u, d) { return under(hostOf(u), d) ? clean.link(u).href : null; }
  // hits[] → [{domain, n: occurrences summed, url: its most-seen page on that host or null}], most-seen first (ties keep
  // the API's order). Two rankings on purpose: this one (occurrences) answers "where is she seen most" (personalize's
  // phones, removals' leak site); the Sites lists (siteGroups(): reportModel().sites, scan.js) rank by how many links a
  // site has, the number they print next to it.
  function rankHosts(raw) {
    var by = {}, out = [];
    (raw && Array.isArray(raw.hits) ? raw.hits : []).slice(0, 1000).forEach(function (x) {
      var d = x && clean.domain(x.domain);
      if (!d) return;
      var n = typeof x.occurrences === 'number' && x.occurrences > 0 ? Math.min(x.occurrences, 1e6) : 1, u = onHost(x.url, d);
      if (!by[d]) out.push(by[d] = { domain: d, n: 0, url: null, best: 0 });
      by[d].n += n;
      if (u && n > by[d].best) { by[d].best = n; by[d].url = u; }
    });
    return out.sort(function (a, b) { return b.n - a.n; }).map(function (h) { return { domain: h.domain, n: h.n, url: h.url }; });
  }

  // What she typed into a form (not an API value): a handle, @handle or pasted profile URL → the bare handle, else null.
  clean.handleInput = function (raw) {
    var h = String(raw || '').trim();
    if (h.indexOf('/') >= 0) {
      var parts = h.split(/[?#]/)[0].split('/').filter(Boolean);
      h = parts.length ? parts[parts.length - 1] : '';
    }
    h = h.replace(/^@+/, '');
    return HANDLE_RE.test(h) ? h : null;
  };
  // The optional Instagram / X field. '' → null (none); instagram.com/<h> → instagram, x.com|twitter.com/<h> → x (only a
  // pasted URL decides); a bare name / @name → `net` (default instagram); anything else → false (invalid).
  clean.social = function (raw, net) {
    var s = String(raw || '').trim(), h;
    if (!s) return null;
    var m = /^(?:https?:\/\/)?(?:www\.|m\.|mobile\.)?(instagram\.com|x\.com|twitter\.com)\/+@?([^\/?#\s]+)/i.exec(s);
    if (m) { h = m[2]; net = m[1].toLowerCase() === 'instagram.com' ? 'instagram' : 'x'; }
    else if (/[\/:]/.test(s)) return false;
    else h = s.replace(/^@+/, '');
    return HANDLE_RE.test(h) ? { net: net === 'x' ? 'x' : 'instagram', handle: h } : false;
  };
  // Thumbs from another origin (github.io → the VPS API, the stub) have readable pixels (isPhoto) only from a CORS load
  var XO = !!API && new URL(API, location.href).origin !== location.origin;
  function thumb(u) {
    return typeof u === 'string' && /^https:\/\//.test(u) ? API + '/api/thumb?u=' + encodeURIComponent(u) : null;
  }
  // fresh(t): the same /api/thumb URL under another cache key (api_thumb reads only u). A CORS load that fails may have
  // hit a copy cached before the API sent ACAO / Vary (max-age a day): it retries once on this before the plain load.
  // unfresh(t): back to the plain URL (the key a thumb is known by).
  function fresh(t) { return t.replace('/api/thumb?u=', '/api/thumb?c=1&u='); }
  function unfresh(t) { return (t || '').replace('/api/thumb?c=1&u=', '/api/thumb?u='); }
  function who(handle, platform) { return '@' + handle + ' (' + (PLATFORMS[platform] || platform) + ')'; }

  // ---------- message links ----------
  // one message, prefilled in each channel → {tg, wa, mail} hrefs
  function messageLinks(text, subject, body) {
    var q = encodeURIComponent(text);
    return { tg: 'https://t.me/jakabasej?text=' + q, wa: 'https://wa.me/38640703992?text=' + q,
      mail: 'mailto:me@jackbase.dev?subject=' + encodeURIComponent(subject) + '&body=' + encodeURIComponent(body) };
  }
  // every [data-msg=tg|wa|mail] link in scope gets its channel's href
  function applyLinks(scope, l) {
    scope.querySelectorAll('[data-msg]').forEach(function (a) { var k = a.getAttribute('data-msg'); a.href = k === 'tg' ? l.tg : k === 'wa' ? l.wa : l.mail; });
  }
  function setMessages(scope, text, subject, body) { applyLinks(scope, messageLinks(text, subject, body)); }
  // The shareable report page of a slug (scan/?r=, on the host serving this page).
  function reportUrl(slug) { return REPORT_BASE + encodeURIComponent(slug); }
  // Forget the last scan in this browser (the personalized page's Reset).
  function forget() { try { localStorage.removeItem(LAST); } catch (e) { /* storage blocked */ } }
  // "Send me the report": report link + handle prefilled → {tg, wa, mail}; sendReport puts them on scope's links.
  function reportLinks(slug, handle, platform) {
    var link = reportUrl(slug);
    return messageLinks('Hi Jaka, I ran the free scan for ' + who(handle, platform) + '. My report: ' + link, 'Free scan report: @' + handle,
      'Hi Jaka,\n\nI ran the free scan.\nMy report link: ' + link + '\nMy handle: ' + who(handle, platform) + '\n\nThanks!');
  }
  function sendReport(scope, slug, handle, platform) { applyLinks(scope, reportLinks(slug, handle, platform)); }
  // Read by js/personalize.js on the homepage + demo site; stays in this browser only.
  function remember(raw, slug, handle, platform) {
    if (!clean.slug(slug)) return;
    var pn = raw.profile && typeof raw.profile.display_name === 'string' && raw.profile.display_name.length <= 60 ? raw.profile.display_name : null;
    try { localStorage.setItem(LAST, JSON.stringify({ slug: slug, handle: handle, platform: platform, name: pn, ts: Date.now() })); } catch (e) { /* storage blocked */ }
  }

  // ---------- letter avatars + image items (scan page, hero card, #free phone) ----------
  var FAV_COLORS = ['#ea4335', '#4285f4', '#34a853', '#fbbc05', '#ab47bc', '#00acc1', '#ff7043']; // cse_mosaic _TAB_PALETTE
  function favColor(dom) {
    var s = 0;
    for (var i = 0; i < (dom || '').length; i++) s += dom.charCodeAt(i);
    return FAV_COLORS[s % FAV_COLORS.length];
  }
  // fav(dom, cls, src?) → <span class=cls> with the domain's first letter on its colour; src (an /api/thumb URL) layers
  // a blurred thumb over it, dropped again if it dies (watchThumb).
  function fav(dom, cls, src) {
    var el = document.createElement('span');
    el.className = cls || 'g-fav';
    el.setAttribute('aria-hidden', 'true');
    el.textContent = ((dom || '').charAt(0) || '?').toUpperCase();
    if (!src) el.style.background = favColor(dom);
    else {   // a plain neutral tile until the thumb loads; the letter (neutral, theme-coloured) only if it fails
      var im = document.createElement('img');
      el.classList.add('fav-wait');
      im.src = src; im.alt = ''; im.loading = 'lazy'; im.referrerPolicy = 'no-referrer';
      el.appendChild(im);
      watchThumb(im, function () { im.remove(); el.classList.remove('fav-wait'); el.classList.add('fav-none'); },
        function () { el.classList.remove('fav-wait'); });
    }
    return el;
  }
  // A video result: the server classifies every result once (`kind`, app/public_app.py); its thumb is a video still:
  // the landing card's image views put it after the real images (no badge), the scan page shows it with a play badge (and
  // lists it in its Videos tab).
  function isVideo(r) { return !!r && r.kind === 'video'; }
  // ---------- people photos only ----------
  // Google Images mixes site logos, banners, icons and placeholders into a handle's images. Drawn at 48x48, a photo has
  // soft texture nearly everywhere (`tex`: share of neighbour steps of 7..60, black letterbox bars not counted); a logo
  // is flat fills and hard edges. Dropped: tex < 0.2, tex < 0.3 with under 10% skin (YCbCr rule), or under 2% skin
  // (a smooth gradient logo / text banner; a person photo always has some). Tuned on 174 real Google thumbs: 34 of 37
  // logos / banners out, 134 of 134 people photos kept (misses: two drawn posters). photoStats(im) → {tex, skin} (0..1),
  // or null when the pixels can't be read (tainted canvas): isPhoto is then true (fail open, never an empty strip).
  // Callers read the image they already load (same origin: no extra request; XO: loaded with crossOrigin).
  var PX = 48;
  function photoStats(im) {
    try {
      var c = document.createElement('canvas');
      c.width = c.height = PX;
      var x = c.getContext('2d', { willReadFrequently: true });
      x.fillStyle = '#fff'; x.fillRect(0, 0, PX, PX);   // a transparent logo reads as on white
      x.drawImage(im, 0, 0, PX, PX);
      var p = x.getImageData(0, 0, PX, PX).data;
    } catch (e) { return null; }
    var n = PX * PX, Y = [], skin = 0, tex = 0, pairs = 0, i;
    for (i = 0; i < n; i++) {
      var r = p[i * 4], g = p[i * 4 + 1], b = p[i * 4 + 2], cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b, cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b;
      Y[i] = 0.299 * r + 0.587 * g + 0.114 * b;
      if (Y[i] > 40 && cb >= 77 && cb <= 127 && cr >= 133 && cr <= 173) skin++;
    }
    var step = function (a, z) {
      if (Y[a] < 24 && Y[z] < 24) return;   // both black: a letterbox bar, not the picture
      var d = Math.abs(p[a * 4] - p[z * 4]) + Math.abs(p[a * 4 + 1] - p[z * 4 + 1]) + Math.abs(p[a * 4 + 2] - p[z * 4 + 2]);
      pairs++;
      if (d > 6 && d <= 60) tex++;
    };
    for (i = 0; i < n; i++) {
      if (i % PX < PX - 1) step(i, i + 1);
      if (i < n - PX) step(i, i + PX);
    }
    return { tex: pairs ? tex / pairs : 0, skin: skin / n };
  }
  function isPhoto(im) {
    var s = photoStats(im);
    return !s || !(s.tex < 0.2 || (s.tex < 0.3 && s.skin < 0.1) || s.skin < 0.02);
  }
  // images[] first (with the result that has the same thumb, if any), then the results' own thumbs; deduped, ok(src)
  // filters. → [{src, title, domain, link, video}] (title/domain/link '' when no result matches; video: its result is one).
  // videos false (landing card's real images): video results' stills are skipped, images[] ones too. videos true (scan page, like Google
  // Images): every images[] entry is an image result, and video results' thumbs count too (tile gets a play badge).
  function imageItems(images, results, ok, max, videos) {
    var by = {}, seen = {}, out = [];
    results.forEach(function (r) { if (r.thumb && !by[r.thumb]) by[r.thumb] = r; });
    var add = function (u, r) {
      if (typeof u !== 'string' || seen[u] || !ok(u) || (!videos && isVideo(r))) return;
      seen[u] = 1;
      out.push({ src: u, title: r && r.title || '', domain: r && r.domain || '', link: r && r.link || '', video: isVideo(r) });
    };
    images.forEach(function (u) { add(u, by[u]); });
    results.forEach(function (r) { add(r.thumb, r); });
    out = out.slice(0, max);   // tiles that open a result first, then the ones that open the report (every view alike)
    return out.filter(function (it) { return it.link; }).concat(out.filter(function (it) { return !it.link; }));
  }

  // ---------- errors: err.kind = rate_limited | busy | bad_handle | not_found | failed (+ err.detail) | network ----------
  function apiError(status, code, fallback) {
    var err = new Error(code || fallback);
    err.kind = code === 'rate_limited' || code === 'busy' || code === 'not_found' || code === 'bad_handle' ? code : 'failed';
    if (err.kind === 'failed') err.detail = 'The scan server answered with an error (HTTP ' + status + ')';
    return err;
  }

  // ---------- SSE over a POST body ----------
  async function streamScan(payload, onEvent) {
    var ctrl = window.AbortController ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, 240000);
    try {
      var res = await fetch(API + '/api/public-scan', {
        method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify(payload), signal: ctrl ? ctrl.signal : undefined
      });
      if (!res.ok) {
        var j = {};
        try { j = await res.json(); } catch (e) { /* not JSON */ }
        throw apiError(res.status, j && j.error, 'failed');
      }
      var stop = false;
      var dispatch = function (block) {
        var ev = 'message', data = [];
        block.split('\n').forEach(function (line) {
          if (!line || line.charAt(0) === ':') return;
          var i = line.indexOf(':');
          var field = i < 0 ? line : line.slice(0, i);
          var val = i < 0 ? '' : line.slice(i + 1).replace(/^ /, '');
          if (field === 'event') ev = val;
          else if (field === 'data') data.push(val);
        });
        if (onEvent(ev, data.join('\n')) === false) stop = true;
      };
      var feed = function (text, final) {
        buf = (buf + text).replace(/\r\n/g, '\n');
        var i;
        while (!stop && (i = buf.indexOf('\n\n')) >= 0) { dispatch(buf.slice(0, i)); buf = buf.slice(i + 2); }
        if (final && !stop && buf.trim()) dispatch(buf);
      };
      var buf = '';
      if (!res.body || !res.body.getReader) { feed(await res.text(), true); return; }
      var reader = res.body.getReader(), dec = new TextDecoder();
      for (;;) {
        var chunk = await reader.read();
        if (chunk.done) { feed(dec.decode(), true); break; }
        feed(dec.decode(chunk.value, { stream: true }), false);
        if (stop) { reader.cancel().catch(function () {}); break; }
      }
    } catch (e) {
      if (!e.kind) { e.kind = 'network'; }
      throw e;
    } finally {
      clearTimeout(timer);
    }
  }

  // runScan({platform, handle, social?: {net, handle}, onProgress(text), onResult(raw), onError(err)}): exactly one of
  // onResult / onError. social adds `instagram` or `x` to the request body. A result is also announced to the page as
  // the `leakscan:result` event (detail = the result), after onResult.
  function runScan(o) {
    var result = null, failed = null, body = { platform: o.platform, handle: o.handle, level: 'low' };
    if (o.social) body[o.social.net] = o.social.handle;
    return streamScan(body, function (ev, data) {
      if (ev === 'progress') { if (o.onProgress) o.onProgress(data); }
      else if (ev === 'result') { if (window.performance && performance.mark) performance.mark('leakscan:result');
        try { result = withoutAggregators(JSON.parse(data)); } catch (e) { failed = 'The scan result could not be read'; } }
      else if (ev === 'failed') failed = data || 'The scan stopped';
      else if (ev === 'done') return false;
    }).then(function () {
      if (failed) { var f = new Error(failed); f.kind = 'failed'; f.detail = failed.replace(/[.\s]+$/, ''); o.onError(f); }
      else if (result) {
        if (result.slug) sheet(result.slug);   // before onResult: its tiles wait for the sheet
        // an API that doesn't echo socials yet: what she typed next to the scan
        if (o.social && !(result.socials && typeof result.socials === 'object')) { result.socials = {}; result.socials[o.social.net] = o.social.handle; }
        o.onResult(result);
        // a fresh result landed on this page: js/personalize.js, js/removals.js re-render from it (read only)
        document.dispatchEvent(new CustomEvent('leakscan:result', { detail: result }));
      }
      else { var n = new Error('network'); n.kind = 'network'; o.onError(n); }
    }, function (e) { o.onError(e); });
  }
  // fetchResult(slug) → Promise of the stored result; rejects with err.kind like runScan. One request per slug per page:
  // the landing's ?r= reopen asks from inline-scan.js and personalize.js, both get this promise (a failure is not kept).
  // Callers only read the result, never mutate it.
  // In a same-origin frame (the landing's video mini player, js/pip.js) the page's own promise is used: still one request.
  var results = {}, host = null;
  try { if (window.parent !== window && window.parent.LeakScanEngine) host = window.parent.LeakScanEngine; } catch (e) { host = null; }
  function fetchResult(slug) {
    sheet(slug);
    if (host) return host.fetchResult(slug);
    if (results[slug]) return results[slug];
    return (results[slug] = fetch(API + '/api/scan-result/' + encodeURIComponent(slug), { credentials: 'omit' }).then(function (res) {
      if (res.ok) return res.json().then(withoutAggregators);
      return res.json().catch(function () { return {}; }).then(function (j) { throw apiError(res.status, j && j.error, 'failed'); });
    }).catch(function (e) { delete results[slug]; if (!e.kind) e.kind = 'network'; throw e; }));
  }
  // ---------- one file instead of dozens of /api/thumb requests ----------
  // GET <API>/api/thumb-sheet/<slug> (app/thumb_sheet.py): 8 digits = the manifest's length, the manifest {cells: [[src, type, bytes]],
  // dead: [src]}, then the thumbs' original bytes back to back, read as they arrive. A cell becomes a blob URL: a real <img>, readable
  // pixels (same origin), no further request, no decoding until an <img> asks. put() holds a thumb until its cell is here or the sheet
  // is over. No sheet (404 / 5xx / an old server / a network error / too slow) or a thumb it does not name: /api/thumb, as always.
  // A same-origin frame (js/pip.js) uses the page's sheet.
  var SHEET_MS = 20000, CELL_MS = 16, sheets = {}, opened = {}, cells = {}, sheetsOut = 0, held = new Map();
  function readSheet(slug, each) {   // each(src, blob URL | null = dead) per thumb: at once for those already read → Promise: the sheet is over; never rejects
    if (host) return host.readSheet(slug, each);
    var s = sheets[slug];
    if (s) { s.got.forEach(function (c) { each(c[0], c[1]); }); s.subs.push(each); return s.end; }
    s = sheets[slug] = { got: [], subs: [each] };
    var say = function (src, u) { s.got.push([src, u]); s.subs.forEach(function (fn) { try { fn(src, u); } catch (e) {} }); };   // a frame may be gone
    var buf = new Uint8Array(0), size = 0, list = null, at = 0, text = function (b) { return new TextDecoder().decode(b); };
    var chew = function () {   // cuts off buf what is complete
      for (;;) {
        var n = !size ? 8 : !list ? size : list[at] ? list[at][2] : Infinity;
        if (buf.length < n) return;
        var part = buf.subarray(0, n);
        buf = buf.subarray(n);
        if (!size) size = +text(part);
        else if (!list) { var j = JSON.parse(text(part)); list = j.cells; j.dead.forEach(function (u) { say(u, null); }); }
        else { say(list[at][0], URL.createObjectURL(new Blob([part], { type: list[at][1] }))); at++; }
      }
    };
    var ctl = new AbortController(), timer = setTimeout(function () { ctl.abort(); }, SHEET_MS);
    return (s.end = fetch(API + '/api/thumb-sheet/' + encodeURIComponent(slug), { credentials: 'omit', signal: ctl.signal }).then(function (res) {
      if (!res.ok || !res.body) throw new Error('no sheet');
      var reader = res.body.getReader(), next = function () {
        return reader.read().then(function (r) {
          if (r.done) return;
          var b = new Uint8Array(buf.length + r.value.length);
          b.set(buf);
          b.set(r.value, buf.length);
          buf = b;
          chew();
          return next();
        });
      };
      return next();
    }).catch(function () {}).then(function () { clearTimeout(timer); }));
  }
  function sheet(slug) {
    if (opened[slug] || !window.fetch || !window.AbortController || !window.TextDecoder) return;
    opened[slug] = 1;
    sheetsOut++;
    var free = function (src, img) { held.delete(img); if (img.isConnected || !img.parentNode) put(img, src); };
    readSheet(slug, function (src, u) {
      if (u) cells[src] = u; else verdict(src, false);
      held.forEach(function (s, img) { if (s === src) free(s, img); });
    }).then(function () { if (!--sheetsOut) held.forEach(free); });
  }
  // A progress event's text → {pct: 5..95 | null, stage: what to show}.
  function progressInfo(text) {
    var m = /(\d+)\s*\/\s*(\d+)/.exec(text);
    if (m && +m[2] > 0) return { pct: Math.min(96, 5 + 90 * (+m[1] / +m[2])), stage: 'Searching Google, step ' + m[1] + ' of ' + m[2] + '…' };
    return { pct: null, stage: text };
  }

  // ---------- thumbs that show: ONE rule everywhere ----------
  // watchThumb(img, onDead, onOk?, photo?): an image that fails or loads blank (< BLANK_PX a side: a hotlink-blocked thumb
  // comes back as a tiny placeholder), or with `photo` (image tiles) is no person photo (isPhoto) → onDead(img); else
  // onOk(img). Once. A failed load asks /api/thumb again (askStatus): a 429 (the thumb bucket is empty) is no verdict: it keeps its
  // turn. A 200 (a hiccup, a bucket since refilled) has the bytes: they become the image, no third request. A CORS load (XO:
  // crossorigin) refused (no status) loads once more on fresh()'s URL, then plain (pixels unread: kept). Anything else is dead at once
  // (the proxy answers 404 / 4xx / 502 for a thumb Google no longer serves). Also right for an image that finished before it was
  // watched. A tile taken off the page is not retried and gets no verdict; a free-standing image (gallery()'s probe) is retried.
  var BLANK_PX = 16, RETRY_MS = 2500, asks = [], asking = false, coolUntil = 0;
  // One status at a time per page (a frame uses its page's queue): one 429 stops all of them for RETRY_MS, so an empty bucket gets
  // what it refills, not a retry chain per thumb (each a new 429, each tile it kills pulling in the next): answer(status, response).
  function askStatus(src, answer) {
    if (host) return host.askStatus(src, answer);
    asks.push([src, answer]);
    askNext();
  }
  function askNext() {
    if (asking || !asks.length) return;
    asking = true;
    setTimeout(function () {
      var job = asks.shift();
      fetch(job[0], { credentials: 'omit', referrerPolicy: 'no-referrer' }).catch(function () { return { status: 0 }; }).then(function (r) {
        asking = false;
        if (r.status === 429) { coolUntil = Date.now() + RETRY_MS; asks.push(job); } else job[1](r.status, r);
        askNext();
      });
    }, Math.max(0, coolUntil - Date.now()));
  }
  function watchThumb(img, onDead, onOk, photo) {
    var done = false;
    var stop = function () {
      done = true;
      img.removeEventListener('load', load);
      img.removeEventListener('error', error);
    };
    var finish = function (ok) {
      if (done) return;
      stop();
      var fn = ok ? onOk : onDead;
      if (fn) fn(img);
    };
    var load = function () {
      var end = function () { finish(img.naturalWidth >= BLANK_PX && img.naturalHeight >= BLANK_PX && (!photo || isPhoto(img))); };
      if (photo && img.decode && (img.getAttribute('src') || '').slice(0, 5) === 'blob:') img.decode().then(end, end);   // WebKit draws a big blob image subsampled until decoded: other pixels, another verdict
      else end();
    };
    var error = function () {
      var src = img.getAttribute('src');
      if (!src || src.slice(0, 5) === 'blob:' || !window.fetch) return finish(false);   // bytes in hand: asking again gets the same
      askStatus(src, function (st, res) {
        if (done) return;
        if (img.parentNode && !img.isConnected) return stop();   // no verdict: it left while queued, its thumb may be fine (the prober checks it)
        if (img.getAttribute('src') !== src) return finish(false);
        if (st === 200) return res.blob().then(function (b) { img.setAttribute('src', URL.createObjectURL(b)); }, function () { finish(false); });
        if (st === 0 && img.hasAttribute('crossorigin')) {   // XO refused: once more on E.fresh's URL (a copy cached before ACAO / Vary), then plain
          return src !== fresh(src) ? img.setAttribute('src', fresh(src)) : img.removeAttribute('crossorigin');
        }
        finish(false);
      });
    };
    img.addEventListener('load', load);
    img.addEventListener('error', error);
    if (img.complete && img.getAttribute('src')) setTimeout(function () { if (!done && img.complete) { if (img.naturalWidth) load(); else error(); } });   // not inside a gallery's sync: a verdict syncs again
  }

  // ---------- tabs: markup-driven, one convention ----------
  // tablist(root, onSelect?): every [role=tab] under root (now or added later: delegated) selects on click and on
  // ←/→/Home/End (roving tabindex, aria-selected); the selected tab's aria-controls panel is shown, the panels of its
  // siblings get `hidden` (CSS decides what hidden looks like: gone, or kept in its grid cell). onSelect(tab) after.
  function tablist(root, onSelect) {
    var tabsOf = function (t) { return Array.prototype.slice.call(t.closest('[role=tablist]').querySelectorAll('[role=tab]')); };
    var pick = function (tab, focus) {
      var want = tab.getAttribute('aria-controls');
      tabsOf(tab).forEach(function (b) {
        var id = b.getAttribute('aria-controls'), panel = id && document.getElementById(id);
        b.setAttribute('aria-selected', String(b === tab));
        b.tabIndex = b === tab ? 0 : -1;
        if (panel) panel.hidden = id !== want;
      });
      if (focus) tab.focus();
      if (onSelect) onSelect(tab);
    };
    var tabAt = function (e) {
      var t = e.target.closest && e.target.closest('[role=tab]');
      return t && root.contains(t) && t.closest('[role=tablist]') ? t : null;
    };
    root.addEventListener('click', function (e) { var t = tabAt(e); if (t) pick(t, false); });
    root.addEventListener('keydown', function (e) {
      var t = tabAt(e), k = ['ArrowLeft', 'ArrowRight', 'Home', 'End'].indexOf(e.key);
      if (!t || k < 0) return;
      var tabs = tabsOf(t), i = tabs.indexOf(t), n = tabs.length;
      e.preventDefault();
      pick(tabs[k === 2 ? 0 : k === 3 ? n - 1 : (i + (k ? 1 : n - 1)) % n], true);
    });
  }

  // ---------- "Show more" under a phone tab's list ----------
  // pager(box, step, grow, left): grow(n) shows its first n (step more per click); the button is gone once left(n) says
  // none are left. → {el: the button (put it under the list), sync: call when left() may have changed}
  function pager(box, step, grow, left) {
    var n = step, b = make('button', 'm-more', ['Show more'], { type: 'button' });
    var sync = function () {
      b.hidden = !left(n);
      if (!b.hidden || b !== document.activeElement) return;
      var a = box.querySelectorAll('a'), to = a[a.length - 1] || box;   // focus stays in the tab: its last link, else the list
      if (to === box && !box.hasAttribute('tabindex')) box.tabIndex = -1;
      to.focus({ preventScroll: true });
    };
    b.addEventListener('click', function () { grow(n += step); sync(); });
    grow(n);
    sync();
    return { el: b, sync: sync };
  }

  // ---------- Reveal: one delegated handler ----------
  // A [data-reveal] button toggles .revealed on its closest [data-reveal-scope]; every [data-reveal] button in that scope
  // follows (aria-pressed + its .reveal-t label). Leak-side images are blurred by CSS (--leak-blur) before any JS runs.
  function revealSync(scope) {
    var on = scope.classList.contains('revealed');
    Array.prototype.forEach.call(scope.querySelectorAll('[data-reveal]'), function (b) {
      b.setAttribute('aria-pressed', String(on));
      var t = b.querySelector('.reveal-t'), own = (b.getAttribute('data-reveal-t') || '').split('|');   // own labels: "off|on"
      if (t && own.length === 2) t.textContent = own[on ? 1 : 0];   // a button with a .rv-w (" images", hidden on narrow screens) keeps it
      else if (t) t.textContent = (on ? 'Blur' : 'Reveal') + (b.querySelector('.rv-w') ? '' : ' images');
    });
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-reveal]'), scope = b && b.closest('[data-reveal-scope]');
    if (!scope) return;
    scope.classList.toggle('revealed');
    revealSync(scope);
  });

  // ---------- DOM helpers (textContent / createElement only, never innerHTML) ----------
  var NEW_TAB = { target: '_blank', rel: 'noopener noreferrer nofollow' };
  function make(tag, cls, kids, attrs) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    for (var k in attrs || {}) if (attrs.hasOwnProperty(k)) el.setAttribute(k, attrs[k]);
    (kids || []).forEach(function (c) { if (c != null) el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return el;
  }
  function icon(id, cls) {
    var NS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(NS, 'svg'), use = document.createElementNS(NS, 'use');
    svg.setAttribute('class', 'icon' + (cls ? ' ' + cls : ''));
    svg.setAttribute('aria-hidden', 'true');
    use.setAttribute('href', '#' + id);
    svg.appendChild(use);
    return svg;
  }
  // a Reveal button for a [data-reveal-scope] (pressed already if that scope is revealed)
  function revealButton(scope) {
    var on = !!scope && scope.classList.contains('revealed');
    return make('button', 'reveal-btn', [icon('i-eye'), make('span', 'reveal-t', [on ? 'Blur images' : 'Reveal images'])],
      { type: 'button', 'aria-pressed': String(on), 'data-reveal': '' });
  }

  // The Sites lists (the landing's Sites tab, the scan page's "Where the copies are"): rows [{domain, url, occ}] in scan
  // order → one group per domain {domain, links: its distinct links in scan order, top: its most-seen link, occ: summed},
  // most links first (the printed count), then occurrences, then first seen.
  function siteGroups(rows) {
    var by = {}, out = [];
    rows.forEach(function (r) {
      var g = by[r.domain], occ = r.occ || 0;
      if (!g) { g = by[r.domain] = { domain: r.domain, links: [], seen: {}, occ: 0, top: r.url, topOcc: -1, i: out.length }; out.push(g); }
      g.occ += occ;
      if (occ > g.topOcc) { g.top = r.url; g.topOcc = occ; }
      if (!g.seen[r.url]) { g.seen[r.url] = 1; g.links.push(r.url); }
    });
    return out.sort(function (x, y) { return y.links.length - x.links.length || y.occ - x.occ || x.i - y.i; })
      .map(function (g) { return { domain: g.domain, links: g.links, top: g.top, occ: g.occ }; });
  }

  // rows whose `key` is a clean http(s) link → copies carrying its normalised href, a clean domain (else its host's; none
  // = dropped) and, where the row has a thumb, only a Google one we may proxy (else null). The one input rule for links:
  // reportModel (landing) and js/scan.js
  function linked(list, key) {
    return (Array.isArray(list) ? list : []).map(function (x) {
      var u = x && typeof x === 'object' && clean.link(x[key]), d = u && (clean.domain(x.domain) || clean.domain(u.hostname));
      if (!d) return null;
      var c = Object.assign({}, x, { domain: d });
      c[key] = u.href;
      if ('thumb' in c) c.thumb = clean.thumbOk(c.thumb) ? c.thumb : null;
      return c;
    }).filter(Boolean);
  }
  // the word for n: plural(1, 'site', 'sites') = 'site'; callers put the number (formatted their way) in front
  function plural(n, one, many) { return n === 1 ? one : many; }

  // ---------- the landing's report model (hero card + #free phone) ----------
  // raw API result → {slug, handle, platform, rows: [{url, domain, title, badge, thumb}], sites: [{domain, n, thumb, url}],
  // images: [{src, title, domain, link}] (images[] + results' thumbs, deduped, no video stills, the ones that open a
  // page first), videos: [{link, domain, title, thumb}], profile, socials, discovered}. fb = {handle, platform} of the
  // scan that asked (a stored result may lack them).
  var MAX_IMAGES = 60;
  function reportModel(raw, fb) {
    if (!raw || typeof raw !== 'object') return null;
    var slug = clean.slug(raw.slug);
    if (!slug) return null;
    var m = { slug: slug, handle: clean.handle(raw.handle) || fb.handle, platform: PLATFORMS[raw.platform] ? raw.platform : fb.platform,
      rows: [], sites: [], images: [], profile: !!(raw.profile && typeof raw.profile === 'object'), socials: {}, discovered: [] };
    if (!m.handle || !PLATFORMS[m.platform]) return null;
    var so = raw.socials && typeof raw.socials === 'object' ? raw.socials : {};
    ['instagram', 'x'].forEach(function (k) { var h = clean.handle(so[k]); if (h) m.socials[k] = h; });
    var al = raw.aliases && typeof raw.aliases === 'object' && Array.isArray(raw.aliases.discovered) ? raw.aliases.discovered : [];
    m.discovered = al.slice(0, 4).filter(function (a) { return clean.handle(a) === a && a !== m.handle; });
    var seen = {}, thumbOf = {}, sr = [], res = [];
    var add = function (u, d, title, badge, thumb, occ) {   // u, d: clean (linked)
      if (seen[u]) return;
      seen[u] = 1;
      m.rows.push({ url: u, domain: d, title: clean.str(title, 200), badge: badge, thumb: thumb || null });
      sr.push({ domain: d, url: u, occ: occ });
      if (!thumbOf[d] && thumb) thumbOf[d] = thumb;
    };
    // Badges only say what the data says: live:true → Live, a Google result → Indexed, anything else → Found.
    linked((Array.isArray(raw.hits) ? raw.hits : []).slice(0, 1000), 'url').forEach(function (h) {
      add(h.url, h.domain, h.title, h.live === true ? 'Live' : 'Found', null, +h.occurrences || 1);
    });
    linked((Array.isArray(raw.results) ? raw.results : []).slice(0, 200), 'link').forEach(function (r) {
      add(r.link, r.domain, r.title, 'Indexed', r.thumb, 0);
      res.push({ link: r.link, domain: r.domain, title: clean.str(r.title, 200), thumb: r.thumb || null, kind: r.kind === 'video' ? 'video' : 'page' });
    });
    m.sites = siteGroups(sr).map(function (g) {   // a site opens its first link
      return { domain: g.domain, n: g.links.length, thumb: thumbOf[g.domain] || null, url: g.links[0] };
    });
    var gi = (Array.isArray(raw.images) ? raw.images : []).slice(0, 200), imgs = imageItems(gi, res, clean.thumbOk, MAX_IMAGES), had = {};
    imgs.forEach(function (it) { had[it.src] = 1; });
    // then video results' stills (no badge; people-photo check like the rest), so a handle Google shows mostly as videos
    // still fills the views
    m.images = imgs.concat(imageItems(gi, res, clean.thumbOk, Infinity, true).filter(function (it) { return it.video && !had[it.src]; })
      .map(function (it) { it.still = true; return it; })).slice(0, MAX_IMAGES);
    m.videos = res.filter(isVideo);
    return m;
  }

  // ---------- image tiles that show (hero strip / Images grid, #free phone, the scan page's pack / grid) ----------
  // One verdict per thumb per page, shared by every gallery: src → true (seen to load) / false (dead: failed twice or
  // blank, watchThumb). Dead wins: a thumb that fails anywhere leaves every view. Thumbs no tile has loaded yet (lazy
  // tiles, the tail past every view) are probed in the background by ONE page-wide prober: PROBE_LANES at a time, each
  // lane PROBE_MS between its probes (together under /api/thumb's 2/s refill; the tile then comes from the HTTP cache;
  // a slow or dead thumb holds up one lane only), so counts settle without scrolling.
  // photo(src, fn): the same verdict for anything else (landing row icons, #free video stills): fn(true) once src passed
  // (a person photo), fn(false) dead; probes it now if nothing has. put(img, src): img shows the exact URL + mode src
  // passed with (`via`: XO crossOrigin, plain or fresh): that load's cached copy, no second request (a plain load of a
  // CORS-loaded URL is another cache entry: twice the thumb requests, past /api/thumb's burst → 429, photos dropped).
  var PROBE_WAIT = 1200, PROBE_MS = 1000, PROBE_LANES = 2, verdicts = {}, probing = {}, galleries = [], lanes = 0, via = {}, waiting = {};
  function verdict(src, ok) {
    if (verdicts[src] === false || verdicts[src] === ok) return;
    verdicts[src] = ok;
    (waiting[src] || []).forEach(function (fn) { fn(ok); });
    delete waiting[src];
    galleries.slice().forEach(function (g) { g.sync(); });
  }
  function passed(src, img) { via[src] = { u: img.getAttribute('src'), cors: img.hasAttribute('crossorigin') }; verdict(src, true); }
  function probe(src, done) {
    probing[src] = 1;
    var img = new Image(), end = function (ok) { delete probing[src]; if (ok) passed(src, img); else verdict(src, false); if (done) done(); };
    img.referrerPolicy = 'no-referrer';
    watchThumb(img, function () { end(false); }, function () { end(true); }, true);
    put(img, src);
  }
  function photo(src, fn) {
    if (verdicts[src] === false || via[src]) return fn(verdicts[src] !== false);
    (waiting[src] = waiting[src] || []).push(fn);
    if (!probing[src]) probe(src);
  }
  // While a sheet is on its way a thumb it may name waits (no src: no request, no default image beside her); put(img, null) forgets
  // img's waiting thumb. A thumb the sheet says is dead fails at once: watchThumb's onDead, no request.
  function put(img, src) {
    if (!src) return held.delete(img);
    if (verdicts[src] === false) return setTimeout(function () { img.dispatchEvent(new Event('error')); });
    if (sheetsOut && !via[src] && !cells[src]) { img.removeAttribute('src'); return held.set(img, src); }
    var p = via[src] || (cells[src] ? { u: cells[src] } : { u: thumb(src), cors: XO });
    if (p.cors) img.crossOrigin = 'anonymous';
    img.src = p.u;
  }
  // paced(src, ms): the gap after checking src: ms for a request, next to nothing for a thumb already here
  function paced(src, ms) { return cells[src] ? CELL_MS : ms; }
  function probeNext() {
    var it = null;
    galleries.some(function (g) { return (it = g.unchecked()); });
    if (!it) { lanes--; return; }
    probe(it.src, function () { setTimeout(probeNext, paced(it.src, PROBE_MS)); });
  }
  // gallery(images, slug): the live list behind the views of one result on one page part. view(box, max, mk, still?)
  // keeps box showing the first `max` images not dead as mk(it) tiles (tile(cap) = the engine's tile, with / without its
  // site caption); a dead one leaves and the next takes its slot (in place, see v.sync). count() → {ok: seen to load,
  // alive: ok + not checked yet, text: "24" once settled, "24+" before ("…" while none is checked)}: never more than
  // will show. view(box, max) again on a box it shows: that view's new max (a "Show more"). onCount(fn) → fn(count()) now
  // and on every change; returns its unsubscribe. close(): done with it.
  function tail(e) { var r = []; for (; e; e = e.nextElementSibling) r.push(e); return r; }
  function seen(e) {   // any part of e on screen: in the viewport and inside every clipping ancestor (a strip, a phone's screen)
    var r = e.getBoundingClientRect(), ok = function (c) { return r.right > c.left && r.left < c.right && r.bottom > c.top && r.top < c.bottom; };
    for (var p = e.parentElement; p && p !== document.body; p = p.parentElement) {
      if (getComputedStyle(p).overflow !== 'visible' && !ok(p.getBoundingClientRect())) return false;
    }
    return ok({ left: 0, top: 0, right: innerWidth, bottom: innerHeight });
  }
  function refocus(box, el) {   // focus stays on the slot: el's link, else (a tile with none) the next one in box, else its last
    var fs = [].slice.call(box.querySelectorAll('a, button')), f = el.matches('a, button') ? el : el.querySelector('a, button');
    f = f || fs.filter(function (x) { return el.compareDocumentPosition(x) & Node.DOCUMENT_POSITION_FOLLOWING; })[0] || fs[fs.length - 1];
    if (f) f.focus({ preventScroll: true });
  }
  var rank = function (it) { return it.still ? 2 : it.link ? 0 : 1; };   // result tiles, report tiles, top-up stills (reportModel)
  function gallery(images, slug) {
    var views = [], subs = [], g = {}, said = '';
    var alive = function () { return images.filter(function (it) { return verdicts[it.src] !== false; }); };
    g.count = function () {
      var a = alive(), ok = a.filter(function (it) { return verdicts[it.src]; }).length;
      return { ok: ok, alive: a.length, text: ok < a.length ? (ok ? ok + '+' : '…') : String(ok) };
    };
    g.unchecked = function () { return alive().filter(function (it) { return !verdicts[it.src] && !probing[it.src]; })[0] || null; };
    g.sync = function () {
      views = views.filter(function (v) { return v.box.isConnected; });
      views.forEach(function (v) { v.sync(); });
      var c = g.count();
      if (c.text + c.alive !== said) { said = c.text + c.alive; subs.slice().forEach(function (fn) { fn(c); }); }
    };
    // a tile: mk(it) → an element whose first <img> is the thumb; its .gi-wait (if any) goes once that loads (fade-in)
    var add = function (box, it, mk, swap) {   // swap: a dead tile whose very slot it takes (focus moves along)
      var el = mk(it), img = el.querySelector('img'), had = swap && swap.contains(document.activeElement);
      if (swap) swap.replaceWith(el); else box.appendChild(el);
      if (had) refocus(box, el);
      el.setAttribute('data-src', it.src);
      if (img) watchThumb(img, function () { verdict(it.src, false); }, function () {
        var w = el.querySelector('.gi-wait');
        if (w) w.classList.remove('gi-wait');
        passed(it.src, img);
      }, true);
    };
    g.tile = function (cap) { return function (it) { return tile(it, slug, cap); }; };
    g.view = function (box, max, mk, still) {
      var v = views.filter(function (x) { return x.box === box; })[0];
      if (v) { v.max = max; v.sync(); return box; }
      v = { box: box, max: max };
      // a dead tile: the next live image not shown takes its very slot, so nothing after it moves. A report tile never
      // sits before a result tile: when the next one is a report tile and a live result tile comes later in the box,
      // the last such result tile takes the dead slot and the report tile its slot (new nodes in both: still nothing
      // moves; same for a top-up video still: after both, rank). Nothing left to show: it just leaves; with still(el) (a view where nothing seen may move: the scan
      // page) the last live tile moves into the slot if it and every tile after it are off screen, else the slot stays
      // as still(el) (an empty tile, data-hole). Then the box fills up to max, in order.
      // One pass at a time: a cached thumb's load verdict lands inside add() (watchThumb → verdict → g.sync), and a
      // nested pass on the same box would re-add what the outer one is still adding (measured: 10-15 repeated tiles).
      v.sync = function () {
        if (v.busy) { v.again = true; return; }
        v.busy = true;
        try { do { v.again = false; pass(); } while (v.again); } finally { v.busy = false; }
      };
      var pass = function () {
        var have = {}, by = {}, kids = Array.prototype.slice.call(box.children);
        var src = function (el) { return el.getAttribute('data-src'); };
        var live = function (el) { return verdicts[src(el)] !== false && !el.hasAttribute('data-hole'); };
        images.forEach(function (it) { by[it.src] = it; });
        kids.forEach(function (el) { if (live(el)) have[src(el)] = 1; });
        var spare = alive().filter(function (it) { return !have[it.src]; });
        kids.forEach(function (el) {
          if (live(el) || el.hasAttribute('data-hole')) return;
          var nx = spare.shift();
          if (!nx && !still) return el.remove();
          if (!nx) {
            var donor = box.lastElementChild;
            while (donor !== el && !live(donor)) donor = donor.previousElementSibling;   // the last tile still showing an image
            var had = el.contains(document.activeElement) || donor.contains(document.activeElement);
            if (donor !== el && !tail(donor).some(seen)) { el.replaceWith(donor); if (had) refocus(box, donor); }
            else { el.setAttribute('data-hole', ''); still(el); }
            return;
          }
          var after = Array.prototype.filter.call(box.children, function (k) {
            var x = by[src(k)];
            return x && rank(x) < rank(nx) && verdicts[x.src] !== false && (el.compareDocumentPosition(k) & Node.DOCUMENT_POSITION_FOLLOWING);
          }), last = after[after.length - 1];
          if (last) { add(box, by[src(last)], mk, el); add(box, nx, mk, last); } else add(box, nx, mk, el);
        });
        spare.forEach(function (it) { if (box.children.length < v.max) add(box, it, mk); });
      };
      views.push(v);
      v.sync();
      return box;
    };
    g.onCount = function (fn) {
      subs.push(fn);
      fn(g.count());
      return function () { subs = subs.filter(function (f) { return f !== fn; }); };
    };
    g.close = function () { views = []; subs = []; galleries = galleries.filter(function (x) { return x !== g; }); };
    galleries.push(g);
    for (; images.length && lanes < PROBE_LANES; lanes++) setTimeout(probeNext, PROBE_WAIT);
    return g;
  }
  // A tile: blurred until Reveal; ↗ on hover / focus (always on touch screens). It links to the result that has that
  // image (new tab); an image no result has links to the full report.
  function tile(it, slug, cap) {
    var img = make('img', 'gi-img', [], { alt: '', loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer' });
    put(img, it.src);   // XO: readable pixels (isPhoto), crossorigin set before src; a passed thumb: its cached copy
    var box = make('span', 'gi-box gi-wait', [img, make('span', 'gi-go', [icon(it.link ? 'i-external-link' : 'i-arrow-right')])]);
    var label = it.link ? 'Image on ' + it.domain + (it.title ? ': ' + it.title : '') + ' (opens in a new tab)' : 'Image result: see it in the full report';
    return make('a', 'gi-card', [box, cap ? make('span', 'gi-cap', [fav(it.domain || 'google.com', 'gi-fav'), make('span', 'gi-cap-t', [it.domain || 'Google Images'])]) : null],
      Object.assign({ 'data-src': it.src }, it.link ? Object.assign({ href: it.link, 'aria-label': label, title: it.domain }, NEW_TAB)
        : { href: reportUrl(slug), 'aria-label': label }));
  }

  window.LeakScanEngine = {
    API: API, SCAN_API: SCAN_API, reportUrl: reportUrl, PLATFORMS: PLATFORMS, NEW_TAB: NEW_TAB,
    clean: clean, under: under, currentSlug: currentSlug, rankHosts: rankHosts, thumb: thumb, fresh: fresh, unfresh: unfresh,
    who: who, setMessages: setMessages, reportLinks: reportLinks, sendReport: sendReport, remember: remember, forget: forget, runScan: runScan,
    fetchResult: fetchResult, progressInfo: progressInfo, favColor: favColor, fav: fav, imageItems: imageItems, isVideo: isVideo,
    watchThumb: watchThumb, tablist: tablist, pager: pager, revealButton: revealButton, make: make, icon: icon,
    siteGroups: siteGroups, reportModel: reportModel, gallery: gallery, linked: linked, plural: plural,
    photoStats: photoStats, isPhoto: isPhoto, photo: photo, put: put, paced: paced, sheet: sheet, readSheet: readSheet, askStatus: askStatus, XO: XO
  };
})();
