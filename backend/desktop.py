"""Memory AI Windows桌面入口: 启动本地服务 + 打开应用窗口"""
import os
import sys
import threading
import time
import webbrowser


import app.main  # noqa: E402,F401  让PyInstaller能分析到应用包


def app_dir() -> "Path":
    from pathlib import Path
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def start_server():
    import uvicorn
    os.chdir(app_dir())
    uvicorn.run("app.main:app", host="127.0.0.1", port=8787, log_level="warning")


def wait_server(timeout=40):
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8787/api/stats",
                                        timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.6)
    return False


def main():
    # 单实例: 若服务已在跑则直接开窗口
    threading.Thread(target=start_server, daemon=True).start()
    wait_server()

    try:
        import webview
        webview.create_window(
            "Memory AI · 私人第二大脑",
            "http://127.0.0.1:8787",
            width=1320, height=860,
            background_color="#0f1115",
        )
        webview.start()
    except Exception:
        # pywebview不可用时退回系统浏览器
        webbrowser.open("http://127.0.0.1:8787")
        print("服务已启动, 请在浏览器中使用 (Ctrl+C 停止)")
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
