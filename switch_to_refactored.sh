#!/bin/bash
# 切换到重构版本的脚本

set -e

echo "=========================================="
echo "切换到重构版本"
echo "=========================================="
echo ""

# 检查文件是否存在
if [ ! -f "run_refactored.py" ]; then
    echo "错误: run_refactored.py 不存在"
    exit 1
fi

# 备份原版本
if [ -f "run.py" ]; then
    BACKUP_FILE="run.py.backup.$(date +%Y%m%d_%H%M%S)"
    cp run.py "$BACKUP_FILE"
    echo "✓ 已备份原版本到: $BACKUP_FILE"
else
    echo "警告: run.py 不存在，跳过备份"
fi

# 复制重构版本
cp run_refactored.py run.py
echo "✓ 已切换到重构版本"

# 检查RTPProxy
echo ""
echo "检查RTPProxy..."
if command -v rtpproxy &> /dev/null; then
    echo "✓ RTPProxy 已安装"
    if pgrep -x rtpproxy > /dev/null; then
        echo "✓ RTPProxy 正在运行"
    else
        echo "⚠ RTPProxy 未运行"
        echo "  请启动RTPProxy:"
        echo "  rtpproxy -l <SERVER_IP> -s udp:127.0.0.1:7722 -F"
    fi
else
    echo "✗ RTPProxy 未安装"
    echo "  请安装: apt-get install rtpproxy"
fi

# 检查Python依赖
echo ""
echo "检查Python依赖..."
if python3 -c "from sipcore.rtpproxy_media_relay import RTPProxyMediaRelay" 2>/dev/null; then
    echo "✓ RTPProxy媒体中继模块可用"
else
    echo "✗ RTPProxy媒体中继模块不可用"
    echo "  请检查 sipcore/rtpproxy_media_relay.py 是否存在"
fi

echo ""
echo "=========================================="
echo "切换完成！"
echo "=========================================="
echo ""
echo "下一步："
echo "1. 确保RTPProxy已启动"
echo "2. 重启服务器: pm2 restart ims-server"
echo "3. 查看日志确认RTPProxy连接成功"
echo ""
echo "如需回退，运行: ./switch_to_original.sh"
