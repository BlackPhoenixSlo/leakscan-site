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

    var cta = document.querySelector('.mobile-cta');
    var hero = document.querySelector('.hero');
    var contact = document.getElementById('contact');
    if (cta && hero) {
      var heroOut = false, contactIn = false;
      var update = function () { cta.classList.toggle('show', heroOut && !contactIn); };
      new IntersectionObserver(function (en) { heroOut = !en[0].isIntersecting; update(); }).observe(hero);
      if (contact) new IntersectionObserver(function (en) { contactIn = en[0].isIntersecting; update(); }).observe(contact);
    }
  }
})();
