#!/bin/bash
#
# 内网穿透启动脚本
# 支持多种免费隧道服务：cloudflare, ngrok, localtunnel, bore, frp
# 使用方法: ./scripts/start_with_tunnel.sh [cloudflare|ngrok|localtunnel|bore|frp] [pm2|direct]
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

TUNNEL_TYPE="${1:-cloudflare}"
START_MODE="${2:-pm2}"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  IMS 服务启动脚本（内网穿透）${NC}"
echo -e "${GREEN}  隧道类型: ${TUNNEL_TYPE}${NC}"
echo -e "${GREEN}========================================${NC}"

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[ERROR] 未找到 python3${NC}"
    exit 1
fi

# 根据隧道类型启动
case "$TUNNEL_TYPE" in
    cloudflare)
        echo -e "${YELLOW}[INFO] 使用 Cloudflare Tunnel${NC}"
        
        # 检查cloudflared
        if ! command -v cloudflared &> /dev/null; then
            echo -e "${RED}[ERROR] 未找到 cloudflared${NC}"
            echo -e "${YELLOW}[INFO] 安装方法:${NC}"
            echo -e "  macOS: brew install cloudflared"
            echo -e "  Linux: wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
            exit 1
        fi
        
        # 设置环境变量启用Cloudflare隧道和TCP服务器
        export ENABLE_CF_TUNNEL=1
        export ENABLE_TCP=1
        
        # 获取公网IP（用于RTP媒体）
        echo -e "${YELLOW}[INFO] 获取公网IP（用于RTP媒体）...${NC}"
        PUBLIC_IP=$(python3 "$SCRIPT_DIR/get_public_ip.py" 2>&1 | tail -n 1)
        if [ -n "$PUBLIC_IP" ] && [[ "$PUBLIC_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            export SERVER_IP="$PUBLIC_IP"
            echo -e "${GREEN}[SUCCESS] 公网IP: ${PUBLIC_IP}${NC}"
        else
            echo -e "${YELLOW}[WARN] 无法获取公网IP，RTP媒体可能无法工作${NC}"
        fi
        
        # 启动服务（Cloudflare隧道由run.py自动启动）
        if [ "$START_MODE" = "pm2" ]; then
            pm2 restart ecosystem.config.js || pm2 start ecosystem.config.js
            pm2 logs ims-server --lines 50
        else
            python3 run.py
        fi
        ;;
        
    ngrok)
        echo -e "${YELLOW}[INFO] 使用 ngrok${NC}"
        
        # 检查ngrok
        if ! command -v ngrok &> /dev/null; then
            echo -e "${RED}[ERROR] 未找到 ngrok${NC}"
            echo -e "${YELLOW}[INFO] 安装方法:${NC}"
            echo -e "  macOS: brew install ngrok"
            echo -e "  Linux: wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz"
            exit 1
        fi
        
        # 检查ngrok配置（macOS和Linux路径不同）
        NGROK_CONFIG_FOUND=false
        if [ -f ~/.ngrok2/ngrok.yml ]; then
            NGROK_CONFIG_FOUND=true
        elif [ -f ~/.config/ngrok/ngrok.yml ]; then
            NGROK_CONFIG_FOUND=true
        elif [ -f ~/Library/Application\ Support/ngrok/ngrok.yml ]; then
            # macOS路径
            NGROK_CONFIG_FOUND=true
        fi
        
        if [ "$NGROK_CONFIG_FOUND" = false ]; then
            echo -e "${YELLOW}[WARN] 未找到ngrok配置，可能需要先运行: ngrok config add-authtoken YOUR_TOKEN${NC}"
            echo -e "${YELLOW}[INFO] 配置位置:${NC}"
            echo -e "  Linux: ~/.config/ngrok/ngrok.yml"
            echo -e "  macOS: ~/Library/Application Support/ngrok/ngrok.yml"
        else
            echo -e "${GREEN}[INFO] 找到ngrok配置${NC}"
        fi
        
        # 启动ngrok隧道（后台运行）
        echo -e "${YELLOW}[INFO] 启动ngrok隧道...${NC}"
        
        # 创建ngrok配置文件（检测ngrok版本）
        NGROK_CONFIG="$PROJECT_DIR/ngrok.yml"
        NGROK_VERSION=$(ngrok version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 | cut -d. -f1)
        
        if [ ! -f "$NGROK_CONFIG" ]; then
            if [ "$NGROK_VERSION" = "3" ]; then
                # ngrok v3 格式（TCP端点需要指定url: tcp://）
                cat > "$NGROK_CONFIG" << EOF
version: 3
endpoints:
  - name: sip-tcp
    url: tcp://
    upstream:
      url: 5060
  - name: web
    upstream:
      url: http://localhost:8888
EOF
                echo -e "${YELLOW}[INFO] 注意: ngrok v3可能不支持UDP，已配置TCP模式${NC}"
            else
                # ngrok v2 格式（兼容旧版本）
                cat > "$NGROK_CONFIG" << EOF
version: "2"
tunnels:
  sip-udp:
    proto: udp
    addr: 5060
  sip-tcp:
    proto: tcp
    addr: 5060
  web:
    proto: http
    addr: 8888
EOF
            fi
            echo -e "${YELLOW}[INFO] 已创建ngrok配置文件: $NGROK_CONFIG (v${NGROK_VERSION}格式)${NC}"
            echo -e "${YELLOW}[INFO] 注意: authtoken已在系统配置中，无需在此文件添加${NC}"
        else
            # 检查现有配置文件格式
            if grep -q "^version: 3" "$NGROK_CONFIG" 2>/dev/null; then
                echo -e "${GREEN}[INFO] 使用ngrok v3格式配置文件${NC}"
            elif grep -q '^version: "2"' "$NGROK_CONFIG" 2>/dev/null; then
                echo -e "${GREEN}[INFO] 使用ngrok v2格式配置文件${NC}"
            else
                echo -e "${YELLOW}[WARN] 配置文件格式可能不正确，建议检查: $NGROK_CONFIG${NC}"
            fi
        fi
        
        # 启动ngrok
        echo -e "${YELLOW}[INFO] 启动ngrok隧道...${NC}"
        
        # 检查端口是否被占用（可能已有ngrok在运行）
        if lsof -Pi :4040 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
            echo -e "${YELLOW}[WARN] ngrok Web界面端口4040已被占用，可能已有ngrok在运行${NC}"
            echo -e "${YELLOW}[INFO] 尝试使用现有ngrok实例...${NC}"
            NGROK_PID=""
        else
            # ngrok v3需要合并系统配置（包含authtoken）和项目配置
            # 使用多个配置文件，系统配置优先
            if [ -f "$NGROK_CONFIG" ]; then
                echo -e "${GREEN}[INFO] 使用项目配置文件: $NGROK_CONFIG${NC}"
                # 合并系统配置和项目配置
                if [ -f ~/Library/Application\ Support/ngrok/ngrok.yml ]; then
                    # macOS系统配置
                    ngrok start --all --config ~/Library/Application\ Support/ngrok/ngrok.yml --config "$NGROK_CONFIG" > /tmp/ngrok.log 2>&1 &
                elif [ -f ~/.config/ngrok/ngrok.yml ]; then
                    # Linux系统配置
                    ngrok start --all --config ~/.config/ngrok/ngrok.yml --config "$NGROK_CONFIG" > /tmp/ngrok.log 2>&1 &
                else
                    # 只使用项目配置（需要包含authtoken）
                    ngrok start --all --config "$NGROK_CONFIG" > /tmp/ngrok.log 2>&1 &
                fi
            else
                echo -e "${GREEN}[INFO] 使用系统默认配置${NC}"
                ngrok start --all > /tmp/ngrok.log 2>&1 &
            fi
            NGROK_PID=$!
            echo -e "${GREEN}[INFO] ngrok进程已启动 (PID: $NGROK_PID)${NC}"
            
            # 等待ngrok启动（最多等待10秒）
            echo -e "${YELLOW}[INFO] 等待ngrok启动...${NC}"
            for i in {1..10}; do
                if curl -s http://localhost:4040/api/tunnels >/dev/null 2>&1; then
                    echo -e "${GREEN}[SUCCESS] ngrok已就绪${NC}"
                    break
                fi
                sleep 1
                echo -n "."
            done
            echo ""
        fi
        
        # 从ngrok API获取地址
        echo -e "${YELLOW}[INFO] 获取ngrok公网地址...${NC}"
        NGROK_INFO=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null || echo "")
        
        if [ -z "$NGROK_INFO" ] || [ "$NGROK_INFO" = "null" ]; then
            echo -e "${RED}[ERROR] 无法获取ngrok地址${NC}"
            echo -e "${YELLOW}[INFO] 可能的原因：${NC}"
            echo -e "  1. ngrok启动失败，查看日志: tail -20 /tmp/ngrok.log"
            echo -e "  2. ngrok Web界面未就绪，访问: http://localhost:4040"
            if [ -f "$NGROK_CONFIG" ]; then
                echo -e "  3. 配置文件错误，检查: $NGROK_CONFIG"
            fi
            if [ -n "$NGROK_PID" ]; then
                kill $NGROK_PID 2>/dev/null || true
            fi
            exit 1
        fi
        
        # 解析地址（需要python）
        TUNNEL_INFO=$(python3 << 'PYEOF'
import json
import sys
try:
    data = json.load(sys.stdin)
    tunnels = data.get('tunnels', [])
    if not tunnels:
        print("NO_TUNNELS", file=sys.stderr)
        sys.exit(1)
    
    # 优先查找UDP隧道（SIP）
    for tunnel in tunnels:
        proto = tunnel.get('proto', '').lower()
        public_url = tunnel.get('public_url', '')
        name = tunnel.get('name', '')
        if 'udp' in proto or 'sip' in name.lower():
            # 解析URL获取host和port
            url = public_url.replace('udp://', '').replace('tcp://', '').replace('http://', '').replace('https://', '')
            if ':' in url:
                host, port = url.split(':', 1)
            else:
                host, port = url, '443'
            print(f"SIP:{host}:{port}")
            break
    else:
        # 如果没有找到UDP，使用第一个TCP隧道
        tunnel = tunnels[0]
        public_url = tunnel.get('public_url', '')
        name = tunnel.get('name', '')
        url = public_url.replace('tcp://', '').replace('http://', '').replace('https://', '')
        if ':' in url:
            host, port = url.split(':', 1)
        else:
            host, port = url, '443'
        print(f"{name}:{host}:{port}")
except Exception as e:
    print(f"ERROR:{e}", file=sys.stderr)
    sys.exit(1)
PYEOF
<<< "$NGROK_INFO")
        
        if [ -z "$TUNNEL_INFO" ] || [[ "$TUNNEL_INFO" == ERROR:* ]] || [[ "$TUNNEL_INFO" == NO_TUNNELS ]]; then
            echo -e "${YELLOW}[WARN] 无法解析ngrok地址${NC}"
            echo -e "${YELLOW}[INFO] 请手动访问 http://localhost:4040 查看隧道信息${NC}"
            echo -e "${YELLOW}[INFO] 或查看ngrok日志: tail -20 /tmp/ngrok.log${NC}"
        else
            # 解析隧道信息
            TUNNEL_NAME=$(echo "$TUNNEL_INFO" | cut -d: -f1)
            TUNNEL_HOST=$(echo "$TUNNEL_INFO" | cut -d: -f2)
            TUNNEL_PORT=$(echo "$TUNNEL_INFO" | cut -d: -f3)
            
            echo -e "${GREEN}[SUCCESS] ngrok隧道已启动${NC}"
            echo -e "${GREEN}  隧道名称: ${TUNNEL_NAME}${NC}"
            echo -e "${GREEN}  公网地址: ${TUNNEL_HOST}:${TUNNEL_PORT}${NC}"
            echo -e "${GREEN}  Web界面: http://localhost:4040${NC}"
            
            # 设置环境变量
            export SERVER_IP="$TUNNEL_HOST"
            export SERVER_PUBLIC_PORT="$TUNNEL_PORT"
        fi
        
        # 保存ngrok进程ID（用于清理）
        export NGROK_PID="$NGROK_PID"
        
        # 启动服务
        if [ "$START_MODE" = "pm2" ]; then
            pm2 restart ecosystem.config.js || pm2 start ecosystem.config.js
            echo -e "${GREEN}[INFO] 服务已启动，查看日志了解ngrok隧道详情${NC}"
            pm2 logs ims-server --lines 30
        else
            python3 run.py
        fi
        
        # 清理（如果是我们启动的ngrok进程）
        if [ -n "$NGROK_PID" ]; then
            trap "echo '[INFO] 停止ngrok进程...'; kill $NGROK_PID 2>/dev/null || true" EXIT
        fi
        ;;
        
    localtunnel)
        echo -e "${YELLOW}[INFO] 使用 localtunnel${NC}"
        
        # 检查localtunnel
        if ! command -v lt &> /dev/null; then
            echo -e "${RED}[ERROR] 未找到 localtunnel${NC}"
            echo -e "${YELLOW}[INFO] 安装方法: npm install -g localtunnel${NC}"
            exit 1
        fi
        
        # localtunnel只支持HTTP，启动Web管理界面
        echo -e "${YELLOW}[INFO] 启动localtunnel（仅HTTP，不支持SIP）...${NC}"
        lt --port 8888 > /tmp/localtunnel.log 2>&1 &
        LT_PID=$!
        sleep 2
        
        LT_URL=$(grep -o 'https://[^ ]*' /tmp/localtunnel.log | head -1)
        if [ -n "$LT_URL" ]; then
            echo -e "${GREEN}[SUCCESS] localtunnel地址: ${LT_URL}${NC}"
        fi
        
        export LT_PID="$LT_PID"
        trap "kill $LT_PID 2>/dev/null || true" EXIT
        
        # 启动服务
        if [ "$START_MODE" = "pm2" ]; then
            pm2 restart ecosystem.config.js || pm2 start ecosystem.config.js
        else
            python3 run.py
        fi
        ;;
        
    bore)
        echo -e "${YELLOW}[INFO] 使用 bore${NC}"
        
        # 检查bore
        if ! command -v bore &> /dev/null; then
            echo -e "${RED}[ERROR] 未找到 bore${NC}"
            echo -e "${YELLOW}[INFO] 安装方法:${NC}"
            echo -e "  wget https://github.com/ekzhang/bore/releases/download/v0.5.0/bore-v0.5.0-x86_64-unknown-linux-musl.tar.gz"
            exit 1
        fi
        
        # bore只支持TCP
        echo -e "${YELLOW}[INFO] 启动bore隧道（TCP 5060）...${NC}"
        bore local 5060 --to bore.pub > /tmp/bore.log 2>&1 &
        BORE_PID=$!
        sleep 2
        
        BORE_ADDR=$(grep -o 'bore.pub:[0-9]*' /tmp/bore.log | head -1)
        if [ -n "$BORE_ADDR" ]; then
            echo -e "${GREEN}[SUCCESS] bore地址: ${BORE_ADDR}${NC}"
            export SERVER_IP=$(echo "$BORE_ADDR" | cut -d: -f1)
            export SERVER_PUBLIC_PORT=$(echo "$BORE_ADDR" | cut -d: -f2)
        fi
        
        export BORE_PID="$BORE_PID"
        export ENABLE_TCP=1  # bore使用TCP，需要启用TCP服务器
        trap "kill $BORE_PID 2>/dev/null || true" EXIT
        
        # 启动服务
        if [ "$START_MODE" = "pm2" ]; then
            pm2 restart ecosystem.config.js || pm2 start ecosystem.config.js
        else
            python3 run.py
        fi
        ;;
        
    frp)
        echo -e "${YELLOW}[INFO] 使用 frp${NC}"
        
        # 检查frpc（先检查系统PATH，再检查项目目录）
        FRPC_CMD=""
        if command -v frpc &> /dev/null; then
            FRPC_CMD="frpc"
        elif [ -f "$PROJECT_DIR/tools/frp/frpc" ]; then
            FRPC_CMD="$PROJECT_DIR/tools/frp/frpc"
        else
            echo -e "${RED}[ERROR] 未找到 frpc${NC}"
            echo -e "${YELLOW}[INFO] 安装方法：${NC}"
            echo -e "  1. 使用安装脚本: ./scripts/install_frp.sh"
            echo -e "  2. 或手动下载: https://github.com/fatedier/frp/releases"
            echo -e ""
            echo -e "${YELLOW}[INFO] 如果没有frp服务器，推荐使用其他免费方案：${NC}"
            echo -e "  - Cloudflare Tunnel: ./scripts/start_with_tunnel.sh cloudflare pm2"
            echo -e "  - ngrok: ./scripts/start_with_tunnel.sh ngrok pm2"
            exit 1
        fi
        
        # 检查配置文件
        FRPC_CONFIG="$PROJECT_DIR/frpc.ini"
        if [ ! -f "$FRPC_CONFIG" ]; then
            echo -e "${YELLOW}[INFO] 创建frp客户端配置模板...${NC}"
            cat > "$FRPC_CONFIG" << EOF
