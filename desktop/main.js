// AI Lighting Studio — Electron main process.
// Встроенный Python (Windows: resources/python/python.exe, embeddable 3.13) запускает
// `python -m app` (stdio JSON-мост к оркестратору). Никакого HTTP/localhost.
'use strict';
const { app, BrowserWindow, ipcMain, dialog, shell, protocol, net, Menu } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const readline = require('readline');
const { pathToFileURL } = require('url');

protocol.registerSchemesAsPrivileged([
  { scheme: 'als', privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true } },
]);

let win = null;
let py = null;
let dataDir = null;
let reqId = 0;
const pending = new Map();
let readyResolve;
const backendReady = new Promise((r) => { readyResolve = r; });
const backendLog = [];

function backendSpec() {
  if (app.isPackaged) {
    const res = process.resourcesPath;
    const pyExe = process.platform === 'win32'
      ? path.join(res, 'python', 'python.exe')
      : (process.env.ALS_PYTHON || 'python3');
    const userData = app.getPath('userData');
    return {
      cmd: pyExe,
      cwd: path.join(res, 'als'),
      env: {
        ALS_DATA_DIR: process.env.ALS_DATA_DIR || path.join(userData, 'data'),
        MPLCONFIGDIR: path.join(userData, 'mpl'),
      },
    };
  }
  // dev: ../.venv (Linux) или ../.venv/Scripts/python.exe (Windows)
  const root = path.resolve(__dirname, '..');
  const venvPy = process.platform === 'win32'
    ? path.join(root, '.venv', 'Scripts', 'python.exe')
    : path.join(root, '.venv', 'bin', 'python');
  const env = {};
  if (process.env.ALS_DATA_DIR) env.ALS_DATA_DIR = process.env.ALS_DATA_DIR;
  return { cmd: process.env.ALS_PYTHON || venvPy, cwd: root, env };
}

function startBackend() {
  const spec = backendSpec();
  if (spec.env.MPLCONFIGDIR) fs.mkdirSync(spec.env.MPLCONFIGDIR, { recursive: true });
  py = spawn(spec.cmd, ['-u', '-m', 'app'], {
    cwd: spec.cwd,
    env: { ...process.env, ...spec.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', PYTHONDONTWRITEBYTECODE: '1', MPLBACKEND: 'Agg' },
    windowsHide: true,
  });
  readline.createInterface({ input: py.stdout }).on('line', (line) => {
    let msg;
    try { msg = JSON.parse(line); } catch { return; }
    if (msg.event === 'ready') { dataDir = msg.info.data_dir; readyResolve(msg.info); return; }
    const p = pending.get(msg.id);
    if (!p) return;
    pending.delete(msg.id);
    msg.ok ? p.resolve(msg.result) : p.reject(new Error(msg.error));
  });
  py.stderr.on('data', (d) => {
    const s = d.toString();
    backendLog.push(s);
    if (backendLog.length > 400) backendLog.shift();
    if (process.env.ALS_DEBUG) process.stderr.write('[py] ' + s);
  });
  py.on('exit', (code) => {
    for (const p of pending.values()) p.reject(new Error('backend exited ' + code));
    pending.clear();
    readyResolve({ error: 'backend exited ' + code, log: backendLog.join('') });
    if (win && !win.isDestroyed()) win.webContents.send('backend-exit', code);
  });
  py.on('error', (e) => {
    backendLog.push(String(e));
    readyResolve({ error: String(e) });
  });
}

function call(cmd, args = {}) {
  return new Promise((resolve, reject) => {
    if (!py || py.exitCode !== null) return reject(new Error('backend not running'));
    const id = ++reqId;
    pending.set(id, { resolve, reject });
    py.stdin.write(JSON.stringify({ id, cmd, args }) + '\n');
  });
}

function safeDataPath(rel) {
  const abs = path.resolve(dataDir, rel);
  const base = path.resolve(dataDir);
  if (abs !== base && !abs.startsWith(base + path.sep)) throw new Error('path outside data dir');
  return abs;
}

function createWindow() {
  win = new BrowserWindow({
    width: 1480, height: 920, minWidth: 1100, minHeight: 700,
    title: 'AI Lighting Studio',
    backgroundColor: '#0f0e0c',
    icon: path.join(__dirname, 'build', 'icon.png'),
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: true,
    },
  });
  Menu.setApplicationMenu(null);
  win.on('page-title-updated', (e) => e.preventDefault());
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (e) => e.preventDefault());
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  win.once('ready-to-show', () => win.show());
}

