let codingCurriculumTrack = 'production';
const codingCurriculumSections = {};
const codingSkillStatuses = {
  not_started: {label:'Not started', help:'This skill is waiting in your curriculum.'},
  learning: {label:'Learning', help:'Study the pattern and work through the guided resources.'},
  practicing: {label:'Practicing', help:'Solve the drills without relying on the solution.'},
  ready: {label:'Ready', help:'You can explain, implement, test, and analyze this pattern under interview constraints.'},
};

function syncPracticeBuilderState() {
  if (!practiceBuilderData) return practiceBuilderData;
  if (practiceTrack === 'leetcode') return practiceBuilderData;
  const track = practiceBuilderData.tracks[practiceTrack];
  const cards = [...document.querySelectorAll('.practice-question')];
  if (cards.length || !$('#practiceQuestionList')) {
    track.items = cards.map((card, index) => ({
      id: card.dataset.itemId || `${practiceTrack}-${index + 1}`,
      question: card.querySelector('.practice-question-input').value.trim(),
      answer: card.querySelector('.practice-answer-input').value.trim(),
    })).filter(item => item.question || item.answer);
  }
  return practiceBuilderData;
}

function renderPracticeLinks(links, sources = {}) {
  if (!links?.length) return '';
  const evidenceRank = {'Corroborated reports':0, 'Cross-report synthesis':1, 'Structural analogue':2, 'Single public report':3};
  const orderedLinks = [...links].sort((left, right) => (evidenceRank[left.evidence_quality] ?? 9) - (evidenceRank[right.evidence_quality] ?? 9));
  const primaryLinks = orderedLinks.filter(link => link.evidence_quality !== 'Single public report');
  const anecdotalLinks = orderedLinks.filter(link => link.evidence_quality === 'Single public report');
  const renderLink = (link, index, anecdotal = false) => {
    const linkUrl = String(link.url || '');
    const openLabel = linkUrl.includes('leetcode.com') ? 'Open judged problem' : linkUrl.includes('prachub.com') ? 'Open full practice brief' : 'Open source report';
    const evidence = (link.source_ids || []).map(id => sources[id]).filter(Boolean);
    const targets = link.target_companies || [];
    const fit = String(link.research_fit || 'Sourced practice');
    const fitClass = fit.toLowerCase().includes('analogue') ? 'analogue' : fit.toLowerCase().includes('synthesis') ? 'synthesis' : 'direct';
    return `<article class="practice-link ${esc(link.access_tier || 'free')} ${anecdotal ? 'anecdotal' : ''}">
    <div class="practice-link-meta"><span>${esc(link.platform || 'Practice platform')}</span><i title="${esc(link.access_detail || '')}">${esc(link.access || 'Check access')}</i></div>
    <div class="practice-research-fit ${fitClass}"><b>${esc(fit)}</b><span>${esc(link.evidence_quality || 'Single public report')}</span></div>
    <div class="practice-link-title"><strong>${esc(link.label)}</strong><em>${anecdotal ? 'Reported once' : index === 0 ? 'Start here' : 'Follow-up'}</em></div>
    <div class="practice-link-plan"><span>${esc(link.level || 'Exercise')}</span><span>${esc(link.time || 'Self-paced')}</span></div>
    ${link.prompt ? `<p class="practice-problem-brief"><b>Problem brief</b>${esc(link.prompt)}</p>` : ''}
    <p><b>Why this is here for you</b>${esc(link.note)}</p>
    ${targets.length ? `<div class="practice-targets"><b>Mapped to</b>${targets.map(company => `<span>${esc(company)}</span>`).join('')}</div>` : ''}
    ${link.deliverable ? `<div class="practice-deliverable"><b>Done when</b><span>${esc(link.deliverable)}</span></div>` : ''}
    <footer><div class="practice-evidence"><small>EVIDENCE</small>${evidence.map(source => `<a href="${esc(source.url)}" target="_blank" rel="noopener" title="${esc(source.evidence)}">${esc(source.publisher)} · ${esc(source.published)}</a>`).join('')}</div><a class="practice-open" href="${esc(link.url)}" target="_blank" rel="noopener" title="${esc(link.access_detail || link.note)}">${openLabel} <b aria-hidden="true">↗</b></a></footer>
  </article>`;
  };
  const primary = primaryLinks.length
    ? `<div class="practice-card-grid">${primaryLinks.map((link, index) => renderLink(link, index)).join('')}</div>`
    : `<div class="practice-no-primary"><b>No corroborated exact exercise yet.</b><span>Study the pattern above; do not memorize a one-off candidate report as an interview prediction.</span></div>`;
  const anecdotes = anecdotalLinks.length ? `<details class="practice-anecdotes"><summary><span><b>Optional candidate-reported prompts</b><small>Each was found in one public report. Useful for company context, not a predicted question.</small></span><em>${anecdotalLinks.length}</em></summary><div class="practice-card-grid">${anecdotalLinks.map((link, index) => renderLink(link, index, true)).join('')}</div></details>` : '';
  return `<div class="pattern-practice"><small>PRACTICE HERE · CURATED FOR ELI</small>${primary}${anecdotes}</div>`;
}

function codingExercises(curriculumTrack) {
  return (curriculumTrack?.sections || []).flatMap(section => section.exercises || []);
}

