(() => {
'use strict';
const $ = (s) => document.querySelector(s);
const MOCK_FORCED = new URLSearchParams(location.search).has('mock');
const TEST_DEFAULT = [   // info.tests가 없을 때 (예전 서버·목업)
  { skill: 'oranda_pickup', label: '오란다 1회', enabled: true, reason: '' },
  { skill: 'dori_dori', label: '도리도리 1회', enabled: true, reason: '' },
  { skill: 'dori_script', label: '코드 도리도리 1회', enabled: true, reason: '' },
  { skill: 'home', label: '홈으로', enabled: true, reason: '' }];

const S = { state: 'IDLE', phase: 'idle', count: 0, remaining: null, vision_method: null, skill: null,
  vision_choice: 'off', vision_options: [], last_count: null,
  th: { safe_max: 3, force_refuse: 6 }, name: '과자', got: false, cycles: [], mock: false,
  twin: { mode: 'replay', urdf: 'twin/so101/so101_new_calib.urdf' }, replays: [], tests: TEST_DEFAULT };

const STATE_KO = { IDLE: '대기', WORKING: '작업 중', REFUSING: '거부 중', DONE: '완료', ESTOP: '비상정지', TESTING: '테스트' };
const PHASE_KO = { idle: '쉬는 중', counting: '개수 세는 중', thinking: '생각 중', speaking: '말하는 중', acting: '옮기는 중', returning: '제자리로', waiting_operator: '도움 필요' };
const METHOD_KO = { yolo: 'YOLO', vlm: 'VLM', opencv: 'OpenCV', fake: '테스트 값' };
const STEP_ORDER = ['counting', 'thinking', 'speaking', 'acting', 'returning'];

/* ---------- render ---------- */
function renderState() {
  document.body.dataset.state = S.state;
  document.body.dataset.phase = S.phase;
  $('#stateBadge').textContent = STATE_KO[S.state] || S.state;
  const testing = S.state === 'TESTING';
  $('#phaseLabel').textContent = testing && S.phase === 'acting' ? '실행 중' : PHASE_KO[S.phase] || S.phase;
  const idx = STEP_ORDER.indexOf(S.phase);
  const stepping = S.state === 'WORKING' || testing;
  const first = testing ? STEP_ORDER.indexOf('acting') : 0;   // 테스트는 옮기기 → 복귀만
  document.querySelectorAll('#steps li').forEach((li, i) => {
    li.className = idx < 0 || !stepping || i < first ? '' : i < idx ? 'done' : i === idx ? 'on' : '';
  });

  const { safe_max, force_refuse } = S.th;
  let tier, fill, mark, countTxt, maxTxt;
  if (S.refuse_mode === 'half') {   // 전체의 절반을 옮기면 거부: 옮긴 수(전체 − 남은)와 거부 시점으로 계산
    const moved = S.total != null && S.remaining != null ? Math.max(0, S.total - S.remaining) : 0;
    const at = S.refuse_at;
    if (at) {
      tier = S.state === 'REFUSING' || moved >= at ? 'max' : moved >= at - 1 ? 'mid' : '';
      fill = (moved / at) * 100; mark = ((at - 1) / at) * 100;
      maxTxt = `전체 ${S.total} · ${at}개째 뒤 거부`;
    } else {
      tier = ''; mark = 100;
      fill = S.total ? (moved / S.total) * 100 : 0;
      maxTxt = S.total ? `전체 ${S.total} · 거부 없음` : '대기 중';
    }
    countTxt = `${moved}개 옮김`;
  } else {
    tier = S.count >= force_refuse ? 'max' : S.count > safe_max ? 'mid' : '';
    fill = (S.count / Math.max(1, force_refuse)) * 100;
    mark = (safe_max / Math.max(1, force_refuse)) * 100;
    countTxt = `${S.count}회 옮김`; maxTxt = `한계 ${force_refuse}회`;
  }
  const t = $('#fatigueTier');
  t.textContent = tier === 'max' ? '한계' : tier === 'mid' ? '지침' : '쌩쌩';
  t.className = 'tier ' + tier;
  const f = $('#gaugeFill');
  f.className = 'gauge-fill ' + tier;
  f.style.width = Math.min(100, fill) + '%';
  $('#gaugeMark').style.left = mark + '%';
  $('#gaugeCount').textContent = countTxt;
  $('#gaugeMax').textContent = maxTxt;

  let mood = tier === 'max' ? 'limit' : tier === 'mid' ? 'tired' : 'fresh';
  if (S.state === 'REFUSING') mood = 'refuse';
  else if (S.state === 'DONE') mood = 'done';
  else if (S.state === 'ESTOP') mood = 'estop';
  $('#robot').dataset.mood = mood;

  const n = $('#cntNum');
  const txt = S.remaining == null ? '–' : String(S.remaining);
  if (n.textContent !== txt) { n.textContent = txt; n.classList.remove('bump'); void n.offsetWidth; n.classList.add('bump'); }
  $('#cntName').textContent = S.name;
  const m = S.vision_method;
  $('#cntMethod').innerHTML = !m ? '' : m === 'estimate'
    ? '개수 · <em>추정</em> 시작 개수 − 성공 수'
    : `개수를 센 방법 · ${METHOD_KO[m] || m}`;

  renderVision();
  const st = S.state;
  $('#btnResume').disabled = !(st === 'REFUSING' || S.phase === 'waiting_operator');
  $('#btnRestart').disabled = st !== 'ESTOP';
  $('#btnEstop').disabled = !S.got || st === 'IDLE' || st === 'DONE' || (st === 'ESTOP' && S.phase !== 'returning');
  document.querySelectorAll('#testBtns .btn-test').forEach((b) => {   // 대기일 때만, 모델 없는 버튼은 꺼 둔다
    const t = S.tests.find((x) => x.skill === b.dataset.skill) || {};
    b.disabled = !S.got || st !== 'IDLE' || t.enabled === false;
    b.title = t.enabled === false ? (t.reason || '모델 없음') : '';
  });
}

const CHOICE_KO = { off: '끔', auto: '자동', opencv: 'OpenCV', yolo: 'YOLO', vlm: 'VLM', fake: '테스트 값' };
let visionKey = '';
function renderVision() {   // 서버가 알려 준 선택지만 보여 준다 (없으면 칸 전체 숨김)
  const opts = S.vision_options || [];
  $('#visionBox').hidden = !opts.length;
  const key = opts.join('|');
  if (key !== visionKey) {
    visionKey = key;
    const seg = $('#visionSeg');
    seg.innerHTML = '';
    opts.forEach((o) => {
      const b = document.createElement('button');
      b.type = 'button'; b.dataset.opt = o; b.textContent = CHOICE_KO[o] || o;
      b.onclick = () => sendWS({ type: 'command', name: 'vision_method', method: o });
      seg.appendChild(b);
    });
  }
  seg_pressed();
  $('#btnCount').disabled = !S.got || S.state !== 'IDLE' || S.vision_choice === 'off' || !opts.length;
  const c = S.last_count;
  $('#visionLast').textContent = c ? `${S.name} ${c.n}개 · ${METHOD_KO[c.method] || c.method} · ${c.ms}ms` : '';
}
function seg_pressed() {
  document.querySelectorAll('#visionSeg button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.opt === S.vision_choice)));
}

function renderInfo(m) {
  if (m.target && m.target.name) S.name = m.target.name;
  const mod = m.models || {};
  document.querySelectorAll('#models > div').forEach((d) => {
    d.querySelector('dd').textContent = mod[d.dataset.k] || '–';
    d.querySelector('dd').title = mod[d.dataset.k] || '';
  });
  clearReplay();
  Object.keys(replayData).forEach((k) => delete replayData[k]);   // 서버 재시작 뒤 새 녹화를 받도록
  S.twin = m.twin || { mode: S.mock ? 'mock' : 'replay', urdf: DEFAULT_URDF };
  S.replays = Array.isArray(m.replays) ? m.replays : [];
  S.tests = Array.isArray(m.tests) && m.tests.length ? m.tests : TEST_DEFAULT;
  buildTestButtons();
  buildTiles(m.ui && m.ui.tiles);
  S.replays.forEach((skill) => loadReplay(skill).then((d) => {   // 미리 받아 두면 acting 순간 바로 튼다
    if (d && !lastQ && S.twin.mode === 'replay' && d.q && d.q.length) setJoints(d.q[0]);
  }));
  renderState();
}

function renderCycles() {
  const real = S.cycles.filter((c) => c.result !== 'done' && c.result !== 'estop');
  const ok = real.filter((c) => c.result === 'success').length;
  $('#succRate').textContent = real.length ? Math.round((ok / real.length) * 100) + '%' : '–';
  $('#succDetail').textContent = real.length ? `${ok}/${real.length}` : '';
  $('#cycleDots').innerHTML = S.cycles.slice(-10).map((c) => `<i class="${c.result}" title="#${c.n} ${c.result}"></i>`).join('');
  const last = [...S.cycles].reverse().find((c) => c.ms) || {};
  const ms = last.ms || {};
  const max = Math.max(1, ...Object.values(ms).filter((v) => typeof v === 'number'));
  document.querySelectorAll('#timings .tm').forEach((el) => {
    const v = ms[el.dataset.k];
    const has = typeof v === 'number';
    el.querySelector('b').innerHTML = has ? `${Math.round(v).toLocaleString()}<small>ms</small>` : '–';
    el.querySelector('.bar i').style.width = has ? (v / max) * 100 + '%' : '0';
  });
}

const log = $('#chatLog');
function addMsg(m) {
  const e = $('#chatEmpty'); if (e) e.remove();
  const d = document.createElement('div');
  d.className = 'msg ' + m.role;
  if (m.role === 'robot') { const av = document.createElement('div'); av.className = 'av'; d.appendChild(av); }
  const b = document.createElement('div'); b.className = 'bub';
  if (m.role === 'user' && m.source === 'voice') {
    b.insertAdjacentHTML('beforeend', '<svg class="mic-i" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>');
  }
  b.appendChild(document.createTextNode(m.text));
  d.appendChild(b);
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
}
function clearChat() { log.innerHTML = '<div class="chat-empty" id="chatEmpty">대화가 없어요. 말을 걸어 보세요.</div>'; }

/* ---------- message handling ---------- */
function handle(m) {
  switch (m.type) {
    case 'info': renderInfo(m); break;
    case 'state': {
      const prev = { state: S.state, phase: S.phase, skill: S.skill };
      S.got = true;
      S.state = m.state; S.phase = m.phase || 'idle';
      S.count = m.count ?? 0; S.remaining = m.remaining ?? null;
      S.vision_method = m.vision_method || null; S.skill = m.skill || null;
      S.vision_choice = m.vision_choice || 'off'; S.vision_options = Array.isArray(m.vision_options) ? m.vision_options : [];
      S.last_count = m.last_count || null;
      S.total = m.total ?? null; S.refuse_at = m.refuse_at ?? null; S.refuse_mode = m.refuse_mode || 'fixed';
      if (m.thresholds) S.th = { safe_max: m.thresholds.safe_max, force_refuse: m.thresholds.force_refuse };
      renderState();
      onReplayState(prev);
      break;
    }
    case 'message': addMsg(m); break;
    case 'cycle': S.cycles.push(m); if (S.cycles.length > 50) S.cycles.shift(); renderCycles(); break;
    case 'joints': if (!replay && Array.isArray(m.q)) setJoints(m.q); break;
  }
}

/* ---------- connection ---------- */
const conn = $('#conn');
function setConn(on, label) {
  conn.className = 'pill ' + (on ? 'pill-on' : 'pill-off');
  conn.querySelector('b').textContent = label;
}
let ws, mock, retryT, everOpened = false;

function startMock() {
  if (mock) return;
  S.mock = true; $('#mockTag').hidden = false;
  resetUI();
  mock = createMock(handle);
  setConn(true, '시뮬레이터');
  mock.start();
  startSway();
}
function stopMock() {
  if (!mock) return;
  mock.stop(); mock = null; S.mock = false; lastQ = null; $('#mockTag').hidden = true; stopSway(); resetUI();
  tiles.forEach((t) => { if (t.spec.kind === 'camera') loadStream(t); });
}
function resetUI() {
  clearReplay();
  clearChat(); S.cycles = []; S.got = false; S.state = 'IDLE'; S.phase = 'idle'; S.count = 0; S.remaining = null; S.vision_method = null;
  renderCycles(); renderState();
}
function connect() {
  clearTimeout(retryT);
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  let opened = false;
  try { ws = new WebSocket(`${proto}://${location.host}/ws`); } catch (e) { fail(); return; }
  ws.onopen = () => { opened = everOpened = true; stopMock(); resetUI(); setConn(true, '연결됨'); };
  ws.onmessage = (ev) => { try { handle(JSON.parse(ev.data)); } catch (e) { console.warn(e); } };
  ws.onclose = () => { if (!mock) setConn(false, '연결 끊김'); fail(); };
  ws.onerror = () => {};
  function fail() {
    if (!opened && !everOpened && !mock) { setConn(false, '연결 끊김'); startMock(); }
    clearTimeout(retryT); retryT = setTimeout(connect, 2000);
  }
}
function sendWS(obj) {
  if (mock) return mock.recv(obj);
  if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj));
}

/* ---------- inputs ---------- */
$('#chatForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const i = $('#chatInput'); const text = i.value.trim();
  if (!text) return;
  sendWS({ type: 'chat', text }); i.value = '';
});
$('#btnResume').onclick = () => sendWS({ type: 'command', name: 'resume' });
$('#btnRestart').onclick = () => sendWS({ type: 'command', name: 'restart' });
$('#btnCount').onclick = () => sendWS({ type: 'command', name: 'count' });
$('#btnEstop').onclick = () => sendWS({ type: 'command', name: 'estop' });
function buildTestButtons() {   // info.tests → "스킬 테스트" 버튼. 활성/비활성은 renderState가 정한다
  const box = $('#testBtns');
  box.innerHTML = '';
  S.tests.forEach((t) => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'btn btn-test'; b.dataset.skill = t.skill; b.disabled = true;
    b.textContent = t.label || t.skill;
    b.onclick = () => sendWS({ type: 'command', name: 'test', skill: t.skill });
    box.appendChild(b);
  });
}

