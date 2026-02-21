# frp 内网穿透搭建指南

frp是一个高性能的反向代理应用，可以将内网服务暴露到公网。适合需要固定域名和端口的生产环境。

## 架构说明

frp需要两部分：
1. **frps (服务器端)** - 运行在有公网IP的服务器上
2. **frpc (客户端)** - 运行在内网服务器上

```
内网服务器 (frpc)  ←→  frp服务器 (frps)  ←→  公网用户
   5060/UDP             7000/TCP             公网IP:5060
```

## 方案一：使用项目安装脚本（推荐）

### 1. 安装frp客户端

```bash
./scripts/install_frp.sh
```

脚本会自动：
- 检测操作系统和架构
- 下载对应版本的frp
- 安装到 `tools/frp/` 目录
- 创建配置文件模板 `frpc.ini`

### 2. 配置frp客户端

编辑 `frpc.ini`:

```ini
[common]
server_addr = your-frp-server.com  # 替换为你的frp服务器地址
server_port = 7000                  # frp服务器端口
token = your-secret-token           # 认证token（需要与服务器端一致）

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
```

### 3. 启动服务

```bash
./scripts/start_with_tunnel.sh frp pm2
```

---

## 方案二：手动安装

### 客户端安装（内网服务器）

```bash
# 1. 下载frp
cd /tmp
wget https://github.com/fatedier/frp/releases/download/v0.52.3/frp_0.52.3_linux_amd64.tar.gz

# 2. 解压
tar xzf frp_0.52.3_linux_amd64.tar.gz
cd frp_0.52.3_linux_amd64

# 3. 复制客户端文件
sudo cp frpc /usr/local/bin/
sudo chmod +x /usr/local/bin/frpc

# 4. 创建配置文件
sudo mkdir -p /etc/frp
sudo cp frpc.ini /etc/frp/
```

### 服务器端安装（有公网IP的服务器）

```bash
# 1. 下载frp
cd /tmp
wget https://github.com/fatedier/frp/releases/download/v0.52.3/frp_0.52.3_linux_amd64.tar.gz

# 2. 解压
tar xzf frp_0.52.3_linux_amd64.tar.gz
cd frp_0.52.3_linux_amd64

# 3. 复制服务器端文件
sudo cp frps /usr/local/bin/
sudo chmod +x /usr/local/bin/frps

# 4. 创建配置文件
sudo mkdir -p /etc/frp
sudo tee /etc/frp/frps.ini > /dev/null << EOF
[common]
bind_port = 7000
token = your-secret-token-here
EOF

# 5. 创建systemd服务
sudo tee /etc/systemd/system/frps.service > /dev/null << EOF
[Unit]
Description=frp server
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/frps -c /etc/frp/frps.ini
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
EOF

# 6. 启动服务
sudo systemctl daemon-reload
sudo systemctl enable frps
sudo systemctl start frps
sudo systemctl status frps
```

---

## 配置说明

### 服务器端配置 (frps.ini)

```ini
[common]
# 监听端口
bind_port = 7000

# 认证token（客户端必须使用相同的token）
token = your-secret-token-here

# 可选：Web管理界面
dashboard_port = 7500
dashboard_user = admin
dashboard_pwd = admin123

# 可选：日志
log_file = /var/log/frps.log
log_level = info
log_max_days = 3
```

### 客户端配置 (frpc.ini)

```ini
[common]
server_addr = your-frp-server.com
server_port = 7000
token = your-secret-token-here

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

# Web管理界面
[web]
type = tcp
local_ip = 127.0.0.1
local_port = 8888
remote_port = 8888
```

---

## 防火墙配置

### 服务器端（frps）

```bash
# 开放frp端口
sudo ufw allow 7000/tcp

# 开放SIP端口（映射后的端口）
sudo ufw allow 5060/udp
sudo ufw allow 5061/tcp
sudo ufw allow 8888/tcp

# 可选：开放Web管理界面
sudo ufw allow 7500/tcp
```

### 客户端（frpc）

```bash
# 通常不需要开放端口，因为是通过frps转发
# 但确保本地服务正常运行
netstat -tuln | grep 5060
```

---

## 使用方式

### 方式1：使用项目脚本（推荐）

```bash
# 安装frp客户端
./scripts/install_frp.sh

# 编辑配置文件
vim frpc.ini

# 启动服务
./scripts/start_with_tunnel.sh frp pm2
```

### 方式2：手动启动

```bash
# 启动frp客户端
frpc -c /etc/frp/frpc.ini

# 或使用systemd
sudo systemctl start frpc
sudo systemctl enable frpc
```

---

## 验证配置

### 1. 检查frp连接

```bash
# 查看frpc日志
tail -f /tmp/frpc.log

# 或查看systemd日志
sudo journalctl -u frpc -f
```

### 2. 测试SIP连接

```bash
# 从公网测试UDP连接
nc -uv your-frp-server.com 5060

# 从公网测试TCP连接
nc -v your-frp-server.com 5061
```

### 3. 访问Web管理界面

如果配置了dashboard，访问：
```
http://your-frp-server.com:7500
```

---

## 常见问题

### Q: 如何获取frp服务器？

A: 需要一台有公网IP的服务器：
1. **云服务器**：阿里云、腾讯云、AWS等
2. **VPS**：Vultr、DigitalOcean等
3. **自建服务器**：如果有公网IP

### Q: 免费方案推荐？

A: 如果没有frp服务器，推荐使用：
- **Cloudflare Tunnel** - 完全免费，无需服务器
- **ngrok** - 免费版可用，需要注册

### Q: frp服务器需要什么配置？

A: 
- **最低配置**：1核1G内存即可
- **带宽**：根据并发连接数，建议至少5Mbps
- **端口**：需要开放7000端口（frp服务端口）

### Q: 如何设置固定域名？

A: 
1. 在frps服务器配置域名解析
2. 使用nginx反向代理
3. 或使用frp的subdomain功能（需要域名）

---

## 相关文件

- `scripts/install_frp.sh` - frp客户端安装脚本
- `scripts/start_with_tunnel.sh` - 隧道启动脚本
- `frpc.ini` - frp客户端配置文件模板
- `docs/FREE_TUNNEL_SOLUTIONS.md` - 免费方案对比

---

## 参考资源

- frp官方文档: https://gofrp.org/docs/
- frp GitHub: https://github.com/fatedier/frp
- frp下载: https://github.com/fatedier/frp/releases