function exerciseTiming(minutes) {
  const total = Math.max(15, Number(minutes) || 30);
  const clarify = Math.max(2, Math.round(total * .12));
  const model = Math.max(3, Math.round(total * .16));
  const test = Math.max(4, Math.round(total * .22));
  return [
    ['Clarify', clarify],
    ['Model', model],
    ['Implement', total - clarify - model - test],
    ['Test + explain', test],
  ];
}

function renderCodingCurriculum(track) {
  const research = track.research || {};
  const curriculum = research.curriculum;
  if (!curriculum?.tracks?.length) return '<section class="coding-curriculum empty">The progressive coding curriculum could not be loaded.</section>';
  const sources = Object.fromEntries((research.sources || []).map(source => [source.id, source]));
  const progress = track.exercise_progress || {};
  const allExercises = curriculum.tracks.flatMap(codingExercises);
  const completedCount = allExercises.filter(exercise => progress[exercise.id]?.completed).length;
  let activeTrack = curriculum.tracks.find(item => item.id === codingCurriculumTrack) || curriculum.tracks[0];
  codingCurriculumTrack = activeTrack.id;
  const activeExercises = codingExercises(activeTrack);
  const activeCompleted = activeExercises.filter(exercise => progress[exercise.id]?.completed).length;
  const activeSections = activeTrack.sections || [];
  let activeSection = activeSections.find(item => item.id === codingCurriculumSections[activeTrack.id]) || activeSections[0];
  if (activeSection) codingCurriculumSections[activeTrack.id] = activeSection.id;
  const visibleExercises = activeSection?.exercises || [];
  const nextExercise = visibleExercises.find(exercise => !progress[exercise.id]?.completed) || visibleExercises[0];
  const tabs = curriculum.tracks.map(item => {
    const exercises = codingExercises(item);
    const complete = exercises.filter(exercise => progress[exercise.id]?.completed).length;
    return `<button type="button" class="coding-track-tab ${item.id === activeTrack.id ? 'selected' : ''}" onclick="setCodingCurriculumTrack('${esc(item.id)}')"><span>${esc(item.short_title || item.title)}</span><em>${complete}/${exercises.length}</em></button>`;
  }).join('');
  const sectionTabs = activeSections.map((section, sectionIndex) => {
    const sectionComplete = (section.exercises || []).filter(exercise => progress[exercise.id]?.completed).length;
    return `<button type="button" class="coding-section-tab ${section.id === activeSection?.id ? 'selected' : ''}" onclick="setCodingCurriculumSection('${esc(activeTrack.id)}','${esc(section.id)}')"><span>${String(sectionIndex + 1).padStart(2, '0')}</span><b>${esc(section.title)}</b><em>${sectionComplete}/${(section.exercises || []).length}</em></button>`;
  }).join('');
  const sections = (activeSection ? [activeSection] : []).map(section => {
    const sectionIndex = activeSections.indexOf(section);
    const exercises = (section.exercises || []).map(exercise => {
      const completion = progress[exercise.id] || {};
      const completed = Boolean(completion.completed);
      const evidence = (exercise.source_ids || []).map(id => sources[id]).filter(Boolean);
      const timing = exerciseTiming(exercise.minutes);
      const resource = exercise.resource_url ? `<a class="exercise-resource" href="${esc(exercise.resource_url)}" target="_blank" rel="noopener"><span>${esc(exercise.resource_label || 'Open practice resource')}</span><em>${esc(exercise.resource_access || 'Check access')}</em><b aria-hidden="true">↗</b></a>` : '';
      const references = (exercise.reference_links || []).length ? `<div class="exercise-references"><b>Focused references</b>${exercise.reference_links.map(link => `<a href="${esc(link.url)}" target="_blank" rel="noopener"><span>${esc(link.label)}</span><em>${esc(link.note || 'Reference')}</em><strong aria-hidden="true">↗</strong></a>`).join('')}</div>` : '';
      const context = exercise.context ? `<div class="exercise-context"><b>What is happening</b><p>${esc(exercise.context)}</p></div>` : '';
      const starter = exercise.starter_code ? `<div class="exercise-starter"><header><b>Starter code</b><span>Read it line by line before changing anything</span></header><pre><code>${esc(exercise.starter_code)}</code></pre></div>` : '';
      const deliverables = (exercise.deliverables || []).length ? `<div class="exercise-deliverables"><b>What you should produce</b><ol>${exercise.deliverables.map(item => `<li>${esc(item)}</li>`).join('')}</ol></div>` : '';
      const hints = (exercise.hints || []).length ? `<details class="exercise-help hints"><summary>Need a nudge? <span>Open hints only after five minutes</span></summary><ol>${exercise.hints.map(item => `<li>${esc(item)}</li>`).join('')}</ol></details>` : '';
      const walkthrough = (exercise.walkthrough || []).length ? `<details class="exercise-help walkthrough"><summary>Check your reasoning <span>Open after attempting the exercise</span></summary><ol>${exercise.walkthrough.map(item => `<li>${esc(item)}</li>`).join('')}</ol></details>` : '';
      return `<article class="curriculum-exercise ${String(exercise.difficulty || '').toLowerCase()} ${completed ? 'completed' : ''} ${exercise.id === nextExercise?.id ? 'next' : ''}">
        <header><div class="exercise-level"><span>${esc(exercise.difficulty)}</span><em>${esc(exercise.minutes)} min</em></div><button type="button" class="exercise-complete ${completed ? 'completed' : ''}" title="${completed ? 'Move this exercise back into your active queue' : 'Mark this exercise complete'}" onclick="toggleCodingExercise('${esc(exercise.id)}')">${completed ? '✓ Completed' : 'Mark complete'}</button></header>
        <div class="exercise-copy"><small>STEP ${sectionIndex + 1}.${(section.exercises || []).indexOf(exercise) + 1}${exercise.id === nextExercise?.id ? ' · START HERE' : ''}</small><h4>${esc(exercise.title)}</h4><p>${esc(exercise.objective)}</p></div>
        ${context}${starter}
        <div class="exercise-prompt"><b>Your task</b><p>${esc(exercise.prompt)}</p></div>
        ${deliverables}
        <div class="exercise-timing" aria-label="Suggested time plan">${timing.map(([label, value]) => `<span><b>${value}m</b><small>${esc(label)}</small></span>`).join('<i aria-hidden="true">→</i>')}</div>
        ${resource}${references}${hints}${walkthrough}
        <details class="exercise-guide"><summary>Practice checklist and finish line <span aria-hidden="true">⌄</span></summary><div><ul>${(exercise.checkpoints || []).map(item => `<li>${esc(item)}</li>`).join('')}</ul><p><b>Done when</b>${esc(exercise.done_when)}</p></div></details>
        <footer><div class="exercise-companies">${(exercise.companies || []).map(company => `<span>${esc(company)}</span>`).join('')}</div><div class="exercise-evidence"><small>${esc(exercise.evidence)}</small>${evidence.map(source => `<a href="${esc(source.url)}" target="_blank" rel="noopener" title="${esc(source.evidence)}">${esc(source.publisher)} ↗</a>`).join('')}</div></footer>
      </article>`;
    }).join('');
    const sectionComplete = (section.exercises || []).filter(exercise => progress[exercise.id]?.completed).length;
    return `<section class="curriculum-section"><header><span>${String(sectionIndex + 1).padStart(2, '0')}</span><div><small>PROGRESSIVE LADDER · EASY → HARD</small><h3>${esc(section.title)}</h3><p>${esc(section.description)}</p></div><em>${sectionComplete}/${(section.exercises || []).length} complete</em></header><div class="curriculum-exercise-grid">${exercises}</div></section>`;
  }).join('');
  const percent = allExercises.length ? Math.round(completedCount / allExercises.length * 100) : 0;
  return `<section class="coding-curriculum">
    <header class="curriculum-hero"><div><small>CURATED FOR ELI · UPDATED ${esc(curriculum.updated_at)}</small><h2>Build up—do not start stuck</h2><p>${esc(curriculum.principle)}</p></div><div class="curriculum-total"><strong>${completedCount}</strong><span>of ${allExercises.length}<br>exercises complete</span></div></header>
    <div class="curriculum-progress"><i><em style="width:${percent}%"></em></i><span>${percent}% complete</span></div>
    <section class="curriculum-how"><div><small>HOW TO USE THIS</small><h3>One exercise, three passes</h3></div><ol><li><span>1</span><p><b>Learn untimed</b>Open the checklist. Build the correct small case and understand every invariant.</p></li><li><span>2</span><p><b>Simulate the round</b>Use the suggested clock, speak aloud, and avoid autocomplete or solution tabs.</p></li><li><span>3</span><p><b>Prove readiness</b>Run edge cases, explain complexity and tradeoffs, then mark complete only if you can repeat it.</p></li></ol></section>
    <nav class="coding-track-tabs" aria-label="Coding curriculum sections">${tabs}</nav>
    <section class="curriculum-track-intro"><div><small>${esc(activeTrack.title).toUpperCase()}</small><h2>${esc(activeTrack.description)}</h2></div><p><b>What the interview feels like</b>${esc(activeTrack.interview_shape)}</p><span>${activeCompleted}/${activeExercises.length} complete</span></section>
    <nav class="coding-section-tabs" aria-label="${esc(activeTrack.short_title || activeTrack.title)} subsections">${sectionTabs}</nav>
    ${nextExercise ? `<aside class="curriculum-next"><div><small>YOUR NEXT EXERCISE</small><b>${esc(nextExercise.title)}</b><span>${esc(nextExercise.difficulty)} · ${esc(nextExercise.minutes)} minutes · begin with the checklist open</span></div><button type="button" onclick="document.querySelector('.curriculum-exercise.next')?.scrollIntoView({behavior:'smooth',block:'center'})">Go to exercise ↓</button></aside>` : ''}
    <div class="curriculum-sections">${sections}</div>
  </section>`;
}

