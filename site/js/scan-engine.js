// Scan transport shared by the scan page (js/scan.js) and the landing hero (js/inline-scan.js). Plain ES2017, no
// tracking, no third parties. The API host is set in ONE place below: same origin, except on *.github.io (the VPS API
// host); <body data-api="..."> overrides it (tools/scan_stub.py does that).
(function () {
  'use strict';
  var API = (document.body.dataset.api || (location.hostname.slice(-9) === 'github.io' ? 'https://scan.srv1395798.hstgr.cloud' : '')).replace(/\/+$/, ''); // '' = same origin (VPS)
  // Shareable report link on the host serving this page (GitHub Pages, the VPS, later abolita.com): js/ -> ../scan/.
  var REPORT_BASE = new URL('../scan/?r=', document.currentScript.src).href;
  var PLATFORMS = { 'onlyfans.com': 'OnlyFans', 'instagram.com': 'Instagram', 'fansly.com': 'Fansly', 'tiktok.com': 'TikTok', 'patreon.com': 'Patreon' };
  var HANDLE_RE = /^[A-Za-z0-9._-]{1,60}$/, SLUG_RE = /^[A-Za-z0-9_-]{4,64}$/;

  function cleanHandle(raw) {
    var h = String(raw || '').trim();
    if (h.indexOf('/') >= 0) {
      var parts = h.split(/[?#]/)[0].split('/').filter(Boolean);
      h = parts.length ? parts[parts.length - 1] : '';
    }
    h = h.replace(/^@+/, '');
    return HANDLE_RE.test(h) ? h : null;
  }
  // The optional Instagram / X field. '' → null (none); instagram.com/<h> → instagram, x.com|twitter.com/<h> → x (only a
  // pasted URL decides); a bare name / @name → `net` (default instagram); anything else → false (invalid).
  function cleanSocial(raw, net) {
    var s = String(raw || '').trim(), h;
    if (!s) return null;
    var m = /^(?:https?:\/\/)?(?:www\.|m\.|mobile\.)?(instagram\.com|x\.com|twitter\.com)\/+@?([^\/?#\s]+)/i.exec(s);
    if (m) { h = m[2]; net = m[1].toLowerCase() === 'instagram.com' ? 'instagram' : 'x'; }
    else if (/[\/:]/.test(s)) return false;
    else h = s.replace(/^@+/, '');
    return HANDLE_RE.test(h) ? { net: net === 'x' ? 'x' : 'instagram', handle: h } : false;
  }
  function thumb(u) {
    return typeof u === 'string' && /^https:\/\//.test(u) ? API + '/api/thumb?u=' + encodeURIComponent(u) : null;
  }
  function who(handle, platform) { return '@' + handle + ' (' + (PLATFORMS[platform] || platform) + ')'; }

  // ---------- message links ----------
  function setMessages(scope, text, subject, body) {
    var q = encodeURIComponent(text);
    scope.querySelectorAll('[data-msg]').forEach(function (a) {
      var k = a.getAttribute('data-msg');
      if (k === 'tg') a.href = 'https://t.me/jakabasej?text=' + q;
      else if (k === 'wa') a.href = 'https://wa.me/38640703992?text=' + q;
      else a.href = 'mailto:me@jackbase.dev?subject=' + encodeURIComponent(subject) + '&body=' + encodeURIComponent(body);
    });
  }
  // "Send me the report": report link + handle prefilled.
  function sendReport(scope, slug, handle, platform) {
    var link = REPORT_BASE + encodeURIComponent(slug);
    var t = 'Hi Jaka, I ran the free scan for ' + who(handle, platform) + '. My report: ' + link;
    setMessages(scope, t, 'Free scan report: @' + handle,
      'Hi Jaka,\n\nI ran the free scan.\nMy report link: ' + link + '\nMy handle: ' + who(handle, platform) + '\n\nThanks!');
  }
  // Read by js/personalize.js on the homepage + demo site; stays in this browser only.
  function remember(raw, slug, handle, platform) {
    if (!SLUG_RE.test(slug)) return;
    var pn = raw.profile && typeof raw.profile.display_name === 'string' && raw.profile.display_name.length <= 60 ? raw.profile.display_name : null;
    try { localStorage.setItem('leakscan.last', JSON.stringify({ slug: slug, handle: handle, platform: platform, name: pn, ts: Date.now() })); } catch (e) { /* storage blocked */ }
  }

  // ---------- letter avatars + image items (scan page, hero card, #free band) ----------
  var FAV_COLORS = ['#ea4335', '#4285f4', '#34a853', '#fbbc05', '#ab47bc', '#00acc1', '#ff7043']; // cse_mosaic _TAB_PALETTE
  function favColor(dom) {
    var s = 0;
    for (var i = 0; i < (dom || '').length; i++) s += dom.charCodeAt(i);
    return FAV_COLORS[s % FAV_COLORS.length];
  }
  // fav(dom, cls, src?) → <span class=cls> with the domain's first letter on its colour; src (an /api/thumb URL) layers
  // a blurred thumb over it, dropped again if it fails to load.
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
      im.addEventListener('load', function () { el.classList.remove('fav-wait'); }, { once: true });
      im.addEventListener('error', function () { im.remove(); el.classList.remove('fav-wait'); el.classList.add('fav-none'); }, { once: true });
      el.appendChild(im);
    }
    return el;
  }
  // A video result (kind: 'video' from the API, or a link that looks like one): its thumb is a video still, often
  // hotlink-blocked; the image views skip it (the scan page's Videos tab still lists it).
  var VIDEO_RE = /\.(?:mp4|m3u8|webm|mov|mkv)(?:[?#]|$)|\/(?:videos?|watch|embed|clips?|vod)(?:[\/?#.-]|$)/i;
  function isVideo(r) { return !!r && (r.kind === 'video' || VIDEO_RE.test(r.link || '')); }
  // images[] first (with the result that has the same thumb, if any), then the results' own thumbs; deduped, ok(src)
  // filters, video results' thumbs skipped. → [{src, title, domain, link}] (title/domain/link '' when no result matches).
  function imageItems(images, results, ok, max) {
    var by = {}, seen = {}, out = [];
    results.forEach(function (r) { if (r.thumb && !by[r.thumb]) by[r.thumb] = r; });
    var add = function (u, r) {
      if (typeof u !== 'string' || seen[u] || !ok(u) || isVideo(r)) return;
      seen[u] = 1;
      out.push({ src: u, title: r && r.title || '', domain: r && r.domain || '', link: r && r.link || '' });
    };
    images.forEach(function (u) { add(u, by[u]); });
    results.forEach(function (r) { add(r.thumb, r); });
    return out.slice(0, max);
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
  // onResult / onError. social adds `instagram` or `x` to the request body.
  function runScan(o) {
    var result = null, failed = null, body = { platform: o.platform, handle: o.handle, level: 'low' };
    if (o.social) body[o.social.net] = o.social.handle;
    return streamScan(body, function (ev, data) {
      if (ev === 'progress') { if (o.onProgress) o.onProgress(data); }
      else if (ev === 'result') { try { result = JSON.parse(data); } catch (e) { failed = 'The scan result could not be read'; } }
      else if (ev === 'failed') failed = data || 'The scan stopped';
      else if (ev === 'done') return false;
    }).then(function () {
      if (failed) { var f = new Error(failed); f.kind = 'failed'; f.detail = failed.replace(/[.\s]+$/, ''); o.onError(f); }
      else if (result) o.onResult(result);
      else { var n = new Error('network'); n.kind = 'network'; o.onError(n); }
    }, function (e) { o.onError(e); });
  }
  // fetchResult(slug) → Promise of the stored result; rejects with err.kind like runScan. One request per slug per page:
  // the landing's ?r= reopen asks from inline-scan.js and personalize.js, both get this promise (a failure is not kept).
  // Callers only read the result, never mutate it.
  var results = {};
  function fetchResult(slug) {
    if (results[slug]) return results[slug];
    return (results[slug] = fetch(API + '/api/scan-result/' + encodeURIComponent(slug), { credentials: 'omit' }).then(function (res) {
      if (res.ok) return res.json();
      return res.json().catch(function () { return {}; }).then(function (j) { throw apiError(res.status, j && j.error, 'failed'); });
    }).catch(function (e) { delete results[slug]; if (!e.kind) e.kind = 'network'; throw e; }));
  }
  // A progress event's text → {pct: 5..95 | null, stage: what to show}.
  function progressInfo(text) {
    var m = /(\d+)\s*\/\s*(\d+)/.exec(text);
    if (m && +m[2] > 0) return { pct: Math.min(96, 5 + 90 * (+m[1] / +m[2])), stage: 'Searching Google, step ' + m[1] + ' of ' + m[2] + '…' };
    return { pct: null, stage: text };
  }

  window.LeakScanEngine = {
    API: API, REPORT_BASE: REPORT_BASE, PLATFORMS: PLATFORMS, SLUG_RE: SLUG_RE, HANDLE_RE: HANDLE_RE, cleanHandle: cleanHandle, cleanSocial: cleanSocial, thumb: thumb,
    who: who, setMessages: setMessages, sendReport: sendReport, remember: remember, runScan: runScan,
    fetchResult: fetchResult, progressInfo: progressInfo, favColor: favColor, fav: fav, imageItems: imageItems, isVideo: isVideo
  };
})();
