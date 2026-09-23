let todoData = [];
let todoViewMode = 'open';

function completedDate(value) {
  if (!value) return 'Completion date not recorded';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return 'Completion date not recorded';
  return `Completed ${new Intl.DateTimeFormat('en-US', {month:'short', day:'numeric', year:'numeric'}).format(parsed)}`;
}

function setTodoView(mode) {
  todoViewMode = mode;
  renderTodos();
}

function renderTodoCard(item) {
  const done = item.status === 'done';
  const blocked = item.status === 'blocked';
  const statusLabel = done ? 'COMPLETED' : blocked ? 'BLOCKER' : 'OPEN';
  return `<article class="todo-card ${esc(item.status)}">
    <button class="todo-check" title="${done ? 'Reopen this item' : 'Mark this item complete'}" aria-label="${done ? 'Reopen' : 'Complete'} ${esc(item.title)}" onclick="toggleTodo('${esc(item.id)}')">${done ? '✓' : ''}</button>
    <div class="todo-copy"><div class="todo-meta"><span>${esc(item.category)}</span><b>${statusLabel}</b>${done ? `<time datetime="${esc(item.completed_at || '')}">${esc(completedDate(item.completed_at))}</time>` : ''}</div><h3>${esc(item.title)}</h3><p>${esc(item.detail)}</p>${blocked && item.blocker ? `<div class="todo-blocker">${esc(item.blocker)}</div>` : ''}</div>
    ${done ? '' : `<button class="todo-block-action ${blocked ? 'active' : ''}" type="button" title="${blocked ? 'Move this blocker back to Open' : 'Mark this item as a blocker'}" onclick="toggleTodoBlocker('${esc(item.id)}')">${blocked ? 'Unblock' : 'Mark blocker'}</button>`}
  </article>`;
}

function renderTodos() {
  const panel = $('#todoView');
  const openItems = todoData.filter(item => item.status === 'todo');
  const blockers = todoData.filter(item => item.status === 'blocked');
  const completed = todoData.filter(item => item.status === 'done');
  const lists = {open:openItems, blockers, completed};
  const visible = lists[todoViewMode] || openItems;
  const incomplete = openItems.length + blockers.length;
  $('#todoCount').textContent = incomplete ? incomplete : '';
  panel.innerHTML = `<header class="todo-hero"><div><small>JOB SEARCH OPERATIONS</small><h2>Eli's setup and application checklist</h2><p>${openItems.length} open · ${blockers.length} blockers · ${completed.length} completed · persisted locally</p></div></header>
    <nav class="todo-tabs" aria-label="Todo views">
      <button class="${todoViewMode === 'open' ? 'selected' : ''}" onclick="setTodoView('open')">Open <span>${openItems.length}</span></button>
      <button class="${todoViewMode === 'blockers' ? 'selected' : ''}" onclick="setTodoView('blockers')">Blockers <span>${blockers.length}</span></button>
      <button class="${todoViewMode === 'completed' ? 'selected' : ''}" onclick="setTodoView('completed')">Completed <span>${completed.length}</span></button>
    </nav>
    <div class="todo-list">${visible.length ? visible.map(renderTodoCard).join('') : `<div class="todo-empty">No ${todoViewMode} items.</div>`}</div>`;
}

async function loadTodos() {
  const panel = $('#todoView');
  panel.innerHTML = '<div class="todo-loading">Loading workflow…</div>';
  const response = await fetch('/api/todos');
  const data = await response.json();
  if (!response.ok) return panel.innerHTML = `<div class="todo-empty">${esc(data.error)}</div>`;
  todoData = data.todos;
  renderTodos();
}

async function toggleTodo(id) {
  const response = await fetch(`/api/todos/${encodeURIComponent(id)}/toggle`, {method:'POST'});
  const data = await response.json();
  if (!response.ok) return toast(data.error);
  todoViewMode = data.status === 'done' ? 'completed' : 'open';
  toast(data.status === 'done' ? 'Moved to Completed' : 'Todo reopened');
  loadTodos();
}

async function toggleTodoBlocker(id) {
  const response = await fetch(`/api/todos/${encodeURIComponent(id)}/block`, {method:'POST'});
  const data = await response.json();
  if (!response.ok) return toast(data.error);
  todoViewMode = data.status === 'blocked' ? 'blockers' : 'open';
  toast(data.status === 'blocked' ? 'Marked as a blocker' : 'Moved back to Open');
  loadTodos();
}

async function loadTodoCount() {
  const response = await fetch('/api/todos');
  if (!response.ok) return;
  const data = await response.json();
  const incomplete = data.todos.filter(item => item.status !== 'done').length;
  $('#todoCount').textContent = incomplete ? incomplete : '';
  $('#todoSubtabCount').textContent = incomplete ? incomplete : '';
}

loadTodoCount();