function setCodingCurriculumTrack(trackId) {
  codingCurriculumTrack = trackId;
  renderPracticeBuilder();
}

function setCodingCurriculumSection(trackId, sectionId) {
  codingCurriculumTrack = trackId;
  codingCurriculumSections[trackId] = sectionId;
  renderPracticeBuilder();
}

async function toggleCodingExercise(exerciseId) {
  syncPracticeBuilderState();
  const track = practiceBuilderData.tracks.leetcode;
  track.exercise_progress ||= {};
  const completed = !track.exercise_progress[exerciseId]?.completed;
  track.exercise_progress[exerciseId] = {completed, completed_at:completed ? new Date().toISOString() : ''};
  renderPracticeBuilder();
  await savePracticeBuilder();
}

function renderCodingSkillResearch(track) {
  const research = track.research;
  if (!research?.patterns?.length) return '<section class="leetcode-research empty">No sourced company research is available yet.</section>';
  const sources = Object.fromEntries((research.sources || []).map(source => [source.id, source]));
  const progress = track.pattern_progress || {};
  const statusFor = pattern => codingSkillStatuses[progress[pattern.id]?.status] ? progress[pattern.id].status : 'not_started';
  const readyCount = research.patterns.filter(pattern => statusFor(pattern) === 'ready').length;
  const activeCount = research.patterns.filter(pattern => ['learning','practicing'].includes(statusFor(pattern))).length;
  const readyPercent = Math.round(readyCount / research.patterns.length * 100);
  const nextPattern = research.patterns.find(pattern => statusFor(pattern) !== 'ready') || research.patterns[0];
  const patterns = research.patterns.map(pattern => {
    const evidence = (pattern.source_ids || []).map(id => sources[id]).filter(Boolean);
    const confidence = String(pattern.confidence || 'medium').toLowerCase();
    const companies = pattern.companies || [];
    const visibleCompanies = companies.slice(0, 4);
    const remaining = companies.length - visibleCompanies.length;
    const status = statusFor(pattern);
    const statusMeta = codingSkillStatuses[status];
    return `<details class="leetcode-pattern" ${pattern.id === nextPattern.id ? 'open' : ''}>
      <summary>
        <span class="pattern-rank">${String(pattern.priority).padStart(2, '0')}</span>
        <span class="pattern-title"><small>${esc(pattern.kind)} · ${esc(confidence)} confidence</small><b>${esc(pattern.title)}</b></span>
        <span class="pattern-companies">${visibleCompanies.map(company => `<i>${esc(company)}</i>`).join('')}${remaining > 0 ? `<i class="more">+${remaining}</i>` : ''}</span>
        <span class="pattern-status ${status}">${esc(statusMeta.label)}</span>
        <span class="pattern-expand" aria-hidden="true">⌄</span>
      </summary>
      <div class="pattern-body"><p>${esc(pattern.why)}</p><div class="pattern-columns">
        <div><small>LEARN</small><ul>${pattern.learn.map(item => `<li>${esc(item)}</li>`).join('')}</ul></div>
        <div><small>PRACTICE DRILLS</small><ul>${pattern.drills.map(item => `<li>${esc(item)}</li>`).join('')}</ul></div>
      </div>${renderPracticeLinks(pattern.practice_links, sources)}<div class="pattern-progress-actions"><div><small>YOUR PROGRESS</small><b>${esc(statusMeta.label)}</b><span>${esc(statusMeta.help)}</span></div><div role="group" aria-label="Progress for ${esc(pattern.title)}">${Object.entries(codingSkillStatuses).map(([key, value]) => `<button type="button" class="${status === key ? 'selected' : ''}" title="${esc(value.help)}" onclick="setCodingSkillStatus('${esc(pattern.id)}','${key}')">${esc(value.label)}</button>`).join('')}</div></div><div class="pattern-company-list"><small>COMPANY SIGNALS</small><span>${companies.map(company => esc(company)).join(' · ')}</span></div><div class="pattern-evidence"><small>EVIDENCE</small>${evidence.map(source => `<a href="${esc(source.url)}" target="_blank" rel="noopener" title="${esc(source.evidence)}">${esc(source.publisher)} · ${esc(source.published)}</a>`).join('')}</div></div>
    </details>`;
  }).join('');
  const uncovered = (research.uncovered_companies || []).map(company => `<span>${esc(company)}</span>`).join('');
  const qualityOrder = ['Corroborated reports','Cross-report synthesis','Structural analogue','Single public report'];
  const qualitySummary = qualityOrder.map(label => `<li class="${label.toLowerCase().replaceAll(' ','-')}"><strong>${esc(research.evidence_quality_summary?.[label] || 0)}</strong><span>${esc(label)}</span></li>`).join('');
  return `<section class="leetcode-research">
    <header class="leetcode-research-head"><div><small>SELECTED-COMPANY RESEARCH · UPDATED ${esc(research.updated_at)}</small><h3>Your mixed-loop practice plan</h3><p><b>Assume both DSA and practical coding unless the recruiter says otherwise.</b> Start with practical implementation, then the top algorithm patterns. ${esc(research.scope)}</p></div><div class="research-coverage"><strong>${research.coverage_count}</strong><span>of ${research.selected_count}<br>company families covered</span></div></header>
    <section class="skill-progress-overview" aria-label="Coding skill progress"><div class="skill-progress-count"><strong>${readyCount}</strong><span>of ${research.patterns.length}<br>skills ready</span></div><div class="skill-progress-meter"><div><b>${readyPercent}% interview-ready</b><span>${activeCount} active · ${research.patterns.length - readyCount - activeCount} not started</span></div><i><em style="width:${readyPercent}%"></em></i></div><div class="skill-next"><small>WORK ON NEXT</small><b>${esc(nextPattern.title)}</b><span>Priority ${nextPattern.priority} · ${esc(nextPattern.kind)}</span></div></section>
    <aside class="research-quality"><div><small>HOW TO READ THESE PROBLEMS</small><b>Patterns are researched; exact questions are not promises.</b><p>“Single public report” is an anecdote and should be optional company-specific practice. Prioritize corroborated patterns and transferable invariants over memorizing prompts.</p></div><ul>${qualitySummary}</ul></aside>
    <div class="leetcode-patterns">${patterns}</div>
    <details class="research-method"><summary>Research method and companies still needing evidence</summary><p>${esc(research.methodology)}</p><div class="uncovered-companies">${uncovered || '<span>All selected companies covered</span>'}</div></details>
  </section>`;
}

