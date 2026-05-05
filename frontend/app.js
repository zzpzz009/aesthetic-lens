/* ============================================================
   AestheticLens — 前端交互 v2
   核心改动：批量模式先渲染缩略图，再逐张调用 score_image
   ============================================================ */

let batchResults = [];
let batchImages = [];    // [{filename, data}, ...]
let slideIndex = 0;      // 批量翻页当前索引
let currentView = "drop"; // "drop" | "single" | "batch" | "slide"

// ---------------------------------------------------------------------------
// 初始化
// ---------------------------------------------------------------------------
window.addEventListener("pywebviewready", () => setupDragDrop());
window.addEventListener("DOMContentLoaded", () => {
  setupDragDrop();
  setupCanvasDragDrop();
});

// ---------------------------------------------------------------------------
// 窗口
// ---------------------------------------------------------------------------
function closeWindow() { window.close(); }
function minimizeWindow() { window.pywebview.api.minimize(); }
function toggleMaximize() { window.pywebview.api.toggle_maximize(); }

// ---------------------------------------------------------------------------
// 视图切换
// ---------------------------------------------------------------------------
function showView(name) {
  currentView = name;
  document.getElementById("drop-zone").style.display    = (name === "drop")      ? "flex" : "none";
  document.getElementById("result-panel").style.display  = (name !== "drop" && name !== "batch") ? "flex" : "none";
  document.getElementById("batch-view").style.display    = (name === "batch")     ? "flex" : "none";

  // 导航按钮控制
  const isBatchSlide = (name === "slide");
  document.getElementById("nav-counter").style.display   = isBatchSlide ? "inline" : "none";
  document.getElementById("nav-prev").style.display      = isBatchSlide ? "inline" : "none";
  document.getElementById("nav-next").style.display      = isBatchSlide ? "inline" : "none";
  document.getElementById("btn-back-batch").style.display = isBatchSlide ? "inline" : "none";
  document.getElementById("btn-back-drop").style.display  = isBatchSlide ? "none"   : "inline";
}

function resetView() {
  batchResults = [];
  batchImages = [];
  showView("drop");
}

function backToBatch() {
  showView("batch");
}

// ---------------------------------------------------------------------------
// 拖拽 — 空白区
// ---------------------------------------------------------------------------
let _dragReady = false;

function setupDragDrop() {
  if (_dragReady) return;
  _dragReady = true;
  const dz = document.getElementById("drop-zone");
  if (!dz) return;

  dz.addEventListener("dragover", e => {
    e.preventDefault();
    dz.classList.add("drag-over");
  });
  dz.addEventListener("dragleave", () => dz.classList.remove("drag-over"));
  dz.addEventListener("drop", e => {
    e.preventDefault();
    dz.classList.remove("drag-over");
    handleDrop(e.dataTransfer.files);
  });
  dz.addEventListener("click", () => pickFiles());
}

// ---------------------------------------------------------------------------
// 拖拽 — 画布区（换图）
// ---------------------------------------------------------------------------
function setupCanvasDragDrop() {
  const canvas = document.querySelector(".cinema-canvas");
  if (!canvas) return;

  canvas.addEventListener("dragover", e => {
    e.preventDefault();
    canvas.classList.add("drag-over");
  });
  canvas.addEventListener("dragleave", () => canvas.classList.remove("drag-over"));
  canvas.addEventListener("drop", e => {
    e.preventDefault();
    canvas.classList.remove("drag-over");
    handleDrop(e.dataTransfer.files);
  });
}

// ---------------------------------------------------------------------------
// 统一入口
// ---------------------------------------------------------------------------
function handleDrop(fileList) {
  const images = [];
  for (const file of fileList) {
    if (!file.type.startsWith("image/")) continue;
    images.push(file);
  }
  if (images.length === 0) return;

  if (images.length === 1) {
    readFile(images[0], data => scoreSingle(data));
  } else {
    readFiles(images, imgs => startBatch(imgs));
  }
}

function readFile(file, cb) {
  const r = new FileReader();
  r.onload = () => cb({ filename: file.name, data: r.result });
  r.readAsDataURL(file);
}

function readFiles(files, cb) {
  const promises = [];
  for (const f of files) {
    if (!f.type.startsWith("image/")) continue;
    promises.push(new Promise(resolve => {
      const r = new FileReader();
      r.onload = () => resolve({ filename: f.name, data: r.result });
      r.readAsDataURL(f);
    }));
  }
  Promise.all(promises).then(cb);
}

