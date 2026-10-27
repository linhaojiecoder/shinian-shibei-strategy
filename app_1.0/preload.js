// preload：安全桥接主进程与渲染进程
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('strategyAPI', {
  getSignal: () => ipcRenderer.invoke('get-signal'),
  getData: () => ipcRenderer.invoke('get-data'),
  refresh: () => ipcRenderer.invoke('refresh'),
  updateHoldings: (payload) => ipcRenderer.invoke('update-holdings', payload),
  resetState: (capital) => ipcRenderer.invoke('reset-state', capital),
  onSignalUpdate: (cb) => ipcRenderer.on('signal-update', (e, data) => cb(data)),
});
