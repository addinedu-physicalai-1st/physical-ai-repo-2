/* ============================================
   pingdergarten Presentation JS
   - Slide loader / keybindings / slide panel
   - Drawing canvas / webcam overlay
   ============================================ */

var SLIDES = [
  '01-title.html',
  '02-sprint-history.html',
  '03-progress-delta.html',
  '03b-section-demo.html',
  '04-eduping.html',
  '05-gogoping.html',
  '06-noriarm.html',
  '06b-noriarm-block.html',
  '06c-section-test.html',
  '07-test-results.html',
  '07a-sprint3-portal.html',
  '07b-sprint3-ui.html',
  '07c-sprint4-summary.html',
  '07d-sprint4-noriarm.html',
  '07e-sprint4-gogoping.html',
  '07f-sprint5.html',
  '08-issues.html',
  '08b-section-tech.html',
  '09a-tech-vla.html',
  '09b-tech-vla-roi.html',
  '09c-tech-depth.html',
  '09d-tech-detect.html',
  '10-sprint67-plan.html',
  '11-thank-you.html',
];

var SLIDE_TITLES = [
  '중간발표',
  '스프린트 히스토리',
  '1차 → 2차 진척도',
  '§ 추가 / 개선 + 데모',
  'EduPing — 추가 / 개선',
  'GogoPing — 추가 / 개선',
  'NoriArm — OX 퀴즈',
  'NoriArm — 블럭쌓기 (개선)',
  '§ 테스트 결과',
  'Sprint 3 — 요약 (81%)',
  'Sprint 3 — Portal · 등록',
  'Sprint 3 — Robot UI · Admin',
  'Sprint 4 — 요약 (45%)',
  'Sprint 4 — NoriArm',
  'Sprint 4 — GogoPing',
  'Sprint 5 — Carry-over + 신규',
  '주요 이슈',
  '§ 기술 조사',
  '기술 조사 — VLA 데모',
  '기술 조사 — VLA? (ROI 우회)',
  '기술 조사 — Depth 카메라',
  '기술 조사 — 상태 검출',
  '남은 스프린트',
  '감사합니다',
];

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

