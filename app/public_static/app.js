"use strict";

// ---- config injected by the server ----------------------------------------
const CONFIG = (() => {
  try { return JSON.parse(document.getElementById("app-config").textContent); }
  catch (e) { return { dm: {}, verifiedDomains: 0, kb: false }; }
})();

const $ = (id) => document.getElementById(id);
const MODE = document.body.dataset.mode; // "home" | "share"
// Display multipliers/caps for the FAST report + poster (server-tuned via env:
// DISPLAY_PER_DOMAIN_MULT / DISPLAY_TOTAL_MULT / STATS_TOP_DOMAINS / TOP_LEAK_URL_MAX_LEN).
const DISPLAY = (() => {
  const d = (CONFIG && CONFIG.display) || {};
  return {
    perDomainMult: Number(d.perDomainMult) > 0 ? Number(d.perDomainMult) : 1,
    totalMult: Number(d.totalMult) > 0 ? Number(d.totalMult) : 1,
    topDomains: Number(d.topDomains) > 0 ? Number(d.topDomains) : 8,
    urlMaxLen: Number(d.urlMaxLen) > 0 ? Number(d.urlMaxLen) : 80,
  };
})();
let currentScan = null;      // last scan/report payload
let scanAbort = null;        // AbortController for an in-flight scan
let selectedLevel = "low";   // "low" (Quick/CSE) | "deep" (slug scrape)
let scanningHandle = "";     // handle of the in-flight scan (for progress chat)
let lastProgress = "";       // latest progress line (for progress chat context)
let lastPhase = "";          // deep-scan pipeline stage id from the server (for stage line + chat)
let foundSites = [];         // domain names discovered mid-scan (for progress chat + live tally)
let foundRows = [];          // {domain, occurrences} discovered mid-scan (for the partial fallback)
let liveSlug = null;         // slug of the in-progress deep scan — so "Copy link" works mid-run

// Deep-scan stages, in run order (ids come from the server's `phase` field). The site
// check is only stage 1 — showing the later stages is what keeps the progress page (and
// the waiting-room chat) honest once the N/M counter maxes out and goes quiet.
const DEEP_STAGES = {
  scan:    "checking every known leak site for your handle & name variations",
  seed:    "collecting the profile pages to crawl on the sites that hit",
  crawl:   "deep-crawling every found site — collecting each leaked page & media file (longest stage; the counter above doesn't move here)",
  clean:   "verifying & cleaning every collected URL",
  triage:  "sorting the verified results",
  export:  "building your confirmed-leaks list & removal quote",
  cse:     "checking where the leaks also show up on Google",
  gallery: "building your preview gallery",
};
const DEEP_STAGE_ORDER = ["scan", "seed", "crawl", "clean", "triage", "export", "cse", "gallery"];
function stageLabel(phase) {
  const i = DEEP_STAGE_ORDER.indexOf(phase);
  if (i < 0) return "";
  return "Stage " + (i + 1) + " of " + DEEP_STAGE_ORDER.length + " — " + DEEP_STAGES[phase];
}

let activePanel = null;   // which panel is showing — so re-showing the same one doesn't yank scroll
function showPanel(name) {
  const changed = name !== activePanel;
  activePanel = name;
  document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
  const el = $("panel-" + name);
  if (el) el.classList.add("active");
  // The header "Unblur" toggle only makes sense on a report — show it there, and reset the
  // page to blurred whenever a fresh report FIRST opens (not on every live-poll re-render).
  const gu = $("global-unblur");
  if (gu) {
    gu.style.display = (name === "results") ? "" : "none";
    if (name === "results" && changed) { document.body.classList.remove("unblurred"); gu.textContent = "🔞 Unblur"; }
  }
  // Only jump to the top when the panel actually CHANGES. During a live deep scan renderLive
  // re-calls showPanel("results") every 1.5 s — re-scrolling there would fight the user, who
  // wants to scroll down and watch the report build. So mid-run scroll position is preserved.
  if (changed) window.scrollTo({ top: 0, behavior: "smooth" });
}

// Header "Unblur" — one tap reveals every blurred image on the report (preview + Google
// grids); tap again to re-blur. Individual tiles can still be tapped one at a time.
function wireGlobalUnblur() {
  const btn = $("global-unblur");
  if (!btn) return;
  btn.onclick = () => {
    const on = document.body.classList.toggle("unblurred");
    btn.textContent = on ? "🙈 Blur" : "🔞 Unblur";
  };
}
function fmtNum(n) {
  const v = Number(n);
  if (!isFinite(v)) return String(n);
  return v.toLocaleString("en-US");
}
function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function showError(msg) {
  const m = $("error-msg");
  if (m) m.textContent = msg;
  showPanel("error");
}

// ---- SSE over fetch (POST-capable, unlike EventSource) ----------------------
async function consumeSSE(resp, onEvent) {
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      onEvent(parseEvent(raw));
    }
  }
}
function parseEvent(raw) {
  let event = "message";
  const data = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  return { event, data: data.join("\n") };
}

// ---- scan flow (home) ------------------------------------------------------
let deepPoll = null;   // setTimeout handle for the deep-scan poll loop

async function runScan(platform, handle, level, aliases, plus) {
  stopDeepPoll();
  scanningHandle = handle;
  lastProgress = "";
  lastPhase = "";
  foundSites = [];
  foundRows = [];
  selectedLevel = level;
  $("progress-handle").textContent = "@" + handle;
  $("progress-log").textContent = "";
  const fl = $("found-live"); if (fl) fl.textContent = "";
  const st = $("progress-stage"); if (st) { st.style.display = "none"; st.textContent = ""; }
  renderSlugs([]);
  if (progressChat) progressChat.reset("Your scan is running — ask me anything while you wait.");
  showPanel("progress");
  if (level === "deep") return startDeepScan(platform, handle, aliases, plus);
  return runScanSSE(platform, handle, level, aliases);
}

// Quick scans are a couple of API calls -> stream over SSE (dies with the tab,
// but it's seconds long so that's fine).
async function runScanSSE(platform, handle, level, aliases) {
  scanAbort = new AbortController();
  let resp;
  try {
    resp = await fetch("/api/public-scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ platform, handle, level, aliases: aliases || "" }),
      signal: scanAbort.signal,
    });
  } catch (e) {
    if (e.name === "AbortError") return;
    return showError("Network error — please check your connection and try again.");
  }
  if (resp.status === 429) return showError("Too many scans from your connection. Please wait a minute, then try again.");
  if (!resp.ok || !resp.body) return showError("The scanner is temporarily unavailable. Please try again shortly.");

  try {
    await consumeSSE(resp, (ev) => {
      if (ev.event === "progress") appendProgress(ev.data);
      else if (ev.event === "result") renderResults(JSON.parse(ev.data));
      else if (ev.event === "failed") showError(ev.data || "The scan failed. Please try again.");
    });
  } catch (e) {
    if (e.name === "AbortError") return;
    if (currentScan) return;                        // full result already rendered
    if (foundRows.length) return renderPartial();   // salvage the sites we streamed
    showError("The connection was interrupted before the scan finished. Please try again.");
  }
}

// Deep scans run detached on the server; we get a slug back immediately, keep it
// in the URL hash (so a reload / shared link resumes it), and poll for progress.
async function startDeepScan(platform, handle, aliases, plus) {
  let data;
  try {
    const resp = await fetch("/api/public-scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ platform, handle, level: "deep", aliases: aliases || "", plus: !!plus }),
    });
    if (resp.status === 429) return showError("The deep scanner is busy right now. Please wait a minute and try again.");
    data = await resp.json();
  } catch (e) {
    return showError("The scanner is temporarily unavailable. Please try again shortly.");
  }
  if (!data || !data.slug) {
    return showError(data && data.error === "bad_handle"
      ? "Enter a valid handle (letters, digits, . _ - only)."
      : "The scanner is temporarily unavailable. Please try again shortly.");
  }
  setResumeHash(data.slug);
  pollDeep(data.slug);
}

function pollDeep(slug) {
  stopDeepPoll();
  const tick = async () => {
    let data;
    try {
      const r = await fetch("/api/scan-result/" + encodeURIComponent(slug));
      if (r.status === 429) { deepPoll = setTimeout(tick, 3000); return; }
      if (r.status === 404) { clearResumeHash(); return showError("That scan link has expired. Please run a new scan."); }
      data = await r.json();
    } catch (e) {
      deepPoll = setTimeout(tick, 2500);   // transient blip — keep trying
      return;
    }
    if (data.status === "running") {
      applyDeepProgress(data);
      if (data.live) renderLive(data.live, data);   // live-building report (deep scans)
      deepPoll = setTimeout(tick, 1500);
    } else if (data.status === "failed") {
      clearResumeHash();
      if (foundRows.length) return renderPartial();
      showError("The scan couldn't be completed. Please try again.");
    } else {
      clearResumeHash();
      renderResults(data);
    }
  };
  tick();
}

function stopDeepPoll() { if (deepPoll) { clearTimeout(deepPoll); deepPoll = null; } }

// Show the exact handle variations (slugs) being checked against every site.
function renderSlugs(slugs) {
  const box = $("slugs-box");
  if (!box) return;
  if (!slugs || !slugs.length) { box.style.display = "none"; return; }
  box.style.display = "";
  const cnt = $("slugs-count"); if (cnt) cnt.textContent = slugs.length;
  const list = $("slugs-list");
  if (list && list.childElementCount !== slugs.length) {
    list.innerHTML = slugs.map((s) => '<span class="slug-chip">' + escapeHtml(s) + "</span>").join("");
  }
}

function applyDeepProgress(data) {
  if (data.handle && !scanningHandle) {
    scanningHandle = data.handle;
    const ph = $("progress-handle"); if (ph) ph.textContent = "@" + data.handle;
  }
  renderSlugs(data.slugs || []);
  const found = data.found || [];
  foundRows = found.map((f) => ({ domain: f.domain, occurrences: f.occurrences || 0, live: true }));
  foundSites = found.map((f) => f.domain);
  if (data.count) lastProgress = data.count;
  if (data.phase) lastPhase = data.phase;
  const st = $("progress-stage");
  if (st) {
    const label = stageLabel(lastPhase);
    st.style.display = label ? "" : "none";
    if (label) st.textContent = "⏳ " + label;
  }
  const fl = $("found-live");
  if (fl && foundSites.length) {
    fl.textContent = "✓ " + foundSites.length + " site" +
      (foundSites.length === 1 ? "" : "s") + " found so far: " + foundSites.slice(0, 20).join(", ");
  }
  const log = $("progress-log");
  if (log) {
    log.textContent = (data.count ? "Checked " + data.count + "\n" : "") +
      found.map((f) => "FOUND " + f.domain + " (" + (f.occurrences || 0) + " matches)").join("\n");
    log.scrollTop = log.scrollHeight;
  }
}

// Resume a background deep scan after a reload or via a shared in-progress link.
function resumeDeep(slug) {
  stopDeepPoll();
  scanningHandle = "";
  lastProgress = "";
  lastPhase = "";
  foundSites = [];
  foundRows = [];
  selectedLevel = "deep";
  const ph = $("progress-handle"); if (ph) ph.textContent = "";
  const log = $("progress-log"); if (log) log.textContent = "Reconnecting to your scan…";
  const fl = $("found-live"); if (fl) fl.textContent = "";
  const st = $("progress-stage"); if (st) { st.style.display = "none"; st.textContent = ""; }
  renderSlugs([]);
  if (progressChat) progressChat.reset("Reconnecting to your scan — ask me anything while you wait.");
  showPanel("progress");
  pollDeep(slug);
}

