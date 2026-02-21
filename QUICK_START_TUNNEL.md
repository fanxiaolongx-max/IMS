# 快速开始：使用免费内网穿透

## 🚀 最简单的方式（推荐）

### Cloudflare Tunnel（完全免费，无需注册）

```bash
# 1. 安装 cloudflared
# macOS
brew install cloudflared

# Linux
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared-linux-amd64
sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared

# 2. 启动服务（自动启用Cloudflare隧道）
export ENABLE_CF_TUNNEL=1
./scripts/start_with_tunnel.sh cloudflare pm2
```

启动后，日志会显示公网地址，类似：
```
[CF-TUNNEL] SIP 隧道已启动: xxxx-xxxx-xxxx.trycloudflare.com:443
[CF-TUNNEL] HTTP 隧道已启动: https://yyyy-yyyy-yyyy.trycloudflare.com
```

**注意**：Cloudflare Tunnel只支持TCP，SIP需要使用TCP模式。

---

## 📋 其他免费方案

### ngrok（支持UDP）

```bash
# 1. 安装
brew install ngrok  # macOS
# 或访问 https://ngrok.com/download

# 2. 注册并配置token
ngrok config add-authtoken YOUR_TOKEN

# 3. 启动
./scripts/start_with_tunnel.sh ngrok pm2
```

### localtunnel（仅HTTP，最简单）

```bash
# 1. 安装
npm install -g localtunnel

# 2. 启动（仅Web管理界面）
./scripts/start_with_tunnel.sh localtunnel pm2
```

### bore（TCP，轻量级）

```bash
# 1. 下载
wget https://github.com/ekzhang/bore/releases/download/v0.5.0/bore-v0.5.0-x86_64-unknown-linux-musl.tar.gz
tar xzf bore-v0.5.0-x86_64-unknown-linux-musl.tar.gz
sudo mv bore /usr/local/bin/

# 2. 启动
./scripts/start_with_tunnel.sh bore pm2
```

---

## 🔍 方案对比

| 方案 | 安装难度 | UDP支持 | 速度 | 推荐度 |
|------|---------|---------|------|--------|
| Cloudflare | ⭐ 简单 | ❌ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| ngrok | ⭐⭐ 中等 | ✅ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| localtunnel | ⭐ 简单 | ❌ | ⭐⭐⭐ | ⭐⭐⭐ |
| bore | ⭐⭐ 中等 | ❌ | ⭐⭐⭐⭐ | ⭐⭐⭐ |

---

## 📖 详细文档

- [免费内网穿透方案完整对比](docs/FREE_TUNNEL_SOLUTIONS.md)
- [动态IP解决方案](docs/DYNAMIC_IP_SOLUTION.md)
- [NAT端口映射配置](docs/NAT_PORT_MAPPING.md)

---

## ⚠️ 注意事项

1. **SIP协议**：
   - UDP模式：需要ngrok或frp
   - TCP模式：所有方案都支持

2. **RTP媒体**：
   - UDP协议，无法通过HTTP隧道
   - 需要服务器有公网IP或使用TURN服务器

3. **域名变化**：
   - 免费服务域名每次启动会变化
   - 需要固定域名：使用frp自建或付费服务
