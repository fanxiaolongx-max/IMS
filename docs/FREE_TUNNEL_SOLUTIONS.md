# 免费内网穿透方案对比

本文档介绍多种免费的内网穿透方案，帮助你在NAT环境下将服务暴露到公网。

## 方案对比表

| 方案 | 免费额度 | UDP支持 | TCP支持 | HTTP支持 | 固定域名 | 速度 | 推荐度 |
|------|---------|---------|---------|----------|---------|------|--------|
| **Cloudflare Tunnel** | ✅ 完全免费 | ❌ | ✅ | ✅ | ❌ (每次变化) | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **ngrok** | ✅ 有限制 | ✅ | ✅ | ✅ | ❌ (免费版) | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **localtunnel** | ✅ 完全免费 | ❌ | ❌ | ✅ | ❌ | ⭐⭐⭐ | ⭐⭐⭐ |
| **serveo** | ✅ 完全免费 | ❌ | ✅ | ✅ | ✅ (SSH) | ⭐⭐⭐ | ⭐⭐⭐ |
| **bore** | ✅ 完全免费 | ❌ | ✅ | ❌ | ❌ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| **frp (自建)** | ✅ 完全免费 | ✅ | ✅ | ✅ | ✅ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |

---

## 1. Cloudflare Tunnel（推荐 ⭐⭐⭐⭐⭐）

### 优点
- ✅ **完全免费**，无限制
- ✅ **速度快**，使用Cloudflare全球CDN
- ✅ **HTTPS自动支持**
- ✅ 项目已集成支持

### 缺点
- ❌ **不支持UDP**（SIP需要TCP模式）
- ❌ 免费版域名每次启动会变化

### 安装

```bash
# macOS
brew install cloudflared

# Linux
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared-linux-amd64
sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared
```

### 使用方法

#### 方法1：使用项目内置支持（推荐）

```bash
# 启用Cloudflare隧道
export ENABLE_CF_TUNNEL=1
export SERVER_IP=your.public.ip  # 如果有公网IP，用于RTP媒体
python run.py
```

#### 方法2：手动启动

```bash
# SIP over TCP (5060)
cloudflared tunnel --url tcp://localhost:5060

# HTTP管理界面 (8888)
cloudflared tunnel --url http://localhost:8888
```

### 获取公网地址

启动后会显示类似：
```
Your quick Tunnel has been created! Visit it at:
https://xxxx-xxxx-xxxx.trycloudflare.com
```

**注意**：SIP需要使用TCP模式，UDP无法通过Cloudflare隧道。

---

## 2. ngrok（推荐 ⭐⭐⭐⭐）

### 优点
- ✅ **支持UDP**（SIP UDP可用）
- ✅ 免费版可用
- ✅ 提供Web界面查看流量

### 缺点
- ❌ 免费版有连接数限制
- ❌ 免费版域名每次变化
- ❌ 需要注册账号

### 安装

```bash
# macOS
brew install ngrok

# Linux
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
tar xvzf ngrok-v3-stable-linux-amd64.tgz
sudo mv ngrok /usr/local/bin/

# 或使用snap
sudo snap install ngrok
```

### 注册和配置

1. 访问 https://dashboard.ngrok.com/ 注册账号
2. 获取authtoken
3. 配置：
   ```bash
   ngrok config add-authtoken YOUR_AUTH_TOKEN
   ```

### 使用方法

```bash
# UDP 5060 (SIP)
ngrok udp 5060

# HTTP 8888 (管理界面)
ngrok http 8888

# TCP 5060 (SIP over TCP)
ngrok tcp 5060
```

### 获取公网地址

ngrok会显示：
```
Forwarding  udp://0.tcp.ngrok.io:12345 -> localhost:5060
```

使用 `0.tcp.ngrok.io:12345` 作为公网地址。

### 配置文件方式（推荐）

创建 `ngrok.yml`:

```yaml
version: "2"
authtoken: YOUR_AUTH_TOKEN
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
```

启动：
```bash
ngrok start --all --config ngrok.yml
```

---

## 3. localtunnel（简单快速 ⭐⭐⭐）

### 优点
- ✅ **完全免费**，无需注册
- ✅ 安装简单
- ✅ 适合HTTP服务

### 缺点
- ❌ **只支持HTTP**，不支持UDP/TCP
- ❌ 域名每次变化
- ❌ 速度一般

### 安装

```bash
npm install -g localtunnel
```

### 使用方法

```bash
# HTTP 8888
lt --port 8888

# 指定子域名（需要付费）
lt --port 8888 --subdomain myservice
```

