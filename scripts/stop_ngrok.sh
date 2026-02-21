#!/bin/bash
#
# 停止ngrok隧道脚本
#

echo "正在停止ngrok..."

# 方法1: 通过进程名停止
pkill -f ngrok

# 方法2: 通过端口4040停止
if lsof -Pi :4040 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    PID=$(lsof -Pi :4040 -sTCP:LISTEN -t)
    echo "找到ngrok进程 (PID: $PID)，正在停止..."
    kill $PID 2>/dev/null
    sleep 1
    # 如果还在运行，强制停止
    if ps -p $PID > /dev/null 2>&1; then
        kill -9 $PID 2>/dev/null
    fi
fi

# 等待进程完全退出
sleep 1

# 验证是否已停止
if ps aux | grep -v grep | grep ngrok > /dev/null; then
    echo "警告: 仍有ngrok进程在运行"
    ps aux | grep ngrok | grep -v grep
else
    echo "✅ ngrok已停止"
fi

# 检查端口4040
if lsof -Pi :4040 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo "警告: 端口4040仍被占用"
    lsof -i :4040
else
    echo "✅ 端口4040已释放"
fi