// ---------------------------------------------------------------------------
// 文件选择
// ---------------------------------------------------------------------------
async function pickFiles() {
  const images = await window.pywebview.api.open_file_dialog();
  if (!images || images.length === 0) return;
  if (images.length === 1) scoreSingle(images[0]);
  else startBatch(images);
}

// ---------------------------------------------------------------------------
// 单图评分
// ---------------------------------------------------------------------------
async function scoreSingle(imageData) {
  showView("single");

  const resultImage = document.getElementById("result-image");
  const loadingOverlay = document.getElementById("loading-overlay");

  resultImage.src = imageData.data;
  loadingOverlay.style.display = "flex";

  document.getElementById("score-number").textContent = "—";
  document.getElementById("score-tier").textContent = "";
  document.getElementById("score-bar-fill").style.width = "0%";
  document.getElementById("score-filename").textContent = "";
  document.getElementById("score-elapsed").textContent = "";

  const result = await window.pywebview.api.score_image(imageData.data);
  loadingOverlay.style.display = "none";

  if (result.error) {
    document.getElementById("score-number").textContent = "!";
    document.getElementById("score-tier").textContent = result.error.substring(0, 30);
    document.getElementById("score-tier").setAttribute("data-tier", "较差");
    return;
  }

  animateScore(result.score);

  const tierEl = document.getElementById("score-tier");
  tierEl.textContent = result.tier;
  tierEl.setAttribute("data-tier", result.tier);

  setTimeout(() => {
    document.getElementById("score-bar-fill").style.width = `${(result.score / 10) * 100}%`;
    document.getElementById("score-bar-fill").setAttribute("data-tier", result.tier);
  }, 100);

  document.getElementById("score-elapsed").textContent = `${result.elapsed_ms} ms`;
  document.getElementById("score-filename").textContent = imageData.filename || "";
}

// ---------------------------------------------------------------------------
// 批量模式 — 先显示缩略图，再逐张评分
// ---------------------------------------------------------------------------
function startBatch(images) {
  batchImages = images;
  batchResults = new Array(images.length).fill(null);

  showView("batch");

  const grid = document.getElementById("batch-grid");
  grid.innerHTML = "";

  // 先渲染所有缩略图（无分数）
  images.forEach((img, idx) => {
    const item = document.createElement("div");
    item.className = "batch-item batch-item-loading";
    item.id = `batch-item-${idx}`;

    item.innerHTML = `
      <img src="${img.data || ''}" alt="${img.filename}" loading="lazy">
      <div class="batch-item-score">
        <span class="score-val">...</span>
      </div>
    `;

    item.dataset.image = img.data || '';
    item.dataset.filename = img.filename || '';
    item.dataset.score = '';
    item.dataset.tier = '';
    item.dataset.error = '';

    item.addEventListener('click', () => openSlide(idx));
    grid.appendChild(item);
  });

  // 进度条
  const progressFill = document.getElementById("progress-bar-fill");
  const progressText = document.getElementById("progress-text");
  const progress = document.getElementById("batch-progress");
  progress.style.display = "flex";
  progressFill.style.width = "0%";
  progressText.textContent = `准备评分 · 0 / ${images.length}`;

  // 逐张异步评分
  scoreBatchSequential(0, images, progressFill, progressText);
}

async function scoreBatchSequential(idx, images, progressFill, progressText) {
  if (idx >= images.length) {
    // 全部完成
    progressFill.style.width = "100%";
    const successCount = batchResults.filter(r => r && !r.error).length;
    progressText.textContent = `完成 · ${successCount} / ${images.length}`;
    document.getElementById("batch-export-btn").style.display = "inline-block";
    return;
  }

  const img = images[idx];
  let result;

  try {
    result = await window.pywebview.api.score_image(img.data);
    result.filename = img.filename || `image_${idx}`;
  } catch (e) {
    result = { filename: img.filename || `image_${idx}`, score: 0, tier: "错误", elapsed_ms: 0, error: String(e) };
  }

  batchResults[idx] = result;

  // 更新对应缩略图
  const item = document.getElementById(`batch-item-${idx}`);
  if (item) {
    item.classList.remove("batch-item-loading");
    if (result.error) {
      item.classList.add("batch-item-error");
      item.querySelector(".batch-item-score").innerHTML = `
        <span class="score-val score-val-error">!</span>
      `;
      item.dataset.error = result.error;
    } else {
      const scoreEl = item.querySelector(".batch-item-score");
      scoreEl.innerHTML = `
        <span class="score-val" data-tier="${result.tier}">${result.score}</span>
        <span class="score-tier-small" data-tier="${result.tier}">${result.tier}</span>
      `;
      item.dataset.score = result.score;
      item.dataset.tier = result.tier;
    }
  }

  // 更新进度
  const pct = ((idx + 1) / images.length) * 100;
  progressFill.style.width = `${pct}%`;
  progressText.textContent = `评分中 · ${idx + 1} / ${images.length}`;

  // 下一张
  scoreBatchSequential(idx + 1, images, progressFill, progressText);
}