/* ---------- tiles: 2×2 (카메라 · 3D · iframe). 설계: docs/superpowers/specs/2026-10-22-digital-twin-design.md 9장 ---------- */
const DEFAULT_TILES = [
  { kind: 'camera', name: 'tower cam', available: true }, { kind: 'camera', name: 'side cam', available: true },
  { kind: 'camera', name: 'follow cam', available: true }, { kind: 'twin', name: '3D' }];
const DEFAULT_URDF = 'twin/so101/so101_new_calib.urdf';
const tilesEl = $('#tiles');
let tiles = [], tilesKey = '', twin = null, twinTile = null, lastQ = null;

function showOnly(t, shown, text) {
  [t.img, t.video, t.frame].forEach((e) => { if (e) e.hidden = e !== shown; });
  t.empty.hidden = !!shown;
  if (!shown && text) t.emptyText.textContent = text;
}

function loadStream(t) {
  clearTimeout(t.retryT);
  if (t.replay) return;
  if (S.mock) { t.img.removeAttribute('src'); showOnly(t, null, '카메라 자리표시 (목업)'); return; }
  if (t.spec.available === false) { showOnly(t, null, '카메라 없음'); return; }
  t.img.src = '/stream/' + encodeURIComponent(t.spec.name) + '?t=' + Date.now();
}

