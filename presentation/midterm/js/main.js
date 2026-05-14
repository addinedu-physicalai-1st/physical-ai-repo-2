/* ============================================
   pingdergarten 중간발표 JS
   - Slide loader / keybindings / slide panel
   - Drawing canvas
   - BT / FSM / Tree 동적 하이라이팅 엔진
   ============================================ */

var SLIDES = [
  '01-title.html',
  '02-project-intro.html',
  '03-robots.html',
  '04-architecture.html',
  '05-repo-structure.html',
  '06-bt-gogoping.html',
  '07-fsm-gogoping.html',
  '08-implemented.html',
  '09-demo-voice.html',
  '10-demo-oxquiz.html',
  '11-sprint-timeline.html',
  '12-jira-status.html',
  '13-remaining.html',
  '14-thanks.html',
];

var SLIDE_TITLES = [
  '중간발표',
  'pingdergarten 이란?',
  '로봇 라인업',
  '시스템 아키텍처',
  '레포 구조',
  'BT — 숨바꼭질',
  'FSM — 보조 모드',
  '구현 완료 항목',
  '데모: 음성 파이프라인',
  '데모: OX 퀴즈',
  '스프린트 타임라인',
  'Jira 현황',
  '남은 과제',
  '감사합니다',
];

/* ── Slide Loader ── */
async function loadSlides() {
  var container = document.querySelector('.reveal .slides');
  var responses = await Promise.all(
    SLIDES.map(function (name) { return fetch('slides/' + name + '?t=' + Date.now()); })
  );
  var htmls = await Promise.all(responses.map(function (r) { return r.text(); }));
  htmls.forEach(function (html) {
    container.insertAdjacentHTML('beforeend', html);
  });
}

/* ── Presentation Init ── */
async function initPresentation() {
  await loadSlides();

  Reveal.initialize({
    hash: true,
    center: false,
    slideNumber: 'c/t',
    width: 1280,
    height: 720,
    margin: 0.04,
    minScale: 0.1,
    maxScale: 2.0,
    transition: 'fade',
    transitionSpeed: 'fast',
    plugins: [RevealNotes, RevealHighlight],
    keyboard: {
      70: function () { toggleFullscreen(); },
      67: function () { toggleDraw(); },
      88: function () { clearDraw(); },
    },
  });

  function forceCenterAlign() {
    var slideHeight = 720;
    document.querySelectorAll('.reveal .slides section').forEach(function (s) {
      s.style.top = '';
      var sectionHeight = s.scrollHeight;
      var topOffset = (slideHeight - sectionHeight) / 2;
      if (topOffset > 0) s.style.top = topOffset + 'px';
    });
  }

  Reveal.on('ready', function () {
    var ls = document.getElementById('loading-screen');
    if (ls) { ls.style.transition = 'opacity 0.4s'; ls.style.opacity = '0'; setTimeout(function () { ls.remove(); }, 400); }
    initDraw();
    initImageZoom();
    initDynamicSlides();
    forceCenterAlign();

    var slideNum = document.querySelector('.reveal .slide-number');
    if (slideNum) {
      slideNum.addEventListener('click', function (e) { e.stopPropagation(); toggleSlidePanel(); });
    }
  });

  Reveal.on('slidechanged', function (event) {
    clearDraw();
    forceCenterAlign();
    var panel = document.getElementById('slide-panel');
    if (panel && !panel.classList.contains('hidden')) updateSlidePanelActive();
  });

  // BT/FSM fragment events
  Reveal.on('fragmentshown', function (e) { handleFragment(e, true); });
  Reveal.on('fragmenthidden', function (e) { handleFragment(e, false); });
}

/* ===== BT / FSM / Tree 동적 하이라이팅 엔진 ===== */

// Registry: slideIndex -> { steps: [...], infoId, cleanup }
var dynamicScenarios = {};

function registerScenario(slideSelector, config) {
  dynamicScenarios[slideSelector] = config;
}