ipcMain.handle('backend:ready', () => backendReady);
ipcMain.handle('backend:call', (_e, cmd, args) => call(cmd, args));
ipcMain.handle('backend:log', () => backendLog.join(''));
ipcMain.handle('fs:readText', (_e, rel) => fs.readFileSync(safeDataPath(rel), 'utf-8'));
ipcMain.handle('dialog:pickInput', async () => {
  const r = await dialog.showOpenDialog(win, {
    title: 'Фото / PDF / видео для инженерии',
    properties: ['openFile'],
    filters: [{ name: 'Фото, PDF, видео', extensions: ['png', 'jpg', 'jpeg', 'webp', 'bmp', 'pdf', 'mp4', 'mov', 'avi', 'mkv', 'webm'] }],
  });
  return r.canceled ? null : r.filePaths[0];
});
ipcMain.handle('fs:saveAs', async (_e, rel) => {
  const src = safeDataPath(rel);
  const r = await dialog.showSaveDialog(win, { defaultPath: path.basename(src) });
  if (r.canceled || !r.filePath) return null;
  fs.copyFileSync(src, r.filePath);
  return r.filePath;
});
ipcMain.handle('dialog:pickExport', async (_e, name) => {
  const safe = String(name || 'project').replace(/[\\/:*?"<>|]+/g, '_').slice(0, 60);
  const r = await dialog.showSaveDialog(win, { title: 'Экспорт проекта', defaultPath: safe + '.alsproj', filters: [{ name: 'AI Lighting Studio project', extensions: ['alsproj'] }] });
  return r.canceled || !r.filePath ? null : r.filePath;
});
ipcMain.handle('dialog:pickImport', async () => {
  const r = await dialog.showOpenDialog(win, { title: 'Импорт проекта', properties: ['openFile'], filters: [{ name: 'AI Lighting Studio project', extensions: ['alsproj'] }] });
  return r.canceled ? null : r.filePaths[0];
});
ipcMain.handle('shell:openPath', (_e, rel) => shell.openPath(safeDataPath(rel)));

async function screenshotMode(outDir) {
  // ALS_SCREENSHOTS=<dir>: снять вкладки и выйти (для CI / проверки сборки)
  fs.mkdirSync(outDir, { recursive: true });
  const wc = win.webContents;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  await new Promise((r) => (wc.isLoading() ? wc.once('did-finish-load', r) : r()));
  await wc.executeJavaScript('window.__alsReady');
  let pid = process.env.ALS_SCREEN_PROJECT || '';
  if (process.env.ALS_SCREEN_CREATE) {
    // создать демо-проект через тот же бэкенд и дождаться done
    const r = await call('create_project', { goal: process.env.ALS_SCREEN_CREATE, pipeline: 'week4', autonomy: 'full_auto' });
    pid = r.id;
    const fin = await call('wait', { id: pid, timeout: 300 });
    console.log(`[screens] project=${pid} status=${fin.status} tasks=${fin.tasks.length}`);
  }
  if (pid) await wc.executeJavaScript(`window.__als.selectProject(${JSON.stringify(pid)})`);
  await wait(1500);
  const tabs = (process.env.ALS_SCREEN_TABS || 'overview,design,3d,engineering,viz,catalog,sales,autonomy').split(',');
  const prefix = process.env.ALS_SCREEN_PREFIX || '';
  for (const t of tabs) {
    // "versions@diff:1:2" — перед снимком показать сравнение v1↔v2
    const [tab, extra] = t.split('@');
    if (extra && extra.startsWith('diff:')) {
      const [, a, b] = extra.split(':');
      await wc.executeJavaScript(`window.__als.diff(${Number(a)}, ${Number(b)})`);
    }
    await wc.executeJavaScript(`window.__als.showTab(${JSON.stringify(tab)})`);
    await wait(tab === '3d' ? 3500 : 1200);
    const img = await wc.capturePage();
    fs.writeFileSync(path.join(outDir, `${prefix}${tab}${extra ? '_' + extra.replace(/[^a-z0-9]+/gi, '') : ''}.png`), img.toPNG());
  }
  app.quit();
}

app.whenReady().then(() => {
  protocol.handle('als', (req) => {
    // als://data/<rel path> → файл в каталоге данных
    const u = new URL(req.url);
    const rel = decodeURIComponent(u.pathname.replace(/^\/+/, ''));
    try {
      return net.fetch(pathToFileURL(safeDataPath(rel)).toString());
    } catch (e) {
      return new Response('forbidden', { status: 403 });
    }
  });
  startBackend();
  createWindow();
  if (process.env.ALS_SCREENSHOTS) screenshotMode(process.env.ALS_SCREENSHOTS).catch((e) => { console.error(e); app.exit(2); });
});

app.on('window-all-closed', () => app.quit());
app.on('before-quit', () => { try { py && py.kill(); } catch { /* ignore */ } });
