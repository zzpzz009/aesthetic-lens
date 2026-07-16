/* ============================================================
   AestheticLens — 前端编排层 v5
   模块化架构：
     BatchStore — 纯数据（images / results / displayOrder）
     BatchGrid  — 纯渲染（封装虚拟滚动 / 直接渲染）
     FilterBar  — 筛选栏 UI
     VirtualGrid — 虚拟滚动引擎
   app.js 仅负责：UI交互 · 事件串联 · 评分流程 · 导航 · 导出
   ============================================================ */

let slideIndex = 0;
let currentView = "drop";
let modelList = [];
let currentModelVersion = "v4.3";
let _batchScrollTop = 0;
let _gpuAvailable = false;
let _gpuEnabled = false;
let _gpuToggling = false;

// ====== 初始化 ======
window.addEventListener("pywebviewready", () => {
  setupDragDrop();
  initModelSelector();
  initGPU();
  FilterBar.init();
  BatchGrid.init(document.getElementById("batch-grid"));
  _wireStoreEvents();
});
window.addEventListener("DOMContentLoaded", () => {
  setupDragDrop();
  setupCanvasDragDrop();
  initModelSelector();
  initGPU();
  FilterBar.init();
  BatchGrid.init(document.getElementById("batch-grid"));
  _wireStoreEvents();
});

// ====== 事件串联：BatchStore → BatchGrid ======
function _wireStoreEvents() {
  // 逐项评分更新
  BatchStore.on("result-updated", ({ dataIdx, result }) => {
    BatchGrid.updateItem(dataIdx, result);
  });

  // 全部评分完成
  BatchStore.on("all-scored", ({ displayOrder }) => {
    FilterBar.show();
    FilterBar.showEmpty(displayOrder.length === 0);
    _showBatchActions();
    // 按默认排序刷新网格
    BatchGrid.refresh(
      displayOrder,
      (di) => BatchStore.allImages()[di],
      (di) => BatchStore.allResults()[di],
      (di) => openSlide(di),
      (di, fp) => loadThumbForItem(di, fp)
    );
  });

  // 筛选/排序变化 → 刷新网格
  BatchStore.on("filter-changed", ({ displayOrder }) => {
    const total = BatchStore.totalCount();
    FilterBar.showEmpty(total > 0 && displayOrder.length === 0);
    BatchGrid.refresh(
      displayOrder,
      (di) => BatchStore.allImages()[di],
      (di) => BatchStore.allResults()[di],
      (di) => openSlide(di),
      (di, fp) => loadThumbForItem(di, fp)
    );
  });
}

function _showBatchActions() {
  document.getElementById("batch-export-btn").style.display = "inline-block";
  document.getElementById("batch-save-btn").style.display = "inline-block";
}

// ====== 窗口控制 ======
function closeWindow() { window.pywebview.api.close(); }
function minimizeWindow() { window.pywebview.api.minimize(); }
function toggleMaximize() { window.pywebview.api.toggle_maximize(); }

// ====== 视图切换 ======
function showView(name) {
  currentView = name;
  document.getElementById("drop-zone").style.display       = (name === "drop")   ? "flex" : "none";
  document.getElementById("result-panel").style.display    = (name !== "drop" && name !== "batch") ? "flex" : "none";
  document.getElementById("batch-view").style.display      = (name === "batch")  ? "flex" : "none";

  const isSlide = (name === "slide");
  document.getElementById("nav-counter").style.display     = isSlide ? "inline" : "none";
  document.getElementById("nav-prev").style.display        = isSlide ? "inline" : "none";
  document.getElementById("nav-next").style.display        = isSlide ? "inline" : "none";
  document.getElementById("nav-hint").style.display        = isSlide ? "inline" : "none";
  document.getElementById("btn-back-batch").style.display  = isSlide ? "inline" : "none";
  document.getElementById("btn-back-drop").style.display   = isSlide ? "none"   : "inline";
}

function resetView() {
  BatchGrid.reset();
  BatchStore.reset();
  FilterBar.reset();
  document.getElementById("batch-progress").style.display = "none";
  document.getElementById("batch-export-btn").style.display = "none";
  document.getElementById("batch-save-btn").style.display = "none";
  showView("drop");
}

