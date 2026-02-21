# 动态公网IP解决方案

本文档提供多种方案，解决局域网服务需要暴露到公网的问题。

## 方案一：动态获取公网IP（推荐用于有公网IP的服务器）

如果你的服务器有公网IP但IP会变化，可以使用此方案。

### 使用方法

1. **使用启动脚本（推荐）**
   ```bash
   # 使用 PM2 启动
   ./scripts/start_with_public_ip.sh pm2
   
   # 或直接启动
   ./scripts/start_with_public_ip.sh direct
   ```

2. **手动获取并设置**
   ```bash
   # 获取公网IP
   export SERVER_IP=$(python3 scripts/get_public_ip.py)
   
   # 启动服务
   pm2 start ecosystem.config.js
   ```

### 工作原理

- 启动脚本会自动调用 `scripts/get_public_ip.py` 获取当前公网IP
- 更新 `config/config.json` 中的 `SERVER_ADDR`
- 更新 `sip_client_config.json` 中的相关IP配置
- 更新 `ecosystem.config.js` 中的 `SERVER_IP` 环境变量
- 使用获取到的IP启动服务

### 限制

- **仅适用于有公网IP的服务器**
- 如果服务器在NAT后（如家庭宽带、企业内网），此方案无法获取到真正的公网IP
- 对于NAT环境，请使用方案二（内网穿透）

---

## 方案二：内网穿透（推荐用于NAT环境）

如果你的服务器在局域网内（如家庭宽带、企业内网），需要使用内网穿透服务。

**📖 详细对比和更多免费方案，请查看：[免费内网穿透方案对比](FREE_TUNNEL_SOLUTIONS.md)**

### 2.1 使用 ngrok（最简单）

ngrok 提供免费的临时公网地址，适合开发和测试。

#### 安装 ngrok

```bash
# macOS
brew install ngrok

# Linux
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
tar xvzf ngrok-v3-stable-linux-amd64.tgz
sudo mv ngrok /usr/local/bin/

# 或使用 snap
sudo snap install ngrok
```

#### 注册并配置

1. 访问 https://dashboard.ngrok.com/ 注册账号
2. 获取 authtoken
3. 配置：
   ```bash
   ngrok config add-authtoken YOUR_AUTH_TOKEN
   ```

#### 启动 ngrok 隧道

```bash
# 为 SIP 服务创建隧道（UDP 5060）
ngrok udp 5060

# 为 Web 服务创建隧道（HTTP 8888）
ngrok http 8888

# 同时创建多个隧道（需要付费版）
# 或使用配置文件 ngrok.yml
```

#### 使用 ngrok 地址

ngrok 会显示类似这样的地址：
```
Forwarding  udp://0.tcp.ngrok.io:12345 -> localhost:5060
```

使用 `0.tcp.ngrok.io` 作为公网地址，端口为 `12345`。

#### 自动启动脚本

创建 `scripts/start_with_ngrok.sh`：

```bash
#!/bin/bash
# 启动 ngrok 并获取地址，然后启动服务

# 启动 ngrok（后台运行）
ngrok udp 5060 --log stdout > /tmp/ngrok.log 2>&1 &
NGROK_PID=$!

# 等待 ngrok 启动
sleep 3

# 从 ngrok API 获取公网地址
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c "
import sys, json
data = json.load(sys.stdin)
for tunnel in data.get('tunnels', []):
    if tunnel.get('proto') == 'udp':
        url = tunnel.get('public_url', '').replace('udp://', '')
        host, port = url.split(':')
        print(host)
        break
")

if [ -z "$NGROK_URL" ]; then
    echo "无法获取 ngrok 地址"
    kill $NGROK_PID
    exit 1
fi

export SERVER_IP="$NGROK_URL"
echo "使用 ngrok 公网地址: $NGROK_URL"

# 启动服务
./scripts/start_with_public_ip.sh pm2

# 清理
trap "kill $NGROK_PID" EXIT
```

---

### 2.2 使用 frp（开源，可自建服务器）

frp 是一个开源的内网穿透工具，可以自建服务器，适合生产环境。

#### 安装 frp

```bash
# 下载 frp
wget https://github.com/fatedier/frp/releases/download/v0.52.3/frp_0.52.3_linux_amd64.tar.gz
tar xzf frp_0.52.3_linux_amd64.tar.gz
cd frp_0.52.3_linux_amd64

# 客户端文件
sudo cp frpc /usr/local/bin/
sudo cp frpc.ini /etc/frpc.ini
```

#### 配置 frp 客户端

编辑 `/etc/frpc.ini`：

