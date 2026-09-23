const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
})[char]);
const money = value => value ? '$' + Math.round(value / 1000) + 'k' : '—';

let viewMode = 'all';
let primaryView = 'jobs';
let resumeViewMode = 'resume';
let practiceTrack = 'expectations';
let workViewMode = 'goals';
let loadRequestId = 0;
let resumeBuilderData = null;
let resumeTargetContext = null;
let practiceBuilderData = null;
let localEventsData = null;

function groups(jobs) {
  const map = new Map();
  for (const job of jobs) {
    const key = job.company_key || (job.company || 'Unknown').toLowerCase().replace(/[^a-z0-9]/g, '');
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(job);
  }
  return [...map.values()];
}

function companyKey(group) {
  const job = group[0] || {};
  return job.company_key || (job.company || 'Unknown').toLowerCase().replace(/[^a-z0-9]/g, '');
}

function fitBadge(label, enabled, title) {
  return `<span class="fitbadge ${enabled ? 'yes' : 'no'}" title="${esc(title)}"><span aria-hidden="true">${enabled ? '✓' : '—'}</span>${esc(label)}</span>`;
}

function row(job, rank, options = {}) {
  const child = Boolean(options.child);
  const count = options.count || 1;
  const status = options.status || job.status;
  const displayStatus = status === 'PROTECTED' ? 'ACTUAL' : status;
  const age = job.age_days == null ? 'Unknown' : job.age_days === 0 ? 'Today' : `${job.age_days}d ago`;
  const ageClass = job.age_days != null && job.age_days <= 7 ? 'fresh' : job.age_days != null && job.age_days > 14 ? 'stale' : '';
  const concern = (job.concerns || []).find(value => !/Austin presence|fully remote posting|Remote role|Protected company/i.test(value));
  const matches = job.matches || [];
  const chips = matches.slice(0, 2).map(value => `<span class="chip">${esc(value)}</span>`).join('') +
    (matches.length > 2 ? `<span class="chip" title="${esc(matches.slice(2).join(', '))}">+${matches.length - 2}</span>` : '');
  const answer = job.suggested_salary ? money(job.suggested_salary) : 'REVIEW';
  const effectiveCompensation = Number(job.salary_max || job.market_compensation || 0);
  const belowTarget = effectiveCompensation > 0 && effectiveCompensation < 200000;
  const actualSaved = Boolean(options.actualSaved);
  const practiceSaved = Boolean(options.practiceSaved);
  const strategicAuto = Boolean(options.strategicAuto);
  const benchmark = job.levels_benchmark;
  const benchmarkAmount = benchmark && (benchmark.senior_total_comp || benchmark.median_total_comp);
  const benchmarkLabel = benchmark && benchmark.senior_total_comp ? (benchmark.senior_level || 'Senior') : 'Company median';
  const marketAmount = Number(job.market_compensation || 0);
  const marketSource = job.market_compensation_source || '';
  const marketUrl = job.market_compensation_url || '';
  const employerBenchmark = marketSource.toLowerCase().includes('employer-posted company benchmark');
  const usReference = marketSource.toLowerCase().includes('u.s.') && marketSource.toLowerCase().includes('reference');
  const marketReference = marketAmount
    ? marketUrl
      ? `<a class="levelsref" href="${esc(marketUrl)}" target="_blank" rel="noopener" title="${employerBenchmark ? 'Median upper bound from this company’s other employer-posted ranges; not this role’s published salary' : 'Crowdsourced annual total compensation estimate; not an employer-posted salary range'}">${esc(marketSource)}${employerBenchmark ? ': ' : ' TC: '}${money(marketAmount)}</a>`
      : `<span class="levelsref estimate" title="Fallback estimate used only because no sourced compensation was available">Estimated TC: ${money(marketAmount)}</span>`
    : benchmarkAmount ? `<a class="levelsref" href="${esc(benchmark.source_url)}" target="_blank" rel="noopener" title="Levels.fyi crowdsourced annual total compensation: base plus annualized stock and bonus. Retrieved ${esc((benchmark.fetched_at || '').slice(0, 10))}.">Levels.fyi ${esc(benchmarkLabel)} TC: ${money(benchmarkAmount)}</a>` : '';
  const compensationHeadline = job.salary_text || (marketAmount ? `${usReference ? 'U.S. market TC reference' : employerBenchmark ? 'Company range benchmark' : 'Market TC estimate'}: ${money(marketAmount)}` : 'No compensation yet');
  const officialSource = ['greenhouse','lever','workable','apple','phenom','amazon','jibe','workday','ashby','google','microsoft','oracle','realtor','tesla','gm','teamtailor','schwab','procore'].includes(String(job.source || '').toLowerCase());
  const sourceLabel = officialSource ? 'Official ATS' : job.source === 'linkedin' ? 'LinkedIn' : (job.source || 'Imported');
  const sourceTitle = officialSource ? `Direct company recruiting feed (${job.source})` : `Listing source: ${sourceLabel}`;

  let companyCell = child ? '<span class="tree">alternate</span>' : esc(job.company || 'Needs review');
  if (!child && count > 1) {
    companyCell += `<div><button id="toggle-${options.group}" class="groupbtn" title="Show ${count - 1} alternate role${count > 2 ? 's' : ''} at ${esc(job.company)}" aria-expanded="false" onclick="toggleCompany('${options.group}',${count - 1})">▸ ${count} roles</button></div>`;
  }
  if (!child) {
    const savedLabel = strategicAuto || actualSaved ? '★ Apply' : '☆ Apply';
    const savedTitle = strategicAuto ? 'Automatically selected to apply as a major technology or AI company' : `${actualSaved ? 'Remove from' : 'Add to'} Selected to apply`;
    const practiceLabel = practiceSaved ? '✓ Practice' : '＋ Practice';
    const practiceTitle = strategicAuto ? 'Automatically selected to apply; unavailable for practice' : practiceSaved ? 'Remove this company from Selected as practice' : actualSaved ? 'Move this company from Selected to apply to Selected as practice' : 'Add this company to Selected as practice';
    companyCell += `<div class="saveactions"><button class="btn actualsave ${actualSaved ? 'actualsaved' : ''}" data-company="${esc(job.company)}" title="${savedTitle}" ${strategicAuto ? 'disabled' : ''} onclick="toggleActual(this)">${savedLabel}</button><button class="btn practicesave ${practiceSaved ? 'practicesaved' : ''}" data-company="${esc(job.company)}" title="${practiceTitle}" ${strategicAuto ? 'disabled' : ''} onclick="togglePractice(this)">${practiceLabel}</button></div>`;
  }

  const austinTitle = job.austin_presence
    ? job.austin_commute_place ? `${job.austin_commute_place} is in the Austin commute-zone mapping (~${job.austin_commute_minutes} min nominal drive)` : `${job.austin_job_count} Austin-area company signal${job.austin_job_count === 1 ? '' : 's'} found`
    : 'No Austin or mapped commute-zone evidence found';
  const remoteTitle = job.remote_presence ? `${job.remote_job_count} fully remote role${job.remote_job_count === 1 ? '' : 's'} found` : 'No fully remote roles found';
  const practiceTitle = job.burn_eligible ? 'Eligible for a practice application' : strategicAuto || actualSaved ? 'Selected to apply, so it is not a practice candidate' : 'Austin or remote presence makes this ineligible for practice';
  const fitSignals = child ? '<span class="alternate-label">Role-level matches</span>' : `<div class="fitbadges">${fitBadge('Austin', job.austin_presence, austinTitle)}${fitBadge('Remote', job.remote_presence, remoteTitle)}${fitBadge('Practice', job.burn_eligible, practiceTitle)}</div>`;
  const skillSignals = `<div class="skillchips" title="${esc(matches.join(', '))}">${chips || '<span class="subline">No resume matches</span>'}</div>`;

  return `<tr class="${child ? 'childrow' : 'companyparent'}" ${child ? `data-parent="${options.group}"` : ''}>
    <td class="prioritycell" data-label="Priority">${child ? `<div class="childscore">${job.actual_score}<small>match</small></div>` : `<div class="rankscore" title="Best match score among this company's roles">${options.matchScore}</div><div class="ranklabel">#${options.matchRank} match</div>`}</td>
    <td class="companycell" data-label="Company">${companyCell}</td>
    <td class="rolecell" data-label="Opportunity"><b title="${esc(job.title)}">${esc(job.title)}</b><div class="rolemeta"><span>${esc(job.location)}</span><span>${esc(job.work_arrangement)}</span><span class="sourcebadge ${officialSource ? 'official' : ''}" title="${esc(sourceTitle)}">${esc(sourceLabel)}</span><span class="agebadge ${ageClass}" title="Posted ${esc(job.date_posted || 'date unknown')}">${age}</span></div>${concern ? `<div class="concern reasonline" title="${esc(concern)}">⚠ ${esc(concern)}</div>` : ''}</td>
    <td class="fitcell" data-label="Fit &amp; resume">${fitSignals}${skillSignals}</td>
    <td class="paycell" data-label="Compensation"><strong>${esc(compensationHeadline)}</strong><div class="subline ${belowTarget ? 'belowtarget' : ''}">Application answer: ${answer}${belowTarget ? ' · below target' : ''}</div>${marketReference}</td>
    <td class="actioncell" data-label="Status & actions"><span class="status status-${String(status || 'new').toLowerCase()}">${esc(displayStatus)}</span><div class="rowactions"><button class="btn primary open-action" title="Open this job posting and mark it OPENED" aria-label="Open job posting" onclick="openJob(${job.id},'${esc(job.url)}')">Open role ↗</button><button class="btn icon-action" data-tooltip="Mark as applied" aria-label="Mark as applied" onclick="setStatus(${job.id},'APPLIED')">✓</button><button class="btn icon-action" data-tooltip="Skip this role" aria-label="Skip this role" onclick="setStatus(${job.id},'SKIPPED')">×</button><button class="btn icon-action" data-tooltip="Select company to apply" aria-label="Select company to apply" onclick="setStatus(${job.id},'PROTECTED')">◆</button></div></td>
  </tr>`;
}

function render(jobs) {
  const companyGroups = groups(jobs);
  const matchScore = group => Math.max(...group.map(job => Number(job.actual_score || 0)));
  const matchRanks = new Map([...companyGroups].sort((a, b) => matchScore(b) - matchScore(a)).map((group, index) => [companyKey(group), index + 1]));
  return companyGroups.map((group, index) => {
    const id = `g${index}`;
    const key = companyKey(group);
    const status = group.some(job => job.status === 'APPLIED') ? 'APPLIED' : group[0].status;
    const actualSaved = group.some(job => job.actual_saved);
    const practiceSaved = group.some(job => job.practice_saved);
    const strategicAuto = group.some(job => job.strategic_auto);
    return row(group[0], index, {group: id, count: group.length, status, actualSaved, practiceSaved, strategicAuto,
      matchScore: matchScore(group).toFixed(1), matchRank: matchRanks.get(key)}) +
      group.slice(1).map(job => row(job, index, {group: id, child: true, status, actualSaved, practiceSaved, strategicAuto})).join('');
  }).join('');
}

function renderNextMoves(jobs) {
  const panel = $('#nextMoves');
  const candidates = groups(jobs).map(group => group.reduce((best, job) => Number(job.actual_score || 0) > Number(best.actual_score || 0) ? job : best));
  const selected = [];
  const take = predicate => {
    const job = candidates.find(candidate => !selected.some(item => companyKey([item]) === companyKey([candidate])) && predicate(candidate));
    if (job) selected.push(job);
  };
  take(() => true);
  if (viewMode === 'all') {
    take(job => job.austin_presence || /austin/i.test(job.location || ''));
    take(job => job.age_days != null && job.age_days <= 7);
  }
  while (selected.length < Math.min(3, candidates.length)) take(() => true);
  if (!selected.length) { panel.hidden = true; panel.innerHTML = ''; return; }
  panel.hidden = false;
  const heading = viewMode === 'actual' ? 'Best roles selected to apply' : viewMode === 'practice' ? 'Your selected practice sequence' : 'Where Eli should focus next';
  const labels = viewMode === 'practice' ? ['Practice first','Practice second','Practice third'] : viewMode === 'all' ? ['Best overall','Best Austin fit','Fresh alternative'] : ['Apply next','Strong alternative','Keep warm'];
  const cards = selected.map((job, index) => {
    const effectiveComp = Number(job.salary_max || job.market_compensation || job.suggested_salary || 0);
    const signals = [job.age_days != null && job.age_days <= 7 ? 'Fresh' : '', job.austin_commute_place ? `${job.austin_commute_place} · ~${job.austin_commute_minutes} min` : job.austin_presence ? 'Austin area' : '', job.work_arrangement === 'remote' ? 'Remote' : '', job.ai_application ? 'AI application' : '', ['greenhouse','lever','workable','apple'].includes(String(job.source || '').toLowerCase()) ? 'Official ATS' : '', effectiveComp ? money(effectiveComp) : ''].filter(Boolean);
    const reason = job.actual_reason || job.reason || 'Strongest current match in this view.';
    const concern = (job.concerns || []).find(value => !/Austin presence|fully remote posting|Remote role|Protected company/i.test(value));
    const readyNow = Number(job.actual_score || 0) >= 8 && effectiveComp >= 240000 && (job.austin_presence || job.work_arrangement === 'remote') && job.age_days != null && job.age_days <= 7;
    const decision = readyNow ? 'APPLY NOW' : Number(job.actual_score || 0) >= 7.5 ? 'REVIEW TODAY' : 'KEEP WARM';
    return `<article class="next-move-card ${index === 0 ? 'primary-move' : ''}">
      <div class="move-rank"><small>${labels[index]}</small><strong>${Number(job.actual_score || 0).toFixed(1)}</strong><span>match</span></div>
      <div class="move-copy"><div class="move-company">${esc(job.company)} <span class="move-decision ${readyNow ? 'ready' : ''}">${decision}</span></div><h3 title="${esc(job.title)}">${esc(job.title)}</h3><p>${esc(job.location)} · ${signals.map(value => `<b>${esc(value)}</b>`).join(' ')}</p><div class="move-reason" title="${esc(reason)}"><b>Why:</b> ${esc(reason)}</div>${concern ? `<div class="move-watchout" title="${esc(concern)}"><b>Check:</b> ${esc(concern)}</div>` : ''}</div>
      <div class="move-actions"><button class="btn primary" onclick="openJob(${job.id},'${esc(job.url)}')">Open role</button>${viewMode === 'practice' ? '' : `<button class="btn ${job.actual_saved ? 'selected' : ''}" data-company="${esc(job.company)}" title="${job.actual_saved ? 'Remove this company from Selected to apply' : 'Add this company to Selected to apply'}" onclick="toggleActual(this)">${job.actual_saved ? '★ Apply' : '☆ Apply'}</button>`}</div>
    </article>`;
  }).join('');
  panel.innerHTML = `<div class="next-moves-heading"><div><small>NEXT-BEST ACTIONS</small><h2>${heading}</h2></div><p>Ranked by your match score, freshness, compensation, and Austin/remote fit.</p></div><div class="next-move-grid">${cards}</div>`;
}

function renderCorpusProgress(data) {
  const panel = $('#corpusProgress');
  const progress = data.corpus_progress || {};
  const jobTarget = Number(progress.job_target || 3000);
  const austinTarget = Number(progress.austin_proper_company_target || 300);
  const jobPercent = Math.min(100, Math.round(Number(data.corpus_total || 0) / jobTarget * 100));
  const austinPercent = Math.min(100, Math.round(Number(progress.austin_proper_company_count || 0) / austinTarget * 100));
  panel.innerHTML = `<div class="corpus-progress-intro"><small>MINING COVERAGE</small><b>Corpus targets</b><span>${data.corpus_companies} distinct companies · ${progress.direct_source_jobs || 0} direct-source postings · ${progress.linkedin_jobs || 0} LinkedIn postings</span></div>
    <div class="corpus-goal"><div><b>${data.corpus_total.toLocaleString()} <small>/ ${jobTarget.toLocaleString()}</small></b><span>relevant postings · ${Number(progress.jobs_remaining || 0).toLocaleString()} remaining</span></div><i><em style="width:${jobPercent}%"></em></i><strong>${jobPercent}%</strong></div>
    <div class="corpus-goal"><div><b>${Number(progress.austin_proper_company_count || 0).toLocaleString()} <small>/ ${austinTarget}</small></b><span>Austin-proper companies · ${Number(progress.austin_companies_remaining || 0).toLocaleString()} remaining</span></div><i><em style="width:${austinPercent}%"></em></i><strong>${austinPercent}%</strong></div>`;
}

function toggleCompany(id, alternateCount) {
  const rows = [...document.querySelectorAll(`[data-parent="${id}"]`)];
  const open = rows.some(row => !row.classList.contains('open'));
  const button = $(`#toggle-${id}`);
  rows.forEach(row => row.classList.toggle('open', open));
  button.textContent = `${open ? '▾ ' : '▸ '}${alternateCount + 1} roles`;
  button.setAttribute('aria-expanded', String(open));
}