function backToBatch() {
  showView("batch");
  requestAnimationFrame(() => {
    const grid = document.getElementById("batch-grid");
    if (grid) grid.scrollTop = _batchScrollTop;
  });
}

// ====== 拖拽 ======
let _dragReady = false;
function setupDragDrop() {
  if (_dragReady) return;
  _dragReady = true;
  const dz = document.getElementById("drop-zone");
  if (!dz) return;
  dz.addEventListener("dragover", e => { e.preventDefault(); dz.classList.add("drag-over"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("drag-over"));
  dz.addEventListener("drop", e => {
    e.preventDefault(); dz.classList.remove("drag-over");
    handleDrop(e.dataTransfer.files);
  });
  dz.addEventListener("click", () => pickFiles());
}

function setupCanvasDragDrop() {
  const canvas = document.querySelector(".cinema-canvas");
  if (!canvas) return;
  canvas.addEventListener("dragover", e => { e.preventDefault(); canvas.classList.add("drag-over"); });
  canvas.addEventListener("dragleave", () => canvas.classList.remove("drag-over"));
  canvas.addEventListener("drop", e => {
    e.preventDefault(); canvas.classList.remove("drag-over");
    handleDrop(e.dataTransfer.files);
  });
}

function handleDrop(fileList) {
  const images = [];
  for (const f of fileList) { if (f.type.startsWith("image/")) images.push(f); }
  if (images.length === 0) return;
  if (images.length === 1) readFile(images[0], data => scoreSingle(data));
  else readFiles(images, imgs => startBatch(imgs));
}

function readFile(file, cb) {
  const r = new FileReader();
  r.onload = () => cb({ filename: file.name, data: r.result });
  r.readAsDataURL(file);
}

function readFiles(files, cb) {
  const promises = files.filter(f => f.type.startsWith("image/")).map(f =>
    new Promise(resolve => {
      const r = new FileReader();
      r.onload = () => resolve({ filename: f.name, data: r.result });
      r.readAsDataURL(f);
    })
  );
  Promise.all(promises).then(cb);
}

// ====== 模型切换 ======
async function initModelSelector() {
  try {
    const result = await window.pywebview.api.list_models();
    if (result?.models) { modelList = result.models; currentModelVersion = result.current.version; updateModelLabel(); }
  } catch (_) {}
}

function updateModelLabel() {
  const label = document.getElementById("model-label");
  if (!label) return;
  const info = modelList.find(m => m.version === currentModelVersion);
  label.textContent = info ? info.label : currentModelVersion;
}

async function cycleModel() {
  if (modelList.length === 0) { await initModelSelector(); if (modelList.length === 0) return; }
  const idx = modelList.findIndex(m => m.version === currentModelVersion);
  const next = modelList[(idx + 1) % modelList.length];
  try {
    const result = await window.pywebview.api.switch_model(next.version);
    if (result.error) return;
    currentModelVersion = next.version; updateModelLabel();
    const el = document.getElementById("score-model"); if (el) el.textContent = next.label;
  } catch (_) {}
}

// ====== GPU 加速 ======
async function initGPU() {
  const indicator = document.getElementById("gpu-indicator");
  const label = document.getElementById("gpu-label");
  if (!indicator || !label) return;
  try {
    const result = await window.pywebview.api.check_gpu_available();
    _gpuAvailable = !!result?.gpu_available;
    if (_gpuAvailable) {
      indicator.classList.add("tb-gpu-on");
      indicator.title = "GPU 加速（已开启）";
      label.textContent = "GPU";
      _gpuEnabled = true;
      window.pywebview.api.set_gpu_mode(true).catch(() => {});
    } else {
      indicator.classList.add("disabled");
      indicator.title = "GPU 不可用（无 CUDA）";
      label.textContent = "CPU";
      _gpuEnabled = false;
    }
  } catch (_) {
    indicator.classList.add("disabled");
    indicator.title = "GPU 不可用";
    label.textContent = "CPU";
    _gpuEnabled = false;
  }
}

async function toggleGPU() {
  if (!_gpuAvailable || _gpuToggling) return;
  _gpuToggling = true;
  _gpuEnabled = !_gpuEnabled;
  const indicator = document.getElementById("gpu-indicator");
  const label = document.getElementById("gpu-label");
  if (!indicator || !label) { _gpuToggling = false; return; }
  try {
    const result = await window.pywebview.api.set_gpu_mode(_gpuEnabled);
    _gpuEnabled = result?.gpu_enabled;
  } catch (_) {}
  if (_gpuEnabled) {
    indicator.classList.remove("tb-gpu-off");
    indicator.classList.add("tb-gpu-on");
    indicator.title = "GPU 加速（已开启）";
    label.textContent = "GPU";
  } else {
    indicator.classList.remove("tb-gpu-on");
    indicator.classList.add("tb-gpu-off");
    indicator.title = "GPU 加速（已关闭）";
    label.textContent = "CPU";
  }
  _gpuToggling = false;
}

// ====== 文件选择 ======
async function pickFiles() {
  const items = await window.pywebview.api.open_file_dialog();
  if (!items?.length) return;
  if (items.length === 1) scoreSinglePath(items[0]);
  else startBatchPath(items);
}

// ====== 单图评分 ======
async function scoreSingle(imageData) {
  showView("single");
  const imgEl = document.getElementById("result-image");
  const overlay = document.getElementById("loading-overlay");
  overlay.style.display = "flex"; imgEl.src = "";
  if (imageData.data) {
    await new Promise(r => { imgEl.onload = r; imgEl.onerror = r; imgEl.src = imageData.data; });
  }
  _resetSingleUI();
  let result;
  try { result = await window.pywebview.api.score_image(imageData.data); }
  catch (e) { result = { error: String(e) }; }
  overlay.style.display = "none";
  _showSingleResult(result, imageData.filename);
}

async function scoreSinglePath(item) {
  showView("single");
  const imgEl = document.getElementById("result-image");
  const overlay = document.getElementById("loading-overlay");
  overlay.style.display = "flex";
  const uri = await window.pywebview.api.get_image_data(item.filepath);
  imgEl.src = "";
  if (uri) { await new Promise(r => { imgEl.onload = r; imgEl.onerror = r; imgEl.src = uri; }); }
  _resetSingleUI();
  document.getElementById("score-filename").textContent = item.filename;
  let result;
  try { result = await window.pywebview.api.score_image_path(item.filepath); }
  catch (e) { result = { error: String(e) }; }
  overlay.style.display = "none";
  _showSingleResult(result, "");
}

function _resetSingleUI() {
  document.getElementById("score-number").textContent = "—";
  document.getElementById("score-tier").textContent = "";
  document.getElementById("score-bar-fill").style.width = "0%";
  document.getElementById("score-filename").textContent = "";
  document.getElementById("score-elapsed").textContent = "";
  document.getElementById("score-model").textContent = "";
}

function _showSingleResult(result, altFilename) {
  if (result.error) {
    document.getElementById("score-number").textContent = "!";
    const t = document.getElementById("score-tier");
    t.textContent = (result.error || "评分失败").substring(0, 50);
    t.setAttribute("data-tier", "较差");
    return;
  }
  animateScore(result.score);
  const tierEl = document.getElementById("score-tier");
  tierEl.textContent = result.tier; tierEl.setAttribute("data-tier", result.tier);
  setTimeout(() => {
    document.getElementById("score-bar-fill").style.width = `${(result.score/10)*100}%`;
    document.getElementById("score-bar-fill").setAttribute("data-tier", result.tier);
  }, 100);
  document.getElementById("score-elapsed").textContent = `${result.elapsed_ms} ms`;
  document.getElementById("score-model").textContent = result.model || currentModelVersion;
  if (altFilename) document.getElementById("score-filename").textContent = altFilename;
}

// ====== 图片数据已统一存盘，无需前端内存管理 ======

// ====== 批量模式（拖拽 base64 → 存盘 → filepath 统一流程） ======
async function startBatch(images) {
  showView("batch");

  const progressFill = document.getElementById("progress-bar-fill");
  const progressText = document.getElementById("progress-text");
  const progress = document.getElementById("batch-progress");
  progress.style.display = "flex";
  progressFill.style.width = "0%";
  progressText.textContent = `正在保存图片 · 0 / ${images.length}`;

  // 第1步：逐张存到临时磁盘文件（避免 base64 内存爆炸）
  const items = [];
  for (let i = 0; i < images.length; i++) {
    const filepath = await window.pywebview.api.save_temp_image(images[i].data, images[i].filename);
    if (filepath) {
      items.push({ filename: images[i].filename, filepath });
    } else {
      items.push({ filename: images[i].filename, filepath: null });
    }
    progressText.textContent = `正在保存图片 · ${i + 1} / ${images.length}`;
    progressFill.style.width = `${((i + 1) / images.length) * 50}%`; // 保存占 50% 进度
  }

  // 第2步：统一走 filepath 批量评分（后 50% 进度）
  _runBatchScore(items, progressFill, progressText, progress, 50);
}

// ====== 批量模式（文件路径） ======
async function startBatchPath(items) {
  showView("batch");

  const progressFill = document.getElementById("progress-bar-fill");
  const progressText = document.getElementById("progress-text");
  const progress = document.getElementById("batch-progress");
  progress.style.display = "flex";
  progressFill.style.width = "0%";
  progressText.textContent = `准备评分 · 0 / ${items.length}`;

  _runBatchScore(items, progressFill, progressText, progress);
}

/** 统一批量评分（所有图片均有 filepath） */
async function _runBatchScore(items, progressFill, progressText, progressEl, progressBase) {
  const images = items.map(it => ({ filename: it.filename, filepath: it.filepath }));
  BatchStore.load(images);
  _renderInitialGrid();

  let scored = 0;
  const total = items.length;
  const base = typeof progressBase === "number" ? progressBase : 0;
  const scale = 100 - base;

  // 注册实时进度回调（Python 每评完一张就推送）
  window.__onBatchProgress = (i, _total, result) => {
    scored++;
    BatchStore.updateResult(i, result);
    const pct = base + Math.round((scored / total) * scale);
    progressFill.style.width = `${pct}%`;
    progressText.textContent = `评分中 · ${scored} / ${total}`;
  };

  try {
    const filepaths = items.map(it => it.filepath);
    await window.pywebview.api.score_batch_paths(JSON.stringify(filepaths));
  } catch (e) {
    progressText.textContent = `错误: ${e.message || e}`;
    return;
  } finally {
    delete window.__onBatchProgress;
  }

  progressFill.style.width = "100%";
  const ok = BatchStore.allResults().filter(r => r && !r.error).length;
  progressText.textContent = `完成 · ${ok} / ${total}`;
  setTimeout(() => { progressEl.style.display = "none"; }, 1200);
  BatchStore.finishAll();
}

// ====== 初始网格渲染 ======
function _renderInitialGrid() {
  const images = BatchStore.allImages();
  // 初始阶段无排序无筛选，displayOrder = 所有已评分项的原始顺序
  // 但此时还没评分，所以用一个虚拟的 order（先渲染 all images，评分后自动更新）
  // 直接以原始顺序渲染（index = data index）
  const order = images.map((_, i) => i); // 原始顺序占位
  BatchGrid.render(
    order,
    (di) => BatchStore.allImages()[di],
    (di) => BatchStore.allResults()[di],
    (di) => openSlide(di),
    (di, fp) => loadThumbForItem(di, fp)
  );
}

// ====== 缩略图加载 ======
function loadThumbForItem(dataIdx, filepath) {
  // 请求 360px retina 缩略图（网格项 180px × 2x）
  window.pywebview.api.get_thumbnail(filepath, 360).then(uri => {
    if (!uri) return;
    // 缓存缩略图，虚拟滚动重建时直接使用
    BatchGrid.cacheThumb(dataIdx, uri);
    const el = BatchGrid.getItem(dataIdx);
    if (el) {
      const img = el.querySelector("img");
      if (img && !img.src) img.src = uri;
    }
  }).catch(() => {});
}

// ====== 幻灯片（批量翻页） ======
function openSlide(dataIdx) {
  const results = BatchStore.allResults();
  const images = BatchStore.allImages();
  if (dataIdx < 0 || dataIdx >= results.length) return;

  const grid = document.getElementById("batch-grid");
  if (grid) _batchScrollTop = grid.scrollTop;

  slideIndex = dataIdx;
  const result = results[dataIdx];
  const img = images[dataIdx];

  const imgEl = document.getElementById("result-image");
  const overlay = document.getElementById("loading-overlay");

  if (img?.filepath) {
    overlay.style.display = "flex"; imgEl.src = "";
    window.pywebview.api.get_image_data(img.filepath).then(uri => {
      imgEl.src = uri || ""; overlay.style.display = "none";
    }).catch(() => { overlay.style.display = "none"; });
  } else {
    imgEl.src = BatchGrid.getThumbSrc(dataIdx);
  }

  document.getElementById("score-filename").textContent = img?.filename || "";
  if (result && !result.error) {
    document.getElementById("score-number").textContent = parseFloat(result.score).toFixed(1);
    const t = document.getElementById("score-tier");
    t.textContent = result.tier || ""; t.setAttribute("data-tier", result.tier || "");
    document.getElementById("score-bar-fill").style.width = `${(parseFloat(result.score||0)/10)*100}%`;
    document.getElementById("score-bar-fill").setAttribute("data-tier", result.tier || "");
    document.getElementById("score-elapsed").textContent = `${result.elapsed_ms} ms`;
    document.getElementById("score-model").textContent = result.model || currentModelVersion;
  } else {
    document.getElementById("score-number").textContent = "!";
    const t = document.getElementById("score-tier");
    t.textContent = result?.error ? result.error.substring(0, 30) : "评分失败";
    t.setAttribute("data-tier", "较差");
    document.getElementById("score-bar-fill").style.width = "0%";
    document.getElementById("score-elapsed").textContent = "";
  }

  const order = BatchStore.displayOrder();
  const pos = order.indexOf(dataIdx);
  document.getElementById("nav-counter").textContent = `${pos + 1}/${order.length}`;
  document.getElementById("nav-prev").disabled = (pos <= 0);
  document.getElementById("nav-next").disabled = (pos >= order.length - 1);

  showView("slide");
}

function navSlide(delta) {
  const order = BatchStore.displayOrder();
  const pos = order.indexOf(slideIndex);
  if (pos < 0) return;
  const next = pos + delta;
  if (next >= 0 && next < order.length) openSlide(order[next]);
}

// ====== 动画 ======
function animateScore(target) {
  const el = document.getElementById("score-number");
  const duration = 1200;
  const start = performance.now();
  el.classList.add("score-animated");
  function tick(now) {
    const p = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - p, 3);
    el.textContent = (target * eased).toFixed(1);
    if (p < 1) requestAnimationFrame(tick);
    else el.textContent = target.toFixed(1);
  }
  requestAnimationFrame(tick);
}

// ====== 键盘 ======
document.addEventListener("keydown", e => {
  if (currentView === "slide") {
    if (e.key === "Escape") { backToBatch(); return; }
    if (e.key === "ArrowLeft") { navSlide(-1); return; }
    if (e.key === "ArrowRight") { navSlide(1); return; }
  }
  if (e.key === "Escape" && currentView !== "drop") {
    if (currentView === "batch" || currentView === "single") resetView();
  }
});

// ====== 导出 ======
async function exportBatch(format) {
  const order = BatchStore.displayOrder();
  const results = BatchStore.allResults();
  const valid = order.map(i => results[i]).filter(r => r && !r.error);
  if (valid.length === 0) return;
  const json = JSON.stringify(valid);
  const out = await window.pywebview.api.export_results(json, format || "csv");
  if (out.path) alert(`已导出到: ${out.path}`);
  else if (out.error) alert(`导出失败: ${out.error}`);
}

// ====== 另存图片 ======
async function saveImagesToFolder() {
  const order = BatchStore.displayOrder();
  if (order.length === 0) return;
  const dest = await window.pywebview.api.pick_save_folder();
  if (!dest?.folder) return;

  const images = BatchStore.allImages();
  const list = order.map(i => ({
    filename: images[i].filename,
    filepath: images[i].filepath || null,
    data: images[i].data || null,
  }));
  const out = await window.pywebview.api.save_images_to_folder(JSON.stringify(list), dest.folder);
  if (out.error) alert(`保存失败: ${out.error}`);
  else alert(`已保存 ${out.count} 张图片到 ${out.folder}`);
}

// ====== 关于 ======
function showAbout() { document.getElementById("about-modal").style.display = "flex"; }
function closeAbout() { document.getElementById("about-modal").style.display = "none"; }