// ---------------------------------------------------------------------------
// 批量翻页 — 复用字幕卡
// ---------------------------------------------------------------------------
function openSlide(idx) {
  if (idx < 0 || idx >= batchResults.length) return;

  slideIndex = idx;
  const result = batchResults[idx];
  const img = batchImages[idx];

  // 填充字幕卡
  document.getElementById("result-image").src = img?.data || '';
  document.getElementById("score-filename").textContent = img?.filename || '';

  if (result && !result.error) {
    document.getElementById("score-number").textContent = parseFloat(result.score).toFixed(1);
    const tierEl = document.getElementById("score-tier");
    tierEl.textContent = result.tier || '';
    tierEl.setAttribute("data-tier", result.tier || '');
    document.getElementById("score-bar-fill").style.width = `${(parseFloat(result.score || 0) / 10) * 100}%`;
    document.getElementById("score-bar-fill").setAttribute("data-tier", result.tier || '');
    document.getElementById("score-elapsed").textContent = `${result.elapsed_ms} ms`;
  } else {
    document.getElementById("score-number").textContent = "!";
    const tierEl = document.getElementById("score-tier");
    tierEl.textContent = result?.error ? result.error.substring(0, 30) : '评分失败';
    tierEl.setAttribute("data-tier", "较差");
    document.getElementById("score-bar-fill").style.width = "0%";
    document.getElementById("score-bar-fill").setAttribute("data-tier", "");
    document.getElementById("score-elapsed").textContent = "";
  }

  // 翻页状态
  document.getElementById("nav-counter").textContent = `${idx + 1}/${batchResults.length}`;
  document.getElementById("nav-prev").disabled = (idx === 0);
  document.getElementById("nav-next").disabled = (idx === batchResults.length - 1);

  showView("slide");
}

function navSlide(delta) {
  const next = slideIndex + delta;
  if (next >= 0 && next < batchResults.length) {
    openSlide(next);
  }
}

// ---------------------------------------------------------------------------
// 动画
// ---------------------------------------------------------------------------
function animateScore(target) {
  const el = document.getElementById("score-number");
  const duration = 1200;
  const start = performance.now();
  el.classList.add("score-animated");

  function tick(now) {
    const progress = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    el.textContent = (target * eased).toFixed(1);
    if (progress < 1) requestAnimationFrame(tick);
    else el.textContent = target.toFixed(1);
  }
  requestAnimationFrame(tick);
}

// ---------------------------------------------------------------------------
// 键盘
// ---------------------------------------------------------------------------
document.addEventListener('keydown', e => {
  if (currentView === "slide") {
    if (e.key === 'Escape') { backToBatch(); return; }
    if (e.key === 'ArrowLeft') { navSlide(-1); return; }
    if (e.key === 'ArrowRight') { navSlide(1); return; }
  }
  if (e.key === 'Escape' && currentView !== 'drop') {
    if (currentView === 'batch') resetView();
    else if (currentView === 'single') resetView();
  }
});

// ---------------------------------------------------------------------------
// 导出
// ---------------------------------------------------------------------------
async function exportBatch(format) {
  const validResults = batchResults.filter(r => r && !r.error);
  if (validResults.length === 0) return;
  const json = JSON.stringify(validResults);
  const result = await window.pywebview.api.export_results(json, format || "csv");
  if (result.path) alert(`已导出到: ${result.path}`);
  else if (result.error) alert(`导出失败: ${result.error}`);
}

// ---------------------------------------------------------------------------
// 关于
// ---------------------------------------------------------------------------
function showAbout() { document.getElementById("about-modal").style.display = "flex"; }
function closeAbout() { document.getElementById("about-modal").style.display = "none"; }