async function initPresentation() {
  await loadSlides();

  // 영상 element 가 자연 비율과 다르게 그려지는 케이스 (회전 메타데이터 등)
  // → 실제 videoWidth/Height 비율 기반으로 명시적 width 지정 (max-width 도 무시).
  window.fitVideoBox = function (v) {
    if (!v.videoWidth || !v.videoHeight) return;
    var h = parseFloat(getComputedStyle(v).height);
    if (!h || h < 10) return;
    var w = h * v.videoWidth / v.videoHeight;
    v.style.width = w + 'px';
    v.style.maxWidth = 'none';
  };
  document.querySelectorAll('video').forEach(function (v) {
    if (v.readyState >= 1) window.fitVideoBox(v);
    else v.addEventListener('loadedmetadata', function () { window.fitVideoBox(v); });
  });

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
      80: function () { toggleVideo(); },      // P
      70: function () { toggleFullscreen(); }, // F
      87: function () { toggleWebcam(); },     // W
      67: function () { toggleDraw(); },       // C
      88: function () { clearDraw(); },        // X
    },
  });

  function forceCenterAlign() {
    var slideHeight = 720;
    document.querySelectorAll('.reveal .slides section').forEach(function (s) {
      if (s.getAttribute('data-center') === 'false') return;
      s.style.top = '';
      var sectionHeight = s.scrollHeight;
      var topOffset = (slideHeight - sectionHeight) / 2;
      if (topOffset > 0) s.style.top = topOffset + 'px';
    });
  }

  Reveal.on('ready', function () {
    var loadingScreen = document.getElementById('loading-screen');
    if (loadingScreen) {
      loadingScreen.style.transition = 'opacity 0.4s';
      loadingScreen.style.opacity = '0';
      setTimeout(function () { loadingScreen.remove(); }, 400);
    }
    initDraw();
    initImageZoom();
    initDynamicSlides();
    forceCenterAlign();

    var slideNum = document.querySelector('.reveal .slide-number');
    if (slideNum) {
      slideNum.addEventListener('click', function (e) {
        e.stopPropagation();
        toggleSlidePanel();
      });
    }
  });

  Reveal.on('slidechanged', function (event) {
    clearDraw();
    forceCenterAlign();
    var panel = document.getElementById('slide-panel');
    if (panel && !panel.classList.contains('hidden')) {
      updateSlidePanelActive();
    }
    event.currentSlide.querySelectorAll('video[autoplay]').forEach(function (v) {
      // slide 가 visible 된 시점에 다시 fit (hidden 상태에서는 getComputedStyle 부정확)
      if (window.fitVideoBox) window.fitVideoBox(v);
      var offset = parseFloat(v.dataset.syncOffset || '0');
      v.currentTime = offset;
      var base = parseFloat(v.dataset.baseRate || '1');
      v.playbackRate = base;
      v.play().catch(function () {});

      // loop 후에도 offset 유지
      if (offset > 0 && !v._syncBound) {
        v._syncBound = true;
        var lastT = offset;
        v.addEventListener('timeupdate', function () {
          if (v.currentTime < lastT - 0.5) {
            v.currentTime = offset;
          }
          lastT = v.currentTime;
        });
      }
    });

    // data-sync-videos="true" — master 기준으로 slave 들 연속 싱크.
    // 드리프트 0.6s 이상이면 slave 의 currentTime 을 master 에 맞춤.
    if (event.currentSlide.getAttribute('data-sync-videos') === 'true') {
      var videos = event.currentSlide.querySelectorAll('video');
      var masterIdx = parseInt(event.currentSlide.getAttribute('data-sync-master-idx') || '0');
      if (videos.length >= 2 && videos[masterIdx]) {
        var master = videos[masterIdx];
        master.addEventListener('timeupdate', function () {
          for (var i = 0; i < videos.length; i++) {
            if (i === masterIdx) continue;
            var slave = videos[i];
            // master loop 시점에 slave 도 0 으로
            // master 가 slave 보다 뒤면 slave 를 master 위치로 당김 (앞이면 그대로)
            var drift = slave.currentTime - master.currentTime;
            if (drift > 0.6 || drift < -0.6) {
              slave.currentTime = master.currentTime;
            }
          }
        });
      }
    }

    // 속도 버튼 active 상태 reset (1x default)
    event.currentSlide.querySelectorAll('.speed-btn').forEach(function (b) {
      b.classList.toggle('active', b.dataset.speed === '1');
    });
  });

  Reveal.on('fragmentshown',  function (e) { handleFragment(e, true); });
  Reveal.on('fragmenthidden', function (e) { handleFragment(e, false); });

  // 속도 버튼 클릭 — 현재 슬라이드의 모든 영상 playbackRate 변경
  document.body.addEventListener('click', function (e) {
    var btn = e.target.closest('.speed-btn');
    if (!btn) return;
    var speed = parseFloat(btn.dataset.speed);
    var slide = Reveal.getCurrentSlide();
    if (!slide) return;
    slide.querySelectorAll('video').forEach(function (v) {
      var base = parseFloat(v.dataset.baseRate || '1');
      v.playbackRate = speed * base;
    });
    slide.querySelectorAll('.speed-btn').forEach(function (b) {
      b.classList.toggle('active', b === btn);
    });
  });
}