function slugFromHash() { const m = (location.hash || "").match(/^#s=([\w-]+)/); return m ? m[1] : null; }
// The slug for the report currently on screen — a finished scan, or (mid-run) the live deep scan.
function currentReportSlug() {
  return (currentScan && currentScan.slug) || liveSlug || slugFromHash() || null;
}
function setResumeHash(slug) { try { history.replaceState(null, "", "#s=" + slug); } catch (e) {} }
function clearResumeHash() {
  try { history.replaceState(null, "", location.pathname + location.search); } catch (e) {}
}

// If a long scan's connection drops mid-way, show what already streamed in.
function renderPartial() {
  currentScan = null;
  const rows = foundRows.slice();
  const head = $("results-head");
  head.className = "results-head report-hero found";
  head.innerHTML =
    '<div class="big">Partial results</div>' +
    '<p class="muted">The connection dropped before the scan finished, but we already found copies on <strong>' +
    rows.length + "</strong> site" + (rows.length === 1 ? "" : "s") + ' for <strong>@' +
    escapeHtml(scanningHandle) + "</strong>. Run the scan again for the full, shareable report.</p>";
  ["report-chips", "report-stats", "report-bars", "report-covers"].forEach((id) => {
    const e = $(id); if (e) e.style.display = "none";
  });
  const cnt = $("report-links-count");
  if (cnt) cnt.textContent = "— " + rows.length + " site" + (rows.length === 1 ? "" : "s");
  $("results-list").innerHTML = rows.map((r) =>
    '<details class="lg"><summary>' + escapeHtml(r.domain) +
    ' <span class="mut">· ' + fmtNum(r.occurrences || 0) + " matches</span></summary></details>"
  ).join("");
  reportLinks = [];
  const wrap = $("report-links"); if (wrap) wrap.style.display = "";
  renderImages([]);
  const dc = $("deep-cta"); if (dc) dc.style.display = "none";
  const dm = $("deep-more"); if (dm) dm.style.display = "none";
  const vc = $("verify-card"); if (vc) vc.style.display = "none";
  if (resultsChat) resultsChat.reset("The scan didn't finish, but I can help with what we found so far — or you can run it again.");
  showPanel("results");
}

function appendProgress(line) {
  lastProgress = line;
  const m = line.match(/FOUND\s+(\S+)\s+\((\d+)/);
  if (m && foundSites.indexOf(m[1]) === -1) {
    foundSites.push(m[1]);
    foundRows.push({ domain: m[1], occurrences: Number(m[2]) || 0, live: true });
    const fl = $("found-live");
    if (fl) fl.textContent = "✓ " + foundSites.length + " site" +
      (foundSites.length === 1 ? "" : "s") + " found so far: " + foundSites.slice(0, 20).join(", ");
  }
  const log = $("progress-log");
  log.textContent += line + "\n";
  log.scrollTop = log.scrollHeight;
}

// ---- report rendering (shared by scan result + share view) -----------------
let reportLinks = [];   // every hit URL, for Download / Copy-all

// Quick (low) scan quote: €250 base + €30/site, capped at €2,500 (rounded to €10).
function computeQuote(sites) {
  return Math.min(2500, Math.round((250 + 30 * sites) / 10) * 10);
}

// Deep-scan quote — IDENTICAL to make_report.price_for (and the server's price_for):
// scaled to the confirmed-leak count, 150→€250 … 20000→€2,500, rounded to €10. The
// deep report prefers the server-computed res.quote; this is the client-side fallback.
function priceForLeaks(n) {
  n = Number(n) || 0;
  if (n <= 150) return 250;
  if (n >= 20000) return 2500;
  return Math.round((250 + (n - 150) * (2500 - 250) / (20000 - 150)) / 10) * 10;
}

function hostOf(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); }
  catch (e) { return String(url || "").replace(/^https?:\/\/(www\.)?/, "").split("/")[0]; }
}

// A hit is a search-echo false positive (drop it) when it was tagged as such
// server-side. Everything else — profile/tag/google/search-verified, or any
// older row with no evidence tag — is a real hosting site.
function isRealHit(h) { return !h || h.evidence !== "search-echo"; }

function renderResults(res) {
  const hits = (res.hits || []).filter(isRealHit);
  res = Object.assign({}, res, { hits: hits });
  currentScan = res;
  liveSlug = null;                                       // the scan is done — currentScan owns the slug now
  const lc = $("live-console"); if (lc) lc.style.display = "none";   // live-only console: hide on the final report
  const isLow = res.level === "low";
  const sites = new Set(hits.map((h) => h.domain)).size;
  const matches = hits.reduce((a, h) => a + (Number(h.occurrences) || 0), 0);
  const chips = (res.slugs && res.slugs.length)
    ? res.slugs
    : Array.from(new Set(hits.map((h) => h.alias).filter(Boolean)));

  const disc = $("report-disclaimer");
  const gAlso = $("report-googlealso");
  const audit = $("report-audit"); if (audit) audit.style.display = "none";  // deep-only; shown below

  if (hits.length === 0) {
    renderEmpty(res);
    if (disc) disc.style.display = "none";
    if (gAlso) { gAlso.style.display = "none"; gAlso.innerHTML = ""; }
    const gs = $("report-gshot"); if (gs) { gs.style.display = "none"; gs.innerHTML = ""; }
  } else if (isLow) {
    // FAST (quick) report — site-count stats, top-links list, one synthetic "Google
    // results" screenshot from the CSE data (no per-domain dropdowns). Display counts
    // are multiplied for impact (DISPLAY.*): per-domain occurrences ×perDomainMult and
    // the "indexed pages" total ×totalMult. Uniform scaling keeps the sort order.
    const P = DISPLAY.perDomainMult, T = DISPLAY.totalMult;
    const dispHits = P !== 1
      ? hits.map((h) => Object.assign({}, h, { occurrences: (Number(h.occurrences) || 0) * P }))
      : hits;
    const dispMatches = Math.round(matches * T);
    renderHero(res, sites, dispMatches, isLow);
    renderChips(chips);
    renderStats(res, sites, dispMatches, computeQuote(sites), isLow);
    renderBars(dispHits);
    renderTopLinks(dispHits);
    renderCovers(res);
    if (disc) disc.style.display = "none";
    if (gAlso) { gAlso.style.display = "none"; gAlso.innerHTML = ""; }
    if (renderFastShot(res)) renderImages([]);
    else { const gs = $("report-gshot"); if (gs) { gs.style.display = "none"; gs.innerHTML = ""; } renderImages(res.images || []); }
  } else {
    // DEEP report — full parity with make_report.py: confirmed-leak stats + make_report
    // price, the curated (handle-verified) preview gallery, several reconstructed Google
    // grids + url/text results, the "Also all over Google" breakdown, and every leak link.
    renderHeroDeep(res);
    renderChips(chips);
    renderStatsDeep(res);
    renderGalleryPreview(res);
    renderGoogleDeep(res);
    renderBars(barsFromLinks(res), "Top sites by confirmed leak URLs — log scale.");
    renderAllLinksDeep(res);
    renderAuditDownloads(res);
    renderCovers(res);
    if (disc) disc.style.display = "";
  }
  renderFoot(res);

  const showDeep = isLow && hits.length;   // "run a deep scan" upsell — only on a quick result
  const deepCta = $("deep-cta");
  if (deepCta) deepCta.style.display = showDeep ? "" : "none";
  const deepCtaTop = $("deep-cta-top");
  if (deepCtaTop) deepCtaTop.style.display = showDeep ? "" : "none";
  const deepMore = $("deep-more");
  if (deepMore) deepMore.style.display = (res.level === "deep") ? "" : "none";
  // "Save shareable image" poster — on BOTH the fast and deep report (any hits).
  const canShare = hits.length > 0;
  const posterBtn = $("poster-save");
  if (posterBtn) {
    posterBtn.style.display = canShare ? "" : "none";
    posterBtn.onclick = canShare ? () => savePoster(res) : null;
  }
  if (canShare) maybeAutoSavePoster(res);   // auto-download the poster on any fresh scan (fast OR deep)
  wireShareDM();                            // "DM me" button in the share row (always live)
  const sh = $("share-hint"); if (sh) sh.textContent = "";
  wireVerify(res);
  wireCTA();
  const greet = hits.length
    ? "I can explain what we found and walk you through getting it removed. Ask me anything."
    : "No public leaks turned up this time. Ask me anything about staying protected or filing takedowns.";
  if (resultsChat) resultsChat.reset(greet);
  // Top "ask about your report" pill — bare (no greeting bubble, no question chips), just the
  // slick ask input; answers appear inline when the visitor asks. Shown whenever there's a report.
  const topchat = $("report-topchat");
  if (topchat) topchat.style.display = canShare ? "" : "none";
  if (topResultsChat) topResultsChat.reset();
  showPanel("results");
}

// ============================ LIVE (building) deep report ====================
// Paints the report AS IT BUILDS during a running deep scan. Honesty contract (see report_live.py
// + _live_report in public_app.py): the "Candidates found" tile is a MONOTONE ticker of media
// detected so far — it only ever grows; the "Confirmed leaks" + "Takedown quote" tiles stay
// SKELETONS until the export step completes and the server sends authoritative numbers, so a
// number is never shown and then lowered. Sections re-render only when their data changes (no
// per-tick flashing); the stat numbers update in place with a brief pulse.
let _liveSigs = {};

function _liveScaffold(handle) {
  const head = $("results-head");
  if (head) {
    head.className = "results-head report-hero live";
    head.innerHTML =
      '<div class="badge live"><span class="live-dot"></span> Live scan in progress' +
      (handle ? " · @" + escapeHtml(handle) : "") + "</div>" +
      '<h1>Finding your <span class="hl">leaked</span> content…</h1>' +
      '<p class="sub">Found <b id="live-hero-cand">0</b> candidate files across ' +
      '<b id="live-hero-sites">0</b> sites so far — confirming which are yours. ' +
      '<span id="live-hero-stage" class="live-stage"></span></p>' +
      '<div class="live-progress"><div class="live-progress-bar"><i id="live-progress-fill"></i></div>' +
      '<span id="live-progress-pct" class="live-progress-pct">Stage 1 of ' + DEEP_STAGE_ORDER.length + '</span></div>';
  }
  const stats = $("report-stats");
  if (stats) {
    stats.innerHTML =
      '<div class="stat"><div class="k">Confirmed leaks</div>' +
        '<div class="v" id="live-stat-leaks"><span class="skel-pill">confirming…</span></div>' +
        '<div class="sub">verified once the scan finishes</div></div>' +
      '<div class="stat"><div class="k">Candidates found</div>' +
        '<div class="v" id="live-stat-cand">0</div>' +
        '<div class="sub">media detected so far</div></div>' +
      '<div class="stat"><div class="k">Sites</div>' +
        '<div class="v" id="live-stat-sites">0</div>' +
        '<div class="sub">where copies were detected</div></div>' +
      '<div class="stat q"><div class="k">Takedown quote</div>' +
        '<div class="v" id="live-stat-quote"><span class="skel-pill">pending</span></div>' +
        '<div class="sub">calculated at confirmation</div></div>';
  }
  _liveSigs = {};
}

function _liveSet(id, txt) {
  const el = document.getElementById(id);
  if (el && el.textContent !== txt) {
    el.textContent = txt;
    el.classList.remove("bump"); void el.offsetWidth; el.classList.add("bump");
  }
}

function renderLive(live, data) {
  if (!live) return;
  currentScan = null;
  if (data && data.slug) liveSlug = data.slug;   // so "Copy link to report" works mid-run
  // (Re)build the scaffold whenever it's absent — fresh scan, or after a final render replaced it.
  if (!document.getElementById("live-stat-cand")) _liveScaffold(live.handle || (data && data.handle));
  showPanel("results");

  const cand = Number(live.candidates) || 0;
  const sites = Number(live.sites_found) || 0;
  _liveSet("live-hero-cand", fmtNum(cand));
  _liveSet("live-hero-sites", fmtNum(sites));
  _liveSet("live-stat-cand", fmtNum(cand));
  _liveSet("live-stat-sites", fmtNum(sites));
  const stageEl = document.getElementById("live-hero-stage");
  if (stageEl) { const lbl = stageLabel(live.phase); stageEl.textContent = lbl ? "· " + lbl : ""; }

  // Progress bar — how far through the 8 pipeline stages we are.
  const si = DEEP_STAGE_ORDER.indexOf(live.phase);
  if (si >= 0) {
    const pct = Math.round(((si + 1) / DEEP_STAGE_ORDER.length) * 100);
    const fill = $("live-progress-fill"); if (fill) fill.style.width = pct + "%";
    _liveSet("live-progress-pct", "Stage " + (si + 1) + " of " + DEEP_STAGE_ORDER.length);
  }

  // Preview grid. Prefer the early-CSE thumbnails (base64/gstatic — they actually render); fall
  // back to crawl candidate URLs only when CSE returned nothing (those may be hotlink-blocked).
  const hasCse = !!(live.google_total || (live.img_meta && live.img_meta.length) ||
                    (live.top_leaks && live.top_leaks.length) || (live.cse_sites && live.cse_sites.length));
  const imgs = live.images || [];
  const imgSig = imgs.length + ":" + (imgs[0] || "");
  if (imgSig !== _liveSigs.imgs) {
    _liveSigs.imgs = imgSig;
    renderImages(imgs);
    const mh = document.querySelector("#report-media .report-sechead h2");
    if (mh) mh.textContent = hasCse ? "Leaked images already showing up on Google" : "Candidate images found so far";
  }

  // Early Google evidence — reconstructed grids + "Also all over Google" (indexed sites + top
  // public results). From the phase-0 CSE pass, so it's on screen within seconds of opening.
  const cseSig = hasCse ? [live.google_total, (live.img_meta || []).length,
                           (live.top_leaks || []).length, (live.cse_sites || []).length].join(":") : "";
  if (cseSig !== _liveSigs.cse) {
    _liveSigs.cse = cseSig;
    if (hasCse) renderGoogleDeep(live);   // sets #report-gshot + #report-googlealso visible
    else { ["report-gshot", "report-googlealso"].forEach((id) => { const el = $(id); if (el) el.style.display = "none"; }); }
  }

  // Live command console at the bottom — the pipeline's own output as it runs.
  renderLiveConsole(data && data.log);

  // Authoritative reveal (never a shrink): confirmed leaks + quote, once export is done.
  if (live.authoritative && Number(live.n_leaks)) {
    const lk = document.getElementById("live-stat-leaks");
    if (lk && !lk.dataset.final) { lk.dataset.final = "1"; lk.innerHTML = '<span class="bump">' + fmtNum(Number(live.n_leaks)) + "</span>"; }
    const q = document.getElementById("live-stat-quote");
    if (q && !q.dataset.final && Number(live.quote)) { q.dataset.final = "1"; q.innerHTML = '<span class="bump">€' + fmtNum(Number(live.quote)) + "</span>"; }
  }

  // Bars + links: re-render only when their data actually changed (no per-tick flashing).
  const hits = live.hits || [];
  const barsSig = hits.map((h) => h.domain + ":" + h.occurrences).join("|");
  if (barsSig !== _liveSigs.bars) { _liveSigs.bars = barsSig; renderBars(hits); }

  const byDom = live.links_by_domain || {};
  const domCount = Object.keys(byDom).length;
  const linkSig = Object.keys(byDom).sort().map((d) => d + ":" + byDom[d].length).join("|");
  if (linkSig !== _liveSigs.links) {
    _liveSigs.links = linkSig;
    const wrap = $("report-links");
    if (domCount) {
      renderAllLinksDeep({ links_by_domain: byDom, hits: hits, handle: live.handle });
      if (wrap) wrap.style.display = "";
      const h2 = document.querySelector("#report-links .report-sechead h2");
      if (h2 && h2.firstChild && h2.firstChild.nodeType === 3) {
        h2.firstChild.nodeValue = live.authoritative ? "All detected leak links " : "Candidate leak links detected so far ";
      }
    } else if (wrap) { wrap.style.display = "none"; }
  }

  // Sections that only exist AFTER confirmation stay hidden during the live build.
  // (report-media + report-gshot + report-googlealso are driven above — candidate/CSE preview.)
  ["report-disclaimer", "report-covers",
   "report-audit", "deep-cta", "deep-cta-top", "deep-more", "verify-card", "report-topchat"].forEach((id) => {
    const el = $(id); if (el) el.style.display = "none";
  });
}

// The live command console (bottom of the building report). Feeds the pipeline's own stderr
// through, newest at the bottom, auto-scrolls to follow — but only if the user is already at
// the bottom, so scrolling up to read isn't yanked back down on the next 1.5 s poll.
function renderLiveConsole(lines) {
  const box = $("live-console");
  if (!box) return;
  const text = (lines && lines.length) ? lines.join("\n") : "";
  box.style.display = "";
  if (box.textContent === text) return;
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.textContent = text || "Starting the pipeline…";
  if (atBottom) box.scrollTop = box.scrollHeight;
}

// The share-row "DM me" button: point it at the first configured contact (IG / Telegram /
// WhatsApp) and reveal it. Always live — works the moment the report renders.
function wireShareDM() {
  const btn = $("share-dm");
  if (!btn) return;
  const dm = CONFIG.dm || {};
  let href = "";
  if (dm.instagram) href = igUrl(dm.instagram);
  else if (dm.telegram) href = tgUrl(dm.telegram);
  else if (dm.whatsapp) href = waUrl(dm.whatsapp);
  if (href) { btn.href = href; btn.style.display = ""; }
  else { btn.style.display = "none"; }
}

// ============================ DEEP-report renderers ==========================
// The deep report mirrors make_report.py's sections. Data comes from the server's
// pipeline bridge: n_leaks/n_media/n_hosting/n_sites/quote (export + crawl), gallery
// (build_gallery), img_meta/images/cse_sites/top_leaks/google_total (Google CSE).

function renderHeroDeep(res) {
  const head = $("results-head");
  const h = escapeHtml(res.handle || "");
  const sitesAff = Number(res.n_sites) || 0;
  const leaks = Number(res.n_leaks) || 0;
  const hosting = Number(res.n_hosting) || 0;
  const u = sitesAff === 1 ? "site" : "sites";
  head.className = "results-head report-hero found";
  head.innerHTML =
    '<div class="badge">Private report · prepared for you</div>' +
    '<h1>Your content was <span class="hl">leaked</span><br>across ' + fmtNum(sitesAff) + " " + u + "</h1>" +
    '<p class="sub">We found <b>' + fmtNum(leaks) + "</b> confirmed copies of @" + h +
    "’s content on <b>" + fmtNum(hosting) + "</b> piracy sites — and traced it across <b>" +
    fmtNum(sitesAff) + "</b> " + u + " in total once Google-indexed pages are included. " +
    "Here’s exactly where — and how we get them removed.</p>";
}

function renderStatsDeep(res) {
  const box = $("report-stats");
  if (!box) return;
  const leaks = Number(res.n_leaks) || 0;
  const media = Number(res.n_media) || 0;
  const hosting = Number(res.n_hosting) || 0;
  const sitesAff = Number(res.n_sites) || hosting;
  const quote = Number(res.quote) || priceForLeaks(leaks);
  const band = Math.max(2, Math.round(((quote - 250) / (2500 - 250)) * 100));
  box.innerHTML =
    '<div class="stat"><div class="k">Confirmed leaks</div><div class="v">' + fmtNum(leaks) +
      '</div><div class="s">unique URLs under your handle</div></div>' +
    '<div class="stat"><div class="k">Media items</div><div class="v">' + fmtNum(media) +
      '</div><div class="s">photos / videos identified as yours</div></div>' +
    '<div class="stat"><div class="k">Sites affected</div><div class="v">' + fmtNum(sitesAff) +
      '</div><div class="s">' + fmtNum(hosting) + " hosting · rest Google-indexed</div></div>" +
    '<div class="stat q"><div class="k">Takedown quote</div><div class="v">€' + fmtNum(quote) + "</div>" +
      '<div class="band"><small>€250</small><span class="t"><i style="width:' + band +
      '%"></i></span><small>€2,500</small></div></div>';
  box.style.display = "";
}

// "Your leaked content" preview — the vetted, handle-verified leak photos the server
// embedded as data: URIs. Falls back to the CSE thumbnails when no gallery was built
// (e.g. the stdlib-only VPS path). Blurred; per-tile hover + a whole-strip reveal.
function renderGalleryPreview(res) {
  const gallery = res.gallery || [];
  if (!gallery.length) { renderImages(res.images || []); return; }
  const box = $("results-images");
  const btn = $("reveal-btn");
  const media = $("report-media");
  if (!box) return;
  box.classList.remove("revealed");
  if (btn) btn.style.display = "none";      // no whole-strip button — tap a tile, or "Unblur" in the header
  if (media) media.style.display = "";
  box.style.display = "";
  box.innerHTML = gallery.map((g) => {
    const cap = g.domain
      ? '<figcaption class="cap-fig"><a class="cap-link" href="' + escapeHtml(g.link || ("https://" + g.domain)) +
        '" target="_blank" rel="noopener noreferrer nofollow" onclick="event.stopPropagation()">' +
        escapeHtml(g.domain) + " ↗</a></figcaption>"
      : "";
    return '<div class="img-cell port"><img src="' + escapeHtml(g.img) + '" alt="" loading="lazy">' +
      '<span class="lock">&#128274;</span>' + cap + "</div>";
  }).join("");
  wireTapReveal(box);
}

// Colored "Google" wordmark (span sequence — CSP-safe, no SVG/remote font).
const G_LOGO = '<span style="color:#4285F4">G</span><span style="color:#EA4335">o</span>' +
  '<span style="color:#FBBC05">o</span><span style="color:#4285F4">g</span>' +
  '<span style="color:#34A853">l</span><span style="color:#EA4335">e</span>';
const cap1 = (s) => { s = String(s || ""); return s ? s.charAt(0).toUpperCase() + s.slice(1) : ""; };

// One reconstructed dark-mode Google IMAGES masonry panel — built from the CURATED,
// handle-verified gallery photos (clean, deduped — NOT the junky CSE thumbnails that
// leak site logos / meme cards into the grid). Mirrors the old pipeline's
// build_google_shots.images_page_modern. Badged 🧪 illustrative.
function gMasonryPanel(query, tiles, total, handle) {
  const name = cap1(handle);
  const caps = [name + " Leaks", name + " Nudes", name + " OnlyFans", name + " Gallery Imgs", name + " Leaked", name + " Nude Pics"];
  const cells = tiles.map((t, i) => {
    const host = escapeHtml(t.host || "");
    return '<figure class="gm-cell"><div class="gm-thumb"><img src="' + escapeHtml(t.img) + '" alt="" loading="lazy">' +
      '<span class="lock">&#128274;</span></div>' +
      '<div class="gm-cap"><div class="gm-ct">' + escapeHtml(caps[i % caps.length]) + "</div>" +
      (host ? '<div class="gm-src"><span class="gm-fav"></span><span class="gm-sn">' + host + "</span></div>" : "") +
      "</div></figure>";
  }).join("");
  const tabs = ["AI Mode", "All", "Images", "Videos", "Short videos", "News", "Books"]
    .map((t) => '<span class="gm-tab' + (t === "Images" ? " on" : "") + '">' + t + "</span>").join("");
  return '<div class="gshot-panel"><div class="gm">' +
    '<div class="gm-top"><span class="gm-logo">' + G_LOGO + "</span>" +
      '<div class="gm-search"><span class="gm-q">' + escapeHtml(query) + '</span><span class="gm-mag">&#128269;</span></div></div>' +
    '<div class="gm-tabs">' + tabs + '<span class="gm-count">About ' + escapeHtml(total) + " results</span></div>" +
    '<div class="gm-ss"><span class="gm-ssl">SafeSearch</span><span class="gm-pill on">&#10003; Off</span>' +
      '<span class="gm-pill">Blur</span><span class="gm-pill">Filter</span></div>' +
    '<div class="gm-grid">' + cells + "</div>" +
    '</div><span class="gtag">🧪 illustrative</span></div>';
}

// One reconstructed dark-mode Google WEB-results panel (the "url texts") from the top
// public results / indexed sites / confirmed hits — the organic result rows.
function gWebPanel(query, rows, total) {
  const rr = rows.map((r) =>
    '<div class="gm-row"><div class="gm-rl"><span class="gm-rfav">' + escapeHtml((r.dom || "•").slice(0, 1).toUpperCase()) + "</span>" +
    '<div class="gm-rmeta"><div class="gm-rsite">' + escapeHtml(r.dom) + "</div>" +
    '<div class="gm-rurl">' + escapeHtml(r.dom + " › " + r.path) + "</div></div></div>" +
    '<a class="gm-h3" href="' + escapeHtml(r.url) + '" target="_blank" rel="noopener noreferrer nofollow">' + escapeHtml(r.title) + "</a>" +
    '<div class="gm-rsnip">' + escapeHtml(r.snip) + "</div></div>").join("");
  return '<div class="gshot-panel"><div class="gm">' +
    '<div class="gm-top"><span class="gm-logo">' + G_LOGO + "</span>" +
      '<div class="gm-search"><span class="gm-q">' + escapeHtml(query) + '</span><span class="gm-mag">&#128269;</span></div></div>' +
    '<div class="gm-tabs"><span class="gm-tab on">All</span><span class="gm-tab">Images</span><span class="gm-tab">Videos</span>' +
      '<span class="gm-tab">News</span><span class="gm-count">About ' + escapeHtml(total) + " results</span></div>" +
    '<div class="gm-webrows">' + rr + "</div>" +
    '</div><span class="gtag">🧪 illustrative</span></div>';
}

// Build a pool of Google organic-result rows from the top public results, the indexed
// sites, and the confirmed hits (deduped by URL).
function orgRows(res) {
  const handle = res.handle || "";
  const out = [], seen = new Set();
  const push = (url, dom, title, occ, snip) => {
    if (!url || seen.has(url)) return;
    seen.add(url);
    let path = "search";
    if (!/\/search\//i.test(url)) {
      try { path = (new URL(url).pathname || "/").slice(0, 40) || "/"; } catch (e) { path = "/"; }
    }
    out.push({ url: url, dom: dom, path: path, title: title,
      snip: (occ ? fmtNum(occ) + " items indexed · " : "") + snip });
  };
  (res.top_leaks || []).forEach((u) => {
    const d = hostOf(u);
    push(u, d, handle + " leaks — " + d, 0, "Explicit leaked content of @" + handle + " surfaced on " + d + " — view the full set …");
  });
  (res.cse_sites || []).forEach((s) => {
    push(s.url || ("https://" + s.domain), s.domain, handle + " leaked photos & videos — " + s.domain, s.occ,
      "Indexed page hosting @" + handle + "'s leaked content on " + s.domain + " …");
  });
  (res.hits || []).forEach((h) => {
    push(h.url, h.domain, h.title || (handle + " — " + h.domain), h.occurrences,
      "Leaked @" + handle + " content indexed on " + h.domain + " …");
  });
  return out;
}

// "Google search results" — several reconstructed IMAGE masonry grids (a different
// query + photo slice each, from the CLEAN curated gallery) plus WEB-results (url/text)
// panels — followed by "Also all over Google".
function renderGoogleDeep(res) {
  const box = $("report-gshot");
  const handle = res.handle || "";
  // Prefer the curated gallery photos (clean, deduped, handle-verified) for the grids;
  // fall back to CSE thumbnails only when no gallery was built (e.g. the stdlib VPS path).
  const galTiles = (res.gallery || []).filter((g) => g.img).map((g) => ({ img: g.img, host: g.domain || "" }));
  const cseTiles = ((res.img_meta && res.img_meta.length)
    ? res.img_meta.map((m) => ({ img: m.data, host: m.host }))
    : (res.images || []).map((u) => ({ img: u, host: "" }))
  ).filter((t) => t.img);
  const tiles = galTiles.length ? galTiles : cseTiles;
  const total = res.google_total ? fmtNum(res.google_total) : fmtNum((res.hits || []).length);
  const rows = orgRows(res);

  if (box) {
    if (!tiles.length && !rows.length) {
      box.style.display = "none"; box.innerHTML = "";
    } else {
      const variants = [handle + " nude", handle + " leaks", handle + " onlyfans", handle + " leaked",
        handle + " nudes", handle + " porn", handle + " sextape", handle + " video"];
      const per = 12, panels = [];
      const nGrids = tiles.length ? Math.min(variants.length, 6) : 0;
      for (let i = 0; i < nGrids; i++) {
        const off = tiles.length ? (i * 4) % tiles.length : 0;
        const slice = tiles.slice(off).concat(tiles.slice(0, off)).slice(0, per);
        panels.push(gMasonryPanel(variants[i], slice, total, handle));
      }
      if (rows.length) panels.push(gWebPanel(handle + " leaks", rows.slice(0, 7), total));
      if (rows.length > 7) panels.push(gWebPanel(handle + " onlyfans leaked", rows.slice(7, 14), total));
      box.innerHTML =
        '<div class="report-sechead"><h2>Google search results</h2>' +
        '<span class="pill warn">🔞 blurred · tap to reveal · drag to scroll</span>' +
        '<button class="ghost-btn" id="gshot-reveal-all" type="button">Reveal all</button></div>' +
        '<p class="report-lead">Reconstructed from Google’s live index (Custom Search) — how @' +
        escapeHtml(handle) + " surfaces across Google Images &amp; web results. Drag sideways to browse all " + panels.length + ".</p>" +
        '<div class="dragrow gshot-strip">' + panels.join("") + "</div>";
      const btn = $("gshot-reveal-all");
      if (btn) btn.onclick = () => {
        const on = box.classList.toggle("revealed");
        box.querySelectorAll(".gm, .gshot").forEach((g) => g.classList.toggle("revealed", on));
        btn.textContent = on ? "Blur all" : "Reveal all";
      };
      box.style.display = "";
    }
  }
  renderGoogleAlso(res);
}

function renderGoogleAlso(res) {
  const box = $("report-googlealso");
  if (!box) return;
  const sites = res.cse_sites || [];
  const top = res.top_leaks || [];
  if (!sites.length && !top.length) { box.style.display = "none"; box.innerHTML = ""; return; }
  const handle = escapeHtml(res.handle || "");
  const total = res.google_total ? "~" + fmtNum(res.google_total) : "";
  const lead = total
    ? "Google is indexing <b>" + total + " results</b> for your name across <b>" + sites.length +
      "+ sites</b> — the public pages anyone finds just by searching. We get them delisted from Google too."
    : "Public pages indexing your name across <b>" + sites.length + "+ sites</b>.";
  const siteRows = sites.map((s) =>
    '<div class="grow"><a class="gdom" href="' + escapeHtml(s.url || ("https://" + s.domain)) +
    '" target="_blank" rel="noopener noreferrer nofollow">' + escapeHtml(s.domain) + "</a>" +
    '<span class="gurls">' + fmtNum(s.occ || 1) + "+ URLs</span></div>").join("");
  const topItems = top.map((u) =>
    '<li><a href="' + escapeHtml(u) + '" target="_blank" rel="noopener noreferrer nofollow">' + escapeHtml(u) + "</a></li>").join("");
  box.innerHTML =
    '<div class="report-sechead"><h2>Also all over Google</h2>' +
    '<span class="pill warn">🔞 blurred · tap any image</span></div>' +
    '<p class="report-lead">' + lead + "</p>" +
    '<div class="report-two">' +
      '<div class="report-card"><h2>Sites indexing you on Google</h2><div class="glist gscroll">' +
        (siteRows || '<span class="mut">—</span>') + "</div></div>" +
      '<div class="report-card"><h2>Top public results</h2><ul class="gtop">' +
        (topItems || '<li class="mut">—</li>') + "</ul></div>" +
    "</div>";
  box.style.display = "";
}

// Every confirmed leak URL, grouped by site in expandable dropdowns (mirrors
// make_report's links_block). Falls back to the per-domain hit list if the server
// sent no link map. Populates reportLinks for the Download / Copy-all buttons.
function renderAllLinksDeep(res) {
  const wrap = $("report-links");
  const list = $("results-list");
  if (!wrap || !list) return;
  const byDom = res.links_by_domain || {};
  const domains = Object.keys(byDom);
  if (!domains.length) { renderLinks(res.hits || []); return; }
  list.className = "results-list linkgrid";
  list.onclick = null;
  domains.sort((a, b) => byDom[b].length - byDom[a].length);
  const all = [];
  domains.forEach((d) => byDom[d].forEach((u) => all.push(u)));
  reportLinks = all;
  const cnt = $("report-links-count");
  if (cnt) cnt.textContent = "— " + fmtNum(all.length) + " link" + (all.length === 1 ? "" : "s");
  // top 2 sites open by default so the section reads at a glance; the rest expand on click.
  list.innerHTML = domains.map((d, i) => {
    const urls = byDom[d];
    const items = urls.map((u) =>
      '<a href="' + escapeHtml(u) + '" target="_blank" rel="noopener noreferrer nofollow">' + escapeHtml(u) + "</a>").join("<br>");
    return '<details class="lg"' + (i < 2 ? " open" : "") + '><summary><span class="lgdom">' + escapeHtml(d) +
      '</span><span class="lgn">· ' + fmtNum(urls.length) + "</span></summary>" +
      '<div class="lk">' + items + "</div></details>";
  }).join("");
  wrap.style.display = "";
}

// Two download buttons to audit the whole triage: every accepted (confirmed) leak in one file,
// every removed (dropped) candidate in another — the removed list is often the big one (7k+),
// which is exactly what a human wants to eyeball to confirm nothing real was cut. Served as
// text/plain attachments by /api/scan-links so the multi-thousand-line lists never bloat the
// report payload.
function renderAuditDownloads(res) {
  const box = $("report-audit");
  if (!box) return;
  const slug = res && res.slug;
  const nAcc = Number(res && res.n_accepted) || 0;
  const nRem = Number(res && res.n_removed) || 0;
  if (!slug || (!nAcc && !nRem)) { box.style.display = "none"; return; }
  const acc = $("dl-accepted"), rem = $("dl-removed");
  if (acc) {
    acc.href = "/api/scan-links/" + encodeURIComponent(slug) + "?set=accepted";
    acc.textContent = "⬇ Accepted leaks (" + fmtNum(nAcc) + ")";
    acc.style.display = nAcc ? "" : "none";
  }
  if (rem) {
    rem.href = "/api/scan-links/" + encodeURIComponent(slug) + "?set=removed";
    rem.textContent = "⬇ Removed leaks (" + fmtNum(nRem) + ")";
    rem.style.display = nRem ? "" : "none";
  }
  box.style.display = "";
}

function renderEmpty(res) {
  const head = $("results-head");
  head.className = "results-head report-hero clear";
  head.innerHTML =
    '<div class="big">No public leaks found</div>' +
    '<p class="muted">We didn\'t find copies of <strong>@' + escapeHtml(res.handle) +
    "</strong> on the sites we checked. New leaks appear over time — rescan periodically.</p>";
  ["report-chips", "report-stats", "report-bars", "report-links", "report-covers",
   "report-gshot", "report-googlealso", "report-disclaimer", "report-media", "report-audit"].forEach((id) => {
    const e = $(id); if (e) e.style.display = "none";
  });
  reportLinks = [];
  const list = $("results-list");
  if (list) list.innerHTML = "";
}

// Synthetic "Google results" screenshot for the FAST (quick) report — a light,
// screenshot-style Google Images + organic-results panel built entirely in the
// browser from the CSE data the quick scan already returned (thumbnails + hit
// sites + result total). Zero capture cost; renders in the shared report too.
// Labeled "illustrative" (it re-renders real Google-index data, it's not a live
// capture) to stay honest, mirroring the deep report's synthetic-shots convention.
function renderFastShot(res) {
  const box = $("report-gshot");
  if (!box) return false;
  const imgs = (res.images || []).filter((u) => typeof u === "string");
  const hits = res.hits || [];
  if (!imgs.length && !hits.length) { box.style.display = "none"; box.innerHTML = ""; return false; }
  const handle = escapeHtml(res.handle || "");
  const domains = Array.from(new Set(hits.map((h) => h.domain).filter(Boolean)));
  const total = res.google_total ? fmtNum(res.google_total) : fmtNum(hits.length);

  const tiles = imgs.slice(0, 12).map((u, i) =>
    '<figure class="gshot-tile"><img src="' + escapeHtml(u) + '" alt="" loading="lazy" referrerpolicy="no-referrer">' +
    '<span class="lock">&#128274;</span>' +
    '<figcaption>' + escapeHtml(domains[i % Math.max(1, domains.length)] || "leaked") + '</figcaption></figure>'
  ).join("");

  const rows = hits.slice(0, 4).map((h) => {
    const dom = escapeHtml(h.domain || "");
    const path = (h.method === "google" || h.evidence === "search-verified") ? "search" : "models/" + res.handle;
    const url = escapeHtml(h.url || ("https://" + (h.domain || "")));
    const title = escapeHtml(h.title || ("@" + res.handle + " leaked photos & videos — " + (h.domain || "")));
    const items = h.occurrences ? (fmtNum(h.occurrences) + " items indexed · ") : "";
    return '<div class="g-row">' +
      '<div class="g-url"><span class="g-fav">' + (dom.slice(0, 1).toUpperCase() || "•") + "</span>" +
      "<span>" + dom + " &rsaquo; " + escapeHtml(path) + "</span></div>" +
      '<a class="g-title" href="' + url + '" target="_blank" rel="noopener noreferrer nofollow">' + title + "</a>" +
      '<div class="g-snip">' + items + "Explicit leaked content of @" + handle +
      " surfaced on " + dom + " — view the full set …</div></div>";
  }).join("");

  box.innerHTML =
    '<div class="gshot-head"><h2>What the web is showing</h2>' +
      '<span class="pill warn">🔞 blurred</span>' +
      '<span class="pill">illustrative</span>' +
      '<button class="ghost-btn" id="gshot-reveal" type="button">Reveal</button></div>' +
    '<div class="gshot">' +
      '<div class="gshot-bar"><span class="g-logo">Google</span>' +
        '<div class="g-box"><span>' + handle + ' leaks</span><span class="g-mag">&#128269;</span></div></div>' +
      '<div class="gshot-tabs"><span class="on">All</span><span>Images</span><span>Videos</span><span>News</span>' +
        '<span class="g-count">About ' + total + ' results</span></div>' +
      (tiles ? '<div class="gshot-imgs">' + tiles + "</div>" : "") +
      (rows ? '<div class="gshot-rows">' + rows + "</div>" : "") +
    "</div>" +
    '<div class="reveal-row"><span class="gshot-note">Illustrative — rendered from live Google results for @' +
      handle + ". Hover any tile to peek.</span></div>";

  const g = box.querySelector(".gshot");
  const btn = $("gshot-reveal");
  if (btn && g) btn.onclick = () => { const on = g.classList.toggle("revealed"); btn.textContent = on ? "Blur" : "Reveal"; };
  box.style.display = "";
  return true;
}

function renderHero(res, sites, matches, isLow) {
  const head = $("results-head");
  const h = escapeHtml(res.handle || "");
  const unit = sites === 1 ? "site" : "sites";
  const noun = isLow
    ? ("indexed page" + (matches === 1 ? "" : "s"))
    : ("confirmed match" + (matches === 1 ? "" : "es"));
  head.className = "results-head report-hero found";
  head.innerHTML =
    '<div class="badge">Private report · prepared for you</div>' +
    '<h1>Your content was <span class="hl">leaked</span><br>across ' + sites + " " + unit + "</h1>" +
    '<p class="sub">We found <b>' + fmtNum(matches) + "</b> " + noun +
    " for <b>@" + h + "</b> across <b>" + sites + "</b> " + unit +
    ". Here's exactly where — and how we get them removed.</p>";
}

function renderChips(chips) {
  const box = $("report-chips");
  if (!box) return;
  if (!chips || !chips.length) { box.style.display = "none"; box.innerHTML = ""; return; }
  box.style.display = "";
  box.innerHTML = chips.slice(0, 24).map((c) => '<span class="chip2">' + escapeHtml(c) + "</span>").join("");
}

function renderStats(res, sites, matches, quote, isLow) {
  const box = $("report-stats");
  if (!box) return;
  const cards = [];
  cards.push('<div class="stat"><div class="k">Sites hosting</div><div class="v">' + fmtNum(sites) +
    '</div><div class="s">confirmed leak sites</div></div>');
  cards.push('<div class="stat"><div class="k">' + (isLow ? "Indexed pages" : "Matches found") +
    '</div><div class="v">' + fmtNum(matches) + '</div><div class="s">' +
    (isLow ? "pages under this handle" : "on-page matches for your handle") + "</div></div>");
  if (res.google_total && Number(res.google_total) > 0) {
    cards.push('<div class="stat"><div class="k">Google index</div><div class="v">' + fmtNum(res.google_total) +
      '</div><div class="s">results across the web</div></div>');
  }
  const band = Math.max(2, Math.round(((quote - 250) / (2500 - 250)) * 100));
  cards.push('<div class="stat q"><div class="k">Takedown quote</div><div class="v">€' + fmtNum(quote) + "</div>" +
    '<div class="band"><small>€250</small><span class="t"><i style="width:' + band + '%"></i></span><small>€2,500</small></div></div>');
  box.innerHTML = cards.join("");
  box.style.display = "";
}

// Bar chart of the top hosts. LOG scale: one host (leakgallery) can carry 10-30× the next, which
// on a linear axis crushes every other bar to a sliver. Log spreads them so the ranking is
// readable while the real count is always printed on the right. Pass hits as [{domain,occurrences}].
function renderBars(hits, leadText) {
  const box = $("report-bars");
  if (!box) return;
  const top = hits.slice().sort((a, b) => (b.occurrences || 0) - (a.occurrences || 0)).slice(0, 8);
  if (!top.length) { box.style.display = "none"; box.innerHTML = ""; return; }
  const vals = top.map((h) => Math.max(1, Number(h.occurrences) || 0));
  const lmax = Math.log(Math.max(...vals)), lmin = Math.log(Math.min(...vals));
  const denom = lmax - lmin;   // 0 when every host is tied
  box.style.display = "";
  box.innerHTML =
    '<div class="report-sechead"><h2>Where the leaks are</h2></div>' +
    '<p class="report-lead">' + escapeHtml(leadText || "Top sites by confirmed matches — log scale.") + "</p>" +
    '<div class="bars">' + top.map((h) => {
      const v = Math.max(1, Number(h.occurrences) || 0);
      const w = denom > 0 ? Math.round(16 + 84 * (Math.log(v) - lmin) / denom) : 100;  // 16% floor so the smallest stays visible
      return '<div class="bar"><span class="bl">' + escapeHtml(h.domain) + "</span>" +
        '<span class="bt"><i style="width:' + w + '%"></i></span>' +
        '<span class="bv">' + fmtNum(Number(h.occurrences) || 0) + "</span></div>";
    }).join("") + "</div>";
}

// Deep report: bar data = the REAL confirmed per-domain URL counts (incl. locale mirrors), not the
// crawl's capped match tallies. Falls back to the hit occurrences if no link map is present.
function barsFromLinks(res) {
  const byDom = res.links_by_domain || {};
  const doms = Object.keys(byDom);
  if (!doms.length) return (res.hits || []);
  return doms.map((d) => ({ domain: d, occurrences: byDom[d].length }));
}

function grpOcc(g) { return g.reduce((a, h) => a + (Number(h.occurrences) || 0), 0); }

// Fast (quick) report link list — one row per site, "N+ leaks" tally, NO
// dropdowns. Click a row to copy its URL (the domain link still opens it).
function renderTopLinks(hits) {
  const wrap = $("report-links");
  const list = $("results-list");
  if (!wrap || !list) return;
  const groups = {};
  hits.forEach((h) => { if (h.domain) (groups[h.domain] = groups[h.domain] || []).push(h); });
  const allDomains = Object.keys(groups).sort((a, b) => grpOcc(groups[b]) - grpOcc(groups[a]));
  const domains = allDomains.slice(0, DISPLAY.topDomains);   // print only the top N sites
  reportLinks = hits.map((h) => h.url).filter(Boolean);      // Download/Copy-all still gets every URL
  const cnt = $("report-links-count");
  if (cnt) cnt.textContent = allDomains.length > domains.length
    ? "— top " + domains.length + " of " + allDomains.length + " sites"
    : "— " + domains.length + " site" + (domains.length === 1 ? "" : "s");
  list.className = "results-list glist";
  list.innerHTML = domains.map((d) => {
    const g = groups[d];
    const url = (g.find((h) => h.url) || {}).url || ("https://" + d + "/");
    const n = Math.max(1, grpOcc(g) || g.length);
    return '<div class="grow" data-url="' + escapeHtml(url) + '">' +
      '<a class="gdom" href="' + escapeHtml(url) + '" target="_blank" rel="noopener noreferrer nofollow">' +
      escapeHtml(d) + "</a>" +
      '<span class="gurls">' + fmtNum(n) + "+ leaks</span></div>";
  }).join("");
  list.onclick = (e) => {
    if (e.target.closest("a")) return;                 // let the domain link open normally
    const row = e.target.closest(".grow");
    if (!row) return;
    const url = row.getAttribute("data-url") || "";
    navigator.clipboard.writeText(url).then(() => {
      const tag = row.querySelector(".gurls");
      if (!tag || row.classList.contains("copied")) return;
      row.classList.add("copied");
      const old = tag.textContent;
      tag.textContent = "copied ✓";
      setTimeout(() => { tag.textContent = old; row.classList.remove("copied"); }, 1200);
    }).catch(() => {});
  };
  wrap.style.display = "";
}

function renderLinks(hits) {
  const wrap = $("report-links");
  const list = $("results-list");
  if (!wrap || !list) return;
  list.className = "results-list";   // reset if a prior fast scan left the flat glist
  list.onclick = null;
  const groups = {};
  hits.forEach((h) => { (groups[h.domain] = groups[h.domain] || []).push(h); });
  const domains = Object.keys(groups);
  reportLinks = hits.map((h) => h.url).filter(Boolean);
  const cnt = $("report-links-count");
  if (cnt) cnt.textContent = "— " + domains.length + " site" + (domains.length === 1 ? "" : "s");
  list.innerHTML = domains.map((d) => {
    const g = groups[d];
    const occ = g.reduce((a, h) => a + (Number(h.occurrences) || 0), 0);
    const links = g.filter((h) => h.url).map((h) =>
      '<a href="' + escapeHtml(h.url) + '" target="_blank" rel="noopener noreferrer nofollow">' +
      escapeHtml(h.url) + "</a>").join("<br>");
    return '<details class="lg"><summary>' + escapeHtml(d) +
      ' <span class="mut">· ' + fmtNum(occ) + " match" + (occ === 1 ? "" : "es") + "</span></summary>" +
      '<div class="lk">' + (links || '<span class="mut">confirmed hit</span>') + "</div></details>";
  }).join("");
  wrap.style.display = "";
}

function renderCovers(res) {
  const box = $("report-covers");
  if (!box) return;
  box.style.display = "";
  box.innerHTML =
    '<div class="report-card"><h2>What the takedown covers</h2>' +
    "<ul><li>DMCA &amp; abuse notices to every host and registrar</li>" +
    "<li>Google delisting for indexed pages</li>" +
    "<li>Language-mirror &amp; re-upload coverage</li>" +
    "<li>Re-scan on re-uploads · progress updates</li></ul></div>";
}

function renderFoot(res) {
  const box = $("report-foot");
  if (!box) return;
  const n = CONFIG.verifiedDomains || 375;
  box.innerHTML =
    "Confidential — prepared for @" + escapeHtml(res.handle || "") + ". " + n +
    " known piracy domains scanned.<br>A site counts as a hit only when the handle appears on a page that site is confirmed to host.";
}

function downloadLinks() {
  if (!reportLinks.length) return;
  const handle = (currentScan && currentScan.handle) ? currentScan.handle.replace(/[^A-Za-z0-9._-]/g, "") : "";
  const b = new Blob([reportLinks.join("\n") + "\n"], { type: "text/plain" });
  const u = document.createElement("a");
  u.href = URL.createObjectURL(b);
  u.download = (handle ? handle + "_" : "") + "leak_links.txt";
  u.click();
  URL.revokeObjectURL(u.href);
  const m = $("links-msg"); if (m) m.textContent = "downloaded " + fmtNum(reportLinks.length) + " links";
}
function copyLinks() {
  if (!reportLinks.length) return;
  navigator.clipboard.writeText(reportLinks.join("\n"))
    .then(() => { const m = $("links-msg"); if (m) m.textContent = "copied " + fmtNum(reportLinks.length) + " links"; })
    .catch(() => { const m = $("links-msg"); if (m) m.textContent = fmtNum(reportLinks.length) + " links"; });
}
// Mail links: opens the visitor's own mail app pre-filled with the recipient they typed,
// a subject, and a body carrying as many links as a mailto body safely holds — then a
// pointer to the full shareable report for the rest. No server/SMTP needed.
function mailLinks() {
  if (!reportLinks.length) { const m = $("links-msg"); if (m) m.textContent = "no links yet"; return; }
  const inp = $("links-email");
  const to = (inp && inp.value.trim()) || "";
  if (inp && to && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(to)) {
    const m = $("links-msg"); if (m) m.textContent = "enter a valid email"; inp.focus(); return;
  }
  const handle = (currentScan && currentScan.handle) || "";
  const slug = (currentScan && currentScan.slug) || "";
  const shareUrl = slug ? (location.origin + "/s/" + slug) : location.href;
  const n = reportLinks.length;
  const subject = n + " detected leak link" + (n === 1 ? "" : "s") + (handle ? " for @" + handle : "");
  let body = "Detected leak links" + (handle ? " for @" + handle : "") + " (" + n + " total):\n\n";
  let shown = 0;
  for (const u of reportLinks) {                 // fit what a mailto body safely holds (~1500 chars)
    if (body.length + u.length + 1 > 1500) break;
    body += u + "\n"; shown++;
  }
  body += shown < n
    ? "\n…and " + fmtNum(n - shown) + " more — full list in the report:\n" + shareUrl + "\n"
    : "\nFull report: " + shareUrl + "\n";
  window.location.href = "mailto:" + encodeURIComponent(to) +
    "?subject=" + encodeURIComponent(subject) + "&body=" + encodeURIComponent(body);
  const m = $("links-msg"); if (m) m.textContent = "opening your email app…";
}

// ---- shareable poster image (fast report) ----------------------------------
// A downloadable PNG "Leak Scan Results" card, built entirely on a <canvas> from
// the fast scan's own data. We deliberately DON'T draw the CSE thumbnails: they're
// remote gstatic URLs that would taint the canvas and make toBlob() throw, so the
// image strip is blurred placeholder tiles instead. Contact line = your DM bio.
const FONT = "-apple-system, 'Segoe UI', Roboto, Arial, sans-serif";
const AUTO_SAVE_POSTER = true;   // auto-download the poster when a fast scan finishes (set false to require a click)
let posterSavedSlug = null;

function posterContact() {
  const dm = CONFIG.dm || {};
  const clean = (v) => String(v || "")
    .replace(/^https?:\/\/(www\.)?(instagram\.com|t\.me|wa\.me)\//i, "")
    .replace(/^@/, "").replace(/\/.*$/, "");
  if (dm.instagram) return "DM @" + clean(dm.instagram) + " on Instagram to get them removed";
  if (dm.telegram) return "DM @" + clean(dm.telegram) + " on Telegram to get them removed";
  if (dm.whatsapp) return "Message us on WhatsApp to get them removed";
  return "Message us to get these removed";
}

// Load one thumbnail through the same-origin /api/thumb proxy → an <img> that can
// be drawn into the canvas WITHOUT tainting it. Resolves null on any failure.
function loadProxImg(u) {
  return new Promise((resolve) => {
    if (!u || typeof u !== "string") return resolve(null);
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = "/api/thumb?u=" + encodeURIComponent(u);
  });
}
function loadPosterThumbs(images, n) {
  const urls = (images || []).filter((u) => typeof u === "string").slice(0, n);
  return Promise.all(urls.map(loadProxImg));
}
// Load a same-origin data: URI straight into an <img> (no proxy, no canvas taint) — used
// by the DEEP poster to draw the curated gallery photos.
function loadDataImg(u) {
  return new Promise((resolve) => {
    if (!u || typeof u !== "string") return resolve(null);
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = u;
  });
}
// Draw an image "cover"-style into a box.
function drawCover(c, img, x, y, w, h) {
  const ir = img.width / img.height, tr = w / h;
  let sw, sh, sx, sy;
  if (ir > tr) { sh = img.height; sw = sh * tr; sx = (img.width - sw) / 2; sy = 0; }
  else { sw = img.width; sh = sw / tr; sx = 0; sy = (img.height - sh) / 2; }
  c.drawImage(img, sx, sy, sw, sh, x, y, w, h);
}

async function buildPoster(res) {
  const W = 1080, H = 1920, P = 70, IW = W - 2 * P;
  const cv = document.createElement("canvas");
  cv.width = W; cv.height = H;
  const c = cv.getContext("2d");
  const hits = (res.hits || []).filter(isRealHit);
  const handle = (res.handle || "").replace(/^@/, "");
  const isDeep = res.level === "deep";
  const PM = DISPLAY.perDomainMult, TM = DISPLAY.totalMult;

  // domains + per-domain counts: deep uses the confirmed leak-URL map (real counts);
  // fast uses hit occurrences (×perDomainMult for display).
  const byDom = {}, domains = [];
  if (isDeep && res.links_by_domain && Object.keys(res.links_by_domain).length) {
    Object.keys(res.links_by_domain).forEach((d) => { byDom[d] = res.links_by_domain[d].length; domains.push(d); });
  } else {
    hits.forEach((h) => { if (h.domain) { if (byDom[h.domain] === undefined) { byDom[h.domain] = 0; domains.push(h.domain); } byDom[h.domain] += (Number(h.occurrences) || 0); } });
  }
  domains.sort((a, b) => byDom[b] - byDom[a]);
  const sites = isDeep ? (Number(res.n_sites) || domains.length) : domains.length;
  const rawPages = hits.reduce((a, h) => a + (Number(h.occurrences) || 0), 0) || hits.length;
  const pages = isDeep ? (Number(res.n_leaks) || 0) : Math.round(rawPages * TM);   // headline count
  const mediaN = isDeep ? (Number(res.n_media) || 0) : 0;
  const quote = isDeep ? (Number(res.quote) || 0) : 0;
  const gtotal = res.google_total ? Number(res.google_total) : 0;
  const topUrls = (isDeep
    ? domains.map((d) => (res.links_by_domain[d] || [])[0]).filter(Boolean)
    : hits.map((h) => h.url).filter(Boolean)).slice(0, 5);
  // Per-fan revenue-loss band. Scales with leak volume — a creator with 10k leaks is far more
  // exposed than one with 100 — but clamped both ways: a floor so a small creator isn't trivial
  // (€40–€120), a ceiling so a massive count can't read as an absurd 5-figure number.
  const lossLo = Math.min(3000, Math.max(40, pages * 0.045));
  const lossHi = Math.min(9000, Math.max(120, pages * 0.135));
  // Tile thumbnails: deep draws the curated gallery photos (data: URIs → no canvas taint);
  // fast draws the CSE thumbnails via the same-origin /api/thumb proxy.
  const thumbs = isDeep
    ? await Promise.all((res.gallery || []).slice(0, 10).map((g) => loadDataImg(g.img)))
    : await loadPosterThumbs(res.images, 10);

  const rr = (x, y, w, h, r) => { c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); };
  const fit = (t, weight, max, maxW) => { let s = max; c.font = weight + " " + s + "px " + FONT; while (s > 14 && c.measureText(t).width > maxW) { s -= 2; c.font = weight + " " + s + "px " + FONT; } return s; };
  const trunc = (t, maxW) => { if (c.measureText(t).width <= maxW) return t; let x = t; while (x.length > 4 && c.measureText(x + "…").width > maxW) x = x.slice(0, -1); return x + "…"; };
  const now = new Date();
  const date = now.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "2-digit" });

  // background
  const bg = c.createLinearGradient(0, 0, 0, H);
  bg.addColorStop(0, "#191138"); bg.addColorStop(0.35, "#0f1020"); bg.addColorStop(1, "#0f1020");
  c.fillStyle = bg; c.fillRect(0, 0, W, H);

  // title + handle + date
  c.textAlign = "center"; c.textBaseline = "alphabetic";
  c.fillStyle = "#eef0ff"; fit("Leak Scan Results", "800", 62, IW);
  c.fillText("Leak Scan Results", W / 2, 150);
  c.fillStyle = "#38d9c7"; c.font = "700 46px " + FONT;
  c.fillText(trunc("@" + handle, IW), W / 2, 208);
  c.fillStyle = "#a3a7c9"; c.font = "400 28px " + FONT;
  c.fillText(date, W / 2, 252);

  // Google mock panel
  const pX = P, pY = 296, pW = IW, pH = 470;
  c.fillStyle = "#0c0d1c"; rr(pX, pY, pW, pH, 22); c.fill();
  c.strokeStyle = "#2c2e57"; c.lineWidth = 2; rr(pX, pY, pW, pH, 22); c.stroke();
  c.textAlign = "left";
  const word = "Google", cols = ["#4285F4", "#EA4335", "#FBBC05", "#4285F4", "#34A853", "#EA4335"];
  c.font = "500 40px arial, sans-serif";
  let pen = pX + 34; const wy = pY + 62;
  for (let i = 0; i < word.length; i++) { c.fillStyle = cols[i]; c.fillText(word[i], pen, wy); pen += c.measureText(word[i]).width; }
  const sbX = pX + 240, sbY = pY + 28, sbW = pW - 240 - 34, sbH = 56;
  c.fillStyle = "#17182f"; rr(sbX, sbY, sbW, sbH, 28); c.fill();
  c.strokeStyle = "#2c2e57"; rr(sbX, sbY, sbW, sbH, 28); c.stroke();
  c.fillStyle = "#cbd0f5"; c.font = "400 26px arial, sans-serif";
  c.fillText(trunc('"' + handle + '" leaks', sbW - 70), sbX + 24, sbY + 37);
  // blurred placeholder tiles (no remote images → no canvas taint)
  const gc = 5, gr = 2, gap = 14, tTop = pY + 118, pad = 34;
  const tW = (pW - 2 * pad - (gc - 1) * gap) / gc;
  const tH = (pH - 118 - pad - (gr - 1) * gap) / gr;
  let ti = 0;
  for (let r = 0; r < gr; r++) for (let col = 0; col < gc; col++) {
    const tx = pX + pad + col * (tW + gap), ty = tTop + r * (tH + gap);
    c.save(); rr(tx, ty, tW, tH, 12); c.clip();
    const img = thumbs[ti];
    if (img) {
      drawCover(c, img, tx, ty, tW, tH);          // real, unblurred leak thumbnail
    } else {
      const hue = (ti * 43 + 275) % 360;           // gradient placeholder when a thumb is missing
      const g2 = c.createLinearGradient(tx, ty, tx + tW, ty + tH);
      g2.addColorStop(0, "hsl(" + hue + ",46%,44%)"); g2.addColorStop(1, "hsl(" + ((hue + 40) % 360) + ",52%,24%)");
      c.fillStyle = g2; c.fillRect(tx, ty, tW, tH);
      c.fillStyle = "rgba(255,255,255,.06)"; c.fillRect(tx, ty + tH * 0.52, tW, tH * 0.16);
      c.fillStyle = "rgba(255,255,255,.85)"; c.font = "26px arial"; c.textAlign = "center";
      c.fillText("🔒", tx + tW / 2, ty + tH / 2 + 9);
    }
    c.restore();
    ti++;
  }

  // headline stats
  let y = pY + pH + 74;
  c.textAlign = "left"; c.fillStyle = "#eef0ff";
  const headline = isDeep
    ? fmtNum(pages) + " confirmed leaks across " + sites + " site" + (sites === 1 ? "" : "s")
    : fmtNum(pages) + "+ indexed pages across " + sites + " site" + (sites === 1 ? "" : "s");
  fit(headline, "800", 46, IW);
  c.fillText(headline, P, y);
  y += 44;
  if (isDeep) {
    c.fillStyle = "#8ea0ff"; c.font = "400 28px " + FONT;
    c.fillText(fmtNum(mediaN) + " media files identified · takedown quote €" + fmtNum(quote), P, y);
    y += 18;
  } else if (gtotal > 0) {
    c.fillStyle = "#8ea0ff"; c.font = "400 28px " + FONT;
    c.fillText("Google estimates ~" + fmtNum(gtotal) + " indexed results", P, y);
    y += 18;
  }
  y += 40;

  // domain rows with "N+ URLs" (per-domain occurrences × perDomainMult, top-N sites)
  c.font = "600 30px " + FONT;
  domains.slice(0, DISPLAY.topDomains).forEach((d) => {
    const n = isDeep ? Math.max(1, byDom[d] || 1) : Math.max(1, Math.round((byDom[d] || 1) * PM));
    c.textAlign = "left"; c.fillStyle = "#dfe2ff";
    c.fillText("•  " + trunc(d, IW - 230), P + 4, y);
    c.textAlign = "right"; c.fillStyle = "#f5b74e";
    c.fillText(fmtNum(n) + (isDeep ? " URLs" : "+ URLs"), W - P, y);
    y += 47;
  });
  y += 22;

  // top leaks
  if (topUrls.length) {
    c.textAlign = "center"; c.fillStyle = "#eef0ff"; c.font = "700 36px " + FONT;
    c.fillText("Top leaks:", W / 2, y); y += 46;
    c.fillStyle = "#8fb4ff"; c.font = "400 25px " + FONT;
    topUrls.forEach((u) => {
      const capped = u.length > DISPLAY.urlMaxLen ? u.slice(0, DISPLAY.urlMaxLen - 1) + "…" : u;
      c.fillText(trunc(capped, IW), W / 2, y); y += 37;
    });
    y += 20;
  }

  // loss estimate
  c.textAlign = "center"; c.fillStyle = "#ff6b6b";
  const loss = "Loss: €" + lossLo.toFixed(1) + " – €" + lossHi.toFixed(1) + " per OnlyFans fan";
  fit(loss, "800", 42, IW);
  y += 24; c.fillText(loss, W / 2, y); y += 80;

  // CTA + footer flow right after the content; then crop the unused tail so the
  // poster isn't a tall band of empty space when there are few sites.
  c.fillStyle = "#38d9c7"; fit(posterContact(), "800", 34, IW);
  c.fillText(posterContact(), W / 2, y); y += 46;
  c.fillStyle = "#a3a7c9"; c.font = "400 24px " + FONT;
  c.fillText("Free scan & how to remove it yourself — or we do it for you.", W / 2, y); y += 36;

  const finalH = Math.round(Math.min(H, y + P));
  if (finalH < H - 4) {
    const out = document.createElement("canvas");
    out.width = W; out.height = finalH;
    out.getContext("2d").drawImage(cv, 0, 0);
    return out;
  }
  return cv;
}

