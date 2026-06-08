/* ══════════════════════════════════════════════════════
  ClippedAI — Frontend Application Logic
  Real-time pipeline with Server-Sent Events
  ══════════════════════════════════════════════════════ */

'use strict';

// ─── State ───────────────────────────────────────────────────────────────────
const state = {
 currentJobId: null,
 eventSource: null,
 ytAuthenticated: false,
 progress: 0,
 clips: [],
 uploads: [],
 statusInterval: null,
};

// ─── DOM Refs ─────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
 initDropzone();
 initFileInput();
 initSettings();
 initGenerateBtn();
 checkYTStatus();
 initYTConnectBtn();
});

// ─── Dropzone ─────────────────────────────────────────────────────────────────
function initDropzone() {
 const dz = $('dropzone');
 const fi = $('file-input');

 dz.addEventListener('click', e => {
  if (!e.target.closest('#btn-browse')) {
   fi.click();
  }
 });

 $('btn-browse').addEventListener('click', e => {
  e.stopPropagation();
  fi.click();
 });

 dz.addEventListener('dragover', e => {
  e.preventDefault();
  dz.classList.add('drag-over');
 });

 dz.addEventListener('dragleave', () => dz.classList.remove('drag-over'));

 dz.addEventListener('drop', e => {
  e.preventDefault();
  dz.classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file && file.type.startsWith('video/')) {
   handleFile(file);
  } else {
   showToast('Please drop a video file', 'error');
  }
 });

 $('btn-clear-file').addEventListener('click', () => {
  fi.value = '';
  $('file-info').style.display = 'none';
  $('dropzone').style.display = '';
  $('btn-generate').disabled = true;
  state.currentJobId = null;
 });
}

function initFileInput() {
 $('file-input').addEventListener('change', e => {
  const file = e.target.files[0];
  if (file) handleFile(file);
 });
}

function handleFile(file) {
 const validTypes = ['video/mp4', 'video/mkv', 'video/x-matroska', 'video/avi',
           'video/mov', 'video/quicktime', 'video/webm', 'video/x-msvideo'];
 // Accept by type or extension
 const ext = file.name.split('.').pop().toLowerCase();
 const validExts = ['mp4', 'mkv', 'mov', 'avi', 'webm', 'flv', 'ts', 'm4v'];
 if (!validExts.includes(ext)) {
  showToast(`Unsupported format: .${ext}`, 'error');
  return;
 }

 const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
 const sizeDisplay = file.size > 1024 * 1024 * 1024
  ? `${(file.size / (1024 ** 3)).toFixed(2)} GB`
  : `${sizeMB} MB`;

 $('file-name-display').textContent = file.name;
 $('file-meta-display').textContent = `${sizeDisplay} • ${ext.toUpperCase()}`;
 $('file-info').style.display = 'flex';
 $('dropzone').style.display = 'none';
 $('btn-generate').disabled = false;

 // Store file reference
 state.selectedFile = file;

 showToast(` ${file.name} ready!`, 'success');
 animateStepPill(1);
}

// ─── Settings ─────────────────────────────────────────────────────────────────
function initSettings() {
 $('auto-upload').addEventListener('change', e => {
  $('toggle-label').textContent = e.target.checked ? 'On' : 'Off';
  if (e.target.checked && !state.ytAuthenticated) {
   showToast('Connect your YouTube account first!', 'warn');
   e.target.checked = false;
   $('toggle-label').textContent = 'Off';
  }
 });
}

// ─── Generate Button ──────────────────────────────────────────────────────────
function initGenerateBtn() {
 $('btn-generate').addEventListener('click', async () => {
  if (!state.selectedFile) return;
  await startPipeline();
 });
}

async function startPipeline() {
 const file = state.selectedFile;
 if (!file) return;

 $('btn-generate').disabled = true;
 $('btn-generate').textContent = '⏳ Uploading...';

 try {
  // Step 1: Upload the file
  showPanel('progress-panel');
  updateProgress(5, 'Uploading video...');
  setStageActive('upload');

  const formData = new FormData();
  formData.append('video', file);

  $('upload-progress-wrap').style.display = 'block';

  const jobId = await uploadFile(file);
  state.currentJobId = jobId;
  $('job-id-badge').textContent = `Job: ${jobId}`;
  setStageActive('transcribe');

  // Step 2: Start processing
  const opts = {
   num_clips: parseInt($('num-clips').value),
   model_size: $('whisper-model').value,
   auto_upload: $('auto-upload').checked,
  };

  const startRes = await fetch(`/api/start/${jobId}`, {
   method: 'POST',
   headers: { 'Content-Type': 'application/json' },
   body: JSON.stringify(opts),
  });

  if (!startRes.ok) throw new Error('Failed to start processing');

  // Step 3: Connect SSE
  connectSSE(jobId);

  $('upload-progress-wrap').style.display = 'none';
  updateProgress(10, 'Starting transcription...');
  logEntry(' Pipeline started!');

 } catch (err) {
  showToast(`Error: ${err.message}`, 'error');
  $('btn-generate').disabled = false;
  $('btn-generate').innerHTML = '<span class="btn-icon"></span> Generate Shorts';
 }
}