function setPrimaryView(mode) {
  if (mode === 'jobs') return setView(viewMode);
  if (mode === 'resume') return setView(resumeViewMode);
  if (mode === 'practiceBuilder') {
    const practiceModes = {expectations:'practiceExpectations', hr:'practiceHr', behavioral:'practiceBehavioral', system_design:'practiceSystem', leetcode:'practiceLeetcode'};
    return setView(practiceModes[practiceTrack] || 'practiceExpectations');
  }
  if (mode === 'voiceInterview') return setView('voiceInterview');
  if (mode === 'localEvents') return setView('localEvents');
  if (mode === 'work') return setView(workViewMode);
  return setView('goals');
}

function setView(mode) {
  const jobModes = ['all', 'practice', 'actual'];
  const practiceModes = {practiceExpectations:'expectations', practiceHr:'hr', practiceBehavioral:'behavioral', practiceSystem:'system_design', practiceLeetcode:'leetcode'};
  if (jobModes.includes(mode)) { primaryView = 'jobs'; viewMode = mode; }
  else if (mode === 'resume' || mode === 'actualResume') { primaryView = 'resume'; resumeViewMode = mode; }
  else if (practiceModes[mode]) { primaryView = 'practiceBuilder'; practiceTrack = practiceModes[mode]; }
  else if (mode === 'voiceInterview') primaryView = 'voiceInterview';
  else if (mode === 'localEvents') primaryView = 'localEvents';
  else if (mode === 'goals' || mode === 'todo') { primaryView = 'work'; workViewMode = mode; }
  else { primaryView = 'work'; workViewMode = 'goals'; }

  const analysisMode = primaryView === 'resume' && resumeViewMode === 'resume';
  const actualResumeMode = primaryView === 'resume' && resumeViewMode === 'actualResume';
  const practiceBuilderMode = primaryView === 'practiceBuilder';
  const voiceInterviewMode = primaryView === 'voiceInterview';
  const localEventsMode = primaryView === 'localEvents';
  const goalsMode = primaryView === 'work' && workViewMode === 'goals';
  const todoMode = primaryView === 'work' && workViewMode === 'todo';
  const tableMode = primaryView === 'jobs';
  $('.toolbar').hidden = !tableMode;
  $('#corpusProgress').hidden = !tableMode;
  $('#nextMoves').hidden = !tableMode;
  $('.queue-heading').hidden = !tableMode;
  $('.tablewrap').hidden = !tableMode;
  $('#resumeAnalysis').hidden = !analysisMode;
  $('#actualResume').hidden = !actualResumeMode;
  $('#practiceBuilder').hidden = !practiceBuilderMode;
  $('#voiceInterview').hidden = !voiceInterviewMode;
  $('#localEvents').hidden = !localEventsMode;
  $('#goalsView').hidden = !goalsMode;
  $('#todoView').hidden = !todoMode;
  $('#jobsSubtabs').hidden = primaryView !== 'jobs';
  $('#resumeSubtabs').hidden = primaryView !== 'resume';
  $('#practiceSubtabs').hidden = primaryView !== 'practiceBuilder';
  $('#workSubtabs').hidden = primaryView !== 'work';
  $('#jobsTab').classList.toggle('selected', primaryView === 'jobs');
  $('#resumeGroupTab').classList.toggle('selected', primaryView === 'resume');
  $('#practiceBuilderTab').classList.toggle('selected', primaryView === 'practiceBuilder');
  $('#voiceInterviewTab').classList.toggle('selected', voiceInterviewMode);
  $('#localEventsTab').classList.toggle('selected', localEventsMode);
  $('#workTab').classList.toggle('selected', primaryView === 'work');
  $('#goalsTab').classList.toggle('selected', goalsMode);
  $('#todoTab').classList.toggle('selected', todoMode);
  for (const name of jobModes) $(`#${name}Tab`).classList.toggle('selected', primaryView === 'jobs' && viewMode === name);
  $('#resumeTab').classList.toggle('selected', analysisMode);
  $('#actualResumeTab').classList.toggle('selected', actualResumeMode);
  Object.entries(practiceModes).forEach(([name, key]) => $(`#${name}Tab`).classList.toggle('selected', practiceBuilderMode && practiceTrack === key));
  if (tableMode) {
    $('#status').value = viewMode === 'actual' ? '' : 'active';
    $('#sort').value = viewMode === 'practice' ? 'score' : 'actual';
    return load();
  }
  if (analysisMode) return loadResumeAnalysis();
  if (actualResumeMode) return loadResumeBuilder();
  if (practiceBuilderMode) return loadPracticeBuilder();
  if (voiceInterviewMode) return loadVoiceInterviews();
  if (localEventsMode) return loadLocalEvents();
  if (goalsMode) return loadGoals();
  if (todoMode) return loadTodos();
}