function makeTile(spec) {
  const el = document.createElement('div');
  el.className = 'tile';
  el.dataset.kind = spec.kind;
  el.innerHTML = '<div class="cam-empty"><div class="stripes"></div><span></span></div><div class="tile-label"><i></i><b></b></div>';
  el.querySelector('.tile-label b').textContent = spec.name || '';
  const t = { spec, el, empty: el.querySelector('.cam-empty'), emptyText: el.querySelector('.cam-empty span'), replay: null, retryT: 0 };
  if (spec.kind === 'camera') {
    t.img = document.createElement('img');
    t.video = document.createElement('video');
    t.frame = document.createElement('img');
    t.img.alt = ''; t.frame.alt = '';
    t.video.muted = true; t.video.playsInline = true; t.video.preload = 'auto';
    el.prepend(t.img, t.video, t.frame);
    showOnly(t, null, '연결 중…');
    t.img.onload = () => { if (!t.replay) showOnly(t, t.img); };
    t.img.onerror = () => {
      if (t.replay || !t.img.getAttribute('src')) return;
      showOnly(t, null, '카메라 없음');
      t.retryT = setTimeout(() => loadStream(t), 3000);
    };
    loadStream(t);
  } else if (spec.kind === 'twin') {
    t.host = document.createElement('div');
    t.host.className = 'twin-host';
    el.prepend(t.host);
    showOnly(t, null, '3D 불러오는 중…');
    twinTile = t;
    loadTwin(t);
  } else if (spec.kind === 'iframe') {
    const f = document.createElement('iframe');
    f.src = spec.url; f.title = spec.name || ''; f.loading = 'lazy'; f.referrerPolicy = 'no-referrer';
    el.prepend(f);
    t.empty.hidden = true;
  }
  return t;
}