async function setCodingSkillStatus(patternId, status) {
  if (!codingSkillStatuses[status]) return;
  syncPracticeBuilderState();
  const track = practiceBuilderData.tracks.leetcode;
  track.pattern_progress ||= {};
  track.pattern_progress[patternId] = {status, updated_at:new Date().toISOString()};
  renderPracticeBuilder();
  await savePracticeBuilder();
  toast(`Coding skill marked ${codingSkillStatuses[status].label.toLowerCase()}`);
}

function renderInterviewExpectations(expectations) {
  if (!expectations?.phases?.length) return '<div class="practice-empty">Interview expectations could not be loaded.</div>';
  const phases = expectations.phases.map(phase => `<article class="expectation-phase">
    <div class="phase-number">${esc(phase.number)}</div>
    <div class="phase-copy"><small>${esc(phase.duration)} · ${esc(phase.format)}</small><h3>${esc(phase.title)}</h3><p>${esc(phase.expect)}</p><div><b>Your job</b><span>${esc(phase.your_goal)}</span></div></div>
  </article>`).join('');
  const rounds = expectations.rounds.map(round => {
    const companies = round.companies || [];
    const visible = companies.slice(0, 5);
    return `<article class="expectation-round-card">
      <header><div><span class="round-likelihood">${esc(round.likelihood)}</span><h3>${esc(round.title)}</h3></div><small>${esc(round.rounds)}</small></header>
      <dl><div><dt>What happens</dt><dd>${esc(round.expect)}</dd></div><div><dt>What strong looks like</dt><dd>${esc(round.strong)}</dd></div></dl>
      ${companies.length ? `<div class="round-company-chips" aria-label="Selected-company signals">${visible.map(company => `<span>${esc(company)}</span>`).join('')}${companies.length > visible.length ? `<span>+${companies.length - visible.length}</span>` : ''}</div>` : ''}
    </article>`;
  }).join('');
  const allocation = expectations.practice_allocation || {};
  const codingSplit = (allocation.coding_split || []).map(item => `<article><div><strong>${esc(item.percent)}%</strong><span>${esc(item.label)}</span></div><p>${esc(item.detail)}</p></article>`).join('');
  const weeklySplit = (allocation.weekly_split || []).map(item => `<li><div><b>${esc(item.label)}</b><span>${esc(item.detail)}</span></div><strong>${esc(item.percent)}%</strong><i><em style="width:${Number(item.percent) || 0}%"></em></i></li>`).join('');
  const adjustments = (allocation.adjustments || []).map(item => `<article><div class="adjustment-heading"><b>${esc(item.trigger)}</b><span>${esc(item.dsa)}% DSA · ${esc(item.practical)}% practical</span></div><div class="adjustment-meter"><i style="width:${Number(item.dsa) || 0}%"></i><em style="width:${Number(item.practical) || 0}%"></em></div><p>${esc(item.note)}</p></article>`).join('');
  const companyFormats = expectations.company_formats || [];
  const formatMeta = {
    'Mixed': {css:'mixed', label:'Mixed evidence', split:'50 / 50', note:'Both algorithm and practical coding signals'},
    'Practical-leaning': {css:'practical', label:'Practical-leaning', split:'30 / 70', note:'More implementation and machine-coding evidence'},
    'DSA-leaning': {css:'dsa', label:'DSA-leaning', split:'70 / 30', note:'More algorithm and data-structure evidence'},
    'Confirm with recruiter': {css:'confirm', label:'Confirm first', split:'50 / 50', note:'Not enough current evidence to specialize'},
  };
  const formatSummary = Object.entries(formatMeta).map(([format, meta]) => `<article class="company-format-stat ${meta.css}"><strong>${esc(expectations.company_format_summary?.[format] || 0)}</strong><span>${esc(meta.label)}</span><small>${esc(meta.split)} DSA / practical</small></article>`).join('');
  const companyFormatGroups = Object.entries(formatMeta).map(([format, meta]) => {
    const companies = companyFormats.filter(item => item.format === format);
    const rows = companies.map(item => {
      const signals = [
        ...(item.algorithm_signals || []).slice(0, 2).map(signal => ({kind:'DSA', text:signal})),
        ...(item.practical_signals || []).slice(0, 2).map(signal => ({kind:'Practical', text:signal})),
        ...(item.depth_signals || []).slice(0, 1).map(signal => ({kind:'Depth', text:signal})),
      ].slice(0, 4);
      return `<article class="company-format-row"><div class="company-format-company"><b>${esc(item.company)}</b><span>${esc(item.evidence_count)} research ${item.evidence_count === 1 ? 'signal' : 'signals'}</span></div><div class="company-format-ratio"><strong>${esc(item.dsa)} / ${esc(item.practical)}</strong><span>DSA / practical</span><i><em style="width:${Number(item.dsa) || 0}%"></em><b style="width:${Number(item.practical) || 0}%"></b></i></div><div class="company-format-reason"><p>${esc(item.reason)}</p>${signals.length ? `<div>${signals.map(signal => `<span class="${signal.kind.toLowerCase()}"><b>${esc(signal.kind)}</b>${esc(signal.text)}</span>`).join('')}</div>` : '<div><span class="unknown"><b>Next step</b>Ask the recruiter before changing your plan</span></div>'}</div></article>`;
    }).join('');
    return `<details class="company-format-group ${meta.css}" ${format === 'Mixed' ? 'open' : ''}><summary><span><b>${esc(meta.label)}</b><small>${esc(meta.note)}</small></span><em>${companies.length} ${companies.length === 1 ? 'company' : 'companies'} · ${esc(meta.split)} DSA / practical</em><i aria-hidden="true">⌄</i></summary><div class="company-format-list">${rows}</div></details>`;
  }).join('');
  const sessions = (expectations.practice_sessions || []).map((session, index) => `<details class="practice-session" ${index === 0 ? 'open' : ''}><summary><span><small>${esc(session.frequency)} · ${esc(session.duration)}</small><b>${esc(session.title)}</b></span><i aria-hidden="true">⌄</i></summary><ol>${session.steps.map(step => `<li>${esc(step)}</li>`).join('')}</ol><p><b>Rule:</b> ${esc(session.rule)}</p></details>`).join('');
  const week = (expectations.weekly_plan || []).map(item => `<li><time>${esc(item.day)}</time><div><b>${esc(item.focus)}</b><span>${esc(item.work)}</span></div><strong>${esc(item.minutes)}m</strong></li>`).join('');
  const gates = (expectations.readiness_gates || []).map(item => `<li><span aria-hidden="true">✓</span><div><b>${esc(item.area)}</b><p>${esc(item.ready)}</p></div></li>`).join('');
  const pacing = expectations.technical_pacing.map(step => `<li><time>${esc(step.minutes)}</time><div><b>${esc(step.title)}</b><span>${esc(step.action)}</span></div></li>`).join('');
  const questions = expectations.recruiter_questions.map((question, index) => `<li><span>${index + 1}</span><p>${esc(question)}</p></li>`).join('');
  const sources = expectations.sources.map(source => `<a href="${esc(source.url)}" target="_blank" rel="noopener"><span><small>${esc(source.company)}</small><b>${esc(source.label)}</b><em>${esc(source.note)}</em></span><strong aria-hidden="true">↗</strong></a>`).join('');
  return `<div class="expectations-view">
    <header class="expectations-hero"><div><small>INTERVIEW PREPARATION · UPDATED ${esc(expectations.updated_at)}</small><h2>Know the loop before you enter it</h2><p>${esc(expectations.scope)}</p><div class="expectation-caveat"><b>Working expectation, not a guarantee.</b> Your recruiter should confirm the exact sequence.</div></div><div class="expectations-coverage"><strong>${esc(expectations.evidence_coverage_count)}</strong><span>of ${esc(expectations.selected_count)} selected<br>company families researched</span></div></header>
    <section class="expectations-section allocation-section"><div class="expectations-heading"><small>THE SHORT ANSWER</small><h2>${esc(allocation.headline)}</h2><p>${esc(allocation.explanation)}</p></div><div class="coding-split">${codingSplit}</div><div class="allocation-layout"><div><small>YOUR DEFAULT WEEK</small><ul class="weekly-allocation">${weeklySplit}</ul></div><div><small>CHANGE IT AFTER THE RECRUITER CALL</small><div class="allocation-adjustments">${adjustments}</div></div></div><p class="allocation-caveat">This is a preparation prior, not a claim that companies use an exact statistical 50/50 split. Public reports reveal likely formats; only your recruiter can confirm your loop.</p></section>
    <section class="expectations-section company-format-section"><div class="expectations-heading"><small>YOUR SELECTED COMPANIES</small><h2>Which companies look mixed—and which do not?</h2><p>This is a research-backed preparation recommendation for each company, not the company's official name for its process. The ratio applies only to coding practice; Senior/Staff loops still usually include system design and behavioral or project-depth rounds.</p></div><div class="company-format-summary">${formatSummary}</div><div class="company-format-groups">${companyFormatGroups}</div><p class="company-format-caveat"><b>Use this as a starting point.</b> Team, role, and interviewer can change the format. Ask the recruiter exactly how many coding rounds you have and whether each is algorithms, practical implementation, debugging, or a mix.</p></section>
    <section class="expectations-section"><div class="expectations-heading"><small>THE LIKELY SEQUENCE</small><h2>From first call to decision</h2><p>The names vary, but most Senior/Staff processes reduce to these four phases.</p></div><div class="expectation-timeline">${phases}</div></section>
    <section class="expectations-section"><div class="expectations-heading"><small>THE “MIXED LOOP” EXPLAINED</small><h2>What the main loop will test</h2><p>“Mixed” means coding is only one evidence stream. You still need algorithms, but you are also evaluated on production judgment, architecture, influence, and depth.</p></div><div class="expectation-round-grid">${rounds}</div></section>
    <section class="expectations-section"><div class="expectations-heading"><small>HOW TO PRACTICE</small><h2>Use the same shape as the actual round</h2><p>Timed work, spoken reasoning, runnable output, and a short retrospective. Open a session to see the exact recipe.</p></div><div class="practice-session-grid">${sessions}</div></section>
    <div class="expectations-two-column prep-execution"><section class="expectations-section"><div class="expectations-heading compact"><small>A CONCRETE DEFAULT</small><h2>Your repeatable seven-day plan</h2><p>About 9 hours including a Saturday mini-loop. Reduce volume by dropping Saturday—not by removing all design or behavioral work.</p></div><ol class="weekly-practice-plan">${week}</ol></section><section class="expectations-section readiness-section"><div class="expectations-heading compact"><small>WHAT TO DO FROM THERE</small><h2>Advance when the evidence is repeatable</h2><p>Do not count questions completed. Use these gates to decide whether to move from learning to mocks and applications.</p></div><ul class="readiness-gates">${gates}</ul></section></div>
    <div class="expectations-two-column"><section class="expectations-section"><div class="expectations-heading compact"><small>INSIDE A TECHNICAL ROUND</small><h2>A simple 45–55 minute rhythm</h2></div><ol class="technical-pacing">${pacing}</ol></section>
    <section class="expectations-section recruiter-brief"><div class="expectations-heading compact"><small>REMOVE THE GUESSWORK</small><h2>Ask before you schedule</h2><p>Copy these into your recruiter call. The answers decide how you divide practice time.</p></div><ol class="recruiter-question-list">${questions}</ol></section></div>
    <section class="expectations-section official-examples"><div class="expectations-heading compact"><small>OFFICIAL EXAMPLES</small><h2>What employers say directly</h2><p>Use these as concrete examples—not universal rules.</p></div><div class="expectation-sources">${sources}</div></section>
  </div>`;
}

