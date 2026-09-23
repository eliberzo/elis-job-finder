let voiceInterviewData = null;
let activeVoiceSession = null;
let interviewRecorder = null;
let interviewChunks = [];
let interviewStartedAt = 0;

function speakInterview(text) {
  if (!('speechSynthesis' in window) || !text) return;
  speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = .96;
  speechSynthesis.speak(utterance);
}

function renderVoiceInterviews() {
  const panel = $('#voiceInterview');
  if (!voiceInterviewData) return;
  if (activeVoiceSession?.status === 'active') return renderActiveVoiceInterview();
  const plans = voiceInterviewData.plans.map(plan => `<article class="interview-plan">
    <small>${esc(plan.company)} · ${esc(plan.round)}</small><h3>${esc(plan.role)}</h3><p>${esc(plan.description)}</p>
    <div><span>${plan.questions.length} primary questions</span><button class="btn primary" ${voiceInterviewData.configured ? '' : 'disabled'} onclick="startVoiceInterview('${esc(plan.id)}')">Start interview</button></div>
  </article>`).join('');
  const sessions = voiceInterviewData.sessions.map(session => {
    const score = session.evaluation?.overall_score;
    return `<details class="interview-history"><summary><span><small>${esc(session.company)} · ${esc(session.round)}</small><b>${new Date(session.started_at).toLocaleString()}</b></span><em>${score ? `${score}/10` : esc(session.status)}</em></summary>
      <div class="history-body">${session.answers.map((answer, index) => `<article><header><b>${index + 1}. ${esc(answer.question)}</b><span>${esc(answer.duration_seconds)}s</span></header><p>${esc(answer.transcript)}</p><audio controls preload="none" src="${esc(answer.audio_url)}"></audio>${session.evaluation?.answer_feedback?.[index] ? `<aside><b>Feedback</b><p>${esc(session.evaluation.answer_feedback[index].feedback)}</p><small>Better outline</small><p>${esc(session.evaluation.answer_feedback[index].better_outline)}</p></aside>` : ''}</article>`).join('')}
      ${session.evaluation ? renderInterviewEvaluation(session.evaluation) : ''}</div></details>`;
  }).join('');
  panel.innerHTML = `<header class="interview-hero"><div><small>COMPANY-SPECIFIC SPOKEN PRACTICE</small><h2>Your AI interview room</h2><p>Every recording, transcript, follow-up, and evaluation is preserved locally as a new attempt.</p></div><div><strong>${voiceInterviewData.sessions.length}</strong><span>saved sessions</span></div></header>
    ${voiceInterviewData.configured ? '' : '<aside class="interview-warning">Set OPENAI_API_KEY before starting the app to enable transcription, follow-ups, and evaluation.</aside>'}
    <section class="interview-plans">${plans}</section><section class="interview-history-list"><h2>Practice history</h2>${sessions || '<p class="practice-empty">No recorded interviews yet.</p>'}</section>`;
}

function renderInterviewEvaluation(value) {
  return `<section class="interview-evaluation"><header><strong>${esc(value.overall_score)}/10</strong><div><small>OVERALL ASSESSMENT</small><p>${esc(value.summary)}</p></div></header>
    <div class="competency-scores">${Object.entries(value.competencies || {}).map(([key, score]) => `<span><b>${esc(key.replaceAll('_',' '))}</b><em>${esc(score)}/10</em></span>`).join('')}</div>
    <div class="evaluation-columns"><div><b>Strengths</b><ul>${value.strengths.map(item => `<li>${esc(item)}</li>`).join('')}</ul></div><div><b>Improve next</b><ul>${value.improvements.map(item => `<li>${esc(item)}</li>`).join('')}</ul></div></div></section>`;
}

