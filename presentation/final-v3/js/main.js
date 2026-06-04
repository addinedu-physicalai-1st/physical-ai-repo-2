/* ============================================
   pingdergarten Presentation JS
   - Slide loader / keybindings / slide panel
   - Drawing canvas / webcam overlay
   ============================================ */

var SLIDES = [
  // ── HOOK ──
  '01-title.html',
  '02-pov-video.html',
  '02b-dev-question.html',
  '03-want.html',
  '04b-reveal.html',
  '05-toc.html',
  '04-need.html',
  '04c-required.html',
  // ── SETUP ──
  '07b-hardware.html',
  '06-system.html',
  '07-tech-stack.html',
  '07c-daily-scenario.html',
  // ── EDUPING ──
  '08-eduping-section.html',
  '09-eduping-arrival-scenario.html',
  '09-eduping-arrival.html',
  '09b-eduping-arrival-content.html',
  '10-eduping-dance-scenario.html',
  '10-eduping-dance.html',
  '10b-eduping-dance-content.html',
  '11-eduping-hibiscus-scenario.html',
  '11-eduping-hibiscus.html',
  '11b-eduping-hibiscus-content.html',
  '12-eduping-doctor-preview.html',
  '12-eduping-doctor.html',
  '12b-eduping-doctor-content.html',
  // ── GOGOPING ──
  '13-gogoping-section.html',
  '14-gogoping-follow-scenario.html',
  '14-gogoping-follow.html',
  '14b-gogoping-follow-content.html',
  '14c-gogoping-guide-intro.html',
  '14c-gogoping-guide-map.html',
  '14c-gogoping-guide-scenario.html',
  '14c-gogoping-guide.html',
  '14d-gogoping-guide-content.html',
  '15-gogoping-hideseek-scenario.html',
  '15-gogoping-hideseek.html',
  '15b-gogoping-hideseek-content.html',
  // ── NORIARM ──
  '18-noriarm-section.html',
  '19-noriarm-blocks-scenario.html',
  '19-noriarm-blocks.html',
  '19b-noriarm-blocks-content.html',
  '20-noriarm-oxquiz-scenario.html',
  '20-noriarm-oxquiz.html',
  '20b-noriarm-oxquiz-content.html',
  '21-noriarm-shop-scenario.html',
  '21-noriarm-shop.html',
  '21b-noriarm-shop-content.html',
  // ── CLOSING ──
  '22b-portal-report.html',
  '22c-process-section.html',
  '22-sprint-jira.html',
  '22a-jira-gantt.html',
  '22d-team-section.html',
  '23a-team-eduping.html',
  '23b-team-gogoping.html',
  '23c-team-noriarm.html',
  // ── Q&A (마지막 슬라이드 · 항목 클릭 → reports/ 의 담당자 보고서로 이동) ──
  '24-ending.html',
];

var SLIDE_TITLES = [
  '핑더가든',
  'POV 영상 (1인칭)',
  '무엇을 만들어야 했나 (Dev)',
  '하고 싶었던 것',
  '핑더가든 reveal',
  '목차',
  'PART 01 — System',
  '그래서 필요했던 것',
  '로봇 하드웨어',
  '시스템 구성',
  '기술 스택',
  '하루 일과 시나리오',
  '— EduPing —',
  '에듀핑 · 등하원 + 하이파이브',
  '에듀핑 · 율동',
  '에듀핑 · 무궁화꽃이 피었습니다',
  '에듀핑 · 원격 진단',
  '— GogoPing —',
  '고고핑 · 교사 추종',
  '고고핑 · 가이드 (인트로)',
  '고고핑 · 가이드 (지도)',
  '고고핑 · 가이드',
  '고고핑 · 가이드 (내용)',
  '고고핑 · 숨바꼭질',
  '고고핑 · 숨바꼭질 (내용)',
  '— NoriArm —',
  '노리암 · 블럭쌓기',
  '노리암 · OX 퀴즈',
  '노리암 · 가게놀이',
  'Portal · 일과 보고서',
  'PART 05 · Process',
  '스프린트 타임라인',
  'Jira Epic 진행',
  'PART 06 · Team',
  'Team · EduPing',
  'Team · GogoPing',
  'Team · NoriArm',
  'Q&A',
];

async function loadSlides() {
  var container = document.querySelector('.reveal .slides');
  var responses = await Promise.all(
    SLIDES.map(function (name) { return fetch('slides/' + name + '?t=' + Date.now(), { cache: 'no-store' }); })
  );
  var htmls = await Promise.all(responses.map(function (r) { return r.text(); }));
  htmls.forEach(function (html) {
    container.insertAdjacentHTML('beforeend', html);
  });
}

