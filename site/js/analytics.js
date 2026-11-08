// Google Ads conversions + Consent Mode v2 banner. gtag.js directly, no GTM. One line per page, nothing else to wire:
// <script src="<relative>/js/analytics.js" defer></script>. Conversions: `leakscan:result` (js/scan-engine.js, once per
// finished scan on any page) and a click on any of Jaka's contact links. [data-cookie-settings] (ships `hidden`) reopens
// the banner. Never sent to Google: handle, name, report slug, search query: URL + title are overridden below, the
// conversions carry no params. Policy: privacy.html#cookies.
(function () {
  'use strict';
  // OWNER: paste the 3 values from Google Ads (conversion's event snippet: send_to = 'AW-123456789/AbCdEfG').
  // While ADS_ID is '' this file does nothing: no network, no banner, no cookies, no storage.
  const ADS_ID = 'AW-18562652989';
  const LABEL_SCAN = '2mDtCPnflrQdEL22rpNF';      // "Free scan finished"
  const LABEL_CONTACT = 'MddqCPzflrQdEL22rpNF';   // "Contact"

  // In a frame (the mini player's video/) the top page does the counting and the asking.
  if (!ADS_ID || window.top !== window) return;

  const KEY = 'leakscan.consent';   // 'granted' | 'denied'
  const TYPES = ['ad_storage', 'ad_user_data', 'ad_personalization', 'analytics_storage'];
  const CONTACT = /^(https:\/\/t\.me\/jakabasej|https:\/\/wa\.me\/38640703992|mailto:dmca@jackbase\.dev)\b/i;   // not any t.me: leak links are listed too
  const AD_CLICK = ['gclid', 'gbraid', 'wbraid', 'dclid', 'gclsrc', 'gad_source', 'gad_campaignid', '_gl'];   // Google's own click ids: all a URL keeps
  const SELF = document.currentScript.src;

  function consent(v) { const o = {}; TYPES.forEach(function (t) { o[t] = v; }); return o; }
  function saved() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }

  window.dataLayer = window.dataLayer || [];
  function gtag() { window.dataLayer.push(arguments); }

  gtag('consent', 'default', Object.assign(consent('denied'), { wait_for_update: 500 }));
  // OWNER DECISION, off: uncomment to grant by default for US visitors (they can still reject in the banner).
  // gtag('consent', 'default', Object.assign(consent('granted'), { region: ['US'] }));
  gtag('set', 'ads_data_redaction', true);
  gtag('set', 'url_passthrough', true);
  if (saved() === 'granted') gtag('consent', 'update', consent('granted'));

  // ?r=<slug>, ?h=<handle>, ?name=<name> stop here, also what replaceState adds later. page_title covers some hits only:
  // gtag.js copies document.title itself into conversion hits (`tiba`), so no page may put a handle or name in its title.
  function pageLocation() {
    const q = new URLSearchParams(location.search), keep = new URLSearchParams();
    AD_CLICK.forEach(function (k) { if (q.has(k)) keep.set(k, q.get(k)); });
    const s = keep.toString();
    return location.origin + location.pathname + (s ? '?' + s : '');
  }
  function pageReferrer() {
    try {
      const r = new URL(document.referrer);
      return r.origin === location.origin ? r.origin + r.pathname : r.origin + '/';
    } catch (e) { return ''; }
  }
  const PAGE = { page_location: pageLocation(), page_referrer: pageReferrer(), page_title: 'Abolita' };
  gtag('set', PAGE);
  gtag('js', new Date());
  gtag('config', ADS_ID, Object.assign({ send_page_view: false, allow_enhanced_conversions: false }, PAGE));

  const tag = document.createElement('script');
  tag.async = true;
  tag.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(ADS_ID);
  document.head.appendChild(tag);

  function conversion(label) {
    if (label) gtag('event', 'conversion', { send_to: ADS_ID + '/' + label });
  }
  document.addEventListener('leakscan:result', function () { conversion(LABEL_SCAN); });

  let contacted = false;
  document.addEventListener('click', function (e) {
    const settings = e.target.closest('[data-cookie-settings]');
    if (settings) { e.preventDefault(); show(); return; }
    const a = e.target.closest('a[href]');
    if (a && !contacted && CONTACT.test(a.href)) { contacted = true; conversion(LABEL_CONTACT); }
  }, true);   // capture: a link's own handler can't hide it

  // ---------- banner ----------
  const CSS = '.cc-banner{position:fixed;left:12px;right:12px;bottom:max(12px,env(safe-area-inset-bottom));z-index:1100;'
    + 'box-sizing:border-box;max-width:760px;margin:0 auto;padding:16px 18px;display:flex;flex-wrap:wrap;align-items:center;gap:12px 18px;'
    + 'background:var(--surface,#fff);color:var(--ink,#1f1a15);border:1px solid var(--line,#e6ddd0);border-radius:var(--radius-sm,12px);'
    + 'box-shadow:0 10px 34px rgb(0 0 0/.28);font-size:.95rem;line-height:1.45}'
    + '.cc-banner p{flex:1 1 300px;margin:0}'
    + '.cc-banner a{color:inherit;text-decoration:underline}'
    + '.cc-btns{flex:1 1 220px;display:flex;gap:10px}'
    + '.cc-btns button{flex:1 1 0;min-height:44px;padding:.5em 1em;border:1.5px solid var(--ink,#1f1a15);border-radius:999px;'
    + 'background:transparent;color:inherit;font:inherit;font-weight:600;cursor:pointer}'
    + '.cc-btns button:hover{background:var(--surface-2,#f3ece2)}'
    + '.cc-btns button:focus-visible,.cc-banner a:focus-visible{outline:3px solid var(--accent,#a8431c);outline-offset:2px}';
  let banner = null, back = null, styled = false;

  function button(text, choice) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = text;
    b.addEventListener('click', function () { choose(choice); });
    return b;
  }

  function show() {
    if (banner) return;
    if (!styled) {
      styled = true;
      const st = document.createElement('style');
      st.textContent = CSS;
      document.head.appendChild(st);
    }
    back = saved() && document.activeElement;   // reopened from a link: focus goes in, and back afterwards
    banner = document.createElement('div');
    banner.className = 'cc-banner';
    banner.setAttribute('role', 'dialog');
    banner.setAttribute('aria-label', 'Cookie choice');
    banner.tabIndex = -1;
    const p = document.createElement('p');
    const link = document.createElement('a');
    link.href = new URL('../privacy.html#cookies', SELF).href;
    link.textContent = 'Privacy policy';
    p.append('Accept lets Google Ads set cookies, so I can see which ads lead to a finished scan or a message. Reject sets no cookies; Google then only gets a cookieless count. Your handle, name and report link are never in it. ', link);
    const btns = document.createElement('div');
    btns.className = 'cc-btns';
    btns.append(button('Accept', 'granted'), button('Reject', 'denied'));
    banner.append(p, btns);
    document.body.appendChild(banner);
    if (back) banner.focus({ preventScroll: true });
  }

  function dropAdStorage() {   // withdrawing consent: what Accept left behind goes too
    const host = location.hostname.split('.');
    document.cookie.split('; ').forEach(function (c) {
      const name = c.split('=')[0];
      if (!/^_(gcl|gac)/.test(name)) return;
      document.cookie = name + '=; Max-Age=0; path=/';
      for (let i = 0; i < host.length; i++) document.cookie = name + '=; Max-Age=0; path=/; domain=' + host.slice(i).join('.');
    });
    try { Object.keys(localStorage).forEach(function (k) { if (k.indexOf('_gcl') === 0) localStorage.removeItem(k); }); } catch (e) { /* storage blocked */ }
  }

  function choose(choice) {
    gtag('consent', 'update', consent(choice));
    try { localStorage.setItem(KEY, choice); } catch (e) { /* storage blocked: asked again next page */ }
    if (choice === 'denied') dropAdStorage();
    banner.remove();
    banner = null;
    if (back && back.focus) back.focus({ preventScroll: true });
  }

  document.querySelectorAll('[data-cookie-settings]').forEach(function (el) { el.hidden = false; });
  if (!saved()) show();
})();