async function toggleActual(button) {
  const company = button.dataset.company;
  const response = await fetch('/api/companies/toggle', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({company})});
  const data = await response.json();
  toast(data.saved ? `${company} selected to apply` : `${company} removed from Selected to apply`);
  load();
}

async function togglePractice(button) {
  const company = button.dataset.company;
  const response = await fetch('/api/companies/toggle-practice', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({company})});
  const data = await response.json();
  if (!response.ok) return toast(data.error);
  toast(data.saved ? `${company} selected as practice` : `${company} removed from Selected as practice`);
  load();
}

async function load() {
  const requestId = ++loadRequestId;
  const query = new URLSearchParams({
    q: $('#search').value,
    location: $('#location').value,
    status: $('#status').value,
    sort: $('#sort').value,
    saved: viewMode === 'actual' ? '1' : '',
    practice: viewMode === 'practice' ? '1' : ''
  });
  const response = await fetch(`/api/jobs?${query}`);
  const data = await response.json();
  if (requestId !== loadRequestId) return;
  const companyGroups = groups(data.jobs);
  $('#applied').textContent = data.applied;
  $('#target').textContent = data.target;
  $('#actualCount').textContent = data.actual_count;
  $('#practiceCount').textContent = data.practice_count;
  $('#progress').style.width = `${Math.min(100, data.applied / data.target * 100)}%`;
  $('#count').textContent = `${data.jobs.length} visible · ${data.corpus_total} persisted · ${data.austin_company_count}/300 Austin-area companies`;
  $('#count').title = `${companyGroups.length} companies are visible in this filtered view; the full local corpus contains ${data.corpus_companies} companies.`;
  renderCorpusProgress(data);
  renderNextMoves(data.jobs);
  const empty = viewMode === 'actual' ? 'No companies selected to apply yet.' : viewMode === 'practice' ? 'No companies selected as practice yet.' : 'No companies match this view.';
  $('#jobs').innerHTML = render(data.jobs) || `<tr><td colspan="6" class="emptyrow">${empty}</td></tr>`;
}