async function savePoster(res) {
  if (!res) return;
  let cv;
  try { cv = await buildPoster(res); } catch (e) { return; }
  const done = (blob) => {
    if (!blob) return;
    const name = "leakscan_" + ((res.handle || "report").replace(/[^A-Za-z0-9._-]/g, "") || "report") + ".png";
    const u = document.createElement("a");
    u.href = URL.createObjectURL(blob);
    u.download = name;
    u.click();
    setTimeout(() => URL.revokeObjectURL(u.href), 4000);
  };
  if (cv.toBlob) cv.toBlob(done, "image/png");
  else { try { const d = cv.toDataURL("image/png"); const a = document.createElement("a"); a.href = d; a.download = "leakscan.png"; a.click(); } catch (e) {} }
}

// Auto-download the poster once, only for a fresh scan the visitor just ran on
// the home page (never on a shared-link view — that would surprise a recipient).
function maybeAutoSavePoster(res) {
  // Auto-download the shareable poster once per scan on the home page — for BOTH fast and deep
  // (buildPoster is level-aware: deep uses the real confirmed-URL counts + quote).
  if (!AUTO_SAVE_POSTER || MODE !== "home") return;
  const key = res.slug || "x";
  if (posterSavedSlug === key) return;
  posterSavedSlug = key;
  savePoster(res);
}