function buildTiles(specs) {
  const list = Array.isArray(specs) && specs.length ? specs : DEFAULT_TILES;
  const key = JSON.stringify(list);
  if (key === tilesKey) return;   // 재접속 때 같은 info면 3D를 다시 불러오지 않는다
  tilesKey = key;
  clearReplay();
  tiles.forEach((t) => { clearTimeout(t.retryT); if (t.img) t.img.removeAttribute('src'); });
  if (twin) { twin.dispose(); twin = null; }
  twinTile = null;
  tilesEl.innerHTML = '';
  tiles = list.map(makeTile);
  tiles.forEach((t) => tilesEl.appendChild(t.el));
  tilesEl.dataset.n = String(tiles.length);
}

function loadTwin(t) {
  const urdf = (S.twin && S.twin.urdf) || DEFAULT_URDF;
  import('./twin.js')
    .then((mod) => mod.createTwin(t.host, urdf))
    .then((api) => {
      if (twinTile !== t) { api.dispose(); return; }
      twin = api;
      t.empty.hidden = true;
      if (lastQ) twin.setJoints(lastQ);
    })
    .catch((e) => { console.warn('3D 로드 실패', e); if (twinTile === t) showOnly(t, null, '3D 없음'); });
}

function setJoints(q) { lastQ = q; if (twin) twin.setJoints(q); }

