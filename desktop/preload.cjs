// What the web UI can ask of the desktop app. It sees only this, not Node or Electron.

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("zwansDesktop", {
  pickFolder: () => ipcRenderer.invoke("pick-folder"),
});