// ---- chat (DeepSeek assistant) — reusable widget ---------------------------
let resultsChat = null, askChat = null, progressChat = null, topResultsChat = null;

function makeChat(opts) {
  const form = $(opts.formId), log = $(opts.logId), input = $(opts.inputId), send = $(opts.sendId);
  if (!form || !log || !input) return null;
  let history = [];
  let busy = false;
  const add = (role, text) => {
    const div = document.createElement("div");
    div.className = "chat-msg " + role;
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  };
  const reset = (greeting) => { history = []; log.innerHTML = ""; if (greeting) add("assistant", greeting); };
  // Send a message programmatically (used by the form AND the prewritten-question
  // chips). Guarded so a burst of chip taps can't overlap in-flight replies.
  const ask = async (text) => {
    text = (text || "").trim();
    if (!text || busy) return;
    busy = true;
    add("user", text);
    history.push({ role: "user", content: text });
    const bubble = add("assistant", "");
    bubble.classList.add("typing");
    if (send) send.disabled = true;
    let acc = "";
    try {
      const extra = (opts.getContext ? opts.getContext() : {}) || {};
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.assign({ messages: history }, extra)),
      });
      if (resp.status === 429) { bubble.textContent = "You're sending messages quickly — please wait a moment."; return; }
      if (!resp.ok || !resp.body) { bubble.textContent = "Sorry, the assistant is unavailable right now."; return; }
      await consumeSSE(resp, (ev) => {
        if (ev.event === "token") { acc += JSON.parse(ev.data); bubble.textContent = acc; log.scrollTop = log.scrollHeight; }
        else if (ev.event === "failed") { bubble.textContent = ev.data || "The assistant is unavailable."; }
      });
      if (acc) history.push({ role: "assistant", content: acc });
    } catch (err) {
      bubble.textContent = acc || "The connection was interrupted. Please try again.";
    } finally {
      bubble.classList.remove("typing");
      busy = false;
      if (send) send.disabled = false;
    }
  };
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    ask(text);
  });
  return { reset, add, ask };
}

