const { app, BrowserWindow } = require("electron")
const { spawn } = require("child_process")
const path = require("path")
const http = require("http")

const PORT = 8787
let backendProc = null
let win = null

// 便携模式: 数据/知识库文件夹 放在 exe 同级目录
function homeDir() {
  try {
    const dir = path.dirname(app.getPath("exe"))
    require("fs").accessSync(dir, require("fs").constants.W_OK)
    return dir
  } catch (e) {
    return app.getPath("userData") // 无写权限时退回用户数据目录
  }
}

function startBackend() {
  // 打包版: resources/backend/NebulaMemory-backend.exe
  const res = process.resourcesPath || path.join(__dirname, "resources")
  const candidates = [
    path.join(res, "backend", "NebulaMemory-backend.exe"),
    path.join(__dirname, "..", "server", "NebulaMemory-backend.exe"),
    // 兼容旧版开发构建
    path.join(res, "backend", "SecondBrain-backend", "SecondBrain-backend.exe"),
  ]
  const exe = candidates.find((p) => {
    try { return require("fs").existsSync(p) } catch (e) { return false }
  })
  if (!exe) {
    console.log("[NebulaMemory] 未找到后端引擎, 若服务已手动启动可直接使用")
    return
  }
  backendProc = spawn(exe, [], {
    cwd: homeDir(),
    env: { ...process.env, NEBULA_MEMORY_HOME: homeDir(), MEMORY_AI_HOME: homeDir() },
    stdio: "ignore",
    windowsHide: true,
  })
}

function waitServer(cb, tries = 60) {
  const req = http.get(`http://127.0.0.1:${PORT}/api/stats`, (res) => {
    res.resume()
    cb()
  })
  req.on("error", () => {
    if (tries-- <= 0) return cb()
    setTimeout(() => waitServer(cb, tries), 800)
  })
  req.setTimeout(1500, () => req.destroy())
}

function createWindow() {
  win = new BrowserWindow({
    width: 1320,
    height: 860,
    title: "Nebula Memory",
    autoHideMenuBar: true,
    backgroundColor: "#0f1115",
    webPreferences: { contextIsolation: true },
  })
  win.loadURL(`http://127.0.0.1:${PORT}`)
  win.on("closed", () => (win = null))
}

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on("second-instance", () => {
    if (win) {
      if (win.isMinimized()) win.restore()
      win.focus()
    }
  })

  app.whenReady().then(() => {
    startBackend()
    waitServer(createWindow)
  })

  app.on("window-all-closed", () => {
    if (backendProc) {
      try { backendProc.kill() } catch (e) {}
    }
    app.quit()
  })
}