let swayRaf = 0;
function startSway() {   // 목업: 홈 자세 근처에서 천천히 흔든다
  cancelAnimationFrame(swayRaf);
  const t0 = performance.now();
  const step = () => {
    const t = (performance.now() - t0) / 1000;
    setJoints([0.35 * Math.sin(t * 0.8), -0.3 + 0.15 * Math.sin(t * 1.1), 0.4 + 0.15 * Math.sin(t * 0.9),
      0.3 * Math.sin(t * 1.3), 0.5 * Math.sin(t * 0.6), 0.4 + 0.3 * Math.sin(t * 2)]);
    swayRaf = requestAnimationFrame(step);
  };
  swayRaf = requestAnimationFrame(step);
}
function stopSway() { cancelAnimationFrame(swayRaf); swayRaf = 0; }

/* ---------- dry-run 재생: phase acting 이 되는 순간 그 스킬의 녹화(영상·프레임 + 관절 궤적)를 함께 튼다 ---------- */
const replayData = {};
let replay = null;

function loadReplay(skill) {
  if (replayData[skill]) return Promise.resolve(replayData[skill]);
  return fetch('/api/replay/' + encodeURIComponent(skill))
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => { if (d) replayData[skill] = d; return d; })
    .catch(() => null);
}

function onReplayState(prev) {
  if (S.state === 'ESTOP') { pauseReplay(); return; }
  if (S.phase === 'acting' && S.skill && (prev.phase !== 'acting' || prev.skill !== S.skill)) {
    if (S.twin.mode === 'replay' && S.replays.includes(S.skill)) startReplay(S.skill);
    return;
  }
  if (S.phase === 'counting' || S.state === 'IDLE' || S.state === 'DONE') clearReplay();
}

function startReplay(skill) {
  if (replayData[skill]) { beginReplay(skill, replayData[skill]); return; }
  loadReplay(skill).then((d) => {
    if (d && S.phase === 'acting' && S.skill === skill && !replay) beginReplay(skill, d);
  });
}

function beginReplay(skill, data) {
  clearReplay();
  const r = { skill, data, t0: performance.now(), created: performance.now(), clock: null, raf: 0, paused: false, tiles: [] };
  replay = r;
  tiles.forEach((t) => {
    if (t.spec.kind !== 'camera') return;
    const cam = data.cameras && data.cameras[t.spec.name];
    if (!cam) return;
    clearTimeout(t.retryT);
    t.replay = r; t.cam = cam; t.ended = false; t.frameIdx = -1;
    t.img.removeAttribute('src');
    r.tiles.push(t);
    if (cam.url) {
      const v = t.video;
      const start = cam.start || 0;
      v.onerror = () => replayFallback(r, t);
      v.onloadedmetadata = () => { v.currentTime = start; };
      v.onseeked = () => { if (replay === r && !r.paused && v.paused && !t.ended) v.play().catch(() => replayFallback(r, t)); };
      v.onplaying = () => {
        if (r.clock && r.clock.video === v && !r.clock.started) {
          r.clock.started = true;
          r.t0 = performance.now() - (v.currentTime - start) * 1000;
        }
      };
      v.src = cam.url;
      showOnly(t, v);
      if (!r.clock) r.clock = { video: v, start, tile: t, started: false };   // 첫 영상이 시계
    } else if (cam.frames && cam.frames.length) {
      showOnly(t, t.frame);
    }
  });
  r.raf = requestAnimationFrame(() => replayTick(r));
}

function replayTick(r) {
  if (replay !== r || r.paused) return;
  const now = performance.now();
  const c = r.clock;
  if (c && !c.started) {
    if (now - r.created > 3000) replayFallback(r, c.tile);   // 영상이 3초 안에 안 나오면 그 칸만 샘플로, 시계는 벽시계
    r.t0 = now;                                              // 영상이 나올 때까지 0초에 머문다
  }
  const v = r.clock && r.clock.started && !r.clock.video.paused ? r.clock.video : null;
  const t = v ? Math.max(0, v.currentTime - r.clock.start) : (now - r.t0) / 1000;
  const q = r.data.q || [];
  if (q.length) setJoints(q[Math.min(q.length - 1, Math.floor(t * r.data.fps))]);
  r.tiles.forEach((tile) => {
    const cam = tile.cam;
    if (!cam || tile.replay !== r) return;
    if (cam.url) {
      if (!tile.ended && cam.end > 0 && tile.video.currentTime >= cam.end) { tile.video.pause(); tile.ended = true; }
    } else if (cam.frames) {
      const i = Math.min(cam.frames.length - 1, Math.floor(t * cam.fps));
      if (i !== tile.frameIdx) { tile.frameIdx = i; tile.frame.src = cam.frames[i]; }
    }
  });
  const videosDone = r.tiles.every((x) => x.replay !== r || !x.cam || !x.cam.url || x.ended);
  if (t >= (r.data.duration || 0) && videosDone) return;   // 끝: 마지막 장면에서 멈춰 둔다
  r.raf = requestAnimationFrame(() => replayTick(r));
}

