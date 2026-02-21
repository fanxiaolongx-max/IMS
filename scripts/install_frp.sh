#!/bin/bash
#
# frp 客户端安装脚本
# 使用方法: ./scripts/install_frp.sh
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

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  frp 客户端安装脚本${NC}"
echo -e "${GREEN}========================================${NC}"

# 检测操作系统
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Linux)
        if [ "$ARCH" = "x86_64" ]; then
            FRP_ARCH="linux_amd64"
        elif [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
            FRP_ARCH="linux_arm64"
        else
            echo -e "${RED}[ERROR] 不支持的架构: $ARCH${NC}"
            exit 1
        fi
        ;;
    Darwin)
        if [ "$ARCH" = "x86_64" ]; then
            FRP_ARCH="darwin_amd64"
        elif [ "$ARCH" = "arm64" ]; then
            FRP_ARCH="darwin_arm64"
        else
            echo -e "${RED}[ERROR] 不支持的架构: $ARCH${NC}"
            exit 1
        fi
        ;;
    *)
        echo -e "${RED}[ERROR] 不支持的操作系统: $OS${NC}"
        exit 1
        ;;
esac

FRP_VERSION="0.52.3"
FRP_URL="https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_${FRP_ARCH}.tar.gz"
INSTALL_DIR="$PROJECT_DIR/tools/frp"
BIN_DIR="$INSTALL_DIR"

echo -e "${YELLOW}[INFO] 操作系统: $OS${NC}"
echo -e "${YELLOW}[INFO] 架构: $ARCH${NC}"
echo -e "${YELLOW}[INFO] 下载地址: $FRP_URL${NC}"
echo -e "${YELLOW}[INFO] 安装目录: $INSTALL_DIR${NC}"

# 创建安装目录
mkdir -p "$INSTALL_DIR"

# 下载frp
echo -e "${YELLOW}[1/3] 下载 frp...${NC}"
cd "$INSTALL_DIR"
if [ -f "frp_${FRP_VERSION}_${FRP_ARCH}.tar.gz" ]; then
    echo -e "${GREEN}[INFO] 文件已存在，跳过下载${NC}"
else
    if command -v wget &> /dev/null; then
        wget "$FRP_URL"
    elif command -v curl &> /dev/null; then
        curl -L -o "frp_${FRP_VERSION}_${FRP_ARCH}.tar.gz" "$FRP_URL"
    else
        echo -e "${RED}[ERROR] 未找到 wget 或 curl${NC}"
        exit 1
    fi
fi

# 解压
echo -e "${YELLOW}[2/3] 解压 frp...${NC}"
tar xzf "frp_${FRP_VERSION}_${FRP_ARCH}.tar.gz"
cd "frp_${FRP_VERSION}_${FRP_ARCH}"

# 复制文件
echo -e "${YELLOW}[3/3] 安装 frp 客户端...${NC}"
cp frpc "$BIN_DIR/"
chmod +x "$BIN_DIR/frpc"

# 创建配置文件模板
CONFIG_FILE="$PROJECT_DIR/frpc.ini"
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${YELLOW}[INFO] 创建配置文件模板: $CONFIG_FILE${NC}"
    cat > "$CONFIG_FILE" << EOF
[common]
# frp服务器地址（需要替换为你的frp服务器地址）
server_addr = your-frp-server.com
# frp服务器端口（默认7000）
server_port = 7000
# 认证token（需要替换为你的token）
token = your-secret-token

# SIP UDP隧道
[sip-udp]
type = udp
local_ip = 127.0.0.1
local_port = 5060
remote_port = 5060

# SIP TCP隧道
[sip-tcp]
type = tcp
local_ip = 127.0.0.1
local_port = 5060
remote_port = 5061

# Web管理界面隧道
[web]
type = tcp
local_ip = 127.0.0.1
local_port = 8888
remote_port = 8888
EOF
    echo -e "${GREEN}[SUCCESS] 配置文件已创建${NC}"
else
    echo -e "${YELLOW}[INFO] 配置文件已存在: $CONFIG_FILE${NC}"
fi

# 创建符号链接到PATH（可选）
if [ -w "/usr/local/bin" ]; then
    echo -e "${YELLOW}[INFO] 创建符号链接到 /usr/local/bin/frpc${NC}"
    sudo ln -sf "$BIN_DIR/frpc" /usr/local/bin/frpc 2>/dev/null || true
    echo -e "${GREEN}[SUCCESS] frpc 已安装到系统PATH${NC}"
else
    echo -e "${YELLOW}[INFO] 无法写入 /usr/local/bin，frpc 位于: $BIN_DIR/frpc${NC}"
    echo -e "${YELLOW}[INFO] 你可以手动添加到PATH或使用完整路径${NC}"
fi

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  frp 客户端安装完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "${BLUE}下一步：${NC}"
echo -e "1. 编辑配置文件: $CONFIG_FILE"
echo -e "2. 设置 frp 服务器地址和 token"
echo -e "3. 启动服务: ./scripts/start_with_tunnel.sh frp pm2"
echo -e ""
echo -e "${BLUE}如果没有frp服务器，可以：${NC}"
echo -e "1. 使用其他免费方案（推荐Cloudflare Tunnel）"
echo -e "2. 或在一台有公网IP的服务器上搭建frp服务器"
echo -e "   参考: https://github.com/fatedier/frp"