async function uploadFile(file) {
 return new Promise((resolve, reject) => {
  const xhr = new XMLHttpRequest();
  const formData = new FormData();
  formData.append('video', file);

  xhr.upload.addEventListener('progress', e => {
   if (e.lengthComputable) {
    const pct = Math.round((e.loaded / e.total) * 100);
    $('upload-bar').style.width = `${pct}%`;
    $('upload-pct').textContent = `${pct}%`;
   }
  });

  xhr.addEventListener('load', () => {
   if (xhr.status === 200) {
    const data = JSON.parse(xhr.responseText);
    resolve(data.job_id);
   } else {
    reject(new Error(`Upload failed: ${xhr.status}`));
   }
  });

  xhr.addEventListener('error', () => reject(new Error('Network error')));
  xhr.open('POST', '/api/upload');
  xhr.send(formData);
 });
}

// ─── SSE ──────────────────────────────────────────────────────────────────────
function connectSSE(jobId) {
 if (state.eventSource) {
  state.eventSource.close();
 }

 const es = new EventSource(`/api/events/${jobId}`);
 state.eventSource = es;

 es.onmessage = e => {
  try {
   const payload = JSON.parse(e.data);
   handleSSEEvent(payload);
  } catch (err) {
   console.error('SSE parse error:', err);
  }
 };

 es.onerror = () => {
  console.warn('SSE connection error');
 };
}

function handleSSEEvent({ event, message, data }) {
 if (!message) return;

 const emojisToStrip = ['', '', '️', '', '', '', '', '', '️', '', '', '', '', '️'];
 let cleanMessage = message;
 emojisToStrip.forEach(e => {
  cleanMessage = cleanMessage.split(e).join('');
 });
 cleanMessage = cleanMessage.trim();

 // Log exactly what the backend sends, stripped of emojis
 logEntry(cleanMessage, event.includes('error') ? 'error' : '');

 // Update stage + progress based on event
 switch (event) {
  case 'start':
  case 'info':
   updateProgress(8, message);
   break;

  case 'info_done':
   updateProgress(12, message);
   setStageActive('transcribe');
   break;

  case 'loading_model':
  case 'transcribing':
   updateProgress(15, message);
   setStageActive('transcribe');
   animateStepPill(2);
   startDynamicStatus();
   break;

  case 'transcription_done':
   stopDynamicStatus();
   updateProgress(40, message);
   setStageDone('upload');
   setStageDone('transcribe');
   setStageActive('score');
   break;

  case 'scoring':
   updateProgress(42, message);
   setStageActive('score');
   break;

  case 'scoring_done':
   updateProgress(50, message);
   setStageDone('score');
   setStageActive('cut');
   animateStepPill(3);
   if (data && data.clips) {
    showToast(` ${data.clips.length} highlights found!`, 'success');
   }
   break;

  case 'processing':
  case 'processing_clip': {
   const match = message.match(/(\d+)\/(\d+)/);
   if (match) {
    const curr = parseInt(match[1]);
    const total = parseInt(match[2]);
    const pct = 50 + Math.round((curr / total) * 35);
    updateProgress(pct, message);
    $('stage-cut-status').textContent = `${curr}/${total} clips`;
   } else {
    updateProgress(state.progress + 2, message);
   }
   break;
  }

  case 'clip_done': {
   if (data && data.clip) {
    state.clips.push(data.clip);
    if (data.progress_pct) {
     const pct = 50 + Math.round((data.progress_pct / 100) * 35);
     updateProgress(pct, ` Clip ${data.clip.clip_number} ready`);
    }
    // Show clip in results as they come in
    addClipCard(data.clip);
    showPanel('results-panel');
   }
   break;
  }

  case 'uploading':
   updateProgress(88, message);
   setStageDone('cut');
   setStageActive('yt');
   animateStepPill(4);
   break;

  case 'upload_progress':
   updateProgress(Math.min(95, state.progress + 1), message);
   break;

  case 'upload_done':
   setStageDone('yt');
   if (data && data.uploads) {
    state.uploads = data.uploads;
   }
   break;

  case 'done':
   handlePipelineDone(data);
   break;

  case 'fatal_error':
   handleFatalError(message);
   break;
 }
}

