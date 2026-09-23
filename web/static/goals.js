function renderGoalCard(item, index) {
  return `<article class="goal-card">
    <div class="goal-number">${index + 1}</div>
    <div class="todo-copy"><div class="todo-meta"><span>${esc(item.category)}</span><b>GOAL</b></div><h3>${esc(item.title)}</h3><p>${esc(item.detail)}</p></div>
  </article>`;
}

async function loadGoals() {
  const panel = $('#goalsView');
  panel.innerHTML = '<div class="todo-loading">Loading goals…</div>';
  const response = await fetch('/api/goals');
  const data = await response.json();
  if (!response.ok) return panel.innerHTML = `<div class="todo-empty">${esc(data.error)}</div>`;
  panel.innerHTML = `<header class="goals-hero"><div><small>CAREER DIRECTION</small><h2>Eli's job-search goals</h2><p>Outcomes and questions that guide the work. Actionable steps belong in the Todo list.</p></div></header>
    <div class="goal-list">${data.goals.length ? data.goals.map(renderGoalCard).join('') : '<div class="todo-empty">No goals yet.</div>'}</div>`;
}
