#!/bin/bash
# 切换到RTPProxy媒体中继的脚本

echo "=========================================="
echo "切换到RTPProxy媒体中继"
echo "=========================================="

# 1. 备份原始文件
echo "1. 备份原始media_relay.py..."
cp sipcore/media_relay.py sipcore/media_relay.py.backup.$(date +%Y%m%d_%H%M%S)

# 2. 修改run.py使用RTPProxy
echo "2. 修改run.py使用RTPProxy..."
sed -i.bak 's/from sipcore.media_relay import/from sipcore.rtpproxy_media_relay import/g' run.py

# 3. 检查rtpproxy是否安装
echo "3. 检查rtpproxy..."
if command -v rtpproxy &> /dev/null; then
    echo "  ✓ rtpproxy已安装"
    rtpproxy -v
else
    echo "  ✗ rtpproxy未安装"
    echo "  请运行: apt-get install rtpproxy"
    exit 1
fi

# 4. 提示启动rtpproxy
echo ""
echo "4. 请启动rtpproxy:"
echo "  方式1 (TCP socket):"
echo "    rtpproxy -l <服务器IP> -s udp:127.0.0.1:7722 -F"
echo ""
echo "  方式2 (Unix socket):"
echo "    rtpproxy -l <服务器IP> -s unix:/var/run/rtpproxy.sock -F"
echo ""
echo "5. 修改run.py中的init_media_relay调用，添加rtpproxy参数:"
echo "   media_relay = init_media_relay(SERVER_IP, rtpproxy_tcp=('127.0.0.1', 7722))"
echo "   或"
echo "   media_relay = init_media_relay(SERVER_IP, rtpproxy_socket='/var/run/rtpproxy.sock')"
echo ""
echo "=========================================="
echo "切换完成！"
echo "=========================================="