/* ===== Tree / Sprint 동적 하이라이팅 엔진 ===== */

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
  registerScenario('repo-tree', {
    steps: [
      { nodes: { 'rt-root': 'active pulse' }, edges: {},
        info: '<span class="hl pk">physical-ai-repo-2/</span> — 모노레포. device · server · ui 3개 레이어로 분리.' },
      { nodes: { 'rt-root': 'success', 'rt-device': 'active pulse' },
        edges: { 'rt-e1': 'active flow' },
        info: '<span class="hl pk">device/</span> — ROS2 워크스페이스. 에듀핑(OpenArm), 고고핑(Nav2 · BT · FSM), 노리암(OMX 게임) 패키지.' },
      { nodes: { 'rt-root': 'success', 'rt-device': 'running', 'rt-edu': 'running', 'rt-gogo': 'running', 'rt-nori': 'running', 'rt-nav': 'running', 'rt-modes': 'running', 'rt-bt': 'running', 'rt-fsm': 'running', 'rt-server': 'active pulse' },
        edges: { 'rt-e1': 'success', 'rt-e2': 'active flow', 'rt-e4': 'running', 'rt-e5': 'running', 'rt-e6': 'running', 'rt-e7': 'running', 'rt-e8': 'running', 'rt-e9': 'running', 'rt-e10': 'running' },
        info: '<span class="hl pk">server/</span> — AI Hub (LLM · Vision · TTS) + Control (FastAPI · rclpy) + DB (PostgreSQL). device 전체 구현 진행 중.' },
      { nodes: { 'rt-root': 'success', 'rt-device': 'running', 'rt-server': 'running', 'rt-ai': 'running', 'rt-ctrl': 'running', 'rt-db': 'running', 'rt-llm': 'running', 'rt-vision': 'running', 'rt-routers': 'running', 'rt-stream': 'running', 'rt-ui': 'active pulse' },
        edges: { 'rt-e1': 'success', 'rt-e2': 'running', 'rt-e3': 'active flow', 'rt-e11': 'running', 'rt-e12': 'running', 'rt-e13': 'running', 'rt-e14': 'running', 'rt-e15': 'running', 'rt-e16': 'running', 'rt-e17': 'running' },
        info: '<span class="hl pk">ui/</span> — Robot UI (감정 표현 · 음성), Portal UI (교사/보호자), Admin UI (텔레옵).' },
      { nodes: { 'rt-root': 'success', 'rt-device': 'running', 'rt-edu': 'running', 'rt-gogo': 'running', 'rt-nori': 'running', 'rt-nav': 'running', 'rt-modes': 'running', 'rt-bt': 'running', 'rt-fsm': 'running', 'rt-server': 'running', 'rt-ai': 'running', 'rt-ctrl': 'running', 'rt-db': 'running', 'rt-ui': 'success', 'rt-robotui': 'success', 'rt-portal': 'success', 'rt-admin': 'success' },
        edges: { 'rt-e1': 'success', 'rt-e2': 'running', 'rt-e3': 'success', 'rt-e4': 'running', 'rt-e5': 'running', 'rt-e6': 'running', 'rt-e7': 'running', 'rt-e8': 'running', 'rt-e9': 'running', 'rt-e10': 'running', 'rt-e11': 'running', 'rt-e12': 'running', 'rt-e13': 'running', 'rt-e18': 'success', 'rt-e19': 'success', 'rt-e20': 'success' },
        info: '전체 현황: <span class="hl mt">ui 완성</span>, <span class="hl bt">device · server</span> 구현 진행 중.' },
    ]
  });

  registerScenario('sprint-tl', {
    steps: [
      { nodes: {}, edges: {},
        info: '<span class="font-display" style="color:#F8B4C4">&rarr;</span> 키를 눌러 스프린트 진행을 확인하세요.',
        onEnter: function() { _setAllSprints([0,0,0,0,0]); } },
      { nodes: { 'sp-n1': 'active pulse' }, edges: {},
        info: '<span class="hl pk">Sprint 1</span> (04/22-23, 2일) — 주제 선정 완료. 팀 구성 + 프로젝트 주제 확정.',
        onEnter: function() { _setAllSprints([100,0,0,0,0]); _animateSprint('sp1-bar', 100, 'sp1-count', '1/1 Done'); } },
      { nodes: { 'sp-n1': 'success', 'sp-n2': 'active pulse' }, edges: { 'sp-e1': 'success' },
        info: '<span class="hl pk">Sprint 2</span> (04/25-30, 6일) — 상세 설계 100% 완료. 아키텍처 · 요구사항 · 폴더 구조 확정.',
        onEnter: function() { _setAllSprints([100,100,0,0,0]); _animateSprint('sp1-bar', 100, 'sp1-count', '1/1 Done'); _animateSprint('sp2-bar', 100, 'sp2-count', '9/9 Done'); } },
      { nodes: { 'sp-n1': 'success', 'sp-n2': 'success', 'sp-n3': 'active pulse' }, edges: { 'sp-e1': 'success', 'sp-e2': 'success' },
        info: '<span class="hl pk">Sprint 3</span> (05/01-07) — Portal · 등록 · Robot UI 골격. Test #2 결과 <strong>21/26 PASS (81%)</strong>.',
        onEnter: function() { _setAllSprints([100,100,81,0,0]); _animateSprint('sp3-bar', 81, 'sp3-count', '21/26 Pass · 81%'); } },
      { nodes: { 'sp-n1': 'success', 'sp-n2': 'success', 'sp-n3': 'success', 'sp-n4': 'active pulse' }, edges: { 'sp-e1': 'success', 'sp-e2': 'success', 'sp-e3': 'success' },
        info: '<span class="hl pk">Sprint 4</span> (05/08-14) — NoriArm · GogoPing 운반/추종. Test #3 결과 <strong>9/20 PASS (45%)</strong>. GogoPing 추종 7개 전부 carry-over.',
        onEnter: function() { _setAllSprints([100,100,81,45,0]); _animateSprint('sp4-bar', 45, 'sp4-count', '9/20 Pass · 45%'); } },
      { nodes: { 'sp-n1': 'success', 'sp-n2': 'success', 'sp-n3': 'success', 'sp-n4': 'success', 'sp-n5': 'running' }, edges: { 'sp-e1': 'success', 'sp-e2': 'success', 'sp-e3': 'success', 'sp-e4': 'running' },
        info: '<span class="hl bt">Sprint 5</span> (05/15-22, 현재) — 로봇별 음성·UI 통합 + EduPing 율동·원격진찰 신규. Test Plan #4 <strong>23항목 진행 중</strong>. 결과 미공개 (마감 5/22).',
        onEnter: function() { _setAllSprints([100,100,81,45,85]); _animateSprint('sp5-bar', 85, 'sp5-count', '0/23 진행중'); } },
    ]
  });
}

