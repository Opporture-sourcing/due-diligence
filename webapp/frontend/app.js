(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const views = { input: $('#view-input'), progress: $('#view-progress'), report: $('#view-report') };
  let pollTimer = null;

  function show(name) {
    Object.entries(views).forEach(([k, el]) => (el.hidden = k !== name));
    window.scrollTo(0, 0);
  }
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const color = (status) => ({ green: '#22c55e', yellow: '#eab308', red: '#ef4444' }[status]);

  // ---------------------------------------------------------------- input
  $('#analyze-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const url = $('#url-input').value.trim();
    const err = $('#input-error');
    err.hidden = true;
    try {
      const r = await fetch('/api/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }) });
      if (!r.ok) throw new Error((await r.json()).detail || 'Request failed');
      const { job_id } = await r.json();
      $('#progress-url').textContent = url;
      $('#progress-error').hidden = true;
      show('progress');
      poll(job_id);
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
    }
  });
  $('#cancel-btn').addEventListener('click', reset);

  function reset() {
    clearTimeout(pollTimer);
    show('input');
  }

  // ---------------------------------------------------------------- progress
  async function poll(id) {
    const r = await fetch('/api/jobs/' + id);
    if (!r.ok) return;
    const job = await r.json();
    renderSteps(job.steps);
    if (job.status === 'done' && job.report) return renderReport(job.report);
    if (job.status === 'failed') {
      const el = $('#progress-error');
      el.textContent = job.error || 'Investigation failed';
      el.hidden = false;
      return;
    }
    pollTimer = setTimeout(() => poll(id), 1200);
  }

  function renderSteps(steps) {
    $('#steps').innerHTML = steps
      .map((s, i) => `<li class="${s.status}"><span class="dot">${s.status === 'done' ? '✓' : s.status === 'failed' ? '!' : i + 1}</span><span class="label">${esc(s.label)}</span><span class="detail">${esc(s.detail)}</span></li>`)
      .join('');
  }

  // ---------------------------------------------------------------- report
  function renderReport(rep) {
    const sc = rep.scoring, c = rep.company;
    const vClass = sc.score >= 75 ? 'green' : sc.score >= 50 ? 'yellow' : 'red';
    const circ = 2 * Math.PI * 70;
    views.report.innerHTML = `
      <div class="card report-head">
        <div>
          <h1>${esc(c.name)}</h1>
          <div class="sub"><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.url)}</a> · ${esc(c.domain)}</div>
          <span class="verdict v-${vClass}">${esc(sc.verdict)}</span>
          <p class="headline">${esc(sc.headline)}</p>
          <div class="flags">
            ${sc.red_flags.map((f) => `<span class="flag red">⚠ ${esc(f)}</span>`).join('')}
            ${sc.cautions.map((f) => `<span class="flag yellow">${esc(f)}</span>`).join('')}
          </div>
        </div>
        <div class="gauge">
          <svg width="170" height="170" viewBox="0 0 170 170">
            <circle cx="85" cy="85" r="70" fill="none" stroke="#e2e8f0" stroke-width="14"/>
            <circle cx="85" cy="85" r="70" fill="none" stroke="${color(vClass)}" stroke-width="14" stroke-linecap="round"
              stroke-dasharray="${circ}" stroke-dashoffset="${circ * (1 - sc.score / 100)}"/>
          </svg>
          <div class="num"><div><b>${sc.score}</b><br><span>CONFIDENCE / 100</span></div></div>
        </div>
      </div>

      <div class="cats">
        ${sc.categories.map((cat) => `
          <div class="cat" data-jump="sec-${cat.key}">
            <div class="top"><span class="light ${cat.status}"></span><span class="weight">weight ${cat.weight}%</span></div>
            <h3>${esc(cat.label)}</h3>
            <div class="score">${cat.score}</div>
            <div class="bar"><i class="${cat.status}" style="width:${cat.score}%"></i></div>
          </div>`).join('')}
      </div>

      <div class="actions">
        <button class="primary" id="new-btn">Analyze another company</button>
        <button class="ghost" onclick="window.print()">Print / Save PDF</button>
        <button class="ghost" id="json-btn">Download JSON</button>
      </div>

      ${section('profile', 'Company Profile', null, profileBody(rep))}
      ${section('domain', 'Domain & Infrastructure', cat(sc, 'domain'), domainBody(rep.domain))}
      ${section('address', 'Physical Address Verification', cat(sc, 'address'), addressBody(rep.address))}
      ${section('corporate', 'Corporate Database Presence', cat(sc, 'corporate'), corporateBody(rep.corporate))}
      ${section('social', 'Social Media Presence', cat(sc, 'social'), socialBody(rep.social))}
      ${section('reviews', 'Online Reviews', cat(sc, 'reviews'), reviewsBody(rep.reputation))}
      ${section('negative', 'Negative Feedback & News', cat(sc, 'negative'), negativeBody(rep.reputation, rep.people))}
      ${section('people', 'People Behind the Company', cat(sc, 'people'), peopleBody(rep.people))}
      ${section('website', 'Website Quality', cat(sc, 'website'), websiteBody(rep.website_quality, rep.company))}
      ${section('method', 'Methodology & Sources', null, methodBody(rep))}
    `;
    show('report');
    $('#new-btn').addEventListener('click', reset);
    $('#json-btn').addEventListener('click', () => {
      const blob = new Blob([JSON.stringify(rep, null, 2)], { type: 'application/json' });
      const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: `dd-${c.domain}.json` });
      a.click();
    });
    views.report.querySelectorAll('.section > header').forEach((h) => h.addEventListener('click', () => h.parentElement.classList.toggle('open')));
    views.report.querySelectorAll('.cat').forEach((el) => el.addEventListener('click', () => {
      const s = $('#' + el.dataset.jump);
      s.classList.add('open');
      s.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }));
  }

  const cat = (sc, key) => sc.categories.find((c) => c.key === key);

  function section(key, title, category, body) {
    const light = category ? `<span class="light ${category.status}"></span><span class="pill na">${category.score}/100</span>` : '';
    const reasons = category ? `<ul class="reasons">${category.reasons.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>` : '';
    return `<div class="section ${category && category.status !== 'green' ? 'open' : ''}" id="sec-${key}">
      <header>${light}<h2>${esc(title)}</h2><span class="chev">▶</span></header>
      <div class="body">${reasons}${body}</div></div>`;
  }
  const kv = (rows) => `<dl class="kv">${rows.filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`;
  const list = (arr) => (arr && arr.length ? arr.map(esc).join('<br>') : '<span class="pill na">none found</span>');
  const link = (r) => `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title || r.url)}</a>${r.snippet ? `<br><small>${esc(r.snippet)}</small>` : ''}`;

  function profileBody(rep) {
    const c = rep.company;
    return kv([
      ['Company name', esc(c.name)], ['Description', esc(c.description) || '<span class="pill na">no meta description</span>'],
      ['Founded (per site)', esc(c.founding_date)], ['Emails', list(c.emails)], ['Phones', list(c.phones)], ['Addresses', list(c.addresses)],
      ['Pages crawled', c.pages_crawled.map((p) => `<a href="${esc(p)}" target="_blank" rel="noopener">${esc(p)}</a>`).join('<br>')],
    ]);
  }
  function domainBody(d) {
    if (!d || !d.whois) return '<p>Not available.</p>';
    const w = d.whois, s = d.ssl, n = d.dns || {};
    return kv([
      ['Domain', esc(d.domain)], ['Registered', w.created ? `${esc(w.created)} (${w.age_years} years)` : `<span class="pill warn">${esc(w.error || 'unknown')}</span>`],
      ['Expires', esc(w.expires)], ['Registrar', esc(w.registrar)], ['Registrant org', esc(w.registrant_org)], ['Registrant country', esc(w.registrant_country)],
      ['WHOIS privacy', w.ok ? (w.privacy_protected ? '<span class="pill warn">hidden</span>' : '<span class="pill ok">disclosed</span>') : null],
      ['SSL certificate', s.ok ? `<span class="pill ok">valid</span> ${esc(s.issuer)} · until ${esc(s.valid_until)}${s.org_validated ? ' · <span class="pill ok">OV</span>' : ''}` : `<span class="pill bad">${esc(s.error)}</span>`],
      ['Mail (MX)', n.mx && n.mx.length ? `${esc(n.email_provider)}<br><small>${n.mx.map(esc).join(', ')}</small>` : '<span class="pill warn">no mail records</span>'],
      ['IP addresses', (n.a || []).map(esc).join(', ')],
    ]);
  }
  function addressBody(a) {
    if (!a || !a.found) return '<p><span class="pill warn">No address found</span> The website does not publish a physical address.</p>';
    const pill = { commercial: 'ok', residential: 'bad', po_box: 'warn', virtual_office: 'warn', unverified: 'na', unknown: 'na' };
    return `<p>Overall: <span class="pill ${pill[a.verdict]}">${esc(a.verdict.replace('_', ' '))}</span></p>
      <table><thead><tr><th>Address</th><th>Verdict</th><th>Geocoded</th><th>OSM type</th><th>Evidence</th></tr></thead><tbody>
      ${a.results.map((r) => `<tr><td>${esc(r.address)}${r.display_name ? `<br><small>${esc(r.display_name)}</small>` : ''}</td>
        <td><span class="pill ${pill[r.verdict]}">${esc(r.verdict.replace('_', ' '))}</span></td>
        <td>${r.geocoded ? `<a href="https://www.openstreetmap.org/?mlat=${r.lat}&mlon=${r.lon}#map=18/${r.lat}/${r.lon}" target="_blank" rel="noopener">map</a>` : 'no'}</td>
        <td>${esc(r.osm_type || '—')}</td><td>${r.reasons.map(esc).join('<br>')}</td></tr>`).join('')}</tbody></table>`;
  }
  function corporateBody(c) {
    if (!c || !c.sources) return '<p>Not available.</p>';
    return `<p>Searched for <b>${esc(c.company_name_searched)}</b> across ${c.checked_count} public databases — found in <b>${c.found_count}</b>.</p>
      <table><thead><tr><th>Source</th><th>Status</th><th>Matches</th></tr></thead><tbody>
      ${c.sources.map((s) => `<tr><td>${esc(s.source)}</td>
        <td>${s.found ? '<span class="pill ok">found</span>' : s.unavailable ? '<span class="pill na">not checked</span>' : '<span class="pill warn">no record</span>'}</td>
        <td>${s.matches.length ? s.matches.map(link).join('<br>') : esc(s.note || '—')}</td></tr>`).join('')}</tbody></table>`;
  }
  function socialBody(s) {
    if (!s || !s.count) return '<p><span class="pill warn">none</span> No social profiles are linked from the website.</p>';
    const pill = { reachable: 'ok', login_gated: 'na', not_found: 'bad', unreachable: 'warn' };
    return `<table><thead><tr><th>Platform</th><th>Status</th><th>Profile</th><th>Details</th></tr></thead><tbody>
      ${s.profiles.map((p) => `<tr><td>${esc(p.platform)}</td><td><span class="pill ${pill[p.status]}">${esc(p.status.replace('_', ' '))}</span>${p.http_status ? ` <small>HTTP ${p.http_status}</small>` : ''}</td>
        <td><a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.url)}</a></td><td>${esc(p.title || '')}${p.followers ? `<br><b>${esc(p.followers)}</b>` : ''}</td></tr>`).join('')}</tbody></table>`;
  }
  function reviewsBody(r) {
    if (!r) return '<p>Not available.</p>';
    const tp = r.trustpilot || {};
    return kv([
      ['Trustpilot', tp.listed ? `<span class="pill ok">listed</span> <b>${tp.rating}/5</b> from ${tp.review_count ?? '?'} reviews · <a href="${esc(tp.url)}" target="_blank" rel="noopener">view</a>` : tp.listed === false ? '<span class="pill warn">not listed</span>' : `<span class="pill na">${esc(tp.note || 'unavailable')}</span>`],
      ['Better Business Bureau', r.bbb.length ? r.bbb.map(link).join('<br>') : '<span class="pill warn">no profile found</span>'],
      ['Review platforms', r.review_sites.length ? r.review_sites.map(link).join('<br>') : '<span class="pill warn">none found</span>'],
    ]);
  }
  function negativeBody(r, p) {
    const hits = (r && r.negative_hits) || [];
    const ppl = ((p && p.people) || []).flatMap((x) => (x.negative_hits || []).map((h) => ({ ...h, who: x.name })));
    if (!hits.length && !ppl.length) return `<p><span class="pill ok">clean</span> No scam, fraud, lawsuit or complaint results found.${r && r.search_unavailable ? ' <span class="pill na">search unavailable</span>' : ''}</p>`;
    return `${hits.map((h) => `<div class="hit"><span class="kw">${h.keywords.join(' · ')}</span><br>${link(h)}</div>`).join('')}
      ${ppl.length ? `<h4>Associated with people</h4>${ppl.map((h) => `<div class="hit"><span class="kw">${esc(h.who)} · ${h.keywords.join(' · ')}</span><br>${link(h)}</div>`).join('')}` : ''}
      <p class="method">Keyword hits in search results are leads, not conclusions — open each source and judge relevance.</p>`;
  }
  function peopleBody(p) {
    if (!p || !p.people || !p.people.length) return `<p><span class="pill warn">none</span> ${esc((p && p.note) || 'No leadership names disclosed.')}</p>`;
    return `<table><thead><tr><th>Name</th><th>Role</th><th>Source</th><th>Verified</th><th>Public profiles</th></tr></thead><tbody>
      ${p.people.map((x) => `<tr><td><b>${esc(x.name)}</b></td><td>${esc(x.role)}</td><td>${esc(x.source)}</td>
        <td>${x.verified === undefined ? '<span class="pill na">not checked</span>' : x.verified ? '<span class="pill ok">yes</span>' : '<span class="pill warn">no</span>'}</td>
        <td>${(x.profiles || []).map(link).join('<br>') || '—'}</td></tr>`).join('')}</tbody></table>`;
  }
  function websiteBody(q, c) {
    if (!q) return '<p>Not available.</p>';
    const yn = (v) => (v ? '<span class="pill ok">yes</span>' : '<span class="pill warn">no</span>');
    return kv([
      ['HTTPS', yn(q.https)], ['Pages crawled', q.pages_found], ['Words of content', q.word_count], ['Meta description', yn(q.has_meta_description)],
      ['Privacy policy', yn(q.has_privacy_policy)], ['Terms of service', yn(q.has_terms)], ['Email published', yn(q.has_email)], ['Phone published', yn(q.has_phone)],
      ['Address published', yn(q.has_address)], ['Copyright year', q.copyright_year], ['Placeholder text', q.placeholder_text ? '<span class="pill bad">detected</span>' : '<span class="pill ok">none</span>'],
      ['Corporate email domain', q.generic_email_only ? '<span class="pill warn">free webmail only</span>' : c.emails.length ? '<span class="pill ok">yes</span>' : '—'],
    ]);
  }
  function methodBody(rep) {
    const w = rep.scoring.categories.map((c) => `<tr><td>${esc(c.label)}</td><td>${c.weight}%</td><td>${c.score}</td></tr>`).join('');
    return `<p class="method">Report generated ${esc(rep.generated_at)}. Sources verified: the company website and its structured data, WHOIS registry, TLS certificate, DNS, OpenStreetMap, Trustpilot, OpenCorporates, Dun &amp; Bradstreet, Crunchbase, LinkedIn, ZoomInfo, Wikipedia, Better Business Bureau and government registries.</p>
      <table><thead><tr><th>Category</th><th>Weight</th><th>Score</th></tr></thead><tbody>${w}<tr><td><b>Confidence score</b></td><td>100%</td><td><b>${rep.scoring.score}</b></td></tr></tbody></table>
      <p class="method">Traffic lights: green ≥ 70, yellow 45–69, red &lt; 45. Verdict: High ≥ 75, Moderate 50–74, Low &lt; 50.</p>`;
  }
})();
