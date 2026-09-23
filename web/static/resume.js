function builderField(label, id, value, options = {}) {
  const wide = options.wide ? ' full' : '';
  if (options.textarea) return `<label class="builder-field${wide}"><span>${esc(label)}</span><textarea id="${id}" rows="${options.rows || 4}">${esc(value)}</textarea></label>`;
  return `<label class="builder-field${wide}"><span>${esc(label)}</span><input id="${id}" value="${esc(value)}"></label>`;
}

function renderResumeSources(sources = []) {
  const panel = $('#resumeSources');
  if (!panel) return;
  const labels = {previous_resume:'Previous resume', performance_review:'Performance review', tech_stack:'Tech stack / projects', career_context:'Career context'};
  panel.innerHTML = sources.length ? sources.map(source => `<article class="source-item"><span>✓</span><div><b>${esc(source.name)}</b><small>${esc(labels[source.kind] || source.kind)} · ${Number(source.characters || 0).toLocaleString()} characters</small><p>${esc(source.preview || '')}</p></div></article>`).join('') : '<span class="analysis-empty">No context uploaded yet.</span>';
}

function renderResumeTargetContext(context = {}) {
  const panel = $('#resumeTargetContext');
  if (!panel) return;
  const skills = (context.top_skills || []).slice(0, 8);
  panel.innerHTML = context.role_count ? `
    <div><small>SELECTED-JOB TARGET SET</small><b>${Number(context.role_count).toLocaleString()} relevant roles across ${Number(context.company_count).toLocaleString()} selected companies</b><span>Filtered to realistic Senior/Staff backend, platform, infrastructure, and SRE opportunities.</span></div>
    <div class="target-skill-chips">${skills.map(item => `<span title="Found in ${Number(item.jobs).toLocaleString()} target roles">${esc(item.skill)} · ${Number(item.jobs).toLocaleString()}</span>`).join('')}</div>`
    : '<div><small>SELECTED-JOB TARGET SET</small><b>No relevant selected roles yet</b><span>Select companies to apply to, then refresh this builder.</span></div>';
}

async function uploadResumeSources(files) {
  if (!files?.length) return;
  const kind = $('#resumeSourceKind').value;
  for (const file of files) {
    try {
      const data = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = reject; reader.readAsDataURL(file); });
      const response = await fetch('/api/resume-builder/source', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name:file.name, type:file.type, kind, data})});
      const result = await response.json();
      if (!response.ok) throw Error(result.error);
      renderResumeSources(result.sources);
      toast(`Added ${file.name}`);
    } catch (error) { toast(error.message || `Could not read ${file.name}`); }
  }
  $('#resumeSourceFiles').value = '';
}

async function generateResumeDraft() {
  const button = $('#generateResumeButton');
  button.disabled = true; button.textContent = 'Reading evidence…';
  try {
    const response = await fetch('/api/resume-builder/generate', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({target:$('#resumeTarget').value})});
    const data = await response.json();
    if (!response.ok) throw Error(data.error);
    resumeBuilderData = data.resume;
    resumeTargetContext = data.targets || resumeTargetContext;
    renderResumeBuilderEditor(data.resume); renderResumeSources(data.sources);
    renderResumeTargetContext(resumeTargetContext);
    $('#actualResumeFrame').src = `/resume/actual?updated=${Date.now()}`;
    toast(`Draft targeted to ${data.resume.generation?.target_job_count || 0} selected roles`);
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; button.textContent = '✦ Generate with AI'; }
}