function renderPracticeBuilder() {
  const panel = $('#practiceBuilder');
  if (practiceTrack === 'expectations') {
    panel.innerHTML = renderInterviewExpectations(practiceBuilderData?.expectations);
    return;
  }
  const track = practiceBuilderData?.tracks?.[practiceTrack];
  if (!track) return panel.innerHTML = '<div class="practice-empty">This practice track could not be loaded.</div>';
  const research = practiceTrack === 'leetcode' ? renderCodingCurriculum(track) : '';
  let workspace = '';
  if (practiceTrack !== 'leetcode') {
    const questions = (track.items || []).map((item, index) => `<article class="practice-question" data-item-id="${esc(item.id)}">
      <div class="practice-question-heading"><small>QUESTION ${index + 1}</small><button class="practice-remove" type="button" onclick="removePracticeQuestion(${index})">Remove</button></div>
      <label class="practice-field"><span>Question</span><input class="practice-question-input" value="${esc(item.question)}" oninput="markPracticeDirty()"></label>
      <label class="practice-field"><span>Your answer</span><textarea class="practice-answer-input" rows="8" oninput="markPracticeDirty()">${esc(item.answer)}</textarea></label>
    </article>`).join('');
    const todo = `<article class="practice-todo ${track.todo.done ? 'done' : ''}"><button type="button" title="${track.todo.done ? 'Reopen this research todo' : 'Mark this research todo complete'}" onclick="togglePracticeTrackTodo()">${track.todo.done ? '✓' : ''}</button><div><small>${track.todo.done ? 'RESEARCH TODO · DONE' : 'RESEARCH TODO · NEXT'}</small><p>${esc(track.todo.text)}</p></div></article>`;
    const questionList = `<div id="practiceQuestionList" class="practice-question-list">${questions || '<div class="practice-empty">No questions yet. Add the first one below.</div>'}</div>`;
    const actions = `<footer class="practice-actions"><div><b>Keep your own solution notes</b><span>Use this workspace after working the ranked practice links.</span></div><div class="practice-action-buttons"><button class="btn" type="button" onclick="addPracticeQuestion()">＋ Add question</button><button id="practiceSaveButton" class="btn primary" type="button" onclick="savePracticeBuilder()">Save answers</button></div></footer>`;
    workspace = `${todo}${questionList}${actions}`;
  }
  const hero = practiceTrack === 'leetcode' ? '' : `<header class="practice-hero"><div><small>INTERVIEW PRACTICE</small><h2>${esc(track.title)}</h2><p>${esc(track.description)}</p></div></header>`;
  panel.innerHTML = `${hero}${research}${workspace}`;
}

