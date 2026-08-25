#!/usr/bin/env python3
"""双fork守护启动 Memory AI 后端, 日志写入 last-run.log"""
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))

if os.fork():
    sys.exit(0)
os.setsid()
if os.fork():
    sys.exit(0)

with open("/dev/null", "rb") as dn:
    os.dup2(dn.fileno(), 0)
log = open(os.path.join(DIR, "last-run.log"), "ab", buffering=0)
os.dup2(log.fileno(), 1)
os.dup2(log.fileno(), 2)

py = os.path.join(DIR, ".venv", "bin", "python")
os.chdir(DIR)
os.execv(py, [py, "-m", "uvicorn", "app.main:app", "--port", "8787"])
