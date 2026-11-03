'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('als', {
  ready: () => ipcRenderer.invoke('backend:ready'),
  call: (cmd, args) => ipcRenderer.invoke('backend:call', cmd, args),
  log: () => ipcRenderer.invoke('backend:log'),
  readText: (rel) => ipcRenderer.invoke('fs:readText', rel),
  pickInput: () => ipcRenderer.invoke('dialog:pickInput'),
  saveAs: (rel) => ipcRenderer.invoke('fs:saveAs', rel),
  pickExport: (name) => ipcRenderer.invoke('dialog:pickExport', name),
  pickImport: () => ipcRenderer.invoke('dialog:pickImport'),
  openPath: (rel) => ipcRenderer.invoke('shell:openPath', rel),
  onBackendExit: (fn) => ipcRenderer.on('backend-exit', (_e, code) => fn(code)),
});
