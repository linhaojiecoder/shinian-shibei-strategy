const { app, BrowserWindow, ipcMain, shell } = require('electron');
const fs = require('fs');
const path = require('path');
const { execFile } = require('child_process');

app.setName('慢富十倍·Codex V1');
app.setPath('userData', path.join(app.getPath('appData'), 'manfu-codex-v1'));
let busy = false;
function run(mode) {
  if (busy) return Promise.reject(new Error('已有更新任务正在运行'));
  busy = true;
  return new Promise((resolve, reject) => {
    execFile('/usr/bin/python3', [path.join(__dirname, 'refresh.py'), app.getPath('userData'), mode],
      { timeout: 180000, maxBuffer: 1024 * 1024 }, (error, stdout, stderr) => {
        busy = false;
        if (error) return reject(new Error('更新失败，已保留原数据。请检查网络和 Python 环境。\n' + (stderr || error.message).slice(-1000)));
        try { resolve(JSON.parse(fs.readFileSync(path.join(app.getPath('userData'), 'snapshot.json'), 'utf8'))); }
        catch (err) { reject(new Error('无法读取回测结果：' + err.message)); }
      });
  });
}
ipcMain.handle('snapshot', async () => run('cached'));
ipcMain.handle('refresh', async () => run('refresh'));
app.whenReady().then(() => {
  const win = new BrowserWindow({ width: 1180, height: 820, minWidth: 800, minHeight: 600,
    title: '慢富十倍·Codex V1', backgroundColor: '#0f1621',
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true } });
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', e => e.preventDefault());
  win.loadFile(path.join(__dirname, 'index.html'));
});
app.on('window-all-closed', () => app.quit());