function handlePipelineDone(data) {
 stopDynamicStatus();
 updateProgress(100, ' All done!');
 setStageDone('upload');
 setStageDone('transcribe');
 setStageDone('score');
 setStageDone('cut');
 setStageDone('yt');

 // Stop progress bar animation
 $('master-bar').classList.remove('progress-bar-animated');
 $('master-bar').style.background = 'linear-gradient(90deg, #10b981, #059669)';

 showToast(` ${data?.total_clips || state.clips.length} Shorts generated!`, 'success');
 showPanel('results-panel');

 if (state.eventSource) {
  state.eventSource.close();
  state.eventSource = null;
 }

 // Show upload-all button if clips ready and YT connected
 if (state.ytAuthenticated && state.clips.length > 0) {
  $('btn-upload-all').style.display = 'flex';
 }

 $('btn-generate').innerHTML = '<span class="btn-icon"></span> Generate Shorts';
 $('btn-generate').disabled = false;
}

function handleFatalError(message) {
 stopDynamicStatus();
 updateProgress(state.progress, ' ' + message);
 $('master-bar').style.background = 'var(--accent-red)';
 $('master-bar').classList.remove('progress-bar-animated');
 showToast(message, 'error');

 if (state.eventSource) {
  state.eventSource.close();
  state.eventSource = null;
 }

 $('btn-generate').innerHTML = '<span class="btn-icon"></span> Generate Shorts';
 $('btn-generate').disabled = false;
}