function handleFragment(e, shown) {
  var slideEl = Reveal.getCurrentSlide();
  if (!slideEl) return;
  var slideId = slideEl.getAttribute('data-scenario');
  if (!slideId || !dynamicScenarios[slideId]) return;

  var sc = dynamicScenarios[slideId];
  var fragIdx = parseInt(e.fragment.dataset.fragmentIndex);
  var stepIdx = shown ? fragIdx : Math.max(0, fragIdx - 1);

  applyScenarioStep(slideEl, sc, stepIdx);
}

function applyScenarioStep(slideEl, sc, stepIdx) {
  // Clear all tree nodes/edges in this slide
  slideEl.querySelectorAll('.tree-node').forEach(function (n) { n.className.baseVal = 'tree-node'; });
  slideEl.querySelectorAll('.tree-edge').forEach(function (e) { e.className.baseVal = 'tree-edge'; });

  var step = sc.steps[stepIdx];
  if (!step) return;

  if (step.nodes) {
    Object.keys(step.nodes).forEach(function (id) {
      var el = document.getElementById(id);
      if (el && step.nodes[id]) el.className.baseVal = 'tree-node ' + step.nodes[id];
    });
  }
  if (step.edges) {
    Object.keys(step.edges).forEach(function (id) {
      var el = document.getElementById(id);
      if (el && step.edges[id]) el.className.baseVal = 'tree-edge ' + step.edges[id];
    });
  }

  var infoEl = slideEl.querySelector('.step-info');
  if (infoEl && step.info) infoEl.innerHTML = step.info;

  if (step.onEnter) step.onEnter();
}