```ini
[common]
server_addr = your-frp-server.com  # frp 服务器地址
server_port = 7000                  # frp 服务器端口
token = your-token                  # 认证token

[sip_udp]
type = udp
local_ip = 127.0.0.1
local_port = 5060
remote_port = 5060

[sip_tcp]
type = tcp
local_ip = 127.0.0.1
local_port = 5060
remote_port = 5061

[web]
type = tcp
local_ip = 127.0.0.1
local_port = 8888
remote_port = 8888
```

#### 启动 frp

```bash
# 启动 frp 客户端
frpc -c /etc/frpc.ini

# 或使用 systemd
sudo systemctl enable frpc
sudo systemctl start frpc
```

#### 获取公网地址

frp 服务器会分配公网地址，格式为：`your-frp-server.com:5060`

---

### 2.3 使用 Cloudflare Tunnel（免费，适合HTTP/HTTPS）

Cloudflare Tunnel 提供免费的HTTP/HTTPS隧道，适合Web服务。

#### 安装 cloudflared

```bash
# macOS
brew install cloudflared

# Linux
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared-linux-amd64
sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared
```

#### 登录并创建隧道

```bash
cloudflared tunnel login
cloudflared tunnel create ims-tunnel
```

#### 配置隧道

创建 `~/.cloudflared/config.yml`：

```yaml
tunnel: <tunnel-id>
credentials-file: /home/user/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: ims.yourdomain.com
    service: http://localhost:8888
  - service: http_status:404
```

#### 启动隧道

```bash
cloudflared tunnel run ims-tunnel
```

---

## 方案三：动态DNS（DDNS）

如果你的服务器有公网IP但IP会变化，可以使用DDNS服务。

### 使用 DuckDNS（免费）

1. 访问 https://www.duckdns.org/ 注册
2. 创建域名，如 `yourname.duckdns.org`
3. 设置更新脚本：

```bash
#!/bin/bash
# 更新 DuckDNS
TOKEN="your-token"
DOMAIN="yourname"
curl "https://www.duckdns.org/update?domains=$DOMAIN&token=$TOKEN&ip="

# 获取当前IP并设置
export SERVER_IP=$(host yourname.duckdns.org | awk '/has address/ {print $4}')
./scripts/start_with_public_ip.sh pm2
```

### 使用阿里云/腾讯云DDNS

如果你有云服务器，可以使用云服务商的DDNS服务。

---

## 方案四：修改代码支持动态IP检测

如果使用内网穿透，可以修改 `run.py` 中的 `get_server_ip()` 函数，支持从环境变量或配置文件读取公网地址。

### 增强 get_server_ip() 函数

已经在 `run.py` 中实现了优先级：
1. 环境变量 `SERVER_IP`
2. 配置文件 `SERVER_ADDR`
3. 自动检测本机IP
4. 默认值

### 使用内网穿透时的配置

```bash
# 设置内网穿透的公网地址
export SERVER_IP="0.tcp.ngrok.io"  # ngrok 地址
export SERVER_PORT="12345"          # ngrok 端口

# 或更新配置文件
# config/config.json
{
  "SERVER_ADDR": "0.tcp.ngrok.io",
  "SERVER_PORT": 12345
}
```

---

## 推荐方案选择

| 场景 | 推荐方案 | 说明 |
|------|---------|------|
| 有公网IP，IP会变化 | 方案一 + 方案三 | 动态获取IP + DDNS |
| 家庭宽带/NAT环境 | 方案二（ngrok/frp） | 内网穿透 |
| 云服务器，有弹性IP | 方案一 | 直接使用弹性IP |
| 生产环境 | 方案二（frp自建） | 稳定可控 |
| 开发测试 | 方案二（ngrok） | 简单快速 |

---

## 常见问题

### Q: 为什么获取到的IP是内网IP？

A: 如果服务器在NAT后，`get_public_ip.py` 获取的是出口公网IP，但该IP可能不是你服务器的直接IP。需要使用内网穿透方案。

### Q: ngrok 地址每次启动都变化怎么办？

A: ngrok 免费版地址会变化。可以：
1. 使用付费版固定域名
2. 使用 frp 自建服务器
3. 每次启动后自动更新配置文件

### Q: 如何验证公网IP是否正确？

A: 
```bash
# 检查当前配置的IP
python3 scripts/get_public_ip.py

# 检查服务是否可访问
curl http://YOUR_PUBLIC_IP:8888/login.html
```

---

## 相关文件

- `scripts/get_public_ip.py` - 获取公网IP工具
- `scripts/start_with_public_ip.sh` - 自动启动脚本
- `config/config.json` - 主配置文件
- `sip_client_config.json` - SIP客户端配置
- `ecosystem.config.js` - PM2配置
