// "Ask AI before you DM me" popup. Common questions are answered instantly from this page's own text (no network);
// anything else streams from the scan server's /api/chat. Model text is rendered with DOM nodes only, and links are
// clickable only for in-page anchors and a short host allowlist. Conversation: memory + sessionStorage, no cookies.
(function () {
  'use strict';
  var launcher = document.querySelector('.askai-launcher');
  var dlg = document.getElementById('askai');
  if (!launcher || !dlg || typeof dlg.showModal !== 'function') return;

  var API = (document.body.dataset.api ||
    (location.hostname.slice(-9) === 'github.io' ? 'https://scan.srv1395798.hstgr.cloud' : '')).replace(/\/+$/, ''); // '' = same origin (VPS)
  var HAS_API = !!API || /^https?:$/.test(location.protocol);   // opened from disk: nothing to call
  var HOSTS = ['t.me', 'wa.me', 'blackphoenixslo.github.io', 'abolita.com', 'www.abolita.com', 'jackbase.me',
    'scan.srv1395798.hstgr.cloud'];
  var CONTACTS = [
    ['Telegram', 'https://t.me/jakabasej?text=' + encodeURIComponent('Hi Jaka, I have a question about Abolita: ')],
    ['WhatsApp', 'https://wa.me/38640703992?text=' + encodeURIComponent('Hi Jaka, I have a question about Abolita: ')],
    ['Email', 'mailto:me@jackbase.dev?subject=' + encodeURIComponent('Question about Abolita') + '&body=' +
      encodeURIComponent('Hi Jaka,\n\nI have a question about Abolita: ')]
  ];
  var MAX_SEND = 8;           // messages sent to the API per request
  var STORE = 'leakscan.askai';
  var phone = window.matchMedia('(max-width: 719px)');
  var calm = window.matchMedia('(prefers-reduced-motion: reduce)');

  var log = dlg.querySelector('.askai-log');
  var form = dlg.querySelector('.askai-form');
  var input = form.querySelector('textarea');
  var sendBtn = form.querySelector('button[type=submit]');
  var opener = launcher;
  var busy = false;
  var msgs = [];              // {role, content, src: 'cached'|'ai', id?}
  try { msgs = JSON.parse(sessionStorage.getItem(STORE) || '[]').filter(function (m) {
    return m && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string';
  }); } catch (e) { msgs = []; }
  function save() { try { sessionStorage.setItem(STORE, JSON.stringify(msgs.slice(-40))); } catch (e) { /* full/off */ } }

  var el = function (tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  var clean = function (s) { return String(s || '').replace(/\s+/g, ' ').trim(); };

  // ---------- knowledge base: read from the page itself ----------
  var KB = [];
  (function () {
    var pricing = document.getElementById('pricing');
    if (pricing) {
      var lines = [], lead = pricing.querySelector('.section-head p:not(.eyebrow)');
      if (lead) lines.push(clean(lead.textContent));
      pricing.querySelectorAll('.plan').forEach(function (plan) {
        var h = plan.querySelector('h3'), amt = plan.querySelector('.amount'), per = plan.querySelector('.per');
        var ticks = [].map.call(plan.querySelectorAll('.ticks li'), function (li) { return clean(li.textContent); });
        if (h && amt) lines.push('- **' + clean(h.textContent) + '**: ' + clean(amt.textContent) + ' ' +
          clean(per && per.textContent) + '. ' + ticks.join(', ') + '.');
      });
      var fine = pricing.querySelector('.fineprint');
      if (fine) lines.push(clean(fine.textContent));
      KB.push({ q: 'What does it cost?', a: lines.join('\n'), id: 'pricing' });
    }
    document.querySelectorAll('#faq details').forEach(function (d) {
      var s = d.querySelector('summary'), p = d.querySelector('p');
      if (s && p) KB.push({ q: clean(s.textContent), a: clean(p.textContent), id: 'faq' });
    });
  })();

  // ---------- fuzzy match: share of the question's content words found in an FAQ question ----------
  var STOP = {};
  ('a an and are as at be but by can could do does did for from get have has how i if in into is it its me my of on ' +
    'or our so that the their them then there these they this to us was we what when where which who why will with ' +
    'would you your ok please hi hello hey jaka tell about know want work take any anything').split(' ')
    .forEach(function (w) { STOP[w] = 1; });
  var SYN = { price: 'cost', pric: 'cost', much: 'cost', pay: 'cost', fee: 'cost', expensive: 'cost', cheap: 'cost',
    euro: 'cost', eur: 'cost', '€': 'cost', money: 'cost', charge: 'cost', plan: 'cost', quick: 'fast', long: 'fast',
    soon: 'fast', legit: 'legal', law: 'legal', lawful: 'legal', allowed: 'legal', illegal: 'legal', ban: 'affect',
    refund: 'cancel', subscription: 'renew', private: 'safe', privacy: 'safe', secure: 'safe', data: 'information',
    info: 'information', signup: 'register', login: 'register', reupload: 'back', return: 'back' };
  function tokens(s) {
    return (String(s).toLowerCase().replace(/[’']/g, '').match(/[a-z0-9€]+/g) || []).filter(function (w) {
      return !STOP[w] && (w.length > 1 || w === '€');
    }).map(function (w) {
      if (w.length > 5 && /ing$/.test(w)) w = w.slice(0, -3);
      else if (w.length > 4 && /ed$/.test(w)) w = w.slice(0, -2);
      else if (w.length > 3 && /s$/.test(w) && !/ss$/.test(w)) w = w.slice(0, -1);
      return SYN[w] || w;
    });
  }
  KB.forEach(function (k) { k.t = tokens(k.q); });
  function match(q) {
    var qt = tokens(q).filter(function (w, i, a) { return a.indexOf(w) === i; });
    if (!qt.length || qt.length > 8) return null;
    var best = null, bestScore = 0;
    KB.forEach(function (k) {
      var hit = qt.filter(function (w) { return k.t.indexOf(w) >= 0; }).length;
      var score = hit / qt.length + (k.t.length ? hit / k.t.length : 0) / 100;   // tie-break: covers more of k
      if (score > bestScore) { bestScore = score; best = k; }
    });
    return bestScore >= 0.6 ? best : null;
  }

  // ---------- safe rendering ----------
  function anchorTarget(id) {
    var t = id && document.getElementById(id);
    return t && !dlg.contains(t) && !t.closest('svg') ? t : null;
  }
  function anchorLabel(id) {
    var nav = document.querySelector('nav a[href="#' + id + '"]');
    if (nav && clean(nav.textContent)) return clean(nav.textContent);
    var t = anchorTarget(id), by = t && t.getAttribute('aria-labelledby');
    var h = (by && document.getElementById(by)) || (t && t.querySelector('h2, h3'));
    return h ? clean(h.textContent).replace(/[.:]+$/, '') : id;
  }
  function hostOk(h) { return HOSTS.indexOf(h) >= 0; }
  function link(href, text) {
    href = String(href || '').trim();
    var a = el('a');
    if (href.charAt(0) === '#') {
      var id = href.slice(1);
      if (!anchorTarget(id)) return null;
      a.href = href;
      a.className = 'askai-anchor';
      a.textContent = !text || text === href || text === id ? anchorLabel(id) : text;
      return a;
    }
    if (/^mailto:me@jackbase\.dev(\?[^\s]*)?$/i.test(href)) {
      a.href = href;
    } else {
      var u;
      try { u = new URL(href); } catch (e) { return null; }
      if (u.protocol !== 'https:' || u.username || u.password || !hostOk(u.hostname)) return null;
      a.href = u.href;
      a.target = '_blank';
      a.rel = 'noopener';
    }
    a.textContent = text || href;
    return a;
  }
  var INLINE = /\[([^\]\n]{1,200})\]\(([^()\s]{1,500}(?:\([^()\s]*\)[^()\s]*)?)\)|\*\*([^*\n]{1,300})\*\*|(https?:\/\/[^\s<>()[\]]+|mailto:[^\s<>()[\]]+)|(^|[^\w/&#])(#[A-Za-z][\w-]{0,40})/g;
  function inline(text, parent) {
    var last = 0, m;
    INLINE.lastIndex = 0;
    while ((m = INLINE.exec(text))) {
      var start = m.index, tail = '';
      if (m[6]) start += m[5].length;
      parent.appendChild(document.createTextNode(text.slice(last, start)));
      if (m[1] != null) {
        parent.appendChild(link(m[2], m[1]) || document.createTextNode(m[1]));
      } else if (m[3] != null) {
        var b = el('strong');
        inline(m[3], b);
        parent.appendChild(b);
        INLINE.lastIndex = m.index + m[0].length;
      } else if (m[4] != null) {
        var url = m[4].replace(/[.,;:!?'"]+$/, '');
        tail = m[4].slice(url.length);
        parent.appendChild(link(url) || document.createTextNode(url));
      } else {
        parent.appendChild(link(m[6]) || document.createTextNode(m[6]));
      }
      if (tail) parent.appendChild(document.createTextNode(tail));
      last = m.index + m[0].length;
      INLINE.lastIndex = last;
    }
    parent.appendChild(document.createTextNode(text.slice(last)));
  }
  function render(text, box) {
    box.textContent = '';
    var p = null, ul = null;
    String(text).replace(/\r\n?/g, '\n').split('\n').forEach(function (line) {
      var bullet = /^\s*(?:[-*•]|\d+[.)])\s+(.*)$/.exec(line);
      if (!line.trim()) { p = ul = null; return; }
      if (bullet) {
        p = null;
        if (!ul) { ul = el('ul'); box.appendChild(ul); }
        var li = el('li');
        inline(bullet[1], li);
        ul.appendChild(li);
        return;
      }
      ul = null;
      if (p) p.appendChild(el('br')); else { p = el('p'); box.appendChild(p); }
      inline(line, p);
    });
  }

  // ---------- conversation UI ----------
  function scrollDown() { log.scrollTop = log.scrollHeight; }
  function bubble(role, src) {
    var b = el('div', 'askai-msg askai-' + (role === 'user' ? 'user' : 'bot'));
    if (src) b.dataset.source = src;
    var body = el('div', 'askai-body');
    b.appendChild(body);
    log.appendChild(b);
    return b;
  }
  function contactLinks(parent) {
    var row = el('p', 'askai-contacts');
    CONTACTS.forEach(function (c, i) {
      if (i) row.appendChild(document.createTextNode(' · '));
      var a = el('a', null, c[0]);
      a.href = c[1];
      if (c[1].indexOf('https:') === 0) { a.target = '_blank'; a.rel = 'noopener'; }
      row.appendChild(a);
    });
    parent.appendChild(row);
  }
  function chip(k) {
    var c = el('button', 'askai-chip', k.q);
    c.type = 'button';
    c.addEventListener('click', function () { ask(k.q, k); });
    return c;
  }
  function greet() {
    var b = bubble('assistant');
    render('Hi! I answer quick questions about Abolita from this page. Pick one or type your own.', b.firstChild);
    var chips = el('div', 'askai-chips');
    KB.slice(0, 6).forEach(function (k) { chips.appendChild(chip(k)); });
    b.appendChild(chips);
  }
  function moreButton(b) {
    var row = el('div', 'askai-actions');
    var more = el('button', 'askai-more', 'Ask the AI for more detail');
    more.type = 'button';
    more.addEventListener('click', function () { if (!busy) send('Can you give me more detail on that?'); });
    row.appendChild(more);
    b.appendChild(row);
  }
  function showMsg(m) {
    var b = bubble(m.role, m.role === 'assistant' ? m.src : null);
    if (m.role === 'user') b.firstChild.textContent = m.content; else render(m.content, b.firstChild);
    if (m.src === 'cached') moreButton(b);
    return b;
  }
  function setBusy(on) {
    busy = on;
    sendBtn.disabled = on;
    log.setAttribute('aria-busy', String(on));
  }

  function ask(q, k) {
    q = String(q || '').trim().slice(0, 500);
    if (!q || busy) return;
    k = k || match(q);
    if (!k) return send(q);
    msgs.push({ role: 'user', content: q });
    showMsg(msgs[msgs.length - 1]);
    var m = { role: 'assistant', src: 'cached', id: k.id, content: k.a + '\n\nMore on this page: [#' + k.id + '](#' + k.id + ')' };
    msgs.push(m);
    showMsg(m);
    save();
    scrollDown();
  }

  function failure(kind, retry) {
    var b = bubble('assistant', 'error');
    b.classList.add('askai-error');
    b.dataset.kind = kind;
    b.firstChild.textContent = kind === 'rate_limited'
      ? 'Too many questions in a short time. Try again in a minute, or message Jaka directly:'
      : kind === 'no_api' ? 'The AI isn’t available on this copy of the site. Message Jaka directly:'
        : 'The AI couldn’t answer right now. Message Jaka directly:';
    contactLinks(b);
    if (retry) {
      var row = el('div', 'askai-actions'), r = el('button', 'askai-more', 'Try again');
      r.type = 'button';
      r.addEventListener('click', function () { if (!busy) { b.remove(); retry(); } });
      row.appendChild(r);
      b.appendChild(row);
    }
    scrollDown();
  }

  // the report this page is about (?r=, else the last scan in this browser): js/scan-engine.js, validated there
  function slug() { var E = window.LeakScanEngine; return E ? E.currentSlug() : null; }

  function send(q) {
    msgs.push({ role: 'user', content: q });
    showMsg(msgs[msgs.length - 1]);
    save();
    stream();
  }

  async function stream() {
    if (!HAS_API) { failure('no_api', null); return; }
    setBusy(true);
    var b = bubble('assistant', 'ai'), body = b.firstChild, text = '';
    b.classList.add('askai-typing');
    var dots = body.appendChild(el('span', 'askai-dots'));
    dots.appendChild(el('i'));
    dots.setAttribute('role', 'img');
    dots.setAttribute('aria-label', 'Typing');
    scrollDown();
    var hist = msgs.slice(-MAX_SEND).map(function (m) { return { role: m.role, content: m.content }; });
    while (hist.length && hist[0].role !== 'user') hist.shift();
    var payload = { kb: 'landing', messages: hist }, s = slug();
    if (s) payload.slug = s;
    var ctrl = window.AbortController ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, 90000);
    var kind = null;
    try {
      var res = await fetch(API + '/api/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify(payload), signal: ctrl ? ctrl.signal : undefined
      });
      if (!res.ok) {
        var j = {};
        try { j = await res.json(); } catch (e) { /* not JSON */ }
        throw { kind: res.status === 429 || (j && j.error === 'rate_limited') ? 'rate_limited' : 'failed' };
      }
      var buf = '', done = false;
      var dispatch = function (block) {
        var ev = 'message', data = [];
        block.split('\n').forEach(function (line) {
          if (!line || line.charAt(0) === ':') return;
          var i = line.indexOf(':');
          var field = i < 0 ? line : line.slice(0, i), val = i < 0 ? '' : line.slice(i + 1).replace(/^ /, '');
          if (field === 'event') ev = val; else if (field === 'data') data.push(val);
        });
        var d = data.join('\n');
        if (ev === 'token') {
          var chunk;
          try { chunk = JSON.parse(d); } catch (e) { chunk = d; }
          if (typeof chunk !== 'string') return;
          text += chunk;
          b.classList.remove('askai-typing');
          render(text, body);
          scrollDown();
        } else if (ev === 'failed') { throw { kind: 'failed' }; } else if (ev === 'done') { done = true; }
      };
      var feed = function (t, final) {
        buf = (buf + t).replace(/\r\n/g, '\n');
        var i;
        while (!done && (i = buf.indexOf('\n\n')) >= 0) { dispatch(buf.slice(0, i)); buf = buf.slice(i + 2); }
        if (final && !done && buf.trim()) dispatch(buf);
      };
      if (!res.body || !res.body.getReader) feed(await res.text(), true);
      else {
        var reader = res.body.getReader(), dec = new TextDecoder();
        for (;;) {
          var c = await reader.read();
          if (c.done) { feed(dec.decode(), true); break; }
          feed(dec.decode(c.value, { stream: true }), false);
          if (done) { reader.cancel().catch(function () {}); break; }
        }
      }
      if (!text.trim()) throw { kind: 'failed' };
    } catch (e) {
      kind = (e && e.kind) || 'network';
    } finally {
      clearTimeout(timer);
    }
    if (kind) {
      b.remove();
      setBusy(false);
      failure(kind, stream);
      return;
    }
    msgs.push({ role: 'assistant', src: 'ai', content: text });
    save();
    setBusy(false);
  }

  // ---------- links inside answers ----------
  log.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a.askai-anchor');
    if (!a) return;
    var t = anchorTarget(a.getAttribute('href').slice(1));
    if (!t) return;
    e.preventDefault();
    if (phone.matches) close();
    t.scrollIntoView({ behavior: calm.matches ? 'auto' : 'smooth', block: 'start' });
  });

  // ---------- open / close ----------
  var started = false;
  function open(from) {
    opener = from || launcher;
    if (!started) {
      started = true;
      greet();
      msgs.forEach(showMsg);
    }
    document.documentElement.classList.add('askai-open');
    dlg.showModal();
    launcher.setAttribute('aria-expanded', 'true');
    scrollDown();
    input.focus();
  }
  function close() {   // unlock page scroll now: the dialog's close event fires a task later
    document.documentElement.classList.remove('askai-open');
    if (dlg.open) dlg.close();
  }
  dlg.addEventListener('close', function () {
    document.documentElement.classList.remove('askai-open');
    launcher.setAttribute('aria-expanded', 'false');
    if (opener && opener.focus) opener.focus({ preventScroll: true });
  });
  dlg.addEventListener('click', function (e) { if (e.target === dlg) close(); });   // backdrop
  dlg.querySelector('.askai-close').addEventListener('click', close);
  dlg.addEventListener('keydown', function (e) {
    if (e.key !== 'Tab') return;
    var f = [].filter.call(dlg.querySelectorAll('a[href], button:not([disabled]), textarea, input'), function (n) {
      return n.offsetParent !== null || n === document.activeElement;
    });
    if (!f.length) return;
    var first = f[0], lastEl = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); lastEl.focus(); }
    else if (!e.shiftKey && document.activeElement === lastEl) { e.preventDefault(); first.focus(); }
  });
  launcher.addEventListener('click', function () { open(launcher); });
  document.querySelectorAll('[data-askai-open]').forEach(function (a) {
    a.addEventListener('click', function (e) { e.preventDefault(); open(a); });
  });

  // ---------- input ----------
  function grow() { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 140) + 'px'; }
  input.addEventListener('input', grow);
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit ? form.requestSubmit() : submit(e); }
  });
  function submit(e) {
    if (e) e.preventDefault();
    var q = input.value.trim();
    if (!q || busy) return;
    input.value = '';
    grow();
    ask(q);
  }
  form.addEventListener('submit', submit);

  // css/chat.css hides the launcher while the hero is on screen (any width); on phones it appears with the sticky scan bar.
  var hero = document.querySelector('.hero');
  if (hero && 'IntersectionObserver' in window) {
    launcher.classList.add('in-hero');
    new IntersectionObserver(function (en) { launcher.classList.toggle('in-hero', en[0].isIntersecting); }).observe(hero);
  }
  launcher.hidden = false;
  // Any width: also out of the way while the pill would sit on the hero card's actions (after a scan) or on the
  // before / after phones or the showcase preview, and while a scan runs with the card on screen (.in-quiet, same look as .in-hero).
  var QUIET = ['.report-card .live-actions', '.ba', '#showcase .browser-demo'], qraf = 0;
  var quiet = function () {
    qraf = 0;
    var b = launcher.getBoundingClientRect(), busy = document.querySelector('.report-card[aria-busy]'), br = busy && busy.getBoundingClientRect();
    var hit = !dlg.open && document.activeElement !== launcher && (
      (br && br.bottom > 0 && br.top < window.innerHeight) ||   // a scan running: the card's skeleton is the thing to watch
      QUIET.some(function (sel) {
        var el = document.querySelector(sel), r = el && el.getBoundingClientRect();
        return r && r.width && r.right > b.left - 8 && r.left < b.right + 8 && r.bottom > b.top - 8 && r.top < b.bottom + 8;
      }));
    launcher.classList.toggle('in-quiet', hit);
  };
  var later = function () { if (!qraf) qraf = requestAnimationFrame(quiet); };
  window.addEventListener('scroll', later, { passive: true });
  window.addEventListener('resize', later);
  if (window.ResizeObserver) new ResizeObserver(later).observe(document.body);   // the hero card growing into a report
  var rc = document.querySelector('.report-card');
  if (rc && window.MutationObserver) new MutationObserver(later).observe(rc, { attributes: true, attributeFilter: ['aria-busy'] });
  launcher.addEventListener('focus', quiet);   // never hide the pill under keyboard focus (Esc returns focus here)
  launcher.addEventListener('blur', later);
  dlg.addEventListener('close', later);
  later();
})();
