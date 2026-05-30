/* ============================================
   pingdergarten Presentation JS
   - Slide loader / keybindings / slide panel
   - Drawing canvas / webcam overlay
   ============================================ */

var SLIDES = [
  // ── HOOK ──
  '01-title.html',
  '02-pain.html',
  '03-reveal.html',
  // ── STAGE ──
  '04-robots-roster.html',
  '05-day-flow.html',
  '06-hardware-specs.html',
  '06b-stage-context.html',
  // ── EDUPING ──
  '07-eduping-section.html',
  '08-eduping-arrival.html',
  '09-eduping-dance.html',
  '10-eduping-hibiscus.html',
  '11-eduping-doctor.html',
  '12-eduping-safety.html',
  // ── GOGOPING ──
  '13-gogoping-section.html',
  '14-gogoping-lullaby.html',
  '15-gogoping-progress.html',
  // ── NORIARM ──
  '16-noriarm-section.html',
  '17-noriarm-blocks.html',
  '18-noriarm-oxquiz.html',
  '19-noriarm-shop.html',
  // ── SYSTEM ──
  '20-architecture.html',
  '21-sim-real-cases.html',
  // ── CLOSING ──
  '22-final-demo.html',
  '23-team.html',
  '24-thanks.html',
  // ── APPENDIX ──
  'a1-wake-word.html',
];

var SLIDE_TITLES = [
  '사랑의 에듀핑',
  '선생님 한 명 · 아이 15명',
  'pingdergarten',
  '세 로봇',
  '하루 일과',
  '하드웨어',
  '유치원 — 맵 · 시뮬',
  '— EduPing —',
  '에듀핑 · 등하원',
  '에듀핑 · 율동',
  '에듀핑 · 무궁화',
  '에듀핑 · 원격 진찰',
  '에듀핑 · 근접 안전정지',
  '— GogoPing —',
  '고고핑 · 자장가 + 카메라',
  '고고핑 · 교사 추종 + 진행 중',
  '— NoriArm —',
  '노리암 · 블럭쌓기 ACT',
  '노리암 · OX 퀴즈',
  '노리암 · 가게놀이',
  '아키텍처',
  '시뮬 → 실물 사례',
  'Final Demo',
  '팀',
  '감사합니다',
  'A1 · 호출어 (wake word)',
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
      var sectionHeight = s.offsetHeight;
      var topOffset = (slideHeight - sectionHeight) / 2;
      if (topOffset > 0) s.style.top = topOffset + 'px';
    });
  }

  // Inject a soft candy-glow background into any slide that doesn't define one
  // (slides 01–10 ship their own .bg-deco; this covers 11–51 uniformly).
  function injectGlows() {
    var palette = ['--babypinkSoft', '--mintSoft', '--lavenderSoft', '--butterSoft', '--skySoft'];
    document.querySelectorAll('.reveal .slides > section').forEach(function (sec, i) {
      if (sec.querySelector(':scope > .bg-deco')) return; // already has one
      var c1 = palette[i % palette.length];
      var c2 = palette[(i + 2) % palette.length];
      var deco = document.createElement('div');
      deco.className = 'bg-deco';
      deco.innerHTML =
        '<div class="blob" style="width:420px;height:420px;background:var(' + c1 + ');top:-150px;left:-130px"></div>' +
        '<div class="blob" style="width:360px;height:360px;background:var(' + c2 + ');bottom:-160px;right:-110px"></div>' +
        '<div class="dots"></div>';
      sec.insertBefore(deco, sec.firstChild);
    });
  }

  // Stagger-animate the content children of a slide that has no explicit .r tags
  function autoAnimate(section) {
    var wrap = section.querySelector(':scope > div:not(.bg-deco)');
    if (!wrap) return;
    var kids = Array.prototype.slice.call(wrap.children);
    kids.forEach(function (el) {
      el.style.transition = 'none';
      el.style.opacity = '0';
      el.style.transform = 'translateY(16px)';
    });
    void wrap.offsetWidth; // reflow → restart from hidden state
    kids.forEach(function (el, i) {
      el.style.transition = 'opacity .5s ease, transform .5s cubic-bezier(.22,.7,.3,1)';
      el.style.transitionDelay = (i * 65) + 'ms';
      el.style.opacity = '1';
      el.style.transform = 'none';
    });
  }

  // Re-trigger entrance motion each time a slide becomes current
  function replayMotion() {
    document.querySelectorAll('.reveal .slides section').forEach(function (s) {
      s.classList.remove('go');
    });
    var cur = Reveal.getCurrentSlide();
    if (!cur) return;
    if (cur.querySelector('.r')) { void cur.offsetWidth; cur.classList.add('go'); } // explicit (01–10)
    else { autoAnimate(cur); }                                                       // auto (11–51)
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
    injectGlows();
    forceCenterAlign();
    replayMotion();

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
    replayMotion();
    var panel = document.getElementById('slide-panel');
    if (panel && !panel.classList.contains('hidden')) {
      updateSlidePanelActive();
    }
    event.currentSlide.querySelectorAll('video[autoplay]').forEach(function (v) {
      v.currentTime = 0;
      v.play().catch(function () {});
    });
  });
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
  hint.innerHTML = 'Press <kbd style="background:#241F33;border:1px solid rgba(255,255,255,0.14);border-radius:4px;padding:1px 5px;font-size:0.9em;color:#F4EFE8">' + key + '</kbd> ' + msg;
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