async function initPresentation() {
  await loadSlides();

  // Architecture flow: all nodes always shown; spotlight moves to current step.
  function applyArchSpotlight() {
    var debugMatch = location.search.match(/[?&]archstep=(\d+)/);
    var debugStep = debugMatch ? parseInt(debugMatch[1], 10) : null;
    document.querySelectorAll('section[data-arch-flow]').forEach(function (slide) {
      var currentStep = 0;
      if (debugStep !== null) {
        currentStep = debugStep;
      } else {
        slide.querySelectorAll('.fragment[data-archstep]').forEach(function (f) {
          if (f.classList.contains('visible') || f.classList.contains('current-fragment')) {
            var s = parseInt(f.dataset.archstep, 10);
            if (s > currentStep) currentStep = s;
          }
        });
      }
      slide.querySelectorAll('.n[data-step]').forEach(function (n) {
        var steps = String(n.dataset.step).split(',').map(function (x) { return parseInt(x, 10); });
        n.classList.toggle('on', steps.indexOf(currentStep) !== -1);
      });
      slide.querySelectorAll('svg.lines [data-flow]').forEach(function (el) {
        var steps = String(el.dataset.flow).split(',').map(function (x) { return parseInt(x, 10); });
        el.classList.toggle('on', steps.indexOf(currentStep) !== -1);
      });
    });
  }

  Reveal.initialize({
    hash: true,
    fragmentInURL: true,
    center: false,
    slideNumber: 'c/t',
    width: 1280,
    height: 720,
    margin: 0,
    minScale: 0.2,
    maxScale: 5.0,
    transition: 'fade',
    transitionSpeed: 'fast',
    plugins: [RevealNotes, RevealHighlight],
    keyboard: {
      80: function () { toggleVideo(); },      // P
      70: function () { toggleFullscreen(); }, // F
      87: function () { toggleWebcam(); },     // W
      67: function () { toggleDraw(); },       // C
      88: function () { clearDraw(); },        // X
      39: function () { advanceOrPlay(); },    // →
      32: function () { advanceOrPlay(); },    // Space
      34: function () { advanceOrPlay(); },    // PageDown
    },
  });

  // 1) 영상 먼저 재생, 2) 시나리오 fragment 진행, 3) 다음 슬라이드.
  function advanceOrPlay() {
    var slide = Reveal.getCurrentSlide();
    if (!slide) { Reveal.right(); return; }
    // 1) 안 재생된 영상 먼저 재생
    var pending = slide.querySelectorAll('video[data-press-to-play]:not([data-played="1"])');
    if (pending.length > 0) {
      pending.forEach(function (v) {
        v.dataset.played = '1';
        v.currentTime = 0;
        v.playbackRate = parseFloat(v.dataset.defaultRate || '2');
        v.play().catch(function () {});
      });
      return;
    }
    Reveal.right();
  }

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
    attachVideoSpeedControls();
    forceCenterAlign();
    replayMotion();
    applyArchSpotlight();

    var slideNum = document.querySelector('.reveal .slide-number');
    if (slideNum) {
      slideNum.addEventListener('click', function (e) {
        e.stopPropagation();
        toggleSlidePanel();
      });
    }
  });

  Reveal.on('fragmentshown', applyArchSpotlight);
  Reveal.on('fragmenthidden', applyArchSpotlight);


  Reveal.on('slidechanged', function (event) {
    clearDraw();
    qnaReset();          // Q&A 슬라이드 재진입 시 리스트 다시 숨김
    forceCenterAlign();
    replayMotion();
    applyArchSpotlight();
    var panel = document.getElementById('slide-panel');
    if (panel && !panel.classList.contains('hidden')) {
      updateSlidePanelActive();
    }
    attachVideoSpeedControls();
    // 슬라이드 진입 시 — press-to-play 영상은 첫 프레임에서 멈추고 대기, 그 외는 자동 재생.
    event.currentSlide.querySelectorAll('video').forEach(function (v) {
      v.currentTime = 0;
      v.playbackRate = parseFloat(v.dataset.defaultRate || '2');
      if (v.hasAttribute('data-press-to-play')) {
        v.dataset.played = '0';
        v.pause();
      } else {
        v.play().catch(function () {});
      }
    });
  });
}

/* ── Q&A 질문 목록 팝업 (Q&A 글씨 클릭 → 팝업, 딤/✕/Esc → 닫기) ── */
function qnaShow() {
  var popup = document.getElementById('qna-popup');
  if (popup) popup.style.display = 'flex';
}
function qnaReset() {
  var popup = document.getElementById('qna-popup');
  if (popup) popup.style.display = 'none';
}

/* ── Q&A → 담당자 보고서 이동 (같은 탭, 크림 페이드로 슬라이드처럼 연결) ── */
function openReport(path) {
  var ov = document.getElementById('page-fade');
  if (!ov) {
    ov = document.createElement('div');
    ov.id = 'page-fade';
    ov.style.cssText = 'position:fixed;inset:0;z-index:9998;background:#16131F;'
      + 'opacity:0;transition:opacity .3s ease;pointer-events:none';
    document.body.appendChild(ov);
  }
  ov.style.pointerEvents = 'auto';
  var url = path + (path.indexOf('?') === -1 ? '?' : '&') + 't=' + Date.now();
  requestAnimationFrame(function () { ov.style.opacity = '1'; });
  setTimeout(function () { window.location.href = url; }, 300);
}

/* ── Video speed controls — UI 숨김, default rate 만 적용 ── */
function attachVideoSpeedControls() {
  document.querySelectorAll('.reveal video').forEach(function (v) {
    if (v.dataset.speedBound) return;
    v.dataset.speedBound = '1';
    var defaultRate = v.dataset.defaultRate || '2';
    v.playbackRate = parseFloat(defaultRate);
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
    qnaReset();
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