function renderActiveVoiceInterview() {
  const panel = $('#voiceInterview');
  const session = activeVoiceSession;
  panel.innerHTML = `<header class="interview-live-head"><div><small>${esc(session.company)} · ${esc(session.round)}</small><h2>${esc(session.role)}</h2></div><button class="btn" onclick="finishVoiceInterview()">Finish and evaluate</button></header>
    <section class="interviewer-stage"><div class="interviewer-avatar">G</div><small>${session.current_kind === 'followup' ? 'FOLLOW-UP' : `QUESTION ${session.question_index + 1}`}</small><h2>${esc(session.current_question || 'You have completed the planned questions.')}</h2><button class="replay-question" onclick="speakInterview(activeVoiceSession.current_question)">🔊 Replay question</button></section>
    <section class="recording-controls"><button id="recordAnswerButton" class="record-answer" onclick="toggleAnswerRecording()" ${session.current_question ? '' : 'disabled'}><i></i><span>Record answer</span></button><p id="recordingStatus">Your audio and transcript will be saved to this attempt.</p></section>
    <section class="live-transcript"><h3>Session transcript</h3>${session.answers.map(answer => `<article><b>${esc(answer.question)}</b><p>${esc(answer.transcript)}</p><audio controls preload="none" src="${esc(answer.audio_url)}"></audio></article>`).join('') || '<p>No answers recorded yet.</p>'}</section>`;
}

async function loadVoiceInterviews() {
  const panel = $('#voiceInterview');
  panel.innerHTML = '<div class="practice-loading">Loading interview room…</div>';
  const response = await fetch('/api/voice-interviews', {cache:'no-store'});
  voiceInterviewData = await response.json();
  if (!response.ok) return panel.innerHTML = `<div class="practice-empty">${esc(voiceInterviewData.error)}</div>`;
  renderVoiceInterviews();
}

async function startVoiceInterview(planId) {
  const response = await fetch('/api/voice-interviews/start', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({plan_id:planId})});
  const data = await response.json();
  if (!response.ok) return toast(data.error);
  activeVoiceSession = data.session; renderActiveVoiceInterview(); speakInterview(activeVoiceSession.current_question);
}

async function toggleAnswerRecording() {
  if (interviewRecorder?.state === 'recording') return interviewRecorder.stop();
  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio:true});
    interviewChunks = []; interviewStartedAt = Date.now();
    interviewRecorder = new MediaRecorder(stream);
    interviewRecorder.ondataavailable = event => { if (event.data.size) interviewChunks.push(event.data); };
    interviewRecorder.onstop = () => submitRecordedAnswer(stream);
    interviewRecorder.start();
    const button = $('#recordAnswerButton'); button.classList.add('recording'); button.querySelector('span').textContent = 'Stop recording';
    $('#recordingStatus').textContent = 'Recording… speak naturally, then press Stop recording.';
  } catch (error) { toast(`Microphone unavailable: ${error.message}`); }
}

async function submitRecordedAnswer(stream) {
  stream.getTracks().forEach(track => track.stop());
  const blob = new Blob(interviewChunks, {type:interviewRecorder.mimeType || 'audio/webm'});
  const duration = (Date.now() - interviewStartedAt) / 1000;
  $('#recordAnswerButton').disabled = true; $('#recordingStatus').textContent = 'Saving audio and transcribing your answer…';
  const base64 = await new Promise(resolve => { const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(',')[1]); reader.readAsDataURL(blob); });
  const response = await fetch(`/api/voice-interviews/${activeVoiceSession.id}/answer`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({audio_base64:base64, mime_type:blob.type, duration_seconds:duration})});
  const data = await response.json();
  if (!response.ok) { renderActiveVoiceInterview(); return toast(data.error); }
  activeVoiceSession = data.session; renderActiveVoiceInterview();
  if (activeVoiceSession.current_question) speakInterview(activeVoiceSession.current_question);
  else toast('Planned questions complete. Finish the interview for your evaluation.');
}

async function finishVoiceInterview() {
  if (!activeVoiceSession?.answers?.length) return toast('Record at least one answer first.');
  const panel = $('#voiceInterview'); panel.innerHTML = '<div class="practice-loading">Evaluating the complete interview…</div>';
  const response = await fetch(`/api/voice-interviews/${activeVoiceSession.id}/finish`, {method:'POST'});
  const data = await response.json();
  if (!response.ok) { renderActiveVoiceInterview(); return toast(data.error); }
  activeVoiceSession = null; await loadVoiceInterviews(); toast('Interview saved and evaluated.');
}
