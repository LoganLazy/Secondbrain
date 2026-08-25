"""打包版后端服务入口(仅启动API服务, 无窗口)"""
import os

home = os.environ.get("MEMORY_AI_HOME")
if home:
    os.chdir(home)

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8787, log_level="warning")