async function setStatus(id, status) {
  await fetch(`/api/jobs/${id}/status`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({status})});
  toast(status === 'PROTECTED' ? 'Selected to apply' : status);
  load();
}

function openJob(id, url) {
  setStatus(id, 'OPENED');
  window.open(url, '_blank', 'noopener');
}

async function doImport(event) {
  event.preventDefault();
  const button = event.submitter;
  const box = $('#importText');
  button.disabled = true;
  const response = await fetch('/api/import', {method: 'POST', headers: {'Content-Type': 'text/plain'}, body: box.value});
  const data = await response.json();
  button.disabled = false;
  if (!response.ok) return toast(data.error);
  box.value = '';
  importDialog.close();
  toast(`Added ${data.created}, updated ${data.updated}`);
  load();
}

async function discoverLinkedIn(event) {
  event.preventDefault();
  const button = $('#liSubmit');
  button.disabled = true;
  button.textContent = 'Searching…';
  try {
    const response = await fetch('/api/discover/linkedin', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({keywords: $('#liKeywords').value, locations: $('#liLocations').value, days: +$('#liDays').value, limit: +$('#liLimit').value})});
    const data = await response.json();
    if (!response.ok) throw Error(data.error);
    linkedinDialog.close();
    toast(`Accepted ${data.accepted}; added ${data.created}`);
    load();
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = 'Search + rank';
  }
}

