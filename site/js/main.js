// Nav toggle, fade-in on scroll, mobile sticky CTA. This file: no tracking, no third parties (ads: js/analytics.js).
(function () {
  var toggle = document.querySelector('.nav-toggle');
  var nav = document.getElementById('nav');
  if (toggle && nav) {
    var setOpen = function (open) {
      toggle.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-label', open ? 'Close menu' : 'Menu');
      nav.classList.toggle('open', open);
    };
    toggle.addEventListener('click', function () { setOpen(toggle.getAttribute('aria-expanded') !== 'true'); });
    nav.addEventListener('click', function (e) { if (e.target.closest('a')) setOpen(false); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && nav.classList.contains('open')) { setOpen(false); toggle.focus(); }
    });
    // Tabbing out of the open menu closes it, else it covers the content that now has focus.
    var header = toggle.closest('header');
    if (header) header.addEventListener('focusout', function (e) {
      if (nav.classList.contains('open') && e.relatedTarget && !header.contains(e.relatedTarget)) setOpen(false);
    });
  }

  // Phone mockups: All / Images / Videos are real tabs (E.tablist: click, ←/→, Home / End). The screen has a fixed
  // height, so a switch never moves the page.
  var E = window.LeakScanEngine;
  if (E) document.querySelectorAll('.phone').forEach(function (phone) { E.tablist(phone); });
  // Before / after phones: each tab's list scrolls inside the screen; "Show more" (like #free) shows its next .m-batch,
  // gone after the last
  if (E) document.querySelectorAll('.ba .m-panel').forEach(function (p) {
    var bs = p.querySelectorAll('.m-batch');
    if (bs.length) p.appendChild(E.pager(p, 1, function (n) { bs.forEach(function (b, i) { b.hidden = i >= n - 1; }); },
      function (n) { return n <= bs.length; }).el);
  });

  // Before / after: one phone at a time, picked by real tabs (click, ←/→, Home / End). Not E.tablist: that sets
  // [hidden], and without JS both phones show. .ba[data-show] picks the one in view (CSS).
  var baTabs = document.querySelector('.ba-tabs'), ba = document.querySelector('.ba[data-show]');
  if (baTabs && ba) {
    var bt = [].slice.call(baTabs.querySelectorAll('[role="tab"]'));
    var pick = function (t, focus) {
      bt.forEach(function (b) { var on = b === t; b.setAttribute('aria-selected', on ? 'true' : 'false'); b.tabIndex = on ? 0 : -1; });
      ba.setAttribute('data-show', t.id.replace('ba-tab-', ''));
      if (focus) t.focus();
    };
    baTabs.addEventListener('click', function (e) { var t = e.target.closest('[role="tab"]'); if (t) pick(t); });
    baTabs.addEventListener('keydown', function (e) {
      var i = bt.indexOf(document.activeElement), n = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: bt.length - 1 }[e.key];
      if (i < 0 || n === undefined) return;
      e.preventDefault(); pick(bt[(n + bt.length) % bt.length], true);
    });
  }

  // Demo frame: data-src until the page has loaded and the frame is near the screen. Chrome's own lazy-frame distance
  // (~3000 px) started it during load on desktop: with a stored scan its photos held the load event and the video player
  // behind it (first frame 6 s vs 1.8 s on Fast 4G, measured). personalize.js writes her ?r= to data-src until then.
  var lazyDemo = document.querySelector('iframe[data-p="demo"][data-src]');
  if (lazyDemo) {
    var demoGo = function () { if (!lazyDemo.getAttribute('src')) lazyDemo.setAttribute('src', lazyDemo.getAttribute('data-src')); };
    var demoWatch = function () {
      if (!('IntersectionObserver' in window)) return demoGo();
      var io = new IntersectionObserver(function (es) { if (es.some(function (e) { return e.isIntersecting; })) { io.disconnect(); demoGo(); } }, { rootMargin: '800px 0px' });
      io.observe(lazyDemo);
    };
    if (document.readyState === 'complete') demoWatch(); else addEventListener('load', demoWatch, { once: true });
  }

  // Demo site: "Full screen" pops the frame out to a layer over the page (same iframe, no reload: it keeps its scroll).
  // Its slot keeps its height and the scrollbar gutter stays, so nothing behind it moves. Esc / the button / the
  // backdrop close it; focus goes back to the button; the rest of the page is inert meanwhile.
  var demoFig = document.querySelector('#showcase .browser-demo'), popBtn = demoFig && demoFig.querySelector('.demo-pop');
  if (popBtn) {
    var frame = demoFig.querySelector('iframe'), backdrop = null, inerted = [], slot = demoFig.parentNode;
    var popOpen = function () { return demoFig.classList.contains('is-pop'); };
    var onKey = function (e) { if (e.key === 'Escape' && popOpen()) { e.preventDefault(); setPop(false); } };
    var setPop = function (on) {
      if (on === popOpen()) return;
      if (on) {
        var h = demoFig.getBoundingClientRect().height, cs = getComputedStyle(demoFig);   // not offsetHeight: it rounds, content below would jump
        var hold = document.createElement('div');
        hold.className = 'demo-hold';
        hold.style.height = h + 'px';
        hold.style.marginTop = cs.marginTop;
        slot.insertBefore(hold, demoFig);
        backdrop = document.createElement('div');
        backdrop.className = 'demo-backdrop';
        backdrop.addEventListener('click', function () { setPop(false); });
        document.body.appendChild(backdrop);
        // everything but the frame is inert: each ancestor's other children, up to <body>
        for (var el = demoFig; el && el !== document.body; el = el.parentElement) {
          Array.prototype.forEach.call(el.parentElement.children, function (sib) {
            if (sib !== el && sib !== backdrop && !sib.inert && sib.tagName !== 'SCRIPT') { sib.inert = true; inerted.push(sib); }
          });
        }
      }
      document.documentElement.classList.toggle('pop-lock', on);
      demoFig.classList.toggle('is-pop', on);
      if (on) {
        demoFig.setAttribute('role', 'dialog');
        demoFig.setAttribute('aria-modal', 'true');
        demoFig.setAttribute('aria-label', 'Demo site, full screen');
      } else {
        ['role', 'aria-modal', 'aria-label'].forEach(function (a) { demoFig.removeAttribute(a); });
        inerted.forEach(function (sib) { sib.inert = false; });
        inerted = [];
        if (backdrop) backdrop.remove();
        backdrop = null;
        var hold0 = slot.querySelector('.demo-hold');
        if (hold0) hold0.remove();
      }
      frame.tabIndex = on ? 0 : -1;   // full screen: the keyboard can go in and scroll it
      popBtn.setAttribute('aria-label', on ? 'Close full screen' : 'Open the demo full screen');
      popBtn.setAttribute('aria-expanded', String(on));
      popBtn.querySelector('.demo-pop-t').textContent = on ? 'Close' : 'Full screen';
      try { frame.contentWindow[on ? 'addEventListener' : 'removeEventListener']('keydown', onKey); } catch (e) { /* not loaded yet */ }
      popBtn.focus({ preventScroll: true });
    };
    popBtn.hidden = false;
    popBtn.setAttribute('aria-expanded', 'false');
    popBtn.addEventListener('click', function () { setPop(!popOpen()); });
    var shot = demoFig.querySelector('.demo-shot');   // phone: the still of the demo's top opens the same full screen
    if (shot) shot.addEventListener('click', function (e) { e.preventDefault(); setPop(true); });
    document.addEventListener('keydown', onKey);
    frame.addEventListener('load', function () {   // a popped frame that navigates keeps Esc
      if (popOpen()) try { frame.contentWindow.addEventListener('keydown', onKey); } catch (e) { /* ignore */ }
    });
  }

  var items = document.querySelectorAll('.reveal');
  if (!('IntersectionObserver' in window)) {
    items.forEach(function (el) { el.classList.add('is-in'); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('is-in'); io.unobserve(en.target); }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    items.forEach(function (el) { io.observe(el); });
    // Tab scrolls a control just into view, often inside the -8% band, so it would stay invisible while focused.
    document.addEventListener('focusin', function (e) {
      var el = e.target.closest && e.target.closest('.reveal:not(.is-in)');
      if (el) { el.classList.add('is-in'); io.unobserve(el); }
    });

    var cta = document.querySelector('.mobile-cta');
    var hero = document.querySelector('.hero');
    var contact = document.getElementById('contact');
    if (cta && hero) {
      var heroOut = false, contactIn = false, demoIn = false, demo = document.querySelector('#showcase .browser-demo');
      var update = function () { cta.classList.toggle('show', heroOut && !contactIn && !demoIn); };
      new IntersectionObserver(function (en) { heroOut = !en[0].isIntersecting; update(); }).observe(hero);
      if (contact) new IntersectionObserver(function (en) { contactIn = en[0].isIntersecting; update(); }).observe(contact);
      // and while the showcase preview is behind the bar (the bottom quarter of the screen): it would cover the preview
      if (demo) new IntersectionObserver(function (en) { demoIn = en[0].isIntersecting; update(); }, { rootMargin: '-75% 0px 0px 0px' }).observe(demo);
    }
  }
})();