function releaseVideo(t) {
  const v = t.video;
  v.onerror = v.onloadedmetadata = v.onseeked = v.onplaying = null;
  v.pause(); v.removeAttribute('src'); v.load();
}

function replayFallback(r, t) {   // 그 칸만 샘플(스트림)로 돌린다 (코덱 등 재생 실패)
  if (t.replay !== r) return;
  t.replay = null; t.cam = null;
  releaseVideo(t);
  if (r.clock && r.clock.video === t.video) r.clock = null;
  loadStream(t);
}

function pauseReplay() {   // 비상정지: 영상·3D를 그 자리에서 멈춘다
  const r = replay;
  if (!r || r.paused) return;
  r.paused = true;
  cancelAnimationFrame(r.raf);
  r.tiles.forEach((t) => { if (t.replay === r) t.video.pause(); });
}

function clearReplay() {
  const r = replay;
  if (!r) return;
  replay = null;
  cancelAnimationFrame(r.raf);
  r.tiles.forEach((t) => {
    if (t.replay !== r) return;
    t.replay = null; t.cam = null;
    releaseVideo(t);
    t.frame.removeAttribute('src');
    loadStream(t);
  });
  if (S.twin.mode !== 'live' && r.data.q && r.data.q.length) setJoints(r.data.q[0]);
}

/* ---------- voice ---------- */
const micBtn = $('#micBtn'), vs = $('#voiceStatus');
let rec = null, recStart = 0, wantRec = false, busy = false;
function vstat(txt, cls) { vs.hidden = !txt; vs.textContent = txt || ''; vs.className = 'voice-status ' + (cls || ''); }
async function micDown(e) {
  e.preventDefault();
  if (busy || wantRec) return;
  wantRec = true; micBtn.classList.add('rec'); micBtn.setPointerCapture?.(e.pointerId);
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true } });
    if (!wantRec) { stream.getTracks().forEach((t) => t.stop()); return; }
    const chunks = []; const mr = new MediaRecorder(stream);
    mr.ondataavailable = (ev) => ev.data.size && chunks.push(ev.data);
    mr.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      const dur = performance.now() - recStart;
      if (dur < 350) { vstat('너무 짧아요. 누른 채로 말해 주세요', ''); setTimeout(() => vstat(''), 1500); return; }
      await upload(new Blob(chunks, { type: mr.mimeType }));
    };
    rec = mr; recStart = performance.now(); mr.start(); vstat('녹음 중… 손을 떼면 보내요', 'rec');
  } catch (err) {
    wantRec = false; micBtn.classList.remove('rec');
    vstat('마이크를 쓸 수 없어요', ''); setTimeout(() => vstat(''), 2500);
  }
}
function micUp() {
  if (!wantRec) return;
  wantRec = false; micBtn.classList.remove('rec');
  if (rec && rec.state === 'recording') rec.stop(); else vstat('');
  rec = null;
}
micBtn.addEventListener('pointerdown', micDown);
['pointerup', 'pointercancel', 'lostpointercapture'].forEach((ev) => micBtn.addEventListener(ev, micUp));
async function upload(blob) {
  busy = true; vstat('인식 중…', '');
  try {
    const wav = await toWav16k(blob);
    if (mock) { await new Promise((r) => setTimeout(r, 900)); mock.voice(); }
    else {
      const r = await fetch('/stt', { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wav });
      if (!r.ok) throw new Error(r.status);
      await r.json();
    }
    vstat('');
  } catch (e) { vstat('음성 인식에 실패했어요', ''); setTimeout(() => vstat(''), 2500); }
  busy = false;
}
async function toWav16k(blob) {
  const ac = new (window.AudioContext || window.webkitAudioContext)();
  const buf = await ac.decodeAudioData(await blob.arrayBuffer()); ac.close();
  const len = Math.max(1, Math.ceil(buf.duration * 16000));
  const off = new OfflineAudioContext(1, len, 16000);
  const src = off.createBufferSource(); src.buffer = buf; src.connect(off.destination); src.start();
  const pcm = (await off.startRendering()).getChannelData(0);
  const out = new DataView(new ArrayBuffer(44 + pcm.length * 2));
  const w = (o, s) => [...s].forEach((c, i) => out.setUint8(o + i, c.charCodeAt(0)));
  w(0, 'RIFF'); out.setUint32(4, 36 + pcm.length * 2, true); w(8, 'WAVEfmt ');
  out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true);
  out.setUint32(24, 16000, true); out.setUint32(28, 32000, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true);
  w(36, 'data'); out.setUint32(40, pcm.length * 2, true);
  for (let i = 0; i < pcm.length; i++) { const v = Math.max(-1, Math.min(1, pcm[i])); out.setInt16(44 + i * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true); }
  return new Blob([out], { type: 'audio/wav' });
}

