// Nav toggle, fade-in on scroll, mobile sticky CTA. No tracking, no third parties.
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
