#!/bin/bash
# RTPProxy安装和启动脚本

set -e

echo "=========================================="
echo "RTPProxy 安装和启动脚本"
echo "=========================================="

# 获取服务器IP（从环境变量或自动检测）
if [ -n "$SERVER_IP" ]; then
    RTPPROXY_IP="$SERVER_IP"
    echo "[信息] 使用环境变量 SERVER_IP: $RTPPROXY_IP"
else
    # 尝试获取公网IP
    RTPPROXY_IP=$(curl -s ifconfig.me 2>/dev/null || curl -s ipinfo.io/ip 2>/dev/null || hostname -I | awk '{print $1}')
    echo "[信息] 自动检测IP: $RTPPROXY_IP"
fi

# RTPProxy配置
RTPPROXY_UDP_HOST="127.0.0.1"
RTPPROXY_UDP_PORT="7722"
RTPPROXY_SOCKET="/var/run/rtpproxy.sock"

echo ""
echo "[步骤1] 检查RTPProxy是否已安装..."

# 检查是否已安装
if command -v rtpproxy &> /dev/null; then
    echo "[成功] RTPProxy已安装: $(which rtpproxy)"
    rtpproxy -V
else
    echo "[警告] RTPProxy未安装"
    echo ""
    echo "请选择安装方式:"
    echo "1. 从源码编译安装（推荐）"
    echo "2. 使用包管理器安装（如果可用）"
    echo "3. 跳过安装，仅启动（如果已安装但不在PATH中）"
    echo ""
    read -p "请选择 (1/2/3): " choice
    
    case $choice in
        1)
            echo "[安装] 从源码编译安装RTPProxy..."
            echo ""
            echo "请执行以下命令手动编译安装:"
            echo "  cd /usr/src"
            echo "  git clone https://github.com/sippy/rtpproxy.git"
            echo "  cd rtpproxy"
            echo "  git submodule update --init --recursive"
            echo "  ./configure"
            echo "  make clean all"
            echo "  make install"
            echo ""
            echo "安装完成后，重新运行此脚本"
            exit 1
            ;;
        2)
            echo "[安装] 尝试使用包管理器安装..."
            # 尝试不同的包管理器
            if command -v apt-get &> /dev/null; then
                # 尝试添加Sippy仓库或使用snap
                echo "Debian/Ubuntu系统，尝试安装..."
                apt-get update
                apt-get install -y rtpproxy || {
                    echo "[错误] apt-get安装失败，请尝试从源码编译"
                    exit 1
                }
            elif command -v yum &> /dev/null; then
                yum install -y rtpproxy || {
                    echo "[错误] yum安装失败，请尝试从源码编译"
                    exit 1
                }
            else
                echo "[错误] 未找到支持的包管理器"
                exit 1
            fi
            ;;
        3)
            echo "[跳过] 假设RTPProxy已安装，继续启动..."
            ;;
        *)
            echo "[错误] 无效选择"
            exit 1
            ;;
    esac
fi

echo ""
echo "[步骤2] 检查RTPProxy是否正在运行..."

if pgrep -x rtpproxy > /dev/null; then
    echo "[警告] RTPProxy已在运行 (PID: $(pgrep -x rtpproxy))"
    read -p "是否停止现有进程并重新启动? (y/n): " restart
    if [ "$restart" = "y" ]; then
        echo "[停止] 停止现有RTPProxy进程..."
        pkill -x rtpproxy
        sleep 2
    else
        echo "[跳过] 保持现有进程运行"
        exit 0
    fi
fi

echo ""
echo "[步骤3] 启动RTPProxy..."

# 创建socket目录
mkdir -p /var/run
chmod 777 /var/run 2>/dev/null || true

# 选择启动方式
echo ""
echo "选择RTPProxy启动方式:"
echo "1. UDP socket (127.0.0.1:7722) - 推荐用于测试"
echo "2. Unix socket (/var/run/rtpproxy.sock) - 推荐用于生产"
read -p "请选择 (1/2): " socket_choice

case $socket_choice in
    1)
        SOCKET_ARG="-s udp:${RTPPROXY_UDP_HOST}:${RTPPROXY_UDP_PORT}"
        echo "[启动] UDP socket模式: ${RTPPROXY_UDP_HOST}:${RTPPROXY_UDP_PORT}"
        ;;
    2)
        SOCKET_ARG="-s unix:${RTPPROXY_SOCKET}"
        echo "[启动] Unix socket模式: ${RTPPROXY_SOCKET}"
        # 确保socket文件可以被删除
        rm -f "${RTPPROXY_SOCKET}"
        ;;
    *)
        echo "[错误] 无效选择，使用UDP socket"
        SOCKET_ARG="-s udp:${RTPPROXY_UDP_HOST}:${RTPPROXY_UDP_PORT}"
        ;;
esac

# 启动命令
START_CMD="rtpproxy -l ${RTPPROXY_IP} ${SOCKET_ARG} -F -d INFO"

echo ""
echo "[执行] $START_CMD"
echo ""

# 启动RTPProxy（后台运行）
nohup $START_CMD > /var/log/rtpproxy.log 2>&1 &
RTPPROXY_PID=$!

sleep 2

# 检查是否启动成功
if ps -p $RTPPROXY_PID > /dev/null; then
    echo "[成功] RTPProxy已启动 (PID: $RTPPROXY_PID)"
    echo "[日志] 日志文件: /var/log/rtpproxy.log"
    echo ""
    echo "=========================================="
    echo "RTPProxy配置信息:"
    echo "  监听IP: $RTPPROXY_IP"
    echo "  控制socket: $SOCKET_ARG"
    echo "  PID: $RTPPROXY_PID"
    echo "=========================================="
    echo ""
    echo "[验证] 运行以下命令验证RTPProxy:"
    echo "  python3 check_rtpproxy.py"
    echo ""
    echo "[停止] 停止RTPProxy:"
    echo "  kill $RTPPROXY_PID"
    echo ""
else
    echo "[错误] RTPProxy启动失败"
    echo "[日志] 查看日志: tail -f /var/log/rtpproxy.log"
    exit 1
fi
