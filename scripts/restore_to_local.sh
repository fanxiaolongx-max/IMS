#!/bin/bash
#
# 恢复到局域网版本脚本
# 移除所有公网IP配置，恢复为自动检测内网IP
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
echo -e "${GREEN}  恢复到局域网版本${NC}"
echo -e "${GREEN}========================================${NC}"

# 获取内网IP
LOCAL_IP=$(python3 << 'PYEOF'
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    print(ip)
except:
    print("192.168.1.100")
PYEOF
)

echo -e "${YELLOW}[INFO] 检测到内网IP: ${LOCAL_IP}${NC}"

# 1. 恢复 config/config.json
echo -e "${YELLOW}[1/3] 恢复 config/config.json...${NC}"
python3 << EOF
import json
import sys

config_file = "config/config.json"

try:
    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    config['SERVER_ADDR'] = "AUTO_DETECT"
    config['SERVER_PUBLIC_PORT'] = None
    
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    
    print(f"[SUCCESS] 已恢复 config/config.json")
except Exception as e:
    print(f"[ERROR] 恢复失败: {e}", file=sys.stderr)
    sys.exit(1)
EOF

# 2. 恢复 sip_client_config.json
echo -e "${YELLOW}[2/3] 恢复 sip_client_config.json...${NC}"
python3 << EOF
import json
import sys

config_file = "sip_client_config.json"

try:
    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    config['server_ip'] = "AUTO_DETECT"
    config['local_ip'] = "AUTO_DETECT"
    config['sdp_ip'] = "AUTO_DETECT"
    
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    print(f"[SUCCESS] 已恢复 sip_client_config.json")
except Exception as e:
    print(f"[ERROR] 恢复失败: {e}", file=sys.stderr)
    sys.exit(1)
EOF

# 3. 恢复 ecosystem.config.js
echo -e "${YELLOW}[3/3] 恢复 ecosystem.config.js...${NC}"
python3 << EOF
import re
import sys

ecosystem_file = "ecosystem.config.js"

try:
    with open(ecosystem_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 替换 SERVER_IP
    pattern = r"(SERVER_IP:\s*['\"])([^'\"]+)(['\"])"
    new_content = re.sub(pattern, r"\1AUTO_DETECT\3", content)
    
    if new_content != content:
        with open(ecosystem_file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"[SUCCESS] 已恢复 ecosystem.config.js")
    else:
        print(f"[INFO] ecosystem.config.js 已经是 AUTO_DETECT")
except Exception as e:
    print(f"[ERROR] 恢复失败: {e}", file=sys.stderr)
    sys.exit(1)
EOF

# 4. 停止所有隧道服务
echo -e "${YELLOW}[INFO] 停止所有隧道服务...${NC}"
pkill -f ngrok 2>/dev/null || true
pkill -f cloudflared 2>/dev/null || true
pkill -f frpc 2>/dev/null || true
pkill -f bore 2>/dev/null || true
pkill -f "lt --port" 2>/dev/null || true

# 5. 清除环境变量（如果使用PM2）
echo -e "${YELLOW}[INFO] 清除PM2环境变量...${NC}"
if command -v pm2 &> /dev/null; then
    pm2 restart ecosystem.config.js 2>/dev/null || true
    echo -e "${GREEN}[SUCCESS] PM2已重启，使用新配置${NC}"
fi

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  已恢复到局域网版本${NC}"
echo -e "${GREEN}  内网IP: ${LOCAL_IP}${NC}"
echo -e "${GREEN}  所有配置已设置为 AUTO_DETECT${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "${YELLOW}提示:${NC}"
echo -e "  - 服务将自动使用内网IP: ${LOCAL_IP}"
echo -e "  - 如需公网访问，请使用内网穿透方案"
echo -e "  - 查看文档: docs/FREE_TUNNEL_SOLUTIONS.md"