### 获取公网地址

会显示：
```
your url is: https://xxxx.loca.lt
```

---

## 4. serveo（SSH隧道 ⭐⭐⭐）

### 优点
- ✅ **完全免费**，无需安装客户端
- ✅ 支持TCP和HTTP
- ✅ 可以设置固定域名（通过SSH）

### 缺点
- ❌ 需要SSH客户端
- ❌ 不支持UDP
- ❌ 稳定性一般

### 使用方法

```bash
# TCP 5060
ssh -R 80:localhost:5060 serveo.net

# HTTP 8888
ssh -R myservice:80:localhost:8888 serveo.net

# 固定域名（需要SSH密钥）
ssh -R myservice:80:localhost:8888 serveo.net
```

---

## 5. bore（轻量级 ⭐⭐⭐⭐）

### 优点
- ✅ **完全免费**
- ✅ 轻量级，单文件
- ✅ 支持TCP

### 缺点
- ❌ 不支持UDP和HTTP
- ❌ 域名每次变化
- ❌ 需要自建服务器（可选）

### 安装

```bash
# 下载二进制
wget https://github.com/ekzhang/bore/releases/download/v0.5.0/bore-v0.5.0-x86_64-unknown-linux-musl.tar.gz
tar xzf bore-v0.5.0-x86_64-unknown-linux-musl.tar.gz
sudo mv bore /usr/local/bin/
```

### 使用方法

```bash
# TCP 5060
bore local 5060 --to bore.pub
```

### 获取公网地址

会显示：
```
bore.pub:12345
```

---

## 6. frp（自建服务器 ⭐⭐⭐⭐）

### 优点
- ✅ **完全免费**（自建）
- ✅ **支持所有协议**（UDP/TCP/HTTP）
- ✅ **固定域名和端口**
- ✅ 完全可控

### 缺点
- ❌ 需要一台有公网IP的服务器
- ❌ 需要自己搭建和维护

### 快速开始

#### 服务器端（有公网IP）

```bash
# 下载frp
wget https://github.com/fatedier/frp/releases/download/v0.52.3/frp_0.52.3_linux_amd64.tar.gz
tar xzf frp_0.52.3_linux_amd64.tar.gz
cd frp_0.52.3_linux_amd64

# 配置 frps.ini
cat > frps.ini << EOF
[common]
bind_port = 7000
token = your-secret-token
EOF

# 启动服务器
./frps -c frps.ini
```

#### 客户端（内网服务器）

```bash
# 配置 frpc.ini
cat > frpc.ini << EOF
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

# 启动客户端
./frpc -c frpc.ini
```

---

## 推荐方案选择

### 场景1：快速测试/开发
**推荐：Cloudflare Tunnel**
- 无需注册，安装即用
- 速度快，稳定

### 场景2：需要UDP支持（SIP UDP）
**推荐：ngrok 或 frp**
- ngrok：简单快速
- frp：完全可控，适合生产

### 场景3：生产环境
**推荐：frp自建**
- 固定域名和端口
- 完全可控
- 无限制

### 场景4：临时演示
**推荐：localtunnel 或 serveo**
- 最简单，无需安装

---

## 自动化脚本

项目提供了自动化脚本，支持多种隧道服务：

```bash
# 使用Cloudflare Tunnel
./scripts/start_with_tunnel.sh cloudflare

# 使用ngrok
./scripts/start_with_tunnel.sh ngrok

# 使用frp
./scripts/start_with_tunnel.sh frp
```

详见 `scripts/start_with_tunnel.sh` 的使用说明。

---

## 注意事项

### SIP协议支持

- **UDP模式**：需要ngrok或frp
- **TCP模式**：所有方案都支持
- **RTP媒体**：UDP协议，需要服务器有公网IP或使用TURN服务器

### 端口映射

- 内网端口：`5060/UDP`（SIP）
- 公网端口：由隧道服务分配（可能不同）

### 域名变化

- 免费服务域名通常每次启动会变化
- 需要固定域名：使用frp自建或付费服务

### 安全性

- 所有隧道都会暴露服务到公网
- 建议配置防火墙和访问控制
- 使用HTTPS（Cloudflare自动支持）

---

## 相关文件

- `scripts/start_with_tunnel.sh` - 自动化隧道启动脚本
- `sipcore/cloudflare_tunnel.py` - Cloudflare隧道集成
- `docs/CLOUDFLARE_TUNNEL.md` - Cloudflare隧道详细文档
- `docs/DYNAMIC_IP_SOLUTION.md` - 动态IP解决方案