function _animateSprint(barId, pct, countId, countText) {
  var bar = document.getElementById(barId);
  if (bar) {
    bar.style.width = pct + '%';
    var label = bar.querySelector('span');
    if (label && pct > 0) label.style.opacity = '1';
    else if (label) label.style.opacity = '0';
  }
  var countEl = document.getElementById(countId);
  if (countEl && countText) countEl.textContent = countText;
}

function _setAllSprints(pcts) {
  var counts = ['-', '-', '-', '-', '예정', '예정', '예정'];
  for (var i = 0; i < pcts.length; i++) {
    var bar = document.getElementById('sp' + (i + 1) + '-bar');
    if (bar) {
      bar.style.width = pcts[i] + '%';
      var label = bar.querySelector('span');
      if (label) label.style.opacity = pcts[i] > 0 ? '1' : '0';
    }
    var countEl = document.getElementById('sp' + (i + 1) + '-count');
    if (countEl && pcts[i] === 0) countEl.textContent = counts[i];
  }
}

/* ── Demo video toggle ── */
function toggleVideo() {
  var slide = Reveal.getCurrentSlide();
  if (!slide) return;
  var video = slide.querySelector('video');
  if (!video) return;
  if (video.paused) video.play(); else video.pause();
}

/* ── Drawing canvas ── */
var _drawActive = false;
var _drawing = false;
var _lastX = 0, _lastY = 0;

function toggleDraw() {
  _drawActive = !_drawActive;
  var canvas = document.getElementById('draw-canvas');
  canvas.style.pointerEvents = _drawActive ? 'auto' : 'none';
  document.body.style.cursor = _drawActive ? 'crosshair' : '';
}
function clearDraw() {
  var canvas = document.getElementById('draw-canvas');
  var ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}
function initDraw() {
  var canvas = document.getElementById('draw-canvas');
  canvas.width  = window.innerWidth;
  canvas.height = window.innerHeight;
  window.addEventListener('resize', function () {
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
  });
  var ctx = canvas.getContext('2d');
  ctx.strokeStyle = '#F8B4C4';
  ctx.lineWidth   = 5;
  ctx.lineCap     = 'round';
  ctx.lineJoin    = 'round';
  canvas.addEventListener('mousedown', function (e) {
    _drawing = true; _lastX = e.clientX; _lastY = e.clientY;
  });
  canvas.addEventListener('mousemove', function (e) {
    if (!_drawing) return;
    ctx.strokeStyle = '#F8B4C4';
    ctx.lineWidth   = 5;
    ctx.lineCap     = 'round';
    ctx.lineJoin    = 'round';
    ctx.beginPath();
    ctx.moveTo(_lastX, _lastY);
    ctx.lineTo(e.clientX, e.clientY);
    ctx.stroke();
    _lastX = e.clientX; _lastY = e.clientY;
  });
  canvas.addEventListener('mouseup',    function () { _drawing = false; });
  canvas.addEventListener('mouseleave', function () { _drawing = false; });
}

/* ── Webcam overlay ── */
var _wcStream = null;
var _wcActive = false;
var _wcAnimFrame = null;