async function rescore() {
  const data = await (await fetch('/api/rescore', {method: 'POST'})).json();
  toast(`Re-scored ${data.updated}`);
  load();
}

async function enrichCompensation() {
  const button = $('#compButton');
  button.disabled = true;
  button.textContent = 'Finding compensation…';
  try {
    const response = await fetch('/api/enrich/compensation', {method: 'POST'});
    const data = await response.json();
    if (!response.ok) throw Error(data.error);
    toast(`Compensation filled: ${data.sourced} Levels.fyi, ${data.company_benchmarked} company benchmarks, ${data.estimated} fallback estimates`);
    load();
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = '$ Fill compensation';
  }
}

async function refreshCompanyBoards() {
  const button = $('#boardsButton');
  button.disabled = true;
  button.textContent = 'Refreshing…';
  try {
    const response = await fetch('/api/discover/company-boards', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
    const data = await response.json();
    if (!response.ok) throw Error(data.error);
    toast(`Priority sites: ${data.created} new roles from ${data.boards} supported companies`);
    load();
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = 'Priority company sites';
  }
}

function toast(text) {
  const element = $('#toast');
  element.textContent = text;
  element.classList.add('show');
  setTimeout(() => element.classList.remove('show'), 2300);
}

const actionTooltip = document.createElement('div');
actionTooltip.id = 'action-tooltip';
actionTooltip.setAttribute('role', 'tooltip');
document.body.append(actionTooltip);

function showActionTooltip(button) {
  const box = button.getBoundingClientRect();
  actionTooltip.textContent = button.dataset.tooltip;
  actionTooltip.classList.add('visible');
  const width = actionTooltip.offsetWidth;
  const left = Math.min(window.innerWidth - width - 10, Math.max(10, box.left + box.width / 2 - width / 2));
  actionTooltip.style.left = `${left}px`;
  actionTooltip.style.top = `${Math.max(8, box.top - actionTooltip.offsetHeight - 9)}px`;
}

function hideActionTooltip() { actionTooltip.classList.remove('visible'); }
document.addEventListener('pointerover', event => { const button = event.target.closest('.icon-action'); if (button) showActionTooltip(button); });
document.addEventListener('pointerout', event => { const button = event.target.closest('.icon-action'); if (button && !button.contains(event.relatedTarget)) hideActionTooltip(); });
document.addEventListener('focusin', event => { const button = event.target.closest('.icon-action'); if (button) showActionTooltip(button); });
document.addEventListener('focusout', event => { if (event.target.closest('.icon-action')) hideActionTooltip(); });

['search', 'location', 'status', 'sort'].forEach(id => $(`#${id}`).addEventListener(id === 'search' ? 'input' : 'change', load));
setView('all');
