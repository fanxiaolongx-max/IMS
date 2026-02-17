#!/usr/bin/env python3
"""
通过信号机制检查媒体状态
"""

import os
import signal

# 向 IMS 进程发送信号，让它打印媒体状态
# 首先找到 ims-server 进程
import subprocess

result = subprocess.run(['pgrep', '-f', 'ims-server'], capture_output=True, text=True)
if result.returncode != 0:
    print("未找到 ims-server 进程")
    exit(1)

pid = int(result.stdout.strip().split('\n')[0])
print(f"找到 ims-server 进程: {pid}")
print(f"发送 USR1 信号让服务器打印媒体诊断...")
os.kill(pid, signal.SIGUSR1)
print("信号已发送，请查看服务器日志")
