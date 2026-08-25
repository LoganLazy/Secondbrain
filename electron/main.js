const { app, BrowserWindow } = require("electron")
const { spawn } = require("child_process")
const path = require("path")
const http = require("http")

const PORT = 8787

function startBackend() {
  const backendDir = path.join(__dirname, "..", "backend")
  const py = path.join(backendDir, ".venv", "bin", "python")
  try {
    spawn(py, ["start_daemon.py"], { cwd: backendDir, stdio: "ignore" }).unref()
  } catch (e) {
    console.error("后端启动失败:", e)
  }
}

function waitBackend(cb, tries = 30) {
  const req = http.get(`http://127.0.0.1:${PORT}/api/stats`, (res) => {
    res.resume()
    cb()
  })
  req.on("error", () => {
    if (tries-- <= 0) {
      cb()
      return
    }
    setTimeout(() => waitBackend(cb, tries), 800)
  })
  req.setTimeout(1500, () => {
    req.destroy()
  })
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1300,
    height: 850,
    title: "Memory AI",
    autoHideMenuBar: true,
    backgroundColor: "#0f1115",
    webPreferences: { contextIsolation: true }
  })
  win.loadURL(`http://127.0.0.1:${PORT}`)
}

app.whenReady().then(() => {
  startBackend()
  waitBackend(createWindow)
})

app.on("window-all-closed", () => app.quit())