function toggleWebcam() {
  if (_wcActive) _stopWebcam(); else _startWebcam();
}
async function _startWebcam() {
  var overlay = document.getElementById('webcam-overlay');
  var video   = document.getElementById('webcam-video');
  var canvas  = document.getElementById('webcam-canvas');
  var ctx     = canvas.getContext('2d');
  try {
    _wcStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'user', width: 640, height: 480 },
    });
    video.srcObject = _wcStream;
    await video.play();
    canvas.width  = video.videoWidth  || 640;
    canvas.height = video.videoHeight || 480;
    overlay.style.display = 'block';
    _wcActive = true;
    (function draw() {
      if (!_wcActive) return;
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      _wcAnimFrame = requestAnimationFrame(draw);
    })();
  } catch (e) {
    console.warn('Webcam error:', e);
  }
}
function _stopWebcam() {
  _wcActive = false;
  if (_wcAnimFrame) { cancelAnimationFrame(_wcAnimFrame); _wcAnimFrame = null; }
  if (_wcStream) { _wcStream.getTracks().forEach(function (t) { t.stop(); }); _wcStream = null; }
  var overlay = document.getElementById('webcam-overlay');
  if (overlay) overlay.style.display = 'none';
}

/* ── Fullscreen ── */
function toggleFullscreen() {
  if (!document.fullscreenElement) document.documentElement.requestFullscreen();
  else document.exitFullscreen();
}
function updateFullscreenHint() {
  var hint = document.getElementById('fullscreen-hint');
  if (!hint) return;
  var key = document.fullscreenElement ? 'ESC' : 'F';
  var msg = document.fullscreenElement ? 'to minimize' : 'for fullscreen';
  hint.innerHTML = 'Press <kbd style="background:#FFFFFF;border:1px solid #FFE0E6;border-radius:4px;padding:1px 5px;font-size:0.9em;color:#5D4037">' + key + '</kbd> ' + msg;
}
document.addEventListener('fullscreenchange', updateFullscreenHint);

/* ── Slide thumbnail panel ── */
function buildSlidePanel() {
  var list = document.getElementById('slide-panel-list');
  list.innerHTML = '';
  var sections = document.querySelectorAll('.reveal .slides > section');
  var current = Reveal.getIndices().h;

  sections.forEach(function (section, i) {
    var item = document.createElement('div');
    item.className = 'slide-thumb-item' + (i === current ? ' active' : '');
    item.dataset.index = i;
    item.innerHTML =
      '<div class="slide-thumb-meta">'
        + '<span class="slide-thumb-num">' + (i + 1) + '</span>'
        + '<span class="slide-thumb-title">' + (SLIDE_TITLES[i] || '') + '</span>'
      + '</div>';
    item.addEventListener('click', function () {
      Reveal.slide(i);
      closeSlidePanel();
    });
    list.appendChild(item);
  });
}
function updateSlidePanelActive() {
  var current = Reveal.getIndices().h;
  document.querySelectorAll('.slide-thumb-item').forEach(function (el, i) {
    el.classList.toggle('active', i === current);
  });
  var activeEl = document.querySelector('.slide-thumb-item.active');
  if (activeEl) activeEl.scrollIntoView({ block: 'nearest' });
}
function toggleSlidePanel() {
  var panel = document.getElementById('slide-panel');
  if (!panel.classList.contains('hidden')) closeSlidePanel();
  else {
    buildSlidePanel();
    panel.classList.remove('hidden');
    panel.classList.add('flex');
    document.getElementById('slide-panel-overlay').classList.remove('hidden');
    setTimeout(function () {
      var activeEl = document.querySelector('.slide-thumb-item.active');
      if (activeEl) activeEl.scrollIntoView({ block: 'center' });
    }, 50);
  }
}
function closeSlidePanel() {
  var panel = document.getElementById('slide-panel');
  panel.classList.add('hidden');
  panel.classList.remove('flex');
  document.getElementById('slide-panel-overlay').classList.add('hidden');
}
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') {
    closeSlidePanel();
    closeImageZoom();
  }
});

/* ── Image zoom lightbox ── */
function openImageZoom(src, alt) {
  var overlay = document.getElementById('image-zoom-overlay');
  var img = document.getElementById('image-zoom-img');
  if (!overlay || !img) return;
  img.src = src;
  img.alt = alt || '';
  overlay.style.display = 'flex';
}
function closeImageZoom() {
  var overlay = document.getElementById('image-zoom-overlay');
  if (overlay) overlay.style.display = 'none';
}
function initImageZoom() {
  document.querySelectorAll('.reveal img.zoomable').forEach(function (img) {
    if (img.dataset.zoomBound) return;
    img.dataset.zoomBound = '1';
    img.style.cursor = 'zoom-in';
    img.addEventListener('click', function (e) {
      e.stopPropagation();
      e.preventDefault();
      openImageZoom(img.src, img.alt);
    });
  });
}

initPresentation();