// ─── Clips Grid ───────────────────────────────────────────────────────────────
function addClipCard(clip) {
 const grid = $('clips-grid');

 // Remove "no clips yet" placeholder if present
 const placeholder = grid.querySelector('.no-clips');
 if (placeholder) placeholder.remove();

 const durationStr = formatDuration(clip.duration);
 const scoreStr = clip.score ? (clip.score * 100).toFixed(0) + '%' : '';
 const timeStr = clip.start ? `${formatTime(clip.start)} → ${formatTime(clip.end)}` : '';

 const card = document.createElement('div');
 card.className = 'clip-card';
 card.id = `clip-card-${clip.clip_index}`;
 card.innerHTML = `
  <div class="clip-thumbnail" id="clip-thumb-${clip.clip_index}">
   <div class="clip-thumbnail-placeholder"></div>
   ${scoreStr ? `<div class="clip-score-badge">⭐ ${scoreStr}</div>` : ''}
   <div class="clip-rank-badge">#${clip.clip_number}</div>
  </div>
  <div class="clip-info">
   <div class="clip-title">${escapeHtml(clip.title || `Short #${clip.clip_number}`)}</div>
   <div class="clip-meta">
    <span class="clip-meta-item">⏱️ ${durationStr}</span>
    <span class="clip-meta-item"> ${timeStr}</span>
    ${clip.size_mb ? `<span class="clip-meta-item"> ${clip.size_mb}MB</span>` : ''}
   </div>
   <div class="clip-actions">
    <button class="btn btn-outline btn-sm" onclick="downloadClip('${state.currentJobId}', ${clip.clip_index})">
     ⬇️ Download
    </button>
    <button class="btn btn-danger btn-sm" onclick="uploadClip('${state.currentJobId}', ${clip.clip_index}, this)">
      Upload
    </button>
   </div>
   <div id="clip-yt-${clip.clip_index}"></div>
  </div>
 `;

 // Load thumbnail if available
 loadThumbnail(clip.clip_index);

 // Animate card entry
 card.style.opacity = '0';
 card.style.transform = 'translateY(20px)';
 grid.appendChild(card);

 requestAnimationFrame(() => {
  card.style.transition = 'opacity 0.4s, transform 0.4s';
  card.style.opacity = '1';
  card.style.transform = 'translateY(0)';
 });
}

function loadThumbnail(clipIndex) {
 if (!state.currentJobId) return;
 const img = new Image();
 const thumbEl = $(`clip-thumb-${clipIndex}`);
 img.onload = () => {
  if (thumbEl) {
   thumbEl.innerHTML = `<img src="/api/thumbnail/${state.currentJobId}/${clipIndex}" alt="Clip ${clipIndex + 1}" />`;
  }
 };
 img.onerror = () => {}; // keep placeholder
 img.src = `/api/thumbnail/${state.currentJobId}/${clipIndex}`;
}

async function downloadClip(jobId, clipIndex) {
 const link = document.createElement('a');
 link.href = `/api/download/${jobId}/${clipIndex}`;
 link.download = `short_${clipIndex + 1}.mp4`;
 link.click();
}

async function uploadClip(jobId, clipIndex, btn) {
 if (!state.ytAuthenticated) {
  showToast('Connect YouTube first!', 'warn');
  openYTModal();
  return;
 }

 btn.disabled = true;
 btn.textContent = '⏳ Uploading...';

 try {
  const res = await fetch(`/api/upload_to_youtube/${jobId}/${clipIndex}`, {
   method: 'POST',
  });
  const data = await res.json();

  if (data.url) {
   const ytDiv = $(`clip-yt-${clipIndex}`);
   if (ytDiv) {
    ytDiv.innerHTML = `
     <a href="${data.url}" target="_blank" class="clip-yt-badge">
       View on YouTube
     </a>
    `;
   }
   btn.textContent = ' Uploaded';
   showToast(`Uploaded! ${data.url}`, 'success');
  } else {
   throw new Error(data.error || 'Upload failed');
  }
 } catch (err) {
  btn.disabled = false;
  btn.textContent = ' Upload';
  showToast(`Upload failed: ${err.message}`, 'error');
 }
}

// ─── Panel Management ─────────────────────────────────────────────────────────
function showPanel(panelId) {
 const panels = ['upload-panel', 'progress-panel', 'results-panel'];
 panels.forEach(id => {
  const el = $(id);
  if (!el) return;
  if (id === panelId || id === 'results-panel') {
   el.style.display = 'block';
  } else if (id !== 'upload-panel' && id !== panelId) {
   // Keep upload panel visible, show progress
  }
 });

 if (panelId === 'progress-panel') {
  $('progress-panel').style.display = 'block';
 }
 if (panelId === 'results-panel') {
  $('results-panel').style.display = 'block';
  $('results-title').textContent = ' Your Shorts Are Ready!';
 }
}

function resetUI() {
 state.currentJobId = null;
 state.clips = [];
 state.uploads = [];
 state.progress = 0;

 if (state.eventSource) {
  state.eventSource.close();
  state.eventSource = null;
 }

 $('file-input').value = '';
 state.selectedFile = null;
 $('file-info').style.display = 'none';
 $('dropzone').style.display = '';
 $('btn-generate').disabled = true;
 $('btn-generate').innerHTML = '<span class="btn-icon"></span> Generate Shorts';
 $('progress-panel').style.display = 'none';
 $('results-panel').style.display = 'none';
 $('clips-grid').innerHTML = '';
 $('log-body').innerHTML = '';
 $('master-bar').style.width = '0%';
 $('master-bar').classList.add('progress-bar-animated');
 $('master-bar').style.background = '';
 stopDynamicStatus();
 updateProgress(0, 'Starting...');

 // Reset stages
 ['upload', 'transcribe', 'score', 'cut', 'yt'].forEach(s => {
  const el = $(`stage-${s}`);
  if (el) {
   el.classList.remove('active', 'done');
   const check = $(`stage-${s}-check`);
   if (check) check.textContent = '○';
   const status = $(`stage-${s}-status`);
   if (status) status.textContent = 'Waiting';
  }
 });

 // Reset step pills
 [1,2,3,4].forEach(n => {
  const el = $(`step-${n}`);
  if (el) el.classList.remove('active');
 });
}

// ─── Stage Management ─────────────────────────────────────────────────────────
const stageMap = {
 upload: 'stage-upload',
 transcribe: 'stage-transcribe',
 score: 'stage-score',
 cut: 'stage-cut',
 yt: 'stage-yt',
};

function setStageActive(key) {
 const el = $(stageMap[key]);
 if (!el) return;
 el.classList.add('active');
 el.classList.remove('done');
 const status = $(`stage-${stageMap[key].split('-')[1]}-status`);
 if (status) status.textContent = 'Running...';
}

function setStageDone(key) {
 const el = $(stageMap[key]);
 if (!el) return;
 el.classList.remove('active');
 el.classList.add('done');
 const check = $(`stage-${stageMap[key].split('-')[1]}-check`);
 if (check) check.textContent = '';
 const status = $(`stage-${stageMap[key].split('-')[1]}-status`);
 if (status) status.textContent = 'Done';
}

function updateProgress(pct, message) {
 state.progress = pct;
 $('master-bar').style.width = `${Math.min(100, pct)}%`;
 if (message) {
  if (message.trim() === '...' && state.statusInterval) return;
  $('progress-status-text').textContent = message;
 }
 $('progress-pct-text').textContent = `${Math.min(100, pct)}%`;
}

// ─── Dynamic Status (Engagement) ─────────────────────────────────────────────
const dynamicPhrases = [
 "Extracting audio frequencies...",
 "Loading neural weights...",
 "Analyzing speech patterns...",
 "Running silence detection...",
 "Mapping semantic context...",
 "Isolating vocal tracks...",
 "Generating timestamps...",
 "Identifying high-retention hooks...",
 "Almost there... processing deeper..."
];

function startDynamicStatus() {
 if (state.statusInterval) return;
 let i = 0;
 state.statusInterval = setInterval(() => {
  const textEl = $('progress-status-text');
  if (textEl) {
   textEl.textContent = `${dynamicPhrases[i % dynamicPhrases.length]}`;
   i++;
  }
 }, 4500); // Change every 4.5 seconds
}

function stopDynamicStatus() {
 if (state.statusInterval) {
  clearInterval(state.statusInterval);
  state.statusInterval = null;
 }
}

// ─── Log ──────────────────────────────────────────────────────────────────────
function logEntry(msg, type = '') {
 const body = $('log-body');
 const entry = document.createElement('div');
 entry.className = `log-entry${type ? ' ' + type : ''}`;
 const time = new Date().toLocaleTimeString();
 entry.innerHTML = `<span style="color:var(--text-muted); margin-right:8px;">[${time}]</span> ${msg}`;
 body.appendChild(entry);
 body.scrollTop = body.scrollHeight;
}

// ─── Step Pills ───────────────────────────────────────────────────────────────
function animateStepPill(step) {
 const el = $(`step-${step}`);
 if (el) el.classList.add('active');
}

// ─── YouTube ──────────────────────────────────────────────────────────────────
function initYTConnectBtn() {
 $('btn-yt-connect').addEventListener('click', openYTModal);
}

function openYTModal() {
 $('yt-modal').style.display = 'flex';
}

function closeYTModal() {
 $('yt-modal').style.display = 'none';
}

async function authenticateYouTube() {
 const btn = $('btn-yt-auth-confirm');
 btn.disabled = true;
 btn.textContent = '⏳ Opening browser...';

 try {
  const res = await fetch('/api/youtube/auth', { method: 'POST' });
  const data = await res.json();

  if (data.authenticated) {
   state.ytAuthenticated = true;
   updateYTStatus(true);
   closeYTModal();
   showToast(' YouTube connected!', 'success');
  } else {
   throw new Error(data.error || 'Authentication failed');
  }
 } catch (err) {
  showToast(`YouTube auth failed: ${err.message}`, 'error');
 } finally {
  btn.disabled = false;
  btn.innerHTML = '<span></span> Authenticate with Google';
 }
}

async function checkYTStatus() {
 try {
  const res = await fetch('/api/youtube/status');
  const data = await res.json();
  state.ytAuthenticated = data.authenticated;
  updateYTStatus(data.authenticated);
 } catch (e) {
  // silent
 }
}

function updateYTStatus(connected) {
 const dot = $('yt-dot');
 const label = $('yt-status-label');
 const btn = $('btn-yt-connect');

 if (connected) {
  dot.classList.add('connected');
  label.textContent = 'YouTube: Connected ';
  btn.textContent = 'Disconnect';
  btn.onclick = async () => {
   await fetch('/api/youtube/logout', { method: 'POST' });
   state.ytAuthenticated = false;
   updateYTStatus(false);
   btn.onclick = openYTModal;
  };
 } else {
  dot.classList.remove('connected');
  label.textContent = 'YouTube: Not Connected';
  btn.textContent = 'Connect YouTube';
  btn.onclick = openYTModal;
 }
}

// ─── Toast ────────────────────────────────────────────────────────────────────
function showToast(message, type = 'info', duration = 4000) {
 const container = $('toast-container');
 const icons = { success: '', error: '', warn: '️', info: 'ℹ️' };
 const icon = icons[type] || 'ℹ️';

 const toast = document.createElement('div');
 toast.className = `toast ${type}`;
 toast.innerHTML = `<span class="toast-icon">${icon}</span><span class="toast-msg">${escapeHtml(message)}</span>`;
 container.appendChild(toast);

 setTimeout(() => {
  toast.classList.add('removing');
  setTimeout(() => toast.remove(), 300);
 }, duration);
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function formatDuration(seconds) {
 if (!seconds) return '--';
 const s = Math.round(seconds);
 const m = Math.floor(s / 60);
 const sec = s % 60;
 return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

function formatTime(seconds) {
 if (seconds === undefined || seconds === null) return '--';
 const h = Math.floor(seconds / 3600);
 const m = Math.floor((seconds % 3600) / 60);
 const s = Math.floor(seconds % 60);
 if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
 return `${m}:${String(s).padStart(2,'0')}`;
}

function escapeHtml(str) {
 if (!str) return '';
 return String(str)
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');
}

// Close modal on backdrop click
$('yt-modal').addEventListener('click', e => {
 if (e.target === $('yt-modal')) closeYTModal();
});

// ─── Awwwards UI Interactive Logic ────────────────────────────────────────────
document.addEventListener('mousemove', e => {
 document.querySelectorAll('.interactive-card').forEach(card => {
  const rect = card.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  
  const glow = card.querySelector('.card-glow');
  if (glow) {
   glow.style.transform = `translate(${x - 200}px, ${y - 200}px)`;
  }
 });
});

// ─── Custom Select Dropdown Logic ───────────────────────────────────────────
document.querySelectorAll('.custom-select').forEach(select => {
 const trigger = select.querySelector('.select-trigger');
 const triggerText = select.querySelector('.trigger-text');
 const options = select.querySelectorAll('.custom-option');
 const hiddenInput = select.querySelector('input[type="hidden"]');

 trigger.addEventListener('click', (e) => {
  e.stopPropagation();
  // Close others
  document.querySelectorAll('.custom-select').forEach(other => {
   if (other !== select) other.classList.remove('open');
  });
  select.classList.toggle('open');
 });

 options.forEach(opt => {
  opt.addEventListener('click', (e) => {
   e.stopPropagation();
   options.forEach(o => o.classList.remove('selected'));
   opt.classList.add('selected');
   triggerText.textContent = opt.textContent;
   hiddenInput.value = opt.getAttribute('data-value');
   select.classList.remove('open');
  });
 });
});

// Close all on click outside
document.addEventListener('click', () => {
 document.querySelectorAll('.custom-select').forEach(select => {
  select.classList.remove('open');
 });
});

// ─── Razorpay Integration ───────────────────────────────────────────────────
async function initiatePayment() {
  try {
    const res = await fetch('/api/payment/create_order', { method: 'POST' });
    const orderData = await res.json();

    if (orderData.error) {
      showToast(orderData.error, 'error');
      return;
    }

    // Dev Mode Fallback: Skip Razorpay UI if key is a dummy string
    if (orderData.key === "dummy_key") {
        const verifyRes = await fetch('/api/payment/verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ razorpay_payment_id: "dev_payment_123" })
        });
        const verifyData = await verifyRes.json();
        if (verifyData.status === 'success') {
          showToast('Payment successful! Credits added.', 'success');
          const credSpan = document.getElementById('user-credits');
          if (credSpan) credSpan.textContent = verifyData.credits;
        } else {
          showToast('Payment verification failed.', 'error');
        }
        return;
    }

    const options = {
      key: orderData.key,
      amount: orderData.amount,
      currency: "INR",
      name: "ClippedAI",
      description: "10 Video Credits",
      order_id: orderData.order_id,
      handler: async function (response) {
        // Verify payment on backend
        const verifyRes = await fetch('/api/payment/verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(response)
        });
        const verifyData = await verifyRes.json();
        if (verifyData.status === 'success') {
          showToast('Payment successful! Credits added.', 'success');
          // Update credits UI
          const credSpan = document.getElementById('user-credits');
          if (credSpan) credSpan.textContent = verifyData.credits;
        } else {
          showToast('Payment verification failed.', 'error');
        }
      },
      prefill: {
        name: "Creator",
      },
      theme: {
        color: "#ff2e93" // --accent-laser
      }
    };
    const rzp1 = new Razorpay(options);
    rzp1.open();
  } catch (err) {
    showToast('Failed to initiate payment', 'error');
  }
}
