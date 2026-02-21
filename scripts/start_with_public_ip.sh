#!/bin/bash
#
# 启动脚本：自动获取公网IP并启动服务
# 使用方法: ./scripts/start_with_public_ip.sh [pm2|direct]
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  IMS 服务启动脚本（自动获取公网IP）${NC}"
echo -e "${GREEN}========================================${NC}"

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[ERROR] 未找到 python3${NC}"
    exit 1
fi

# 获取公网IP
echo -e "${YELLOW}[1/4] 正在获取公网IP地址...${NC}"
PUBLIC_IP=$(python3 "$SCRIPT_DIR/get_public_ip.py" 2>&1 | tail -n 1)

if [ -z "$PUBLIC_IP" ] || [[ ! "$PUBLIC_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo -e "${RED}[ERROR] 无法获取公网IP地址${NC}"
    echo -e "${YELLOW}[INFO] 提示：如果服务器在NAT后，请使用内网穿透方案（见 docs/DYNAMIC_IP_SOLUTION.md）${NC}"
    exit 1
fi

echo -e "${GREEN}[SUCCESS] 公网IP: ${PUBLIC_IP}${NC}"

# 检测NAT端口映射（可选）
echo -e "${YELLOW}[2/4] 检测NAT端口映射（可选）...${NC}"
# 从配置文件读取本地端口，默认5060
LOCAL_PORT=$(python3 << 'PYEOF'
import json
import sys
try:
    with open("config/config.json", 'r') as f:
        config = json.load(f)
    print(config.get('SERVER_PORT', 5060))
except:
    print(5060)
PYEOF
)
PUBLIC_PORT=$(python3 "$SCRIPT_DIR/get_public_port.py" --port "$LOCAL_PORT" --format port 2>&1 | tail -n 1)

if [ -n "$PUBLIC_PORT" ] && [[ "$PUBLIC_PORT" =~ ^[0-9]+$ ]] && [ "$PUBLIC_PORT" != "$LOCAL_PORT" ]; then
    echo -e "${GREEN}[INFO] 检测到NAT端口映射: ${LOCAL_PORT} -> ${PUBLIC_PORT}${NC}"
    echo -e "${YELLOW}[INFO] 将配置公网端口: ${PUBLIC_PORT}${NC}"
else
    echo -e "${YELLOW}[INFO] 未检测到端口映射或端口相同，使用默认端口: ${LOCAL_PORT}${NC}"
    PUBLIC_PORT="$LOCAL_PORT"
fi

# 更新配置文件（可选，备份原配置）
CONFIG_FILE="$PROJECT_DIR/config/config.json"
if [ -f "$CONFIG_FILE" ]; then
    echo -e "${YELLOW}[3/4] 更新配置文件...${NC}"
    # 备份原配置
    cp "$CONFIG_FILE" "${CONFIG_FILE}.bak.$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true
    
    # 使用python更新JSON配置
    python3 << EOF
import json
import sys

config_file = "$CONFIG_FILE"
public_ip = "$PUBLIC_IP"
public_port = "$PUBLIC_PORT"
local_port = "$LOCAL_PORT"

try:
    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    old_ip = config.get('SERVER_ADDR', '')
    # 如果配置是 AUTO_DETECT 或空，则更新为实际IP
    if not old_ip or old_ip.upper() == "AUTO_DETECT":
        config['SERVER_ADDR'] = public_ip
        print(f"[INFO] 已设置 SERVER_ADDR: {public_ip}")
    elif old_ip != public_ip:
        config['SERVER_ADDR'] = public_ip
        print(f"[INFO] 已更新 SERVER_ADDR: {old_ip} -> {public_ip}")
    else:
        print(f"[INFO] SERVER_ADDR 已经是: {public_ip}")
    
    # 更新公网端口（如果检测到端口映射）
    if public_port != local_port:
        old_public_port = config.get('SERVER_PUBLIC_PORT')
        config['SERVER_PUBLIC_PORT'] = int(public_port)
        if old_public_port != int(public_port):
            print(f"[INFO] 已设置 SERVER_PUBLIC_PORT: {public_port} (内网端口: {local_port})")
        else:
            print(f"[INFO] SERVER_PUBLIC_PORT 已经是: {public_port}")
    
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
except Exception as e:
    print(f"[WARN] 更新配置文件失败: {e}", file=sys.stderr)
    sys.exit(0)  # 不阻止启动
EOF
fi

# 更新 sip_client_config.json
SIP_CLIENT_CONFIG="$PROJECT_DIR/sip_client_config.json"
if [ -f "$SIP_CLIENT_CONFIG" ]; then
    echo -e "${YELLOW}[3/4] 更新 SIP 客户端配置...${NC}"
    python3 << EOF
import json
import sys

config_file = "$SIP_CLIENT_CONFIG"
public_ip = "$PUBLIC_IP"

try:
    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    old_server_ip = config.get('server_ip', '')
    old_local_ip = config.get('local_ip', '')
    old_sdp_ip = config.get('sdp_ip', '')
    
    # 如果配置是 AUTO_DETECT 或空，则更新为实际IP
    updates = []
    if not old_server_ip or old_server_ip.upper() == "AUTO_DETECT":
        config['server_ip'] = public_ip
        updates.append(f"server_ip: {old_server_ip} -> {public_ip}")
    elif old_server_ip != public_ip:
        config['server_ip'] = public_ip
        updates.append(f"server_ip: {old_server_ip} -> {public_ip}")
    
    if not old_local_ip or old_local_ip.upper() == "AUTO_DETECT":
        config['local_ip'] = public_ip
        updates.append(f"local_ip: {old_local_ip} -> {public_ip}")
    elif old_local_ip != public_ip:
        config['local_ip'] = public_ip
        updates.append(f"local_ip: {old_local_ip} -> {public_ip}")
    
    if not old_sdp_ip or old_sdp_ip.upper() == "AUTO_DETECT":
        config['sdp_ip'] = public_ip
        updates.append(f"sdp_ip: {old_sdp_ip} -> {public_ip}")
    elif old_sdp_ip != public_ip:
        config['sdp_ip'] = public_ip
        updates.append(f"sdp_ip: {old_sdp_ip} -> {public_ip}")
    
    if updates:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print(f"[INFO] 已更新 SIP 客户端配置:")
        for update in updates:
            print(f"  {update}")
    else:
        print(f"[INFO] SIP 客户端配置已是最新: {public_ip}")
except Exception as e:
    print(f"[WARN] 更新 SIP 客户端配置失败: {e}", file=sys.stderr)
    sys.exit(0)
EOF
fi

# 设置环境变量并启动服务
echo -e "${YELLOW}[4/4] 启动服务...${NC}"
export SERVER_IP="$PUBLIC_IP"
export NODE_ENV="production"
if [ "$PUBLIC_PORT" != "$LOCAL_PORT" ]; then
    export SERVER_PUBLIC_PORT="$PUBLIC_PORT"
    echo -e "${GREEN}[INFO] 设置环境变量 SERVER_PUBLIC_PORT=${PUBLIC_PORT}${NC}"
fi

START_MODE="${1:-pm2}"

if [ "$START_MODE" = "pm2" ]; then
    # 使用PM2启动
    if ! command -v pm2 &> /dev/null; then
        echo -e "${RED}[ERROR] 未找到 pm2，请先安装: npm install -g pm2${NC}"
        exit 1
    fi
    
    # 更新 ecosystem.config.js 中的 SERVER_IP
    if [ -f "ecosystem.config.js" ]; then
        python3 << EOF
import re

ecosystem_file = "ecosystem.config.js"
public_ip = "$PUBLIC_IP"

try:
    with open(ecosystem_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 查找当前的 SERVER_IP 值
    pattern = r"(SERVER_IP:\s*['\"])([^'\"]+)(['\"])"
    match = re.search(pattern, content)
    
    if match:
        old_ip = match.group(2)
        # 如果配置是 AUTO_DETECT 或需要更新，则替换
        if old_ip.upper() == "AUTO_DETECT" or old_ip != public_ip:
            new_content = re.sub(pattern, f"\\g<1>{public_ip}\\g<3>", content)
            with open(ecosystem_file, 'w', encoding='utf-8') as f:
                f.write(new_content)
            if old_ip.upper() == "AUTO_DETECT":
                print(f"[INFO] 已设置 ecosystem.config.js 中的 SERVER_IP: {public_ip}")
            else:
                print(f"[INFO] 已更新 ecosystem.config.js 中的 SERVER_IP: {old_ip} -> {public_ip}")
        else:
            print(f"[INFO] ecosystem.config.js 中的 SERVER_IP 已经是: {public_ip}")
    else:
        print(f"[WARN] 未找到 SERVER_IP 配置", file=sys.stderr)
except Exception as e:
    print(f"[WARN] 更新 ecosystem.config.js 失败: {e}", file=sys.stderr)
EOF
    fi
    
    echo -e "${GREEN}[INFO] 使用 PM2 启动服务，公网IP: ${PUBLIC_IP}${NC}"
    pm2 restart ecosystem.config.js || pm2 start ecosystem.config.js
    pm2 logs ims-server --lines 50
    
elif [ "$START_MODE" = "direct" ]; then
    # 直接启动
    if [ ! -f "run.py" ]; then
        echo -e "${RED}[ERROR] 未找到 run.py${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}[INFO] 直接启动服务，公网IP: ${PUBLIC_IP}${NC}"
    python3 run.py
    
else
    echo -e "${RED}[ERROR] 未知的启动模式: $START_MODE${NC}"
    echo -e "${YELLOW}使用方法: $0 [pm2|direct]${NC}"
    exit 1
fi

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  服务已启动${NC}"
echo -e "${GREEN}  公网IP: ${PUBLIC_IP}${NC}"
if [ "$PUBLIC_PORT" != "$LOCAL_PORT" ]; then
    echo -e "${GREEN}  内网端口: ${LOCAL_PORT} -> 公网端口: ${PUBLIC_PORT}${NC}"
else
    echo -e "${GREEN}  端口: ${LOCAL_PORT}${NC}"
fi
echo -e "${GREEN}========================================${NC}"