/* ---------- mock simulator ---------- */
function createMock(emit) {
  const TOTAL = 8, TH = { safe_max: 3, force_refuse: 6 };
  const st = { state: 'IDLE', phase: 'idle', count: 0, remaining: TOTAL, skill: null };
  let tok = 0, n = 0, resumeFn = null, timers = new Set(), dead = false;
  let vchoice = 'fake', lastCount = null;
  const now = () => Date.now() / 1000;
  const sleep = (ms) => new Promise((r) => { const t = setTimeout(() => { timers.delete(t); r(); }, ms); timers.add(t); });
  const pushState = (o = {}) => { Object.assign(st, o); emit({ type: 'state', ...st, vision_method: 'fake', vision_choice: vchoice, vision_options: ['fake', 'off'], last_count: lastCount, thresholds: TH }); };
  const say = (role, text, source) => emit({ type: 'message', role, text, ...(role === 'user' ? { source: source || 'text' } : {}), ts: now() });
  const rnd = (a, b) => Math.round(a + Math.random() * (b - a));
  const tired = (c) => c <= TH.safe_max ? ['', '', ''] : null;
  const chatter = [
    '으… 팔이 조금 뻐근한데요.', '벌써 몇 개째예요? 세고 있다고요.', '저도 쉬고 싶어요… 과자만 보면 어지러워요.',
    '아직 남았어요? 진짜로요?', '헉헉, 관절에서 소리 나는 거 들려요?'];
  const waitResume = (t, ms) => new Promise((res) => { resumeFn = res; const x = setTimeout(res, ms); timers.add(x); });

  async function work(t) {
    pushState({ state: 'WORKING', phase: 'counting' });
    let refusedOnce = st.count >= 5;
    while (t === tok && st.remaining > 0) {
      const ms = { vision: rnd(600, 950), llm: rnd(800, 1300), act: rnd(12000, 15500), return: rnd(2800, 3400) };
      pushState({ phase: 'counting', skill: null }); await sleep(900); if (t !== tok) return;
      pushState({ phase: 'thinking' }); await sleep(1000); if (t !== tok) return;
      if (st.count >= 4 && !refusedOnce) {
        refusedOnce = true;
        say('robot', '힘들어요! 이제 안 할래요. 도리도리~');
        pushState({ state: 'REFUSING', phase: 'idle', skill: 'dori_dori' });
        emit({ type: 'cycle', n: ++n, result: 'refuse', ms: { vision: ms.vision, llm: ms.llm } });
        await waitResume(t, 9000); resumeFn = null; if (t !== tok) return;
        if (st.state === 'REFUSING') { say('user', '조금만 더 해줘, 간식 줄게', 'voice'); await sleep(700); say('robot', '…간식이라고요? 으으, 딱 조금만이에요.'); }
        pushState({ state: 'WORKING', phase: 'counting', skill: null }); continue;
      }
      if (st.count > TH.safe_max && Math.random() < .7) say('robot', chatter[rnd(0, chatter.length - 1)]);
      pushState({ phase: 'speaking', skill: 'oranda_pickup' }); await sleep(900); if (t !== tok) return;
      pushState({ phase: 'acting', skill: 'oranda_pickup' }); await sleep(2600); if (t !== tok) return;
      pushState({ phase: 'returning', skill: null }); await sleep(1100); if (t !== tok) return;
      const ok = Math.random() > .1;
      if (ok) { st.count++; st.remaining--; }
      const last = st.remaining <= 0;
      emit({ type: 'cycle', n: ++n, result: ok ? 'success' : 'fail', ms });
      pushState({});
      if (!ok) { say('robot', '앗, 놓쳤어요! 다시 해볼게요.'); }
    }
    if (t === tok && st.remaining <= 0) {
      emit({ type: 'cycle', n: ++n, result: 'done', ms: { vision: rnd(600, 900) } });
      say('robot', '다 옮겼어요! 이제 진짜 쉴래요. 칭찬해 주세요.');
      pushState({ state: 'DONE', phase: 'idle', skill: 'done' });
    }
  }
  function begin() { const t = ++tok; work(t); }
  async function runTest(skill, fromChat) {   // 스킬 1회 실행 흉내: TESTING (acting → returning) → IDLE
    const t = ++tok, t0 = Date.now();
    if (skill === 'home') {
      pushState({ state: 'TESTING', phase: 'returning', skill }); await sleep(1200); if (t !== tok) return;
    } else {
      pushState({ state: 'TESTING', phase: 'acting', skill }); await sleep(skill === 'dori_dori' || skill === 'dori_script' ? 1800 : 2600); if (t !== tok) return;
      if (skill === 'oranda_pickup') { pushState({ phase: 'returning' }); await sleep(1100); if (t !== tok) return; }
    }
    const how = { oranda_pickup: '놓기 감지로 끝남 · 쥠 성공', dori_dori: '코드 동작 완료', dori_script: '코드 동작 완료', home: '완료' }[skill];
    const label = { oranda_pickup: '오란다', dori_dori: '도리도리', dori_script: '코드 도리도리', home: '홈으로' }[skill];
    const sec = ((Date.now() - t0) / 1000).toFixed(1);
    say('system', fromChat ? `도리도리 · ${how} · ${sec}초` : `테스트 · ${label}: ${how} · ${sec}초`);
    pushState({ state: 'IDLE', phase: 'idle', skill: null });
  }

  const api = {
    start() {
      emit({ type: 'info', target: { name: '오란다' }, models: { vision: 'YOLO-World · OpenVINO · GPU', llm: 'API · openrouter', stt: 'Whisper · OpenVINO · CPU', act: 'ACT · OpenVINO · GPU' },
        ui: { tiles: DEFAULT_TILES }, twin: { mode: 'mock', urdf: DEFAULT_URDF }, replays: [], tests: TEST_DEFAULT });
      pushState({});
      say('system', '시뮬레이터가 연결되었어요');
      sleep(1800).then(() => { if (dead) return; say('user', '과자 옮겨줘'); return sleep(700); })
        .then(() => { if (dead || st.state !== 'IDLE') return; say('robot', '네네~ 오란다부터 옮길게요!'); begin(); });
    },
    stop() { dead = true; tok++; timers.forEach(clearTimeout); timers.clear(); resumeFn && resumeFn(); },
    voice() { api.recv({ type: 'chat', text: '조금만 더 해줘', _voice: true }); },
    recv(m) {
      if (m.type === 'chat') {
        const text = m.text; say('user', text, m._voice ? 'voice' : 'text');
        sleep(700).then(() => {
          if (dead) return;
          if (st.state === 'REFUSING' && /조금|더|힘내|고마|부탁|간식|해줘|달래/.test(text)) { say('robot', '으으… 알겠어요, 조금만 더요.'); resumeFn && resumeFn(); }
          else if (st.state === 'IDLE' && /도리도리|고개/.test(text)) { say('robot', '도리도리~ 이렇게요?'); runTest('dori_dori', true); }
          else if (st.state === 'IDLE' && /옮|시작|해줘|치워/.test(text)) { say('robot', '네네~ 시작할게요!'); begin(); }
          else if (st.state === 'TESTING') say('robot', '지금 테스트 중이에요. 끝나면 시켜 주세요!');
          else if (st.state === 'ESTOP') say('robot', '…(멈춰 있어요)');
          else if (st.state === 'WORKING') say('robot', '지금 일하는 중이에요. 말 걸지 마세요, 팔 떨려요.');
          else say('robot', /안녕/.test(text) ? '안녕하세요… 저는 오늘도 출근했어요.' : '그건 제 월급 밖의 일이에요.');
        });
      } else if (m.type === 'command') {
        if (m.name === 'estop' && !['IDLE', 'DONE', 'ESTOP'].includes(st.state)) {
          tok++; timers.forEach(clearTimeout); timers.clear(); resumeFn = null;
          say('system', '비상정지됨'); pushState({ state: 'ESTOP', phase: 'idle', skill: null });
        } else if (m.name === 'restart' && st.state === 'ESTOP') {
          tok++; n = 0; say('system', '재시작했어요'); pushState({ state: 'IDLE', phase: 'idle', count: 0, remaining: TOTAL, skill: null });
          say('robot', '다시 출근했어요. 뭐 시키실 거예요?');
        } else if (m.name === 'resume' && resumeFn) { say('system', '진행자가 재개했어요'); resumeFn(); }
        else if (m.name === 'vision_method' && ['fake', 'off'].includes(m.method)) { vchoice = m.method; pushState({}); }
        else if (m.name === 'count') {
          if (st.state !== 'IDLE') say('system', '대기 상태에서만 지금 세기를 할 수 있어요');
          else if (vchoice === 'off') say('system', '개수 세기가 꺼져 있어요');
          else { lastCount = { n: st.remaining ?? TOTAL, method: 'fake', ms: rnd(80, 160) }; pushState({ remaining: lastCount.n }); }
        }
        else if (m.name === 'test') {
          if (st.state === 'IDLE' && TEST_DEFAULT.some((x) => x.skill === m.skill)) runTest(m.skill, false);
          else say('system', st.state === 'TESTING' ? '이미 테스트 중이에요' : '대기 상태에서만 테스트할 수 있어요');
        }
      }
    },
  };
  return api;
}

/* ---------- start (모든 선언 뒤) ---------- */
buildTestButtons();
if (MOCK_FORCED) startMock(); else connect();
})();
