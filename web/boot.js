'use strict';
// Browser compatibility wrapper only. Rich4.exe and its data remain byte-for-byte original.
const ui = id => document.getElementById(id);
let resourceManifest;
let runtimeStarted = false;
let syncBusy = false;
function fail(message) {
  ui('status').textContent = message;
  ui('status').classList.add('error');
  ui('detail').textContent = '游戏尚未启动。请完成兼容包准备与运行验证后再发布。';
  ui('launch').disabled = true;
  ui('progress').hidden = true;
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
async function loadChunks(item, label) {
  const result = new Uint8Array(item.size);
  let offset = 0;
  for (const chunk of item.chunks) {
    ui('status').textContent = '正在加载' + label;
    const response = await fetch(chunk.url);
    if (!response.ok) throw new Error(label + '下载失败（' + response.status + '）');
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.length !== chunk.size || await digest(bytes) !== chunk.sha256) throw new Error(label + '文件校验失败');
    result.set(bytes, offset); offset += bytes.length;
    ui('progress').hidden = false;
    ui('progress').value = 100 * offset / item.size;
    await new Promise(resolve => setTimeout(resolve, 0));
  }
  if (offset !== item.size || await digest(result) !== item.sha256) throw new Error(label + '整体校验失败');
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
  if (runtimeStarted) return;
  ui('launch').disabled = true;
  try {
    const files = { 'rich4.zip': await loadChunks(resourceManifest.game,'原版游戏'),
                    'boxedwine.zip': await loadChunks(resourceManifest.runtime,'兼容环境') };
    await script('boxedwine-shell.js');
    // Keep the upstream shell API and the original program. Only resource delivery changes.
    Config.urlParams = 'app=rich4&p=Rich4.exe&resolution=800x600&bpp=16&disableHideCursor=true&env=%22LANG:zh_TW.UTF-8%22';
    Config.storageMode = STORAGE_INDEXED_DB;
    Config.persist_d_drive = true;
    loadFile = function(prefix, filename, callback) {
      if (!files[filename]) { fail('兼容环境请求了未知文件：' + filename); return; }
      callback(files[filename]);
    };
    Module.locateFile = name => 'runtime/' + name;
    const originalPrint = Module.print;
    Module.print = function(...args) { originalPrint(...args); };
    Module.printErr = function(...args) {
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
fetch('resources.json').then(response => {
  if (!response.ok) throw new Error('原版资源清单尚未生成');
  return response.json();
}).then(manifest => {
  resourceManifest = manifest;
  if (!manifest.runtime) { fail('兼容运行包尚未下载，当前不能启动游戏'); return; }
  ui('status').textContent = '兼容运行包已准备，游戏兼容性尚未验证';
  ui('detail').textContent = '首次启动需要加载原版资源；请等待文件校验完成。';
  ui('launch').disabled = false;
}).catch(error => fail(error.message));
