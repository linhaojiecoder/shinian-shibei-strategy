const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('strategy', {
  snapshot: () => ipcRenderer.invoke('snapshot'),
  refresh: () => ipcRenderer.invoke('refresh')
});