function initDynamicSlides() {
  /* ── Repo Structure (slide 05) ── */
  registerScenario('repo-tree', {
    steps: [
      { nodes: { 'rt-root': 'active pulse' }, edges: {},
        info: '<span class="hl pk">physical-ai-repo-2/</span> \u2014 \ubaa8\ub178\ub808\ud3ec. device \xb7 server \xb7 ui 3\uac1c \ub808\uc774\uc5b4\ub85c \ubd84\ub9ac.' },
      { nodes: { 'rt-root': 'success', 'rt-device': 'active pulse' },
        edges: { 'rt-e1': 'active flow' },
        info: '<span class="hl pk">device/</span> \u2014 ROS2 \uc6cc\ud06c\uc2a4\ud398\uc774\uc2a4. \uace0\uace0\ud551(Nav2, BT, FSM), \ub178\ub9ac\uc554(OMX \uac8c\uc784 \ud504\ub808\uc784\uc6cc\ud06c) \ud328\ud0a4\uc9c0.' },
      { nodes: { 'rt-root': 'success', 'rt-device': 'success', 'rt-gogo': 'success', 'rt-nori': 'success', 'rt-nav': 'success', 'rt-modes': 'running', 'rt-bt': 'running', 'rt-fsm': 'running', 'rt-server': 'active pulse' },
        edges: { 'rt-e1': 'success', 'rt-e2': 'active flow', 'rt-e4': 'success', 'rt-e5': 'success', 'rt-e6': 'success', 'rt-e7': 'running', 'rt-e8': 'running', 'rt-e9': 'running' },
        info: '<span class="hl pk">server/</span> \u2014 AI Hub (Ollama LLM) + Control Service (FastAPI + rclpy). <span class="hl bt">modes/</span> \ub294 \uc2a4\uce90\ud3f4\ub4dc \ub2e8\uacc4.' },
      { nodes: { 'rt-root': 'success', 'rt-device': 'success', 'rt-server': 'success', 'rt-ai': 'success', 'rt-ctrl': 'success', 'rt-llm': 'success', 'rt-vision': 'success', 'rt-routers': 'success', 'rt-stream': 'success', 'rt-ui': 'active pulse' },
        edges: { 'rt-e1': 'success', 'rt-e2': 'success', 'rt-e3': 'active flow', 'rt-e10': 'success', 'rt-e11': 'success', 'rt-e12': 'success', 'rt-e13': 'success', 'rt-e14': 'success', 'rt-e15': 'success' },
        info: '<span class="hl pk">ui/</span> \u2014 Robot UI (\uac10\uc815 \ud45c\ud604, \uc74c\uc131), Portal UI (\uad50\uc0ac/\ubcf4\ud638\uc790), Admin UI (\ud154\ub808\uc635).' },
      { nodes: { 'rt-root': 'success', 'rt-device': 'success', 'rt-gogo': 'success', 'rt-nori': 'success', 'rt-nav': 'success', 'rt-modes': 'running', 'rt-bt': 'running', 'rt-fsm': 'running', 'rt-server': 'success', 'rt-ai': 'success', 'rt-ctrl': 'success', 'rt-ui': 'success', 'rt-robotui': 'success', 'rt-portal': 'success', 'rt-admin': 'success' },
        edges: { 'rt-e1': 'success', 'rt-e2': 'success', 'rt-e3': 'success', 'rt-e4': 'success', 'rt-e5': 'success', 'rt-e6': 'success', 'rt-e7': 'running', 'rt-e8': 'running', 'rt-e9': 'running', 'rt-e10': 'success', 'rt-e11': 'success', 'rt-e16': 'success', 'rt-e17': 'success', 'rt-e18': 'success', 'rt-e19': 'success' },
        info: '\uc804\uccb4 \ud604\ud669: <span class="hl mt">\uc11c\ubc84 \xb7 UI \uc644\uc131</span>, <span class="hl bt">BT/FSM \uc2a4\uce90\ud3f4\ub4dc</span> \u2192 \uc774\ubc88 \uc2a4\ud504\ub9b0\ud2b8\uc5d0\uc11c \uad6c\ud604 \uc9c4\ud589 \uc911.' },
    ]
  });

  /* ── BT Hide-and-seek (slide 06) ── */
  registerScenario('bt-hide', {
    steps: [
      { nodes: {}, edges: {},
        info: '\u2192 \ud0a4\ub97c \ub20c\ub7ec BT \uc2e4\ud589 \ud750\ub984\uc744 \ub530\ub77c\uac00\uc138\uc694.' },
      { nodes: { 'bt-root': 'active pulse' }, edges: { 'bt-e1': 'active flow' },
        info: '<span class="hl pk">\u2460 Root Sequence \u2192</span> \uc2dc\uc791 \u2014 \uc790\uc2dd\uc744 \uc67c\ucabd\ubd80\ud130 \uc21c\ucc28 \uc2e4\ud589' },
      { nodes: { 'bt-root': 'active', 'bt-move': 'active pulse' },
        edges: { 'bt-e1': 'active', 'bt-e2': 'active flow' },
        info: '<span class="hl pk">\u2461 \uc704\uce58 \uc774\ub3d9</span> \u2014 Nav2\ub85c play_area \uc774\ub3d9 \uc911...' },
      { nodes: { 'bt-root': 'active', 'bt-move': 'success', 'bt-reg': 'active pulse' },
        edges: { 'bt-e1': 'active', 'bt-e2': 'success', 'bt-e3': 'active flow' },
        info: '<span class="hl mt">\uc704\uce58 \uc774\ub3d9 SUCCESS</span> \u2192 <span class="hl pk">\u2462 \ucc38\uac00\uc790 \ud655\uc815</span> \u2014 \uc5bc\uad74 \uc778\uc2dd\uc73c\ub85c \ucd5c\ub300 5\uba85 \ub4f1\ub85d' },
      { nodes: { 'bt-root': 'active', 'bt-move': 'success', 'bt-reg': 'success', 'bt-count': 'active pulse' },
        edges: { 'bt-e1': 'active', 'bt-e2': 'success', 'bt-e3': 'success', 'bt-e4': 'active flow' },
        info: '<span class="hl mt">\ucc38\uac00\uc790 \ud655\uc815 SUCCESS</span> \u2192 <span class="hl pk">\u2463 \uce74\uc6b4\ud2b8\ub2e4\uc6b4</span> \u2014 30\ucd08 \ub208 \uac00\ub9ac\uae30 + \uc74c\uc131' },
      { nodes: { 'bt-root': 'running', 'bt-move': 'success', 'bt-reg': 'success', 'bt-count': 'success', 'bt-patrol': 'running', 'bt-fb': 'active pulse' },
        edges: { 'bt-e1': 'running', 'bt-e2': 'success', 'bt-e3': 'success', 'bt-e4': 'success', 'bt-e5': 'running flow', 'bt-e6': 'active flow' },
        info: '<span class="hl mt">\uce74\uc6b4\ud2b8\ub2e4\uc6b4 SUCCESS</span> \u2192 <span class="hl bt">\u2464 \uc21c\ucc30 RUNNING</span> \u2014 Fallback \uc9c4\uc785' },
      { nodes: { 'bt-root': 'running', 'bt-move': 'success', 'bt-reg': 'success', 'bt-count': 'success', 'bt-patrol': 'running', 'bt-fb': 'active', 'bt-find': 'fail', 'bt-next': 'success' },
        edges: { 'bt-e1': 'running', 'bt-e2': 'success', 'bt-e3': 'success', 'bt-e4': 'success', 'bt-e5': 'running', 'bt-e6': 'active', 'bt-e7': 'fail', 'bt-e8': 'success flow' },
        info: '<span class="hl cr">\u2465 \uc544\uc774 \ubc1c\uacac FAILURE</span> \u2014 \uc774 \uc9c0\uc810\uc5d4 \uc5c6\uc74c \u2192 Fallback\uc774 <span class="hl mt">\ub2e4\uc74c \uc9c0\uc810</span>\uc73c\ub85c \uc774\ub3d9' },
      { nodes: { 'bt-root': 'running', 'bt-move': 'success', 'bt-reg': 'success', 'bt-count': 'success', 'bt-patrol': 'running', 'bt-fb': 'success', 'bt-find': 'success' },
        edges: { 'bt-e1': 'running', 'bt-e2': 'success', 'bt-e3': 'success', 'bt-e4': 'success', 'bt-e5': 'running', 'bt-e6': 'success', 'bt-e7': 'success flow' },
        info: '<span class="hl mt">\u2466 \uc544\uc774 \ubc1c\uacac SUCCESS!</span> \u2014 \uc774\ub984 \ud638\uba85 \u2192 \u201c\uc7a1\ud798\u201d \ucc98\ub9ac \u2192 \ub0a8\uc740 \uc544\uc774 \uc788\uc73c\uba74 \uc21c\ucc30 \uacc4\uc18d' },
    ]
  });

  /* ── FSM Assist mode (slide 07) ── */
  registerScenario('fsm-assist', {
    steps: [
      { nodes: {}, edges: {},
        info: '\u2192 \ud0a4\ub97c \ub20c\ub7ec FSM \uc804\ud658\uc744 \ub530\ub77c\uac00\uc138\uc694.' },
      { nodes: { 'fm-idle': 'active pulse' }, edges: {},
        info: '<span class="hl pk">\u2460 \ub300\uae30</span> \u2014 \ubcf4\uc870 \ubaa8\ub4dc \uc9c4\uc785. Admin UI\uc5d0\uc11c \u201c\ucd94\uc885 \uc2dc\uc791\u201d \ud074\ub9ad \ub300\uae30.' },
      { nodes: { 'fm-idle': 'success', 'fm-confirm': 'active pulse' },
        edges: { 'fm-e1': 'active flow' },
        info: '<span class="hl pk">\u2461 \ucd94\uc885 \ub300\uc0c1 \ud655\uc778</span> \u2014 \uc5bc\uad74 \uce90\ucc98 \u2192 \ub9e4\uce6d \u2192 \u201c\u25cb\u25cb\uc120\uc0dd\ub2d8 \ub9de\uc544\uc694?\u201d' },
      { nodes: { 'fm-confirm': 'success', 'fm-follow': 'active pulse' },
        edges: { 'fm-e1': 'success', 'fm-e2': 'active flow' },
        info: '<span class="hl mt">\u2462 \ucd94\uc885</span> \u2014 Deep SORT + LiDAR \uac70\ub9ac \uc81c\uc5b4\ub85c \uad50\uc0ac \ub530\ub77c\uac10.' },
      { nodes: { 'fm-confirm': 'success', 'fm-follow': 'running', 'fm-search': 'active pulse' },
        edges: { 'fm-e1': 'success', 'fm-e6': 'active flow' },
        info: '<span class="hl bt">\u2463 Searching</span> \u2014 \uc2dc\uc57c \ub85c\uc2a4\ud2b8! \ud68c\uc804\ud558\uba70 \u201c\uc120\uc0dd\ub2d8?\u201d \uc74c\uc131 \ud638\ucd9c.' },
      { nodes: { 'fm-confirm': 'success', 'fm-search': 'success', 'fm-follow': 'active pulse' },
        edges: { 'fm-e1': 'success', 'fm-e7': 'success flow' },
        info: '<span class="hl mt">\u2464 \uc7ac\ubc1c\uacac!</span> \u2192 \ucd94\uc885 \uc7ac\uac1c. (\ud0c0\uc784\uc544\uc6c3 \uc2dc \ub300\uae30 \ubcf5\uadc0)' },
    ]
  });

  /* ── Sprint Timeline (slide 11) ── */
  registerScenario('sprint-tl', {
    steps: [
      { nodes: {}, edges: {},
        info: '\u2192 \ud0a4\ub97c \ub20c\ub7ec \uc2a4\ud504\ub9b0\ud2b8 \uc9c4\ud589\uc744 \ud655\uc778\ud558\uc138\uc694.' },
      { nodes: {}, edges: {},
        info: '<span class="hl pk">Sprint 1-2</span> \u2014 \uc8fc\uc81c \uc120\uc815 + \uc0c1\uc138 \uc124\uacc4 100% \uc644\ub8cc. \uc544\ud0a4\ud14d\ucc98, \uc694\uad6c\uc0ac\ud56d, \ud3f4\ub354 \uad6c\uc870 \ud655\uc815.',
        onEnter: function() { _animateSprint('sp1-bar', 100, 'sp1-count', '1/1 Done'); _animateSprint('sp2-bar', 100, 'sp2-count', '9/9 Done'); } },
      { nodes: {}, edges: {},
        info: '<span class="hl pk">Sprint 3</span> \u2014 \uc2a4\uce90\ud3f4\ub4dc \uad6c\ud604 + \uae30\uc220 \uc870\uc0ac. BT \uc124\uacc4, OMX \ub180\uc774 \uc124\uacc4, \ud0a4\ubcf4\ub4dc \ud154\ub808\uc635 \uad6c\ud604.',
        onEnter: function() { _animateSprint('sp3-bar', 100, 'sp3-count', '9/9 Done'); } },
      { nodes: {}, edges: {},
        info: '<span class="hl bt">Sprint 4 (\ud604\uc7ac)</span> \u2014 \uad6c\ud604 week1. Done 5 + QA 2 = <strong>39%</strong>. \uace0\uace0\ud551 Nav \ud0dc\uc2a4\ud06c 10\uac1c backlog.',
        onEnter: function() { _animateSprint('sp4-bar', 39, 'sp4-count', '5 Done / 2 QA / 1 WIP / 10 Todo'); } },
    ]
  });
}

