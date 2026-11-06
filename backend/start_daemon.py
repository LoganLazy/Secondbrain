#!/usr/bin/env python3
"""Linux 后台启动器：健康检查成功后才报告就绪。"""
import sys
from service_control import main

if __name__ == '__main__':
    sys.exit(main(['start', *sys.argv[1:]]))