// Prewritten questions shown as tappable chips under the results assistant. Each
// [label, question] — the short label shows on the chip; the full question is
// what we send to DeepSeek. (Shown in both fast & deep reports — the chat is shared.)
const RESULT_QS = [
  ["Is this all of them?", "Is this all the leaks, or only these websites?"],
  ["Which sites?", "Which sites are my leaks on?"],
  ["How to remove them?", "How do I get these leaks removed?"],
  ["Will they come back?", "Will the leaks come back after they're removed?"],
  ["What's the cost?", "What does a full takedown of all these leaks cost?"],
];
function wireQuestionChips(rowId, chat) {
  const row = $(rowId);
  if (!row) return;
  row.innerHTML = RESULT_QS.map(([label]) =>
    '<button type="button" class="qchip">' + escapeHtml(label) + "</button>").join("");
  Array.from(row.children).forEach((btn, i) => {
    btn.addEventListener("click", () => { const c = chat(); if (c) c.ask(RESULT_QS[i][1]); });
  });
}

function scanContextStr() {
  const deep = selectedLevel === "deep";
  if (!deep) {
    let q = "A quick scan — a Google search across known leak sites. Handle: @" + scanningHandle +
      ". It is running RIGHT NOW on this page and takes under a minute.";
    if (foundSites.length) {
      q += " CONFIRMED HITS SO FAR — these are REAL results, report them and do NOT say 'no results yet': copies found on " +
           foundSites.slice(0, 15).join(", ") + ".";
    } else {
      q += " No confirmed hits have come back yet (scan still early).";
    }
    q += " The full shareable report appears here when the scan finishes.";
    return q;
  }
  // Deep scan: teach the model the WHOLE pipeline, so it never mistakes the end of
  // stage 1 (the site-check counter maxing out) for the end of the scan. That exact
  // hallucination shipped once: 375/375 checks done -> "The scan is finished" while
  // the crawl was still running, and it doubled down when the visitor pushed back.
  let s = "A DEEP SCAN for @" + scanningHandle + " is running RIGHT NOW on this page. " +
    "THE SCAN IS NOT FINISHED. It is finished ONLY when the full report replaces this progress screen on its own. " +
    "NEVER tell the visitor it is finished, complete, or done — if they ask, say which stage it is in and what is still left.";
  s += " It runs 8 stages in order: 1) site check — every known leak site tested against the handle + name variations (the N/M counter); " +
    "2) profile-page seeding; 3) deep crawl of every found site, collecting each leaked page & media file (LONGEST stage — several minutes, the counter does NOT move); " +
    "4) URL cleaning & verification; 5) triage; 6) confirmed-leaks export (final counts, per-site links, removal quote); " +
    "7) Google-index sweep; 8) preview gallery.";
  const label = stageLabel(lastPhase);
  if (label) s += " CURRENT STAGE: " + label + ".";
  const pm = lastProgress && lastProgress.match(/(\d+)\s*\/\s*(\d+)/);
  if (pm) {
    s += " Site-check counter: " + pm[1] + " of " + pm[2] + " checks (one check = one name-variation against one site — a CHECK count, never call it a site count).";
    if (pm[1] === pm[2]) s += " The counter maxing out only ends stage 1 — the later stages are still running.";
  }
  if (foundSites.length) {
    const shown = foundSites.slice(0, 12);
    const more = foundSites.length - shown.length;
    s += " CONFIRMED SO FAR: copies found on " + foundSites.length + " sites — a PARTIAL, still-growing number. " +
      "First " + shown.length + ": " + shown.join(", ") + (more > 0 ? " … and " + more + " more" : "") +
      ". Always give the total (" + foundSites.length + " so far); never present the listed names as the complete set.";
  } else {
    s += " No confirmed hits have come back yet (scan still early).";
  }
  s += " The deep crawl typically multiplies these findings; the final numbers come from the export stage and land in the report.";
  return s;
}