function _animateSprint(barId, pct, countId, countText) {
  var bar = document.getElementById(barId);
  var label = bar ? bar.querySelector('span') : null;
  if (bar) bar.style.width = pct + '%';
  if (label) label.style.opacity = '1';
  var countEl = document.getElementById(countId);
  if (countEl && countText) countEl.textContent = countText;
}

/* ── Drawing Canvas ── */
var _drawActive = false, _drawing = false, _lastX = 0, _lastY = 0;

function toggleDraw() {
  _drawActive = !_drawActive;
  var c = document.getElementById('draw-canvas');
  c.style.pointerEvents = _drawActive ? 'auto' : 'none';
  document.body.style.cursor = _drawActive ? 'crosshair' : '';
}
function clearDraw() {
  var c = document.getElementById('draw-canvas');
  c.getContext('2d').clearRect(0, 0, c.width, c.height);
}
function initDraw() {
  var c = document.getElementById('draw-canvas');
  c.width = window.innerWidth; c.height = window.innerHeight;
  window.addEventListener('resize', function () { c.width = window.innerWidth; c.height = window.innerHeight; });
  var ctx = c.getContext('2d');
  ctx.strokeStyle = '#F8B4C4'; ctx.lineWidth = 5; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  c.addEventListener('mousedown', function (e) { _drawing = true; _lastX = e.clientX; _lastY = e.clientY; });
  c.addEventListener('mousemove', function (e) {
    if (!_drawing) return;
    var ctx2 = c.getContext('2d');
    ctx2.strokeStyle = '#F8B4C4'; ctx2.lineWidth = 5; ctx2.lineCap = 'round'; ctx2.lineJoin = 'round';
    ctx2.beginPath(); ctx2.moveTo(_lastX, _lastY); ctx2.lineTo(e.clientX, e.clientY); ctx2.stroke();
    _lastX = e.clientX; _lastY = e.clientY;
  });
  c.addEventListener('mouseup', function () { _drawing = false; });
  c.addEventListener('mouseleave', function () { _drawing = false; });
}