function markPracticeDirty() {
  const state = $('#practiceSaveState');
  if (state) { state.textContent = 'Unsaved edits'; state.classList.add('dirty'); }
}

function addPracticeQuestion() {
  syncPracticeBuilderState();
  practiceBuilderData.tracks[practiceTrack].items.push({id:`${practiceTrack}-${Date.now()}`, question:'', answer:''});
  renderPracticeBuilder();
  markPracticeDirty();
  document.querySelector('.practice-question:last-child input')?.focus();
}

function removePracticeQuestion(index) {
  syncPracticeBuilderState();
  practiceBuilderData.tracks[practiceTrack].items.splice(index, 1);
  renderPracticeBuilder();
  markPracticeDirty();
}

async function togglePracticeTrackTodo() {
  syncPracticeBuilderState();
  const todo = practiceBuilderData.tracks[practiceTrack].todo;
  todo.done = !todo.done;
  renderPracticeBuilder();
  await savePracticeBuilder();
}

async function loadPracticeBuilder() {
  const panel = $('#practiceBuilder');
  const refreshResearch = !practiceBuilderData || practiceTrack === 'leetcode' || practiceTrack === 'expectations';
  if (refreshResearch) {
    panel.innerHTML = '<div class="practice-loading">Loading practice workspace…</div>';
    const response = await fetch(`/api/practice-builder?refresh=${Date.now()}`, {cache:'no-store'});
    const data = await response.json();
    if (!response.ok) return panel.innerHTML = `<div class="practice-empty">${esc(data.error)}</div>`;
    if (!practiceBuilderData) {
      practiceBuilderData = data.practice;
    } else {
      // Research and expectations are generated server-side. Refresh only those fields so
      // an open tab cannot retain an obsolete curriculum or discard unsaved editable notes.
      practiceBuilderData.expectations = data.practice.expectations;
      practiceBuilderData.tracks.leetcode.research = data.practice.tracks.leetcode.research;
      practiceBuilderData.tracks.leetcode.pattern_progress = data.practice.tracks.leetcode.pattern_progress;
      practiceBuilderData.tracks.leetcode.exercise_progress = data.practice.tracks.leetcode.exercise_progress;
    }
  }
  renderPracticeBuilder();
}