function initChatWidgets() {
  resultsChat = makeChat({ formId: "chat-form", logId: "chat-log", inputId: "chat-input", sendId: "chat-send",
    getContext: () => ({ slug: currentScan && currentScan.slug }) });
  askChat = makeChat({ formId: "ask-form", logId: "ask-answer", inputId: "ask-input", sendId: "ask-send",
    getContext: () => ({}) });
  progressChat = makeChat({ formId: "pchat-form", logId: "pchat-log", inputId: "pchat-input", sendId: "pchat-send",
    getContext: () => ({ scan_context: scanContextStr() }) });
  // Top "ask about your report" widget (same DeepSeek chat, placed above the report).
  topResultsChat = makeChat({ formId: "topchat-form", logId: "topchat-log", inputId: "topchat-input", sendId: "topchat-send",
    getContext: () => ({ slug: currentScan && currentScan.slug }) });
  wireQuestionChips("chat-qrow", () => resultsChat);   // bottom chat keeps its greeting + chips
  if (askChat) askChat.reset("Hi! Ask me anything about leaks, DMCA takedowns, or how this works.");
}

function initHelpButton() {
  const b = $("nav-help");
  if (!b) return;
  b.addEventListener("click", () => {
    // On the results/report screen jump to the report's AI chat at the bottom
    // (the landing #ask box isn't on that panel); on the landing use the ask pill.
    const results = $("panel-results");
    const onResults = results && results.classList.contains("active");
    const target = onResults ? ($("chat") || $("ask")) : ($("ask") || $("chat"));
    if (target) target.scrollIntoView({ behavior: "smooth", block: onResults ? "start" : "center" });
    const inp = onResults ? ($("chat-input") || $("ask-input")) : ($("ask-input") || $("chat-input"));
    if (inp) setTimeout(() => inp.focus({ preventScroll: true }), 350);
  });
}

