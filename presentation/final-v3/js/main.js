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
  // ── EDUPING ──
  '08-eduping-section.html',
  '09-eduping-arrival.html',
  '10-eduping-dance.html',
  '11-eduping-hibiscus.html',
  '12-eduping-doctor.html',
  // ── GOGOPING ──
  '13-gogoping-section.html',
  '14-gogoping-follow.html',
  // ── NORIARM ──
  '18-noriarm-section.html',
  '19-noriarm-blocks.html',
  '20-noriarm-oxquiz.html',
  '21-noriarm-shop.html',
  // ── CLOSING ──
  '22-sprint-jira.html',
  '22b-portal-report.html',
  '23-team.html',
  '24-ending.html',
  // ── Q&A 부록 (클릭하면 점프) ──
  'qa-1-act.html',
  'qa-2-mugunghwa.html',
  'qa-3-doctor.html',
  'qa-4-safety.html',
  'qa-5-follow.html',
  'qa-6-wakeword.html',
  'qa-7-nav.html',
  'qa-8-portal.html',
  'qa-9-architecture.html',
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
  '— EduPing —',
  '에듀핑 · 등하원 + 하이파이브',
  '에듀핑 · 율동',
  '에듀핑 · 무궁화꽃이 피었습니다',
  '에듀핑 · 원격 진단',
  '— GogoPing —',
  '고고핑 · 교사 추종',
  '— NoriArm —',
  '노리암 · 블럭쌓기',
  '노리암 · OX 퀴즈',
  '노리암 · 가게놀이',
  '스프린트 Jira',
  'Portal · 일과 보고서',
  '팀',
  'Q&A',
  'Q&A · 모방학습 (ACT)',
  'Q&A · 무궁화 perception',
  'Q&A · 원격 진찰',
  'Q&A · 근접 안전정지',
  'Q&A · 교사 추종',
  'Q&A · 호출어',
  'Q&A · 자율 주행 + BT',
  'Q&A · Portal 보고서',
  'Q&A · 아키텍처',
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

  // 현재 슬라이드에 아직 안 재생된 [data-press-to-play] 영상이 있으면 재생, 없으면 다음 슬라이드.
  function advanceOrPlay() {
    var slide = Reveal.getCurrentSlide();
    if (!slide) { Reveal.right(); return; }
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

/* ── Video speed controls (overlay on every video) ── */
function attachVideoSpeedControls() {
  document.querySelectorAll('.reveal video').forEach(function (v) {
    if (v.dataset.speedBound) return;
    v.dataset.speedBound = '1';
    var rates = ['1', '1.5', '2', '3'];
    var ctl = document.createElement('div');
    ctl.className = 'video-speed show';
    ctl.innerHTML = rates.map(function (s) {
      return '<button data-rate="' + s + '">' + s + 'x</button>';
    }).join('');
    ctl.querySelectorAll('button').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        var rate = parseFloat(b.dataset.rate);
        v.playbackRate = rate;
        ctl.querySelectorAll('button').forEach(function (x) {
          x.classList.toggle('active', x === b);
        });
      });
    });
    var defaultRate = v.dataset.defaultRate || '2';
    v.playbackRate = parseFloat(defaultRate);
    var defBtn = ctl.querySelector('button[data-rate="' + defaultRate + '"]');
    if (defBtn) defBtn.classList.add('active');
    var parent = v.parentElement;
    if (parent) {
      if (getComputedStyle(parent).position === 'static') {
        parent.style.position = 'relative';
      }
      parent.appendChild(ctl);
    }
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
