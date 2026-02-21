# 动态公网IP使用指南

## 快速开始

### 方法一：使用自动启动脚本（推荐 - 有公网IP）

```bash
# 使用 PM2 启动（会自动获取公网IP并更新所有配置）
./scripts/start_with_public_ip.sh pm2

# 或直接启动
./scripts/start_with_public_ip.sh direct
```

### 方法二：使用内网穿透（推荐 - NAT环境）

如果你的服务器在NAT后（局域网），使用内网穿透服务：

```bash
# Cloudflare Tunnel（推荐，完全免费，速度快）
./scripts/start_with_tunnel.sh cloudflare pm2

# ngrok（支持UDP，需要注册）
./scripts/start_with_tunnel.sh ngrok pm2

# 其他免费方案
./scripts/start_with_tunnel.sh localtunnel pm2  # HTTP only
./scripts/start_with_tunnel.sh bore pm2         # TCP only
./scripts/start_with_tunnel.sh frp pm2          # 需要自建服务器
```

**📖 详细对比和更多方案，请查看：[免费内网穿透方案对比](docs/FREE_TUNNEL_SOLUTIONS.md)**

启动脚本会自动：
1. 获取当前公网IP地址
2. 更新 `config/config.json` 中的 `SERVER_ADDR`
3. 更新 `sip_client_config.json` 中的相关IP配置
4. 更新 `ecosystem.config.js` 中的 `SERVER_IP` 环境变量
5. 启动服务

### 方法二：手动设置环境变量

```bash
# 获取公网IP
export SERVER_IP=$(python3 scripts/get_public_ip.py)

# 启动服务
pm2 start ecosystem.config.js
```

### 方法三：使用内网穿透（适用于NAT环境）

如果你的服务器在局域网内，需要使用内网穿透服务。详见 `docs/DYNAMIC_IP_SOLUTION.md`。

## 配置文件说明

所有配置文件中的IP地址已更新为 `AUTO_DETECT`，表示会自动检测或使用启动脚本设置的IP。

- `config/config.json`: `SERVER_ADDR` = `"AUTO_DETECT"`
- `sip_client_config.json`: `server_ip`, `local_ip`, `sdp_ip` = `"AUTO_DETECT"`
- `ecosystem.config.js`: `SERVER_IP` = `'AUTO_DETECT'`

启动脚本会自动将这些 `AUTO_DETECT` 替换为实际获取的公网IP。

## 验证配置

```bash
# 检查当前公网IP
python3 scripts/get_public_ip.py

# 检查配置文件
cat config/config.json | grep SERVER_ADDR
cat sip_client_config.json | grep server_ip
```

## 常见问题

### Q: 获取到的IP是内网IP怎么办？

A: 如果服务器在NAT后（如家庭宽带），需要使用内网穿透方案：

**免费方案推荐：**
1. **Cloudflare Tunnel** ⭐⭐⭐⭐⭐ - 完全免费，速度快，项目已集成
2. **ngrok** ⭐⭐⭐⭐ - 支持UDP，需要注册
3. **localtunnel** ⭐⭐⭐ - 简单快速，仅HTTP
4. **frp自建** ⭐⭐⭐⭐ - 完全可控，适合生产

**快速使用：**
```bash
# Cloudflare Tunnel（推荐）
./scripts/start_with_tunnel.sh cloudflare pm2

# 或查看详细对比
cat docs/FREE_TUNNEL_SOLUTIONS.md
```

详见 `docs/FREE_TUNNEL_SOLUTIONS.md` 和 `docs/DYNAMIC_IP_SOLUTION.md`。

### Q: 每次启动IP都会变化吗？

A: 
- 如果使用动态获取公网IP方案，IP取决于你的网络环境
- 如果使用内网穿透（如ngrok免费版），每次启动地址会变化
- 可以使用DDNS服务固定域名，或使用付费的内网穿透服务

### Q: 如何固定IP地址？

A: 
1. 手动设置：编辑配置文件，将 `AUTO_DETECT` 替换为实际IP
2. 使用环境变量：`export SERVER_IP=your.ip.address`
3. 使用DDNS：配置动态DNS服务

## 相关文件

- `scripts/get_public_ip.py` - 获取公网IP工具
- `scripts/start_with_public_ip.sh` - 自动启动脚本（有公网IP时）
- `scripts/start_with_tunnel.sh` - 内网穿透启动脚本（NAT环境）
- `QUICK_START_TUNNEL.md` - 快速开始指南
- `docs/FREE_TUNNEL_SOLUTIONS.md` - 免费内网穿透方案完整对比
- `docs/DYNAMIC_IP_SOLUTION.md` - 完整解决方案文档
- `docs/NAT_PORT_MAPPING.md` - NAT端口映射配置