// ---- blurred preview grid --------------------------------------------------
// Tap a blurred tile to unblur just that one. The old whole-strip "Reveal images"
// button is gone — a global "Unblur" lives in the header. Caption links still click through.
function wireTapReveal(box) {
  if (!box) return;
  box.onclick = (e) => {
    if (e.target.closest("a")) return;
    const cell = e.target.closest(".img-cell");
    if (cell) cell.classList.toggle("show");
  };
}

function renderImages(images) {
  const box = $("results-images");
  const btn = $("reveal-btn");
  const media = $("report-media");
  if (!box) return;
  box.classList.remove("revealed");
  if (btn) btn.style.display = "none";
  if (!images || !images.length) {
    box.innerHTML = ""; box.style.display = "none";
    if (media) media.style.display = "none";
    return;
  }
  if (media) media.style.display = "";
  box.style.display = "";
  // onerror hides tiles whose source won't load (hotlink-blocked leak-site media) so the grid
  // never shows broken-image icons — it just shrinks to the ones that render.
  box.innerHTML = images.map((u) =>
    '<div class="img-cell"><img src="' + escapeHtml(u) + '" alt="" loading="lazy" referrerpolicy="no-referrer" ' +
    "onerror=\"this.closest('.img-cell').style.display='none'\">" +
    '<span class="lock">&#128274;</span></div>'
  ).join("");
  wireTapReveal(box);
}