/* ── Fullscreen ── */
function toggleFullscreen() {
  if (!document.fullscreenElement) document.documentElement.requestFullscreen();
  else document.exitFullscreen();
}
function updateFullscreenHint() {
  var h = document.getElementById('fullscreen-hint');
  if (!h) return;
  var k = document.fullscreenElement ? 'ESC' : 'F';
  var m = document.fullscreenElement ? 'to minimize' : 'for fullscreen';
  h.innerHTML = 'Press <kbd style="background:#FFFFFF;border:1px solid #FFE0E6;border-radius:4px;padding:1px 5px;font-size:0.9em;color:#5D4037">' + k + '</kbd> ' + m;
}
document.addEventListener('fullscreenchange', updateFullscreenHint);

/* ── Slide Panel ── */
function buildSlidePanel() {
  var list = document.getElementById('slide-panel-list');
  list.innerHTML = '';
  var sections = document.querySelectorAll('.reveal .slides > section');
  var current = Reveal.getIndices().h;
  sections.forEach(function (s, i) {
    var item = document.createElement('div');
    item.className = 'slide-thumb-item' + (i === current ? ' active' : '');
    item.innerHTML = '<div class="slide-thumb-meta"><span class="slide-thumb-num">' + (i + 1) + '</span><span class="slide-thumb-title">' + (SLIDE_TITLES[i] || '') + '</span></div>';
    item.addEventListener('click', function () { Reveal.slide(i); closeSlidePanel(); });
    list.appendChild(item);
  });
}
function updateSlidePanelActive() {
  var current = Reveal.getIndices().h;
  document.querySelectorAll('.slide-thumb-item').forEach(function (el, i) { el.classList.toggle('active', i === current); });
  var active = document.querySelector('.slide-thumb-item.active');
  if (active) active.scrollIntoView({ block: 'nearest' });
}
function toggleSlidePanel() {
  var panel = document.getElementById('slide-panel');
  if (!panel.classList.contains('hidden')) closeSlidePanel();
  else {
    buildSlidePanel();
    panel.classList.remove('hidden'); panel.classList.add('flex');
    document.getElementById('slide-panel-overlay').classList.remove('hidden');
    setTimeout(function () { var a = document.querySelector('.slide-thumb-item.active'); if (a) a.scrollIntoView({ block: 'center' }); }, 50);
  }
}
function closeSlidePanel() {
  var panel = document.getElementById('slide-panel');
  panel.classList.add('hidden'); panel.classList.remove('flex');
  document.getElementById('slide-panel-overlay').classList.add('hidden');
}
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') { closeSlidePanel(); closeImageZoom(); }
});

/* ── Image Zoom ── */
function openImageZoom(src, alt) {
  var o = document.getElementById('image-zoom-overlay');
  var i = document.getElementById('image-zoom-img');
  if (!o || !i) return;
  i.src = src; i.alt = alt || ''; o.style.display = 'flex';
}
function closeImageZoom() {
  var o = document.getElementById('image-zoom-overlay');
  if (o) o.style.display = 'none';
}
function initImageZoom() {
  document.querySelectorAll('.reveal img.zoomable').forEach(function (img) {
    if (img.dataset.zoomBound) return;
    img.dataset.zoomBound = '1';
    img.style.cursor = 'zoom-in';
    img.addEventListener('click', function (e) { e.stopPropagation(); e.preventDefault(); openImageZoom(img.src, img.alt); });
  });
}

initPresentation();