function resumeBuilderReadiness(data) {
  const contact = data.contact || {};
  const headline = String(contact.headline || '');
  const summary = String(data.summary || '');
  const skillText = Object.values(data.skills || {}).join(' ').toLowerCase();
  const experience = data.experience || [];
  const bullets = experience.flatMap(item => item.bullets || []);
  const metricBullets = bullets.filter(value => /\d|%|\$|latency|throughput|faster|reduc|improv/i.test(value));
  const resumeEvidence = `${summary} ${skillText} ${bullets.join(' ')}`.toLowerCase();
  const aiEvidence = /\b(ai|machine learning|ml|llm|agentic)\b|agent-orchestration/i.test(resumeEvidence);
  const targetSkills = (resumeTargetContext?.top_skills || []).slice(0, 8);
  const aliases = {
    'Reliability / SRE':['reliability','site reliability','sre'], 'API design':['api design','graphql','rest api'],
    'Distributed systems':['distributed system'], 'Data pipelines':['data pipeline','etl'],
    'Machine learning':['machine learning','ml platform'], 'Leadership':['leadership','led ','managed','mentor'],
  };
  const hasSkill = item => (aliases[item.skill] || [String(item.skill).toLowerCase()]).some(value => resumeEvidence.includes(value));
  const coveredTargetSkills = targetSkills.filter(hasSkill);
  const missingTargetSkills = targetSkills.filter(item => !hasSkill(item));
  const targetSkillPoints = targetSkills.length ? Math.round(16 * coveredTargetSkills.length / targetSkills.length) : 0;
  const checks = [
    {label:'Complete contact details', detail:'Phone, email, Austin location, and a clickable LinkedIn URL', points:10, earned:(contact.phone && contact.email && /austin/i.test(contact.location || '') ? 6 : 0) + (/^https?:\/\//i.test(contact.linkedin_url || contact.linkedin || '') ? 4 : 0), action:'Add your full LinkedIn profile URL.'},
    {label:'Targeted Senior → Staff headline', detail:'Names both level and backend/platform direction', points:15, earned:(/(senior|staff)/i.test(headline) && /(backend|platform|distributed|infrastructure|cloud|ai)/i.test(headline)) ? 15 : 0, action:'Make the headline explicitly target Senior or Staff backend/platform work.'},
    {label:'Outcome-led summary', detail:'Enough context plus a concrete scale or result', points:15, earned:summary.length >= 180 && /\d|\+|%|scale|high-availability/i.test(summary) ? 15 : Math.min(10, Math.round(summary.length / 24)), action:'Add years, system scale, and one measurable outcome to the summary.'},
    {label:'Selected-role technical coverage', detail:`Covers ${coveredTargetSkills.length} of the top ${targetSkills.length} recurring skills plus truthful AI evidence`, points:20, earned:Math.min(20, targetSkillPoints + (aiEvidence ? 4 : 0)), action:missingTargetSkills.length ? `Add ${missingTargetSkills[0].skill} only if your career evidence supports it.` : 'Keep the strongest selected-role skills tied to achievement bullets.'},
    {label:'Career evidence depth', detail:'Three roles and at least twelve focused bullets', points:20, earned:Math.min(20, experience.length * 4 + Math.min(8, bullets.length)), action:'Keep at least three roles and twelve high-signal bullets.'},
    {label:'Quantified impact', detail:'At least five bullets show scale, speed, reliability, or business results', points:20, earned:Math.min(20, metricBullets.length * 4), action:'Quantify more bullets with latency, reliability, volume, time, or cost.'},
  ];
  const score = checks.reduce((total, item) => total + item.earned, 0);
  const next = checks.filter(item => item.earned < item.points).sort((a,b) => (b.points-b.earned) - (a.points-a.earned))[0];
  return {score, checks, next};
}

function renderResumeBuilderHealth(data) {
  const panel = $('#resumeBuilderHealth');
  if (!panel || !data) return;
  const result = resumeBuilderReadiness(data);
  const tone = result.score >= 90 ? 'ready' : result.score >= 75 ? 'close' : 'work';
  panel.innerHTML = `<div class="readiness-score ${tone}"><strong>${result.score}</strong><span>/100</span><small>APPLICATION READINESS</small></div>
    <div class="readiness-main"><div class="readiness-heading"><div><small>SELECTED-JOB QUALITY CHECK</small><h3>${result.score >= 90 ? 'Ready for targeted applications' : 'Strengthen before the next application'}</h3></div><p><b>Next:</b> ${esc(result.next ? result.next.action : 'Keep the summary and top bullets aligned to the selected-job cohort.')}</p></div>
    <div class="readiness-meter"><i style="width:${result.score}%"></i></div><div class="readiness-checks">${result.checks.map(item => `<div class="readiness-check ${item.earned === item.points ? 'complete' : ''}" title="${esc(item.detail)}"><span>${item.earned === item.points ? '✓' : `${item.earned}/${item.points}`}</span><b>${esc(item.label)}</b></div>`).join('')}</div></div>`;
}

function experienceEditor(item, index) {
  return `<article class="experience-editor" data-experience-index="${index}">
    <div class="experience-heading"><b>Experience ${index + 1}</b><button type="button" class="builder-remove" title="Remove this experience section" onclick="removeResumeExperience(${index})">Remove</button></div>
    <div class="builder-field-grid">
      <label class="builder-field"><span>Company</span><input class="exp-company" value="${esc(item.company)}"></label>
      <label class="builder-field"><span>Business unit</span><input class="exp-business-unit" value="${esc(item.business_unit || '')}" placeholder="e.g. Platform Engineering"></label>
      <label class="builder-field"><span>Role</span><input class="exp-role" value="${esc(item.role)}"></label>
      <label class="builder-field"><span>Location</span><input class="exp-location" value="${esc(item.location)}"></label>
      <label class="builder-field"><span>Dates</span><input class="exp-dates" value="${esc(item.dates)}"></label>
      <label class="builder-field full"><span>Impact bullets · one per line</span><textarea class="exp-bullets" rows="7">${esc((item.bullets || []).join('\n'))}</textarea></label>
    </div>
  </article>`;
}

function renderResumeBuilderEditor(data) {
  const contact = data.contact || {};
  const skills = data.skills || {};
  const education = (data.education || [])[0] || {school:'', degree:''};
  const fields = $('#resumeBuilderFields');
  fields.className = 'resume-editor-fields';
  fields.innerHTML = `
    <section class="builder-card"><div class="builder-section-heading"><div><small>IDENTITY</small><h3>Header and target</h3></div></div><div class="builder-field-grid">
      ${builderField('Name','resume-name',contact.name)}${builderField('Target headline','resume-headline',contact.headline)}
      ${builderField('Location','resume-location',contact.location)}${builderField('Phone','resume-phone',contact.phone)}
      ${builderField('Email','resume-email',contact.email)}${builderField('LinkedIn URL','resume-linkedin',contact.linkedin_url || contact.linkedin)}
    </div></section>
    <section class="builder-card"><div class="builder-section-heading"><div><small>POSITIONING</small><h3>Professional summary</h3></div><span>Lead with scope and outcomes</span></div>${builderField('Summary','resume-summary',data.summary,{wide:true,textarea:true,rows:6})}</section>
    <section class="builder-card"><div class="builder-section-heading"><div><small>ATS COVERAGE</small><h3>Core skills</h3></div><span>Comma-separated</span></div><div class="builder-field-grid">
      ${['Languages','Platforms & Systems','Leadership'].map(label => `<label class="builder-field ${label === 'Platforms & Systems' ? 'full' : ''}"><span>${label}</span><textarea data-skill-label="${label}" rows="${label === 'Platforms & Systems' ? 3 : 2}">${esc(skills[label] || '')}</textarea></label>`).join('')}
    </div></section>
    <section class="builder-card"><div class="builder-section-heading"><div><small>CAREER EVIDENCE</small><h3>Experience</h3></div><button type="button" class="btn" onclick="addResumeExperience()">＋ Add experience</button></div><div id="resumeExperienceEditors">${(data.experience || []).map(experienceEditor).join('')}</div></section>
    <section class="builder-card"><div class="builder-section-heading"><div><small>EDUCATION</small><h3>Degree</h3></div></div><div class="builder-field-grid">${builderField('School','resume-school',education.school)}${builderField('Degree','resume-degree',education.degree)}</div></section>
    <footer class="builder-actions"><div><b>Saved to a local text file</b><span>Saving regenerates the downloadable PDF.</span></div><button id="resumeSaveButton" class="btn primary" type="submit">Save + rebuild PDF</button></footer>`;
  renderResumeBuilderHealth(data);
}

function syncResumeBuilderState() {
  if (!resumeBuilderData || !$('#resume-name')) return resumeBuilderData;
  const value = id => $(`#${id}`).value.trim();
  const skills = {};
  document.querySelectorAll('[data-skill-label]').forEach(field => skills[field.dataset.skillLabel] = field.value.trim());
  const experience = [...document.querySelectorAll('.experience-editor')].map(card => ({
    company: card.querySelector('.exp-company').value.trim(), business_unit: card.querySelector('.exp-business-unit').value.trim(), role: card.querySelector('.exp-role').value.trim(),
    location: card.querySelector('.exp-location').value.trim(), dates: card.querySelector('.exp-dates').value.trim(),
    bullets: card.querySelector('.exp-bullets').value.split('\n').map(line => line.trim()).filter(Boolean)
  }));
  resumeBuilderData = {
    version: 1,
    contact: {name:value('resume-name'), headline:value('resume-headline'), location:value('resume-location'), phone:value('resume-phone'), email:value('resume-email'), linkedin:'LinkedIn', linkedin_url:value('resume-linkedin')},
    summary: value('resume-summary'), skills, experience,
    education: [{school:value('resume-school'), degree:value('resume-degree')}]
  };
  return resumeBuilderData;
}

function markResumeDirty() {
  const state = $('#resumeSaveState');
  if (state) { state.textContent = 'Unsaved edits'; state.classList.add('dirty'); }
  if ($('#resume-name')) renderResumeBuilderHealth(syncResumeBuilderState());
}

function addResumeExperience() {
  syncResumeBuilderState();
  resumeBuilderData.experience.push({company:'', business_unit:'', role:'', location:'', dates:'', bullets:[]});
  renderResumeBuilderEditor(resumeBuilderData);
  markResumeDirty();
  document.querySelector('.experience-editor:last-child')?.scrollIntoView({behavior:'smooth', block:'center'});
}

function removeResumeExperience(index) {
  syncResumeBuilderState();
  resumeBuilderData.experience.splice(index, 1);
  renderResumeBuilderEditor(resumeBuilderData);
  markResumeDirty();
}

async function loadResumeBuilder() {
  const fields = $('#resumeBuilderFields');
  if (!resumeBuilderData) {
    fields.className = 'resume-editor-loading';
    fields.innerHTML = '<div class="resume-editor-loading">Loading editable resume…</div>';
    const response = await fetch('/api/resume-builder');
    const data = await response.json();
    if (!response.ok) return fields.innerHTML = `<div class="analysis-empty">${esc(data.error)}</div>`;
    resumeBuilderData = data.resume;
    resumeTargetContext = data.targets || {};
    renderResumeSources(data.sources);
    renderResumeTargetContext(resumeTargetContext);
    const aiStatus = $('#resumeAiStatus');
    if (aiStatus) {
      aiStatus.textContent = data.ai?.configured ? `${data.ai.model} ready` : 'API key required';
      aiStatus.className = `ai-status ${data.ai?.configured ? 'ready' : 'missing'}`;
      $('#generateResumeButton').title = data.ai?.configured ? `Generate using ${data.ai.model}` : 'Set OPENAI_API_KEY and restart the app';
    }
    renderResumeBuilderEditor(resumeBuilderData);
  }
  const frame = $('#actualResumeFrame');
  if (!frame.getAttribute('src')) frame.src = `/resume/actual?updated=${Date.now()}`;
}

async function saveResumeBuilder(event) {
  event.preventDefault();
  const button = $('#resumeSaveButton');
  button.disabled = true; button.textContent = 'Rebuilding…';
  const response = await fetch('/api/resume-builder', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({resume:syncResumeBuilderState()})});
  const data = await response.json();
  button.disabled = false; button.textContent = 'Save + rebuild PDF';
  if (!response.ok) return toast(data.error);
  resumeBuilderData = data.resume;
  const state = $('#resumeSaveState'); state.textContent = 'Saved locally'; state.classList.remove('dirty');
  $('#actualResumeFrame').src = `/resume/actual?updated=${Date.now()}`;
  toast('Resume saved and PDF rebuilt');
}

function demandBars(items, missing = false) {
  const max = Math.max(1, ...items.map(item => item.jobs));
  if (!items.length) return '<p class="analysis-empty">Nothing to show yet.</p>';
  return items.map(item => `<div class="demand-row">
    <div><b>${esc(item.skill)}</b><span>${item.jobs} jobs</span></div>
    <i><em class="${missing ? 'gap' : ''}" style="width:${Math.max(8, item.jobs / max * 100)}%"></em></i>
  </div>`).join('');
}

async function loadResumeAnalysis(version = 'current') {
  const panel = $('#resumeAnalysis');
  panel.innerHTML = '<div class="analysis-loading">Analyzing resume against the local job corpus…</div>';
  const response = await fetch(`/api/resume-analysis?version=${encodeURIComponent(version)}`);
  const data = await response.json();
  if (!response.ok) return panel.innerHTML = `<div class="analysis-empty">${esc(data.error)}</div>`;
  const covered = data.demanded.filter(item => item.on_resume).length;
  const coverage = Number(data.review.target_skill_coverage ?? Math.round(covered / Math.max(1, data.demanded.length) * 100));
  const allSkills = data.resume_skills.map(skill => `<span class="resume-chip">${esc(skill)}</span>`).join('');
  const reviewDimensions = data.review.dimensions.map(item => `<div class="review-dimension">
    <div class="review-score"><b>${item.score}</b><span>/10</span></div>
    <div><h4>${esc(item.name)}</h4><strong>${esc(item.assessment)}</strong><p>${esc(item.evidence)}</p></div>
  </div>`).join('');
  const recommendations = data.review.recommendations.map(item => `<article class="recommendation">
    <span class="priority ${item.priority.toLowerCase()}">${esc(item.priority)}</span>
    <div><h4>${esc(item.title)}</h4><p>${esc(item.why)}</p><b>Do this:</b> ${esc(item.action)}</div>
  </article>`).join('');
  panel.innerHTML = `
    <header class="analysis-hero">
      <div><small>LOCAL RESUME INTELLIGENCE · SELECTED COMPANIES</small><h2>${esc(data.name)} · Targeted resume analysis</h2><p>Compared with ${data.stats.jobs_analyzed} relevant roles across ${data.stats.selected_companies} selected companies. Unrelated specializations and duplicate locations are excluded.</p></div>
      <div class="analysis-version-control"><label><span>VERSION TO ANALYZE</span><select id="analysisVersion" onchange="loadResumeAnalysis(this.value)">${data.versions.map(item => `<option value="${esc(item.id)}" ${item.id === data.selected_version ? 'selected' : ''}>${esc(item.label)}</option>`).join('')}</select></label>${data.selected_version === 'v0' ? `<a class="btn primary download-resume" href="/resume/download" download>↓ Download original</a>` : `<span class="version-badge">${data.selected_version === 'current' ? 'Live builder draft' : 'Saved builder snapshot'}</span>`}</div>
    </header>
    <div class="analysis-grid stats-grid">
      <article><strong>${data.stats.strong_matches}</strong><span>Selected roles scoring 8+</span></article>
      <article><strong>${data.stats.fresh_jobs}</strong><span>Selected roles posted this week</span></article>
      <article><strong>${data.stats.selected_roles}</strong><span>Relevant selected roles analyzed</span></article>
      <article class="coverage-card"><div class="coverage-ring" style="--coverage:${coverage * 3.6}deg"><b>${coverage}%</b></div><span>Weighted selected-role skill coverage</span></article>
    </div>
    <div class="analysis-grid two-column">
      <article class="analysis-card"><div class="card-heading"><div><small>STRONGEST ALIGNMENT</small><h3>What the resume proves for selected roles</h3></div><span class="good-pill">${data.strengths.length} strengths</span></div>${demandBars(data.strengths)}</article>
      <article class="analysis-card gaps-card"><div class="card-heading"><div><small>VISIBLE GAPS</small><h3>Recurring selected-role requirements</h3></div><span class="gap-pill">${data.gaps.length} gaps</span></div>${demandBars(data.gaps, true)}<p class="analysis-note">A gap means the term is not explicit in this resume version; add it only when your career evidence supports it.</p></article>
    </div>
    <article class="analysis-card review-summary">
      <div class="card-heading"><div><small>SENIOR / STAFF REVIEW</small><h3>What the document communicates beyond keywords</h3></div><span class="good-pill">${data.review.word_count} words · ${data.review.quantified_outcomes} measured outcomes</span></div>
      <p class="review-headline">${esc(data.review.headline)}</p>
      <div class="review-dimensions">${reviewDimensions}</div>
    </article>
    <article class="analysis-card improvement-plan">
      <div class="card-heading"><div><small>IMPROVEMENT PLAN</small><h3>Highest-leverage changes for selected roles</h3></div><span class="gap-pill">${data.review.recommendations.length} actions</span></div>
      <div class="recommendations">${recommendations}</div>
    </article>
    <article class="analysis-card skill-inventory"><div class="card-heading"><div><small>DETECTED EVIDENCE</small><h3>Skills explicitly visible in the resume</h3></div></div><div class="resume-chips">${allSkills || '<span class="analysis-empty">No skills detected.</span>'}</div></article>`;
}
