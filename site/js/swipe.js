// Phone swipe row (#removals panels, the page's one carousel): the static .swipe-nav after it gets
// working arrows + dots. CSS shows the nav only where the row scrolls (< 820px); the markup is static, so no shift.
(function () {
  document.querySelectorAll('.swipe-nav').forEach(function (nav) {
    var row = nav.previousElementSibling;
    while (row && !row.matches('.rm-grid')) row = row.previousElementSibling;
    if (!row) return;
    var items = [].slice.call(row.children).filter(function (el) { return el.matches('.rm-card'); });
    var dots = [].slice.call(nav.querySelectorAll('.swipe-dot'));
    var prev = nav.querySelector('.swipe-prev'), next = nav.querySelector('.swipe-next');
    var reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
    function at() {   // the item whose centre is nearest the row's centre
      var c = row.getBoundingClientRect(), mid = c.left + c.width / 2, best = 0, d = Infinity;
      items.forEach(function (el, i) { var r = el.getBoundingClientRect(), k = Math.abs(r.left + r.width / 2 - mid); if (k < d) { d = k; best = i; } });
      return best;
    }
    function go(i) {
      var el = items[Math.max(0, Math.min(items.length - 1, i))], c = row.getBoundingClientRect(), r = el.getBoundingClientRect();
      row.scrollBy({ left: r.left + r.width / 2 - (c.left + c.width / 2), behavior: reduce.matches ? 'auto' : 'smooth' });
    }
    function sync() {
      var i = at();
      dots.forEach(function (d, k) { if (k === i) d.setAttribute('aria-current', 'true'); else d.removeAttribute('aria-current'); });
      prev.disabled = i === 0; next.disabled = i === items.length - 1;
    }
    prev.addEventListener('click', function () { go(at() - 1); });
    next.addEventListener('click', function () { go(at() + 1); });
    dots.forEach(function (d, k) { d.addEventListener('click', function () { go(k); }); });
    var t = 0;
    row.addEventListener('scroll', function () { cancelAnimationFrame(t); t = requestAnimationFrame(sync); }, { passive: true });
    sync();
  });
})();
