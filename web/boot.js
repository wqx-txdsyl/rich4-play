'use strict';
// Browser compatibility wrapper only. Rich4.exe and its data remain byte-for-byte original.
const ui = id => document.getElementById(id);
let resourceManifest;
let runtimeStarted = false;
let runtimeBooted = false;
let syncBusy = false;
function fail(message) {
  ui('status').textContent = message;
  ui('status').classList.add('error');
  ui('detail').textContent = runtimeBooted ? '运行环境启动失败，请重新加载页面。' : '已校验的资源保存在本机，点击继续即可接着加载。';
  ui('launch').textContent = runtimeBooted ? '重新加载' : '继续加载';
  ui('launch').disabled = false;
  runtimeStarted = false;
  document.body.classList.remove('running');
  ui('canvas').classList.remove('visible');
  ui('toolbar').hidden = true;
}
function script(src) {
  return new Promise((resolve, reject) => {
    const element = document.createElement('script');
    element.src = src; element.onload = resolve;
    element.onerror = () => reject(new Error('无法加载兼容运行组件：' + src));
    document.body.append(element);
  });
}
async function digest(bytes) {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), v => v.toString(16).padStart(2, '0')).join('');
}
async function fetchVerifiedChunk(chunk, label) {
  let lastError;
  for (let attempt = 0; attempt < 5; attempt++) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 45000);
    try {
      const resourceUrl = new URL(chunk.url, location.href);
      resourceUrl.searchParams.set('sha256', chunk.sha256);
      const response = await fetch(resourceUrl, {signal:controller.signal});
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (bytes.length !== chunk.size || await digest(bytes) !== chunk.sha256) throw new Error('文件校验未通过');
      return bytes;
    } catch(error) {
      lastError = error;
      ui('detail').textContent = '正在重试资源下载（' + (attempt + 1) + '/5），已完成的部分会保留。';
      if (attempt < 4) await new Promise(resolve => setTimeout(resolve, 800 * (attempt + 1)));
    } finally { clearTimeout(timeout); }
  }
  throw new Error(label + '下载中断：' + chunk.url + '（' + lastError.message + '）');
}
async function loadChunks(item, label) {
  const result = new Uint8Array(item.size);
  let cache;
  try { cache = await caches.open('rich4-verified-assets-v1'); } catch(error) { console.warn(error); }
  let completed = 0;
  let next = 0;
  let offset = 0;
  const chunks = item.chunks.map(chunk => {
    const entry = {...chunk, offset}; offset += chunk.size; return entry;
  });
  const worker = async () => {
    while (next < chunks.length) {
      const chunk = chunks[next++];
      const cacheKey = new URL(chunk.url, location.href);
      cacheKey.searchParams.set('sha256',chunk.sha256);
      let cached;
      try { cached = await cache?.match(cacheKey); } catch(error) { console.warn(error); }
      let bytes;
      if (cached) {
        bytes = new Uint8Array(await cached.arrayBuffer());
        if (bytes.length !== chunk.size || await digest(bytes) !== chunk.sha256) bytes = undefined;
      }
      if (!bytes) {
        bytes = await fetchVerifiedChunk(chunk, label);
        try { await cache?.put(cacheKey, new Response(bytes)); } catch(error) { console.warn(error); }
      }
      result.set(bytes, chunk.offset);
      completed += bytes.length;
      ui('status').textContent = '正在加载' + label + ' · ' + Math.round(completed / 1048576) + ' / ' + Math.round(item.size / 1048576) + ' MB';
      ui('progress').hidden = false;
      ui('progress').value = 100 * completed / item.size;
      await new Promise(resolve => setTimeout(resolve, 0));
    }
  };
  await Promise.all(Array.from({length:Math.min(6,chunks.length)},worker));
  if (completed !== item.size || offset !== item.size || await digest(result) !== item.sha256) throw new Error(label + '整体校验失败');
  return result;
}
function getSaves() {
  const result = [];
  const walk = path => {
    if (!FS.analyzePath(path).exists) return;
    for (const name of FS.readdir(path)) {
      if (name === '.' || name === '..') continue;
      const child = path + '/' + name;
      const node = FS.lookupPath(child, {follow:false}).node;
      if (FS.isLink(node.mode)) continue;
      if (FS.isDir(node.mode)) walk(child);
      else if (/^(save\d+\.dat|rich4\.cfg)$/i.test(name)) {
        const bytes = FS.readFile(child);
        result.push({path:child,data:Array.from(bytes)});
      }
    }
  };
  walk('/root'); walk('/d_drive');
  return result;
}
function syncSaves() {
  if (!runtimeStarted || syncBusy || typeof FS === 'undefined') return;
  syncBusy = true;
  FS.syncfs(false, error => {
    syncBusy = false;
    ui('save-status').textContent = error ? '保存到浏览器失败，请导出存档' : '浏览器存储已同步';
  });
}
ui('fullscreen').onclick = () => ui('canvas').requestFullscreen().catch(error => { ui('save-status').textContent = error.message; });
ui('logs').onclick = () => { ui('output').hidden = !ui('output').hidden; };
ui('export').onclick = () => {
  try {
    const files = getSaves();
    if (!files.length) throw new Error('请先在原版游戏内保存进度');
    const blob = new Blob([JSON.stringify({format:'rich4-saves-v1', files})], {type:'application/json'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href = url; link.download = 'rich4-saves.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  } catch(error) { ui('save-status').textContent = error.message; }
};
ui('import').onchange = async event => {
  try {
    const file = event.target.files[0]; if (!file) return;
    if (file.size > 8 * 1024 * 1024) throw new Error('存档备份不能超过 8 MB');
    const data = JSON.parse(await file.text());
    if (data.format !== 'rich4-saves-v1' || !Array.isArray(data.files) || data.files.length > 64) throw new Error('存档格式不正确');
    const files = data.files.map(item => {
      if (!/^\/(root|d_drive)\/(?:[a-zA-Z0-9_.():-]+\/)*(?:save\d+\.dat|rich4\.cfg)$/i.test(item.path) || item.path.includes('..') ||
          !Array.isArray(item.data) || item.data.length > 1024 * 1024 || item.data.some(v => !Number.isInteger(v) || v < 0 || v > 255)) throw new Error('存档内容不正确');
      return item;
    });
    for (const item of files) {
      FS.mkdirTree(item.path.slice(0,item.path.lastIndexOf('/')));
      FS.writeFile(item.path, Uint8Array.from(item.data));
    }
    syncSaves();
    ui('save-status').textContent = '已导入，请在原版游戏中读取存档';
  } catch(error) { ui('save-status').textContent = error.message; }
  event.target.value = '';
};
ui('launch').onclick = async () => {
  if (runtimeBooted) { location.reload(); return; }
  if (runtimeStarted) return;
  ui('status').classList.remove('error');
  ui('status').textContent = '正在加载已缓存的资源';
  ui('launch').disabled = true;
  try {
    Rich4Midi.unlock();
    const files = { 'rich4.zip': await loadChunks(resourceManifest.game,'原版游戏'),
                    'boxedwine.zip': await loadChunks(resourceManifest.runtime,'兼容环境') };
    runtimeBooted = true;
    await script('boxedwine-shell.js');
    // Keep the upstream shell API and the original program. Only resource delivery changes.
    Config.urlParams = 'app=rich4&p=Rich4.exe&resolution=800x600&bpp=16&disableHideCursor=true';
    Config.storageMode = STORAGE_INDEXED_DB;
    Config.persist_d_drive = true;
    const upstreamParams = getEmulatorParams;
    getEmulatorParams = function() {
      return ['-env','LANG=zh_TW.UTF-8','-env','WINEDEBUG=+winmm', ...upstreamParams()];
    };
    loadFile = function(prefix, filename, callback) {
      if (!files[filename]) { fail('兼容环境请求了未知文件：' + filename); return; }
      callback(files[filename]);
    };
    Module.locateFile = name => 'runtime/' + name;
    const originalPrint = Module.print;
    Module.print = function(...args) {
      if (!Rich4Midi.onLog(args.join(' '))) originalPrint(...args);
    };
    Module.printErr = function(...args) {
      if (Rich4Midi.onLog(args.join(' '))) return;
      console.error(...args);
      ui('output').value += args.join(' ') + '\n';
    };
    Module.onAbort = reason => fail('兼容环境停止：' + String(reason));
    Module.postRun.push(() => { ui('save-status').textContent = '原版程序已退出'; syncSaves(); });
    await script('runtime/boxedwine.js');
    runtimeStarted = true;
    ui('canvas').classList.add('visible');
    document.body.classList.add('running');
    ui('toolbar').hidden = false;
    ui('canvas').focus();
    setInterval(syncSaves, 5000);
  } catch(error) { fail(error.message); }
};
window.addEventListener('beforeunload', event => {
  if (runtimeStarted) { syncSaves(); event.preventDefault(); event.returnValue = ''; }
});
document.addEventListener('visibilitychange', () => { if (document.hidden) syncSaves(); });
fetch('resources.json', {cache:'no-store'}).then(response => {
  if (!response.ok) throw new Error('原版资源清单尚未生成');
  return response.json();
}).then(manifest => {
  resourceManifest = manifest;
  if (!manifest.runtime) { fail('兼容运行包尚未下载，当前不能启动游戏'); return; }
  ui('status').textContent = '兼容运行包已准备，游戏兼容性尚未验证';
  ui('detail').textContent = '首次启动需要加载原版资源；请等待文件校验完成。';
  ui('launch').disabled = false;
}).catch(error => fail(error.message));
