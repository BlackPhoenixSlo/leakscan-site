/* ============================================================
   main.js — shared across all pages
   ============================================================ */

// Nav scroll effect
const nav = document.querySelector('.nav');
if (nav) {
  const onScroll = () => {
    nav.classList.toggle('scrolled', window.scrollY > 40);
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
}

// Mobile menu toggle
const toggle = document.querySelector('.nav__toggle');
const navLinks = document.querySelector('.nav__links');
if (toggle && navLinks) {
  toggle.addEventListener('click', () => {
    navLinks.classList.toggle('open');
    const open = navLinks.classList.contains('open');
    toggle.setAttribute('aria-expanded', open);
    document.body.style.overflow = open ? 'hidden' : '';
  });
  navLinks.querySelectorAll('a').forEach(a => {
    a.addEventListener('click', () => {
      navLinks.classList.remove('open');
      document.body.style.overflow = '';
    });
  });
}

// Highlight active nav link. Compares resolved paths rather than raw hrefs,
// so it works at any depth (blog/ posts link "../about.html") and under any
// subfolder the site is served from (the showcase lives at /…/showcase/).
{
  const clean = p => p.replace(/index\.html$/, '');
  const here = clean(window.location.pathname);
  const inBlog = /\/blog\//.test(window.location.pathname);
  document.querySelectorAll('.nav__links a').forEach(a => {
    const target = clean(new URL(a.getAttribute('href'), window.location.href).pathname);
    if (target === here || (inBlog && /\/blog\.html$/.test(target))) {
      a.classList.add('active');
    }
  });
}

// Demo ribbon (showcase only): dismissible, remembered for the session.
// Hidden when framed (the landing page's preview iframe): there it would cover
// the demo and its "Back to LeakScan" link would load the landing inside the frame.
const ribbon = document.querySelector('.demo-ribbon');
if (ribbon && window.self !== window.top) ribbon.classList.add('is-hidden');
else if (ribbon) {
  try {
    if (sessionStorage.getItem('demo-ribbon') === 'off') ribbon.classList.add('is-hidden');
  } catch (e) { /* storage blocked: the ribbon just stays */ }
  ribbon.querySelector('.demo-ribbon__close')?.addEventListener('click', () => {
    ribbon.classList.add('is-hidden');
    try { sessionStorage.setItem('demo-ribbon', 'off'); } catch (e) { /* ignore */ }
  });
}

// Lightbox
const lightbox = document.querySelector('.lightbox');
const lightboxImg = document.querySelector('.lightbox__img');
const lightboxClose = document.querySelector('.lightbox__close');

if (lightbox) {
  let opener = null;   // the gallery button that opened it; focus goes back there on close

  document.querySelectorAll('[data-lightbox]').forEach(item => {
    item.addEventListener('click', () => {
      const src = item.querySelector('img')?.src || item.dataset.lightbox;
      const alt = item.querySelector('img')?.alt || '';
      opener = item.querySelector('button') || document.activeElement;
      lightboxImg.src = src;
      lightboxImg.alt = alt;
      lightbox.classList.add('open');
      document.body.style.overflow = 'hidden';
      lightboxClose?.focus();
    });
  });

  const closeLightbox = () => {
    if (!lightbox.classList.contains('open')) return;
    lightbox.classList.remove('open');
    document.body.style.overflow = '';
    lightboxImg.src = '';
    opener?.focus();
    opener = null;
  };

  lightboxClose?.addEventListener('click', closeLightbox);
  lightbox.addEventListener('click', e => {
    if (e.target === lightbox) closeLightbox();
  });
  document.addEventListener('keydown', e => {
    if (!lightbox.classList.contains('open')) return;
    if (e.key === 'Escape') closeLightbox();
    // aria-modal: the close button is the only control inside, so Tab stays on it
    if (e.key === 'Tab') { e.preventDefault(); lightboxClose?.focus(); }
  });
}

// Fade-in via IntersectionObserver. Initial state is in CSS so no flash.
const fadeEls = document.querySelectorAll('[data-fade]');
if (fadeEls.length) {
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce) {
    fadeEls.forEach(el => el.classList.add('in-view'));
  } else {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('in-view');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

    fadeEls.forEach(el => observer.observe(el));
  }
}
