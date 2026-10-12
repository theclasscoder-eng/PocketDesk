'use strict';

const $ = (s) => document.querySelector(s);
const view = $('#view'), video = $('#video'), stage = $('#stage'), keys = $('#keys');
const TOKEN_KEY = 'pocketdesk_token';

// The phone remembers its sign-in; the computer decides how long it is good
// for (1, 12 or 24 hours, or no limit) and answers 401 once it has expired.
let token = null;
try { token = localStorage.getItem(TOKEN_KEY); } catch (e) { /* private mode */ }
let pc = null, dc = null;

function show(id) {
  for (const el of document.querySelectorAll('main')) el.hidden = el.id !== id;
  if (id !== 'app') stopApp();
  if (id === 'pair') { setPin(''); $('#pin').focus(); }
}

function setToken(value) {
  token = value;
  try {
    if (value) localStorage.setItem(TOKEN_KEY, value);
    else localStorage.removeItem(TOKEN_KEY);
  } catch (e) { /* keep it in memory only */ }
}

async function api(path, body) {
  const headers = {};
  if (body) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = 'Bearer ' + token;
  const res = await fetch(path, {
    method: body ? 'POST' : 'GET', headers, body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    setToken(null);
    show('pair');
  }
  if (!res.ok) {
    const err = new Error(data.error || res.statusText);
    err.status = res.status;
    throw err;
  }
  return data;
}

// ---- Control style -------------------------------------------------------

// "default": touch the picture directly. "controlled": the picture takes one
// half of the screen and a trackpad with two buttons takes the other.
let style = 'default';
// "mobile": touch gestures and the on-screen keyboard. "desktop": this
// computer's own mouse, wheel and keyboard are passed straight through.
let device = 'mobile';

function chooseDevice() {
  const sheet = $('#devicesheet');
  sheet.classList.remove('closing');
  for (const b of sheet.querySelectorAll('[data-device]')) b.classList.remove('picked');
  sheet.hidden = false;
  return new Promise((resolve) => {
    sheet.onclick = (e) => {
      const btn = e.target.closest('[data-device]');
      if (!btn) return;
      sheet.onclick = null;
      btn.classList.add('picked');
      device = btn.dataset.device;
      const desktop = device === 'desktop';
      document.body.dataset.device = device;
      $('#device-name').textContent = desktop ? 'Desktop' : 'Mobile';
      $('#default-hint').textContent = desktop ? 'Use your mouse on the screen' : 'Touch the screen directly';
      $('#controlled-hint').textContent = desktop ? 'Screen beside a trackpad' : 'Screen above, trackpad below';
      sheet.classList.add('closing');
      setTimeout(() => { sheet.hidden = true; resolve(); }, 230);
    };
  });
}

$('#redevice').addEventListener('click', chooseDevice);

function chooseStyle() {
  const sheet = $('#sheet');
  sheet.classList.remove('closing');
  for (const b of sheet.querySelectorAll('[data-style]')) b.classList.remove('picked');
  sheet.hidden = false;
  return new Promise((resolve) => {
    sheet.onclick = (e) => {
      const btn = e.target.closest('[data-style]');
      if (!btn) return;
      sheet.onclick = null;
      btn.classList.add('picked');
      style = btn.dataset.style;
      document.body.dataset.style = style;
      $('#style-name').textContent = style === 'controlled' ? 'Controlled' : 'Default';
      sheet.classList.add('closing');
      setTimeout(() => { sheet.hidden = true; resolve(); }, 230);
    };
  });
}

$('#restyle').addEventListener('click', chooseStyle);

// ---- Pairing -------------------------------------------------------------

const code = $('#code'), pin = $('#pin');
const cells = [...code.querySelectorAll('span:not(.gap)')];

function setPin(value) {
  pin.value = value;
  cells.forEach((cell, i) => {
    cell.textContent = value[i] || '';
    cell.classList.toggle('next', i === value.length);
  });
}

async function pair(value) {
  $('#pair-error').textContent = '';
  code.classList.add('busy');
  try {
    const name = navigator.userAgent.replace(/^.*?\(([^;)]+).*$/, '$1').slice(0, 60);
    setToken((await api('/api/pair', { pin: value, name })).token);
    await loadSources();
  } catch (err) {
    show('pair');
    $('#pair-error').textContent = err.message;
    code.classList.add('wrong');
    setTimeout(() => code.classList.remove('wrong'), 400);
  } finally {
    code.classList.remove('busy');
  }
}

pin.addEventListener('input', () => {
  const value = pin.value.replace(/\D/g, '').slice(0, 6);
  setPin(value);
  if (value.length === 6) pair(value);
});

$('#unpair').addEventListener('click', () => { disconnect(); setToken(null); show('pair'); });

// ---- Source picker -------------------------------------------------------

function fillGroup(ul, items, kind, emptyText) {
  ul.textContent = '';
  const add = (title, detail, onTap) => {
    const li = document.createElement('li');
    const row = document.createElement(onTap ? 'button' : 'div');
    row.className = onTap ? 'row go' : 'row empty';
    const label = document.createElement('span');
    label.textContent = title;
    row.append(label);
    if (detail) {
      const small = document.createElement('small');
      small.textContent = detail;
      row.append(small);
    }
    if (onTap) row.addEventListener('click', onTap);
    li.append(row);
    ul.append(li);
  };
  if (!items.length) add(emptyText);
  for (const item of items) {
    add(item.title, item.detail, async () => {
      // Chat apps can open as a phone-style app instead of a live picture.
      const view = item.appview ? await chooseView(item) : 'desktop';
      if (view === 'app') openApp(item);
      else if (view === 'desktop') connect({ kind, id: item.id });
    });
  }
}

async function loadSources(note) {
  const data = await api('/api/sources');
  $('#host').textContent = data.host || 'Computer';
  $('#pick-note').textContent = note || (data.viewOnly ? 'View only. Touch input is turned off on this computer.' : '');
  fillGroup($('#screens'), data.screens, 'screen', 'No Displays');
  fillGroup($('#windows'), data.windows, 'window', 'No Open Windows');
  $('#pick-foot').textContent = data.limited
    ? 'This computer only shares the apps its owner chose.'
    : 'Share a single window to keep the rest of your computer private.';
  const mac = data.platform === 'darwin';
  const names = mac ? { ctrl: '⌃', alt: '⌥', shift: '⇧', meta: '⌘' }
    : { ctrl: 'ctrl', alt: 'alt', shift: 'shift', meta: 'win' };
  for (const b of document.querySelectorAll('[data-mod]')) b.textContent = names[b.dataset.mod];
  show('pick');
}

$('#refresh').addEventListener('click', () => loadSources().catch(() => {}));

// ---- App view ------------------------------------------------------------

// For chat apps the computer reads the window's own interface (the same data
// a screen reader gets) and sends it as text. The phone lays it out like a
// phone app, and taps are mapped back onto the real buttons.
let appWin = null, appTimer = null, appVersion = null, appStop = null;
let appEarlier = null, appLoading = false, appQuiet = 0, appScrollTimer = null;

// Resolves to 'app', 'desktop', or null when dismissed by tapping outside.
function chooseView(item) {
  const sheet = $('#viewsheet');
  $('#view-title').textContent = 'Open ' + (item.appview === 'codex' ? 'Codex' : 'Claude');
  sheet.classList.remove('closing');
  sheet.hidden = false;
  return new Promise((resolve) => {
    sheet.onclick = (e) => {
      const btn = e.target.closest('[data-view]');
      if (!btn && e.target !== sheet) return;
      sheet.onclick = null;
      sheet.classList.add('closing');
      setTimeout(() => { sheet.hidden = true; resolve(btn ? btn.dataset.view : null); }, 230);
    };
  });
}

function openApp(item) {
  disconnect();
  appWin = item;
  appVersion = null;
  $('#app').dataset.theme = item.appview;
  $('#app-title').textContent = item.title;
  $('#app-feed').textContent = '';
  $('#app-note').textContent = '';
  $('#app-input').value = '';
  closeDrawer();
  show('app');
  pollApp();
}

function stopApp() {
  appWin = null;
  clearTimeout(appTimer);
}

async function pollApp() {
  clearTimeout(appTimer);
  const win = appWin;
  if (!win) return;
  let wait = 1500;
  try {
    const model = await api('/api/app?id=' + win.id);
    if (appWin !== win) return;
    renderApp(model);
    wait = model.busy ? 700 : model.ready ? 1500 : 600;
  } catch (err) {
    if (appWin !== win || err.status === 401) return;
    if (err.status === 410 || err.status === 403) {
      loadSources('That window was closed, so sharing stopped.').catch(() => {});
      return;
    }
  }
  appTimer = setTimeout(pollApp, wait);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function renderApp(model) {
  if (model.v === appVersion) return;
  const first = appVersion === null;
  appVersion = model.v;
  appStop = model.busy ? model.stop : null;
  appEarlier = model.viewOnly ? null : model.earlier;
  const feed = $('#app-feed');
  const pinned = first || feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80;
  // Rebuilding the list must not move what you are reading. Older messages
  // arrive above, so then the distance from the bottom is what stays fixed.
  const fromTop = feed.scrollTop, fromBottom = feed.scrollHeight - feed.scrollTop;

  if (model.title) $('#app-title').textContent = model.title;
  feed.textContent = '';
  if (!model.messages.length) {
    feed.append(el('p', 'app-empty', model.ready ? 'No messages yet.' : 'Reading the app\u2026'));
  }
  for (const msg of model.messages) {
    const wrap = el('div', 'msg ' + msg.role);
    const body = msg.role === 'user' ? wrap.appendChild(el('div')) : wrap;
    for (const b of msg.blocks) {
      if (b.k === 'h') body.append(el('h3', '', b.t));
      else if (b.k === 'code') body.append(el('pre', '', b.t));
      else if (b.k === 'li' && b.ref) {
        const chip = el('button', 'li', b.t);
        chip.addEventListener('click', () => pressApp(b.ref));
        body.append(chip);
      } else if (b.k === 'li') body.append(el('div', 'li', b.t));
      else if (msg.role === 'user') body.append(el('div', '', b.t));
      else body.append(el('p', '', b.t));
    }
    feed.append(wrap);
  }
  if (model.busy) {
    const dots = el('div', 'typing');
    dots.append(el('i'), el('i'), el('i'));
    feed.append(dots);
  }
  appQuiet = Date.now() + 250;  // the scroll this causes is ours, not a swipe
  if (pinned) feed.scrollTop = feed.scrollHeight;
  else if (appLoading) feed.scrollTop = feed.scrollHeight - fromBottom;
  else feed.scrollTop = fromTop;
  appLoading = false;

  const controls = $('#app-controls');
  controls.textContent = '';
  for (const c of model.viewOnly ? [] : model.controls) {
    const chip = el('button', '', c.label);
    chip.type = 'button';
    chip.addEventListener('click', () => pressApp(c.ref));
    controls.append(chip);
  }
  const nav = $('#app-nav');
  nav.textContent = '';
  for (const n of model.nav) {
    const li = el('li'), btn = el('button', '', n.label);
    btn.addEventListener('click', () => { closeDrawer(); if (!model.viewOnly) pressApp(n.ref); });
    li.append(btn);
    nav.append(li);
  }
  const input = $('#app-input');
  input.placeholder = model.viewOnly ? 'View only' : (model.placeholder || 'Message');
  input.disabled = model.viewOnly || !model.canType;
  syncSend();
}

// The round button sends when there is text, and stops a running reply.
function syncSend() {
  const btn = $('#app-send'), hasText = $('#app-input').value.trim() !== '';
  const stop = !hasText && appStop !== null;
  btn.classList.toggle('stop', stop);
  btn.disabled = $('#app-input').disabled || (!hasText && !stop);
  btn.setAttribute('aria-label', stop ? 'Stop' : 'Send');
}

async function appPost(path, body) {
  if (!appWin) return;
  $('#app-note').textContent = '';
  try {
    await api(path, Object.assign({ id: appWin.id }, body));
  } catch (err) {
    $('#app-note').textContent = err.message;
  }
  clearTimeout(appTimer);
  appTimer = setTimeout(pollApp, 300);
}

function pressApp(ref) { return appPost('/api/app/press', { ref }); }

$('#app-composer').addEventListener('submit', (e) => {
  e.preventDefault();
  const input = $('#app-input'), text = input.value.trim();
  if (!text) {
    if (appStop !== null) pressApp(appStop);
    return;
  }
  input.value = '';
  input.style.height = '';
  syncSend();
  appPost('/api/app/send', { text });
});
$('#app-input').addEventListener('input', () => {
  const input = $('#app-input');
  input.style.height = 'auto';
  input.style.height = input.scrollHeight + 'px';
  syncSend();
});

// Swiping the chat scrolls the real app on the computer to the same place,
// and reaching the top asks it for earlier messages.
$('#app-feed').addEventListener('scroll', () => {
  const feed = $('#app-feed');
  if (!appWin || Date.now() < appQuiet) return;
  if (feed.scrollTop < 60 && appEarlier !== null && !appLoading) {
    appLoading = true;
    pressApp(appEarlier);
  }
  clearTimeout(appScrollTimer);
  appScrollTimer = setTimeout(() => {
    const range = feed.scrollHeight - feed.clientHeight;
    if (!appWin || range <= 0 || $('#app-input').disabled) return;
    api('/api/app/scroll', { id: appWin.id, pos: feed.scrollTop / range }).catch(() => {});
  }, 120);
}, { passive: true });

// Keep the app view inside the visible area when the keyboard opens, so the
// message list stays scrollable above it.
function fitApp() {
  const vv = window.visualViewport;
  if (!vv) return;
  $('#app').style.height = vv.height + 'px';
  $('#app').style.top = vv.offsetTop + 'px';
}
if (window.visualViewport) {
  visualViewport.addEventListener('resize', fitApp);
  visualViewport.addEventListener('scroll', fitApp);
}

function closeDrawer() { $('#app-drawer').hidden = $('#app-shade').hidden = true; }
$('#app-menu').addEventListener('click', () => { $('#app-drawer').hidden = $('#app-shade').hidden = false; });
$('#app-shade').addEventListener('click', closeDrawer);
$('#app-close').addEventListener('click', () => loadSources().catch(() => {}));
$('#app-desktop').addEventListener('click', () => {
  const win = appWin;
  if (win) connect({ kind: 'window', id: win.id });
});

// ---- WebRTC session ------------------------------------------------------

function status(text, busy) {
  $('#status').hidden = !text;
  $('#status').classList.toggle('still', !busy);
  $('#status span').textContent = text || '';
}

function iceComplete(conn) {
  if (conn.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => { clearTimeout(timer); resolve(); };
    const timer = setTimeout(done, 3000);
    conn.addEventListener('icegatheringstatechange', () => {
      if (conn.iceGatheringState === 'complete') done();
    });
  });
}

async function connect(source) {
  disconnect();
  show('view');
  fitViewport();
  status('Connecting', true);
  // No STUN/TURN: both ends are already on the same private tunnel.
  pc = new RTCPeerConnection({ iceServers: [] });
  const conn = pc;
  pc.addTransceiver('video', { direction: 'recvonly' });
  dc = pc.createDataChannel('input');
  dc.addEventListener('message', (e) => onHostMessage(JSON.parse(e.data)));
  // The host hangs up when the shared window closes; follow it straight away.
  dc.addEventListener('close', () => { if (pc === conn) leave('The connection ended.'); });
  pc.addEventListener('track', (e) => {
    video.srcObject = e.streams[0] || new MediaStream([e.track]);
    video.play().catch(() => {});
  });
  pc.addEventListener('connectionstatechange', () => {
    if (pc !== conn) return;
    if (conn.connectionState === 'connected') status('');
    if (conn.connectionState === 'disconnected') status('Reconnecting', true);
    if (conn.connectionState === 'failed') leave('The connection was lost.');
  });
  try {
    await pc.setLocalDescription(await pc.createOffer());
    await iceComplete(pc);
    const answer = await api('/api/offer', {
      sdp: pc.localDescription.sdp, type: pc.localDescription.type, source,
    });
    await pc.setRemoteDescription(answer);
  } catch (err) {
    if (pc === conn) leave(err.message);
  }
}

function disconnect() {
  const oldPc = pc, oldDc = dc;
  pc = dc = null;
  if (oldDc) oldDc.close();
  if (oldPc) oldPc.close();
  video.srcObject = null;
  keys.blur();
  pointer = null;
  $('#cursor').hidden = true;
  strokes.length = 0;
  setDrawing(false);
  setZoom(1, 0, 0);
}

function leave(note) {
  disconnect();
  if (token) loadSources(note).catch(() => {});
}

$('#leave').addEventListener('click', () => leave());
window.addEventListener('pagehide', disconnect);

function send(msg) {
  if (dc && dc.readyState === 'open') dc.send(JSON.stringify(msg));
}

function onHostMessage(msg) {
  if (msg.t === 'gone') {
    leave('That window was closed, so sharing stopped.');
  } else if (msg.t === 'ptr') {
    pointer = msg.off ? null : { x: msg.x, y: msg.y };
    if (pointer && style === 'controlled') followPointer();
    else drawPointer();
  } else if (msg.t === 'caret' && msg.on && document.activeElement !== keys) {
    // A text field took focus on the host. Browsers only open the keyboard
    // from a touch, so try, and pulse the button in case it is refused.
    keys.focus({ preventScroll: true });
    $('#kb').classList.toggle('hint', document.activeElement !== keys);
  }
}

// ---- Layout and zoom -----------------------------------------------------

// Zoom is purely local: a CSS transform on the <video>. The host keeps
// streaming the same picture and the desktop itself is never scaled.
const MAX_ZOOM = 8;
const zoom = { s: 1, x: 0, y: 0 };

const base = { w: 0, h: 0 };  // the picture at 1x: as large as fits the stage

// Drawing is a note to yourself: it lives on a canvas over the picture and
// is never sent to the computer. Strokes are stored as fractions of the
// picture, so they stay on the same spot when you zoom, pan or rotate.
const ink = $('#ink'), strokes = [];
let drawing = false;

function drawInk() {
  const dpr = window.devicePixelRatio || 1;
  const w = stage.clientWidth, h = stage.clientHeight;
  if (ink.width !== Math.round(w * dpr) || ink.height !== Math.round(h * dpr)) {
    ink.width = Math.round(w * dpr);
    ink.height = Math.round(h * dpr);
  }
  const ctx = ink.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = ctx.fillStyle = '#ff453a';
  ctx.lineWidth = 3.5;
  ctx.lineCap = ctx.lineJoin = 'round';
  const px = (p) => [zoom.x + p.x * base.w * zoom.s, zoom.y + p.y * base.h * zoom.s];
  for (const stroke of strokes) {
    ctx.beginPath();
    if (stroke.length === 1) {
      ctx.arc(...px(stroke[0]), 2, 0, 7);
      ctx.fill();
      continue;
    }
    ctx.moveTo(...px(stroke[0]));
    for (const p of stroke.slice(1)) ctx.lineTo(...px(p));
    ctx.stroke();
  }
  $('#inkbar').hidden = !drawing;
  $('#undo').disabled = $('#clear').disabled = !strokes.length;
}

function setDrawing(on) {
  drawing = on;
  $('#draw').classList.toggle('on', on);
  $('#draw').setAttribute('aria-pressed', on);
  stage.classList.toggle('inking', on);
  drawInk();
}
$('#draw').addEventListener('click', () => setDrawing(!drawing));
$('#undo').addEventListener('click', () => { strokes.pop(); drawInk(); });
$('#clear').addEventListener('click', () => { strokes.length = 0; drawInk(); });

// x, y are where the picture's top-left corner sits inside the stage. Along
// an axis where the picture is smaller than the stage it stays centred;
// where it is larger it can be panned but never pulled away from the edges.
function setZoom(s, x, y) {
  s = Math.min(Math.max(s, 1), MAX_ZOOM);
  const along = (stageSize, size, pos) =>
    size <= stageSize ? (stageSize - size) / 2 : Math.min(0, Math.max(stageSize - size, pos));
  zoom.s = s;
  zoom.x = along(stage.clientWidth, base.w * s, x);
  zoom.y = along(stage.clientHeight, base.h * s, y);
  video.style.transform = `translate(${zoom.x}px, ${zoom.y}px) scale(${s})`;
  $('#zoom').hidden = s < 1.05;
  $('#zoom').textContent = s.toFixed(1) + '×';
  drawPointer();
  drawInk();
}

// The stream does not include the mouse pointer, so with the trackpad the
// host reports where it is and the phone draws it on top of the picture.
let pointer = null;

function pointerOnStage() {
  return { x: zoom.x + pointer.x * base.w * zoom.s, y: zoom.y + pointer.y * base.h * zoom.s };
}

function drawPointer() {
  const el = $('#cursor');
  el.hidden = !pointer;
  if (!pointer) return;
  const p = pointerOnStage();
  el.style.transform = `translate(${p.x}px, ${p.y}px)`;
}

// When zoomed in, slide the view so the pointer never leaves it.
function followPointer() {
  const p = pointerOnStage(), m = 24;
  const dx = p.x < m ? m - p.x : Math.min(0, stage.clientWidth - m - p.x);
  const dy = p.y < m ? m - p.y : Math.min(0, stage.clientHeight - m - p.y);
  if ((dx || dy) && zoom.s > 1) setZoom(zoom.s, zoom.x + dx, zoom.y + dy);
  else drawPointer();
}

$('#zoom').addEventListener('click', () => setZoom(1, 0, 0));

// Size the picture to the stage. Runs whenever either one changes: phone
// rotated, keyboard shown or hidden, or the shared window resized.
function layout() {
  const vw = video.videoWidth || 16, vh = video.videoHeight || 9;
  const fit = Math.min(stage.clientWidth / vw, stage.clientHeight / vh);
  base.w = vw * fit;
  base.h = vh * fit;
  video.style.width = base.w + 'px';
  video.style.height = base.h + 'px';
  setZoom(zoom.s, zoom.x, zoom.y);
}
video.addEventListener('resize', layout);
video.addEventListener('loadedmetadata', layout);

// Keep the session exactly as tall as what is visible, so the picture
// re-fits on rotation and when the on-screen keyboard slides up.
function fitViewport() {
  const vv = window.visualViewport;
  if (vv) {
    view.style.height = vv.height + 'px';
    view.style.top = vv.offsetTop + 'px';
  }
  layout();
}
if (window.visualViewport) {
  visualViewport.addEventListener('resize', fitViewport);
  visualViewport.addEventListener('scroll', fitViewport);
}
window.addEventListener('resize', fitViewport);

// ---- Touch -> mouse ------------------------------------------------------

const TAP_MS = 350, HOLD_MS = 350, SLOP = 8, PINCH_SLOP = 18, EDGE = 28;
let gesture = null, pendingMove = null;

// Map a touch (CSS pixels) to a 0..1 position inside the video picture.
// The element is exactly the picture, and its bounding box already includes
// the zoom transform, so local zoom and pan never change what a touch means.
// The host turns the result into desktop pixels: X = left + x * (width - 1).
function toStream(touch) {
  const box = video.getBoundingClientRect();
  if (!video.videoWidth || !box.width) return null;
  const x = (touch.clientX - box.left) / box.width;
  const y = (touch.clientY - box.top) / box.height;
  return { x: Math.min(Math.max(x, 0), 1), y: Math.min(Math.max(y, 0), 1) };
}

function pinchState(touches) {
  const box = stage.getBoundingClientRect();
  return {
    x: (touches[0].clientX + touches[1].clientX) / 2 - box.left,
    y: (touches[0].clientY + touches[1].clientY) / 2 - box.top,
    d: Math.hypot(touches[0].clientX - touches[1].clientX, touches[0].clientY - touches[1].clientY),
  };
}

function queueMove(p) {
  if (!pendingMove) {
    requestAnimationFrame(() => {
      send({ t: 'move', x: pendingMove.x, y: pendingMove.y });
      pendingMove = null;
    });
  }
  pendingMove = p;
}

// While zoomed in, pushing the pointer against an edge slides the view.
function edgePan(t) {
  if (zoom.s === 1) return;
  const box = stage.getBoundingClientRect();
  const dx = t.clientX - box.left < EDGE ? 10 : box.right - t.clientX < EDGE ? -10 : 0;
  const dy = t.clientY - box.top < EDGE ? 10 : box.bottom - t.clientY < EDGE ? -10 : 0;
  if (dx || dy) setZoom(zoom.s, zoom.x + dx, zoom.y + dy);
}

stage.addEventListener('touchstart', (e) => {
  e.preventDefault();
  if (e.touches.length === 1 && !gesture && drawing) {
    // Pencil on: one finger draws, and nothing is sent to the computer.
    const p = toStream(e.touches[0]);
    if (!p) return;
    gesture = { mode: 'ink', stroke: [p], t0: Date.now() };
    strokes.push(gesture.stroke);
    drawInk();
  } else if (e.touches.length === 1 && !gesture && style === 'controlled') {
    // The trackpad owns the mouse here; on the picture one finger only pans.
    const t = e.touches[0];
    gesture = { mode: 'pan', x: t.clientX, y: t.clientY, t0: Date.now() };
  } else if (e.touches.length === 1 && !gesture) {
    const t = e.touches[0];
    const p = toStream(t);
    if (!p) return;
    gesture = { mode: 'one', p, sx: t.clientX, sy: t.clientY, t0: Date.now(), moved: false, drag: false };
    send({ t: 'move', x: p.x, y: p.y });
    // Press and hold without moving starts a left-button drag.
    gesture.timer = setTimeout(() => {
      if (gesture && gesture.mode === 'one' && !gesture.moved) {
        gesture.drag = true;
        send({ t: 'down', b: 'left', x: gesture.p.x, y: gesture.p.y });
        if (navigator.vibrate) navigator.vibrate(15);
      }
    }, HOLD_MS);
  } else if (e.touches.length === 2 && gesture && gesture.mode !== 'two') {
    clearTimeout(gesture.timer);
    if (gesture.drag) send({ t: 'up', b: 'left', x: gesture.p.x, y: gesture.p.y });
    if (gesture.mode === 'ink' && gesture.stroke.length < 4) {
      strokes.pop();  // the first finger of a pinch, not a stroke
      drawInk();
    }
    const c = pinchState(e.touches);
    Object.assign(gesture, { mode: 'two', kind: null, drag: false, c, c0: c, t0: Date.now() });
  }
}, { passive: false });

stage.addEventListener('touchmove', (e) => {
  e.preventDefault();
  if (!gesture) return;
  if (gesture.mode === 'ink' && e.touches.length === 1) {
    const p = toStream(e.touches[0]);
    if (p) { gesture.stroke.push(p); drawInk(); }
  } else if (gesture.mode === 'pan' && e.touches.length === 1) {
    const t = e.touches[0];
    setZoom(zoom.s, zoom.x + t.clientX - gesture.x, zoom.y + t.clientY - gesture.y);
    gesture.x = t.clientX;
    gesture.y = t.clientY;
  } else if (gesture.mode === 'one' && e.touches.length === 1) {
    const t = e.touches[0];
    if (Math.hypot(t.clientX - gesture.sx, t.clientY - gesture.sy) > SLOP) gesture.moved = true;
    if (gesture.moved || gesture.drag) {
      edgePan(t);
      const p = toStream(t);
      if (p) { gesture.p = p; queueMove(p); }
    }
  } else if (gesture.mode === 'two' && e.touches.length === 2) {
    const c = pinchState(e.touches), prev = gesture.c;
    // Fingers spreading or closing means zoom; fingers travelling together
    // means scroll. Decided once per gesture so the two never fight.
    if (!gesture.kind) {
      if (Math.abs(c.d - gesture.c0.d) > PINCH_SLOP) gesture.kind = 'zoom';
      else if (Math.hypot(c.x - gesture.c0.x, c.y - gesture.c0.y) > SLOP) gesture.kind = 'scroll';
    }
    if (gesture.kind === 'zoom') {
      const s = Math.min(Math.max(zoom.s * c.d / prev.d, 1), MAX_ZOOM);
      const k = s / zoom.s;
      // Keep the point under the fingers fixed, and follow them as they pan.
      setZoom(s, c.x - (prev.x - zoom.x) * k, c.y - (prev.y - zoom.y) * k);
    } else if (gesture.kind === 'scroll' && !drawing) {
      send({ t: 'scroll', dx: c.x - prev.x, dy: c.y - prev.y });
    }
    gesture.c = c;
  }
}, { passive: false });

function endGesture(e) {
  e.preventDefault();
  if (!gesture || e.touches.length) return;
  clearTimeout(gesture.timer);
  const g = gesture, quick = Date.now() - g.t0 < TAP_MS;
  gesture = null;
  if (g.mode === 'one') {
    if (g.drag) send({ t: 'up', b: 'left', x: g.p.x, y: g.p.y });
    else if (!g.moved && quick) send({ t: 'click', b: 'left', x: g.p.x, y: g.p.y });
  } else if (g.mode === 'two' && !g.kind && quick && g.p) {
    send({ t: 'click', b: 'right', x: g.p.x, y: g.p.y });
  }
}
stage.addEventListener('touchend', endGesture, { passive: false });
stage.addEventListener('touchcancel', endGesture, { passive: false });

// ---- Resizable split (controlled style) ----------------------------------

// Drag the bar between the picture and the trackpad to share the space
// differently. The share is remembered on this phone.
const divider = $('#divider'), SPLIT_KEY = 'pocketdesk_split';
let split = 0.5;
try { split = parseFloat(localStorage.getItem(SPLIT_KEY)) || 0.5; } catch (e) { /* default */ }

function setSplit(share) {
  split = Math.min(Math.max(share, 0.2), 0.8);
  // Scaled so each is above 1; in the default style the picture is alone
  // and must still fill everything.
  stage.style.flexGrow = split * 100;
  $('#pad').style.flexGrow = (1 - split) * 100;
  layout();
}
setSplit(split);

divider.addEventListener('pointerdown', (e) => {
  e.preventDefault();
  divider.setPointerCapture(e.pointerId);
  divider.classList.add('dragging');
});
divider.addEventListener('pointermove', (e) => {
  if (!divider.classList.contains('dragging')) return;
  const box = $('#split').getBoundingClientRect();
  const sideBySide = getComputedStyle($('#split')).flexDirection === 'row';
  setSplit(sideBySide ? (e.clientX - box.left) / box.width : (e.clientY - box.top) / box.height);
});
function endSplit() {
  if (!divider.classList.contains('dragging')) return;
  divider.classList.remove('dragging');
  try { localStorage.setItem(SPLIT_KEY, split.toFixed(3)); } catch (e) { /* not remembered */ }
}
divider.addEventListener('pointerup', endSplit);
divider.addEventListener('pointercancel', endSplit);

// ---- Trackpad (controlled style) -----------------------------------------

// Works like a laptop trackpad: slide to move the pointer from where it is,
// tap to click, two-finger tap to right-click, two-finger slide to scroll.
// The buttons below it can be held with one thumb while the other drags.
const surface = $('#surface');
const PAD_SPEED = 1.5;
let pad = null, padMove = null;

function padCentre(touches) {
  return {
    x: (touches[0].clientX + touches[1].clientX) / 2,
    y: (touches[0].clientY + touches[1].clientY) / 2,
  };
}

function queueRel(dx, dy) {
  if (!padMove) {
    padMove = { dx: 0, dy: 0 };
    requestAnimationFrame(() => {
      send({ t: 'rel', dx: padMove.dx, dy: padMove.dy });
      padMove = null;
    });
  }
  padMove.dx += dx;
  padMove.dy += dy;
}

surface.addEventListener('touchstart', (e) => {
  e.preventDefault();
  const ts = e.targetTouches;
  surface.classList.add('touching', 'used');
  if (ts.length === 1 && !pad) {
    pad = { mode: 'one', x: ts[0].clientX, y: ts[0].clientY, t0: Date.now(), travel: 0 };
  } else if (ts.length === 2 && pad && pad.mode === 'one') {
    Object.assign(pad, { mode: 'two', c: padCentre(ts), t0: Date.now(), travel: 0 });
  }
}, { passive: false });

surface.addEventListener('touchmove', (e) => {
  e.preventDefault();
  const ts = e.targetTouches;
  if (!pad) return;
  if (pad.mode === 'one' && ts.length === 1) {
    const dx = ts[0].clientX - pad.x, dy = ts[0].clientY - pad.y;
    pad.x = ts[0].clientX;
    pad.y = ts[0].clientY;
    pad.travel += Math.abs(dx) + Math.abs(dy);
    // Slow strokes are precise, fast strokes cross the screen.
    const gain = PAD_SPEED * (1 + Math.min(Math.hypot(dx, dy) / 10, 2.5));
    if (pad.travel > SLOP) queueRel(dx * gain, dy * gain);
  } else if (pad.mode === 'two' && ts.length === 2) {
    const c = padCentre(ts);
    pad.travel += Math.abs(c.x - pad.c.x) + Math.abs(c.y - pad.c.y);
    if (pad.travel > SLOP) send({ t: 'scroll', dx: c.x - pad.c.x, dy: c.y - pad.c.y });
    pad.c = c;
  }
}, { passive: false });

function endPad(e) {
  e.preventDefault();
  if (e.targetTouches.length) return;
  surface.classList.remove('touching');
  if (!pad) return;
  const p = pad;
  pad = null;
  if (p.travel <= SLOP && Date.now() - p.t0 < TAP_MS) {
    send({ t: 'click', b: p.mode === 'one' ? 'left' : 'right' });
  }
}
surface.addEventListener('touchend', endPad, { passive: false });
surface.addEventListener('touchcancel', endPad, { passive: false });

for (const [id, b] of [['#lclick', 'left'], ['#rclick', 'right']]) {
  const btn = $(id);
  const set = (down) => (e) => {
    e.preventDefault();
    if (btn.classList.contains('down') === down) return;
    btn.classList.toggle('down', down);
    send({ t: down ? 'down' : 'up', b });
  };
  btn.addEventListener('pointerdown', set(true));
  btn.addEventListener('pointerup', set(false));
  btn.addEventListener('pointercancel', set(false));
  btn.addEventListener('pointerleave', set(false));
}

// ---- Mouse and keyboard (desktop device) ----------------------------------

// On a computer the local mouse is the remote mouse: move, press, release
// and wheel go across as they happen. In the controlled style the picture
// only pans, and the trackpad panel takes the mouse instead.
const BUTTONS = ['left', 'middle', 'right'];
let mouseInk = null, mousePan = null;
const mouseHeld = new Set();

stage.addEventListener('mousedown', (e) => {
  if (device !== 'desktop') return;
  e.preventDefault();
  const p = toStream(e);
  if (drawing) {
    if (!p) return;
    mouseInk = [p];
    strokes.push(mouseInk);
    drawInk();
  } else if (style === 'controlled') {
    mousePan = { x: e.clientX, y: e.clientY };
  } else if (p && BUTTONS[e.button]) {
    mouseHeld.add(BUTTONS[e.button]);
    send({ t: 'down', b: BUTTONS[e.button], x: p.x, y: p.y });
  }
});

window.addEventListener('mousemove', (e) => {
  if (device !== 'desktop' || view.hidden) return;
  if (mouseInk) {
    const p = toStream(e);
    if (p) { mouseInk.push(p); drawInk(); }
  } else if (mousePan) {
    setZoom(zoom.s, zoom.x + e.clientX - mousePan.x, zoom.y + e.clientY - mousePan.y);
    mousePan = { x: e.clientX, y: e.clientY };
  } else if (style !== 'controlled' && !drawing && (mouseHeld.size || e.target === stage || stage.contains(e.target))) {
    const p = toStream(e);
    if (p) queueMove(p);
  }
});

window.addEventListener('mouseup', (e) => {
  if (device !== 'desktop') return;
  mouseInk = mousePan = null;
  const b = BUTTONS[e.button];
  if (mouseHeld.delete(b)) {
    const p = toStream(e) || { x: 0, y: 0 };
    send({ t: 'up', b, x: p.x, y: p.y });
  }
});

stage.addEventListener('contextmenu', (e) => { if (device === 'desktop') e.preventDefault(); });

// Wheel scrolls the remote app; with Ctrl held it zooms the local picture.
stage.addEventListener('wheel', (e) => {
  if (device !== 'desktop') return;
  e.preventDefault();
  if (e.ctrlKey) {
    const box = stage.getBoundingClientRect();
    const x = e.clientX - box.left, y = e.clientY - box.top;
    const s = Math.min(Math.max(zoom.s * Math.exp(-e.deltaY / 300), 1), MAX_ZOOM), k = s / zoom.s;
    setZoom(s, x - (x - zoom.x) * k, y - (y - zoom.y) * k);
  } else if (!drawing) {
    const unit = e.deltaMode === 1 ? 30 : 1;  // lines or pixels
    send({ t: 'scroll', dx: -e.deltaX * unit, dy: -e.deltaY * unit });
  }
}, { passive: false });

// The trackpad panel with a mouse: drag to move the remote pointer, click
// to click, right-click to right-click, wheel to scroll.
let padMouse = null;
surface.addEventListener('mousedown', (e) => {
  if (device !== 'desktop' || e.button !== 0) return;
  e.preventDefault();
  surface.classList.add('touching', 'used');
  padMouse = { x: e.clientX, y: e.clientY, travel: 0 };
});
window.addEventListener('mousemove', (e) => {
  if (!padMouse) return;
  const dx = e.clientX - padMouse.x, dy = e.clientY - padMouse.y;
  padMouse.x = e.clientX;
  padMouse.y = e.clientY;
  padMouse.travel += Math.abs(dx) + Math.abs(dy);
  if (padMouse.travel > 3) queueRel(dx * PAD_SPEED, dy * PAD_SPEED);
});
window.addEventListener('mouseup', () => {
  if (!padMouse) return;
  surface.classList.remove('touching');
  if (padMouse.travel <= 3) send({ t: 'click', b: 'left' });
  padMouse = null;
});
surface.addEventListener('contextmenu', (e) => {
  if (device !== 'desktop') return;
  e.preventDefault();
  send({ t: 'click', b: 'right' });
});
surface.addEventListener('wheel', (e) => {
  if (device !== 'desktop') return;
  e.preventDefault();
  send({ t: 'scroll', dx: -e.deltaX, dy: -e.deltaY });
}, { passive: false });

// Every key pressed while the session is showing goes to the remote app.
// Shortcuts the browser keeps for itself (Ctrl+W, Ctrl+T, Alt+Tab...) never
// reach the page; use the on-screen modifier keys for those.
const MOD_KEYS = new Set(['Control', 'Shift', 'Alt', 'Meta', 'CapsLock', 'AltGraph']);
window.addEventListener('keydown', (e) => {
  if (device !== 'desktop' || view.hidden || e.isComposing || MOD_KEYS.has(e.key)) return;
  const held = [...mods];
  if (e.ctrlKey) held.push('ctrl');
  if (e.altKey) held.push('alt');
  if (e.metaKey) held.push('meta');
  const named = SPECIAL.has(e.key) || /^F\d{1,2}$/.test(e.key);
  if (!named && e.key.length !== 1) return;
  e.preventDefault();
  if (named || held.length) {
    if (e.shiftKey) held.push('shift');
    takeMods();
    send({ t: 'key', k: e.key, mods: [...new Set(held)] });
  } else {
    send({ t: 'text', s: e.key });
  }
});

// ---- Keyboard ------------------------------------------------------------

// The hidden textarea always holds one sentinel character followed by what
// has been typed since the last reset. Diffing against what was already sent
// turns anything the on-screen keyboard does (autocorrect, IME composition,
// swipe typing) into plain "delete N, then type S" on the host.
const SENTINEL = ' ';
const SPECIAL = new Set(['Enter', 'Backspace', 'Tab', 'Escape', 'Delete', 'ArrowUp', 'ArrowDown',
  'ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageUp', 'PageDown']);
const mods = new Set();
let sent = '';

function resetKeys() {
  keys.value = SENTINEL;
  sent = '';
  keys.setSelectionRange(1, 1);
}

function takeMods() {
  const list = [...mods];
  mods.clear();
  for (const b of document.querySelectorAll('[data-mod]')) b.classList.remove('on');
  return list;
}

function sendKey(k) { send({ t: 'key', k, mods: takeMods() }); }

keys.addEventListener('input', (e) => {
  const value = keys.value;
  if (!value.startsWith(SENTINEL)) {  // backspace with nothing left to diff
    if (!e.isComposing) { sendKey('Backspace'); resetKeys(); }
    return;
  }
  const now = value.slice(1);
  let same = 0;
  while (same < sent.length && same < now.length && sent[same] === now[same]) same++;
  for (let i = sent.length; i > same; i--) send({ t: 'key', k: 'Backspace', mods: [] });
  const added = now.slice(same);
  if (added === '\n') sendKey('Enter');
  else if (added.length === 1 && mods.size) sendKey(added);  // e.g. Ctrl + C
  else if (added) send({ t: 'text', s: added });
  sent = now;
  if (!e.isComposing && (sent.length > 48 || added.includes('\n'))) resetKeys();
});

// Hardware keyboards and browsers that report real key names.
keys.addEventListener('keydown', (e) => {
  if (SPECIAL.has(e.key) && !e.isComposing) {
    e.preventDefault();
    sendKey(e.key);
    resetKeys();
  }
});

$('#kb').addEventListener('click', () => {
  $('#kb').classList.remove('hint');
  if (document.activeElement === keys) keys.blur();
  else { resetKeys(); keys.focus({ preventScroll: true }); }
});
keys.addEventListener('focus', () => { resetKeys(); $('#kb').classList.add('on'); });
keys.addEventListener('blur', () => $('#kb').classList.remove('on'));

for (const btn of document.querySelectorAll('#bar button')) {
  // Keep the on-screen keyboard open while toolbar buttons are used.
  if (btn.id !== 'kb') btn.addEventListener('pointerdown', (e) => e.preventDefault());
}
for (const btn of document.querySelectorAll('[data-mod]')) {
  btn.addEventListener('click', () => {
    const m = btn.dataset.mod;
    if (mods.delete(m)) btn.classList.remove('on');
    else { mods.add(m); btn.classList.add('on'); }
  });
}
for (const btn of document.querySelectorAll('[data-key]')) {
  btn.addEventListener('click', () => sendKey(btn.dataset.key));
}

// ---- Start ---------------------------------------------------------------

(async function start() {
  await chooseDevice();
  await chooseStyle();
  if (token) {
    try { await loadSources(); return; } catch (e) { /* expired: ask for the PIN */ }
  }
  show('pair');
})();