// ---- ownership verification (bio code) -------------------------------------
// Ownership verification is OFF for now (testing). Flip REQUIRE_VERIFY back to
// true to re-enable the bio-code prompt on the results screen.
const REQUIRE_VERIFY = false;
function wireVerify(res) {
  const card = $("verify-card");
  if (!card) return;
  if (!REQUIRE_VERIFY) { card.style.display = "none"; return; }
  // Already-verified saved scans (share view) don't need the prompt.
  if (res && res.ownership_verified) { card.style.display = "none"; return; }
  card.style.display = "";
  $("verify-handle").textContent = "@" + escapeHtml((res && res.handle) || "you");
  $("verify-step1").style.display = "";
  $("verify-step2").style.display = "none";
  $("verify-status").textContent = "";
  const handle = (res && res.handle) || "";
  const slug = (res && res.slug) || null;
  let code = "";

  const get = $("verify-get");
  if (get) get.onclick = async () => {
    get.disabled = true;
    try {
      const r = await fetch("/api/verify-start", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ handle }),
      });
      const d = await r.json();
      if (!r.ok || !d.code) { $("verify-status").textContent = "Couldn't start verification — try again."; get.disabled = false; return; }
      code = d.code;
      $("verify-code").textContent = code;
      $("verify-instr").textContent = d.instructions || "";
      $("verify-step1").style.display = "none";
      $("verify-step2").style.display = "";
    } catch (e) {
      $("verify-status").textContent = "Network error — try again.";
      get.disabled = false;
    }
  };

  const copy = $("verify-copy");
  if (copy) copy.onclick = async () => {
    try { await navigator.clipboard.writeText(code); copy.textContent = "Copied"; }
    catch (e) { /* ignore */ }
  };

  const run = $("verify-run");
  if (run) run.onclick = async () => {
    run.disabled = true;
    $("verify-status").textContent = "Checking your bio…";
    try {
      const resp = await fetch("/api/verify-check", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ handle, code, slug, platforms: ["instagram", "onlyfans"] }),
      });
      if (!resp.ok || !resp.body) { $("verify-status").textContent = "Verification unavailable — try again."; run.disabled = false; return; }
      let done = false;
      await consumeSSE(resp, (ev) => {
        if (ev.event === "progress") $("verify-status").textContent = ev.data;
        else if (ev.event === "result") {
          done = true;
          let d = {}; try { d = JSON.parse(ev.data); } catch (e) {}
          if (d.verified) {
            $("verify-card").classList.add("verified");
            $("verify-step2").innerHTML = '<div class="verify-ok">✅ Verified — you own @' +
              escapeHtml(handle) + " on " + escapeHtml(d.matched_platform || "your account") +
              ". We can now file takedowns for you.</div>";
          } else {
            $("verify-status").textContent =
              "Code not found in your bio yet. Make sure it's saved and public, then try again.";
            run.disabled = false;
          }
        } else if (ev.event === "failed") { $("verify-status").textContent = ev.data || "Verification failed."; run.disabled = false; }
      });
      if (!done) { $("verify-status").textContent = "Verification didn't complete — try again."; run.disabled = false; }
    } catch (e) {
      $("verify-status").textContent = "Network error — try again.";
      run.disabled = false;
    }
  };
}

function wireShareButton() {
  const btn = $("share-btn");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const slug = currentReportSlug();
    if (!slug) return;
    const url = location.origin + "/s/" + slug;
    try {
      await navigator.clipboard.writeText(url);
      $("share-hint").textContent = "Link copied!";
    } catch (e) {
      $("share-hint").textContent = url;
    }
  });
}

function wireCTA() {
  const dm = CONFIG.dm || {};
  const box = $("dm-cta");
  if (!box) return;
  const btns = [];
  if (dm.instagram) btns.push('<a class="dm-btn dm-ig" target="_blank" rel="noopener noreferrer" href="' + igUrl(dm.instagram) + '">Instagram</a>');
  if (dm.whatsapp) btns.push('<a class="dm-btn dm-wa" target="_blank" rel="noopener noreferrer" href="' + waUrl(dm.whatsapp) + '">WhatsApp</a>');
  if (dm.telegram) btns.push('<a class="dm-btn dm-tg" target="_blank" rel="noopener noreferrer" href="' + tgUrl(dm.telegram) + '">Telegram</a>');
  box.innerHTML = btns.length
    ? btns.join("")
    : '<span class="muted">Contact options are being set up — check back soon.</span>';
}
function igUrl(h) { return /^https?:\/\//.test(h) ? h : "https://instagram.com/" + String(h).replace(/^@/, ""); }
function waUrl(h) { return /^https?:\/\//.test(h) ? h : "https://wa.me/" + String(h).replace(/[^0-9]/g, ""); }
function tgUrl(h) { return /^https?:\/\//.test(h) ? h : "https://t.me/" + String(h).replace(/^@/, ""); }

// ---- share view ------------------------------------------------------------
// A shared link may point at a scan that's still running (deep scans are shareable
// the moment they start) — keep the "Loading report…" panel and poll until done.
async function loadShare() {
  const slug = location.pathname.replace(/^\/s\//, "");
  const tick = async () => {
    let data;
    try {
      const resp = await fetch("/api/scan-result/" + encodeURIComponent(slug));
      if (!resp.ok) return showPanel("error");
      data = await resp.json();
    } catch (e) {
      return setTimeout(tick, 2500);   // transient blip — keep trying
    }
    if (data.status === "running") {
      // A shared link opened mid-scan now paints the SAME live building report as the home page
      // (CSE preview + candidates ticker + progress bar + console) instead of an endless spinner.
      if (data.live) renderLive(data.live, data);
      return setTimeout(tick, 1500);
    }
    if (data.status === "failed") return showPanel("error");
    renderResults(data);
  };
  tick();
}

// ---- boot ------------------------------------------------------------------
function initHome() {
  const dc = $("domain-count");
  if (dc) dc.textContent = CONFIG.verifiedDomains ? CONFIG.verifiedDomains + " known" : "known";

  // Quick / Deep level toggle (Deep reveals the aliases field)
  const NOTES = {
    low: "Instant Google search across known leak sites for your leaked URLs.",
    deep: "Deep-crawls the sites hosting you + Google's index, and captures screenshots of what's out there — across the handle and every name you add. Slower, most thorough. Add more names for a wider pass.",
  };
  function setLevel(lvl) {
    selectedLevel = lvl;
    document.querySelectorAll(".level-toggle .lvl").forEach((b) => b.classList.toggle("active", b.dataset.level === lvl));
    const note = $("lvl-note"); if (note) note.textContent = NOTES[lvl] || "";
    const af = $("aliases-field"); if (af) af.style.display = (lvl === "deep") ? "" : "none";
  }
  document.querySelectorAll(".level-toggle .lvl").forEach((btn) => {
    btn.addEventListener("click", () => setLevel(btn.dataset.level));
  });

  const form = $("scan-form");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const handle = $("handle").value.trim().replace(/^@/, "");
    const platform = $("platform").value;
    if (!/^[A-Za-z0-9._-]{1,60}$/.test(handle)) {
      $("handle").focus();
      return;
    }
    const aliases = ($("aliases") && $("aliases").value) || "";
    runScan(platform, handle, selectedLevel, aliases);
  });

  // Deep-scan CTA — one at the top of the fast report, one at the bottom.
  const goDeep = () => {
    setLevel("deep");
    if (currentScan && currentScan.handle) $("handle").value = currentScan.handle;
    showPanel("landing");
    window.scrollTo({ top: 0, behavior: "smooth" });
    const al = $("aliases"); if (al) al.focus();
  };
  ["deep-cta-btn", "deep-cta-top-btn"].forEach((id) => {
    const b = $(id); if (b) b.addEventListener("click", goDeep);
  });
  const deepMoreBtn = $("deep-more-btn");
  if (deepMoreBtn) deepMoreBtn.addEventListener("click", () => {
    if (!currentScan || !currentScan.handle) return;
    const extra = ($("deep-more-aliases") && $("deep-more-aliases").value) || "";
    const plat = currentScan.platform || ($("platform") && $("platform").value) || "onlyfans.com";
    runScan(plat, currentScan.handle, "deep", extra, true);   // plus = wider pass
  });

  const cancel = $("cancel-btn");
  if (cancel) cancel.addEventListener("click", () => {
    if (scanAbort) scanAbort.abort();
    stopDeepPoll();
    clearResumeHash();
    showPanel("landing");
  });
  const retry = $("retry-btn");
  if (retry) retry.addEventListener("click", () => showPanel("landing"));
  const rescan = $("rescan-btn");
  if (rescan) rescan.addEventListener("click", () => {
    stopDeepPoll();
    clearResumeHash();
    $("handle").value = ""; showPanel("landing"); $("handle").focus();
  });
  wireShareButton();

  // A deep scan in the URL hash means we reloaded / returned mid-scan -> resume it.
  const hm = (location.hash || "").match(/^#s=([A-Za-z0-9_-]{6,24})$/);
  if (hm) resumeDeep(hm[1]);
  else prefillFromUrl();

  // Landing-site funnel: ?p=<platform>&h=<handle>[&l=deep][&go=1] prefills (and auto-runs) the scan.
  function prefillFromUrl() {
    const q = new URLSearchParams(location.search);
    if (!["p", "h", "l", "go"].some((k) => q.has(k))) return;
    const sel = $("platform"), inp = $("handle");
    const p = (q.get("p") || "").trim().toLowerCase();
    const pv = [...sel.options].map((o) => o.value).find((v) => v === p || v === p + ".com");
    if (pv) sel.value = pv;
    let h = (q.get("h") || "").trim();
    if (h.includes("/")) h = h.replace(/[?#].*$/, "").split("/").filter(Boolean).pop() || "";
    h = h.replace(/^@/, "");
    if (h) inp.value = h;
    if ((q.get("l") || "").toLowerCase() === "deep") setLevel("deep");
    try { history.replaceState(null, "", location.pathname + location.hash); } catch (e) {}  // reload must not re-scan
    const go = q.get("go");
    if (!/^[A-Za-z0-9._-]{1,60}$/.test(h)) { inp.focus(); return; }
    if (go && !/^(0|false|no)$/i.test(go)) {
      if (form.requestSubmit) form.requestSubmit();
      else form.dispatchEvent(new Event("submit", { cancelable: true }));
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  wireShareButton();
  wireGlobalUnblur();
  initChatWidgets();
  initHelpButton();
  const ld = $("links-download"); if (ld) ld.addEventListener("click", downloadLinks);
  const lc = $("links-copy"); if (lc) lc.addEventListener("click", copyLinks);
  const lm = $("links-mail"); if (lm) lm.addEventListener("click", mailLinks);
  const le = $("links-email"); if (le) le.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); mailLinks(); } });
  if (MODE === "share") loadShare();
  else initHome();
});