let eventFilter = 'recommended';

function localEventDate(value) {
  const date = new Date(value);
  return {month:date.toLocaleDateString('en-US',{month:'short'}).toUpperCase(), day:date.getDate(), when:date.toLocaleDateString('en-US',{weekday:'short',month:'short',day:'numeric'}) + ' · ' + date.toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit'})};
}

function renderLocalEvents() {
  const panel = $('#localEvents');
  const data = localEventsData;
  if (!data) return;
  const upcoming = data.events.filter(event => event.starts_at.slice(0,10) >= data.today && event.status !== 'passed');
  const recommended = upcoming.filter(event => event.recommendation === 'recommended');
  const visible = upcoming.filter(event => eventFilter === 'all' || (eventFilter === 'recommended' ? event.recommendation === 'recommended' : event.category === eventFilter));
  const counts = Object.fromEntries(['learn','hackathon','recruiting','networking'].map(category => [category, upcoming.filter(event => event.category === category).length]));
  const filters = [['recommended','For you',recommended.length],['all','All',upcoming.length],['learn','Learn',counts.learn],['hackathon','Hackathons',counts.hackathon],['recruiting','Recruiting',counts.recruiting],['networking','Networking',counts.networking]].map(([key,label,count]) => `<button class="${eventFilter === key ? 'selected' : ''}" onclick="eventFilter='${key}';renderLocalEvents()">${label} <span>${count}</span></button>`).join('');
  const cards = visible.map(event => { const date = localEventDate(event.starts_at); return `<article class="local-event-card ${event.status} ${event.recommendation}"><div class="event-date"><small>${date.month}</small><strong>${date.day}</strong></div><div class="event-details"><div class="event-meta"><span class="event-kind ${event.category}">${esc(event.category)}</span><span>${esc(date.when)}</span></div><div class="event-fit ${event.recommendation}"><b>${esc(event.recommendation_label)}</b><span>${esc(event.fit_score)}% profile fit</span></div><h3>${esc(event.title)}</h3><p>${esc(event.description)}</p><p class="event-fit-reason"><b>Why for you:</b> ${esc(event.fit_reason)}</p>${event.skill_matches?.length ? `<div class="event-skill-matches">${event.skill_matches.map(skill => `<span>${esc(skill)}</span>`).join('')}</div>` : ''}<div class="event-place"><b>${esc(event.venue)}</b><span>${esc(event.address)} · ${esc(event.cost)}</span></div></div><div class="event-actions"><span class="event-source">Verified via ${esc(event.source)}</span><a class="btn primary" href="${esc(event.url)}" target="_blank" rel="noopener">View event ↗</a><select aria-label="Your status for ${esc(event.title)}" onchange="setLocalEventStatus('${esc(event.id)}',this.value)"><option value="new" ${event.status==='new'?'selected':''}>Not decided</option><option value="interested" ${event.status==='interested'?'selected':''}>Interested</option><option value="going" ${event.status==='going'?'selected':''}>Going</option><option value="passed">Pass</option></select></div></article>`; }).join('');
  panel.innerHTML = `<header class="practice-hero events-hero"><div><small>LOCAL TECH COMMUNITY · PERSONALIZED FOR YOUR SEARCH</small><h2>${recommended.length} event${recommended.length === 1 ? '' : 's'} you should actually attend</h2><p>Prioritized for recruiter access, useful market conversations, and places where your senior backend background helps you stand out.</p></div><div class="events-summary"><strong>${recommended.length}</strong><span>strong<br>matches</span></div></header><section class="event-toolbar"><div class="event-filters">${filters}</div><span>Curated ${esc(data.updated_at)} · Always confirm details with the organizer</span></section><section class="local-event-list">${cards || '<div class="practice-empty">No strong search-goal matches in this filter yet. Check All events for lower-priority options.</div>'}</section><aside class="event-sources"><div><small>DISCOVER MORE</small><b>Watch the sources where Austin events show up first</b></div>${data.source_links.map(source => `<a href="${esc(source.url)}" target="_blank" rel="noopener">${esc(source.label)} ↗</a>`).join('')}</aside>`;
}

async function loadLocalEvents() {
  const panel = $('#localEvents');
  if (!localEventsData) {
    panel.innerHTML = '<div class="practice-loading">Loading Austin events…</div>';
    const response = await fetch('/api/local-events');
    const data = await response.json();
    if (!response.ok) return panel.innerHTML = `<div class="practice-empty">${esc(data.error)}</div>`;
    localEventsData = data.events;
  }
  renderLocalEvents();
}

async function setLocalEventStatus(eventId, status) {
  const response = await fetch(`/api/local-events/${encodeURIComponent(eventId)}/status`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})});
  const data = await response.json();
  if (!response.ok) return toast(data.error);
  localEventsData = data.events;
  renderLocalEvents();
  toast(status === 'passed' ? 'Event hidden' : `Event marked ${status}`);
}

async function savePracticeBuilder() {
  syncPracticeBuilderState();
  const button = $('#practiceSaveButton');
  if (button) { button.disabled = true; button.textContent = 'Saving…'; }
  const response = await fetch('/api/practice-builder', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({practice:practiceBuilderData})});
  const data = await response.json();
  if (button) { button.disabled = false; button.textContent = 'Save answers'; }
  if (!response.ok) return toast(data.error);
  practiceBuilderData = data.practice;
  toast('Practice workspace saved');
}
