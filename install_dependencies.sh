#!/bin/bash
# 安装新方案所需的依赖

echo "=========================================="
echo "安装新方案依赖"
echo "=========================================="

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then 
    echo "请使用root权限运行此脚本"
    exit 1
fi

# 1. 安装RTPProxy
echo ""
echo "1. 安装RTPProxy..."
if command -v rtpproxy >/dev/null 2>&1; then
    echo "  ✓ rtpproxy已安装"
    rtpproxy -v 2>&1 | head -3
else
    echo "  正在安装rtpproxy..."
    apt-get update
    apt-get install -y rtpproxy
    if command -v rtpproxy >/dev/null 2>&1; then
        echo "  ✓ rtpproxy安装成功"
        rtpproxy -v 2>&1 | head -3
    else
        echo "  ✗ rtpproxy安装失败"
        exit 1
    fi
fi

# 2. 安装Python sippy库
echo ""
echo "2. 安装Python sippy库..."
if python3 -c "import sippy" >/dev/null 2>&1; then
    echo "  ✓ sippy已安装"
    python3 -c "import sippy; print('  sippy模块可用')"
else
    echo "  正在安装sippy..."
    pip3 install sippy
    if python3 -c "import sippy" >/dev/null 2>&1; then
        echo "  ✓ sippy安装成功"
    else
        echo "  ✗ sippy安装失败（可选，如果只使用RTPProxy媒体中继可以跳过）"
        echo "  可以稍后手动安装: pip3 install sippy"
    fi
fi

# 3. 验证代码导入
echo ""
echo "3. 验证代码..."
if python3 -c "from sipcore.rtpproxy_client import RTPProxyClient" >/dev/null 2>&1; then
    echo "  ✓ RTPProxy客户端代码正常"
else
    echo "  ✗ RTPProxy客户端代码有问题"
    exit 1
fi

if python3 -c "from sipcore.rtpproxy_media_relay import RTPProxyMediaRelay" >/dev/null 2>&1; then
    echo "  ✓ RTPProxy媒体中继代码正常"
else
    echo "  ✗ RTPProxy媒体中继代码有问题"
    exit 1
fi

echo ""
echo "=========================================="
echo "依赖安装完成！"
echo "=========================================="
echo ""
echo "下一步："
echo "1. 启动RTPProxy:"
echo "   rtpproxy -l <服务器IP> -s udp:127.0.0.1:7722 -F"
echo ""
echo "2. 修改run.py使用新方案（参考RTPPROXY_QUICKSTART.md）"
echo ""
echo "3. 重启服务器:"
echo "   pm2 restart ims-server"
echo ""