[common]
server_addr = your-frp-server.com
server_port = 7000
token = your-secret-token

[sip-udp]
type = udp
local_ip = 127.0.0.1
local_port = 5060
remote_port = 5060

[sip-tcp]
type = tcp
local_ip = 127.0.0.1
local_port = 5060
remote_port = 5061

[web]
type = tcp
local_ip = 127.0.0.1
local_port = 8888
remote_port = 8888
EOF
            echo -e "${YELLOW}[INFO] 请编辑配置文件: $FRPC_CONFIG${NC}"
            exit 1
        fi
        
        # 启动frpc
        echo -e "${YELLOW}[INFO] 启动frp客户端...${NC}"
        "$FRPC_CMD" -c "$FRPC_CONFIG" > /tmp/frpc.log 2>&1 &
        FRPC_PID=$!
        sleep 2
        
        # 检查是否启动成功
        if ! ps -p $FRPC_PID > /dev/null 2>&1; then
            echo -e "${RED}[ERROR] frp客户端启动失败${NC}"
            echo -e "${YELLOW}[INFO] 查看日志: tail -20 /tmp/frpc.log${NC}"
            cat /tmp/frpc.log | tail -10
            exit 1
        fi
        
        # 从配置文件读取服务器地址
        FRP_SERVER=$(grep '^server_addr' "$FRPC_CONFIG" | cut -d= -f2 | tr -d ' ')
        if [ -n "$FRP_SERVER" ]; then
            echo -e "${GREEN}[SUCCESS] frp已连接到: ${FRP_SERVER}${NC}"
            export SERVER_IP="$FRP_SERVER"
        fi
        
        export FRPC_PID="$FRPC_PID"
        export ENABLE_TCP=1  # frp可能使用TCP，启用TCP服务器
        trap "kill $FRPC_PID 2>/dev/null || true" EXIT
        
        # 启动服务
        if [ "$START_MODE" = "pm2" ]; then
            pm2 restart ecosystem.config.js || pm2 start ecosystem.config.js
        else
            python3 run.py
        fi
        ;;
        
    *)
        echo -e "${RED}[ERROR] 未知的隧道类型: $TUNNEL_TYPE${NC}"
        echo -e "${YELLOW}支持的隧道类型: cloudflare, ngrok, localtunnel, bore, frp${NC}"
        echo -e "${YELLOW}使用方法: $0 [隧道类型] [pm2|direct]${NC}"
        exit 1
        ;;
esac

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  服务已启动（${TUNNEL_TYPE}隧道）${NC}"
echo -e "${GREEN}========================================${NC}"
