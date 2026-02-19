# 公网部署配置指南

本文档说明如何将 IMS SIP 服务器部署到公网，并配置公网 SIP 服务器地址和外呼服务器地址。

## 1. SIP 服务器地址配置

### 方式一：环境变量配置（推荐）

在启动服务器前设置环境变量：

```bash
# 设置公网 SIP 服务器 IP 地址
export SERVER_IP=your.public.ip.address

# 设置 SIP 服务器端口（默认 5060）
export SERVER_PORT=5060

# 启动服务器
python run.py
```

### 方式二：修改代码配置

编辑 `run.py` 文件，修改以下配置：

```python
# 第 78-79 行
SERVER_IP = "your.public.ip.address"  # 公网 IP 地址
SERVER_PORT = 5060  # SIP 端口

# 第 81-82 行（可选，用于 Cloudflare 隧道等场景）
SERVER_PUBLIC_HOST = None  # 例如 xxx.trycloudflare.com
SERVER_PUBLIC_PORT = None  # 隧道 TCP 端口
```

### 方式三：使用配置文件（推荐用于生产环境）

编辑 `config/config.json`，添加服务器配置：

```json
{
    "SERVER_IP": "your.public.ip.address",
    "SERVER_PORT": 5060,
    "SERVER_PUBLIC_HOST": null,
    "SERVER_PUBLIC_PORT": null,
    "FORCE_LOCAL_ADDR": false,
    "USERS": {
        "1001": "1234",
        "1002": "1234"
    },
    "LOG_LEVEL": "DEBUG",
    "CDR_MERGE_MODE": true
}
```

然后在 `run.py` 中读取配置：

```python
# 从配置文件读取（需要添加代码）
config_mgr = init_config_manager("config/config.json")
SERVER_IP = config_mgr.get("SERVER_IP") or get_server_ip()
SERVER_PORT = config_mgr.get("SERVER_PORT", 5060)
```

## 2. 外呼服务器地址配置

外呼服务器地址在 `sip_client_config.json` 文件中配置：

```json
{
  "server_ip": "your.public.ip.address",
  "server_port": 5060,
  "username": "0000",
  "password": "0000",
  "local_ip": "your.public.ip.address",
  "local_port": 20000,
  "sdp_ip": "your.public.ip.address",
  "media_dir": "media",
  "media_file": "media/default.wav"
}
```

**配置说明：**
- `server_ip`: 外呼客户端连接的 SIP 服务器地址（应与 SERVER_IP 一致）
- `server_port`: SIP 服务器端口（默认 5060）
- `local_ip`: 外呼客户端的本地 IP（公网部署时使用公网 IP）
- `sdp_ip`: SDP 中的媒体地址（公网部署时使用公网 IP）

## 3. 防火墙配置

确保以下端口已开放：

- **5060/UDP**: SIP 信令端口（必需）
- **5060/TCP**: SIP 信令端口（如果启用 TCP 支持）
- **10000-20000/UDP**: RTP 媒体端口范围（用于音视频传输）
- **8888/TCP**: MML 管理界面端口（可选）
- **8889/TCP**: WebSocket 端口（可选）

### Linux 防火墙配置示例

```bash
# UFW (Ubuntu/Debian)
sudo ufw allow 5060/udp
sudo ufw allow 5060/tcp
sudo ufw allow 10000:20000/udp
sudo ufw allow 8888/tcp
sudo ufw allow 8889/tcp

# firewalld (CentOS/RHEL)
sudo firewall-cmd --permanent --add-port=5060/udp
sudo firewall-cmd --permanent --add-port=5060/tcp
sudo firewall-cmd --permanent --add-port=10000-20000/udp
sudo firewall-cmd --permanent --add-port=8888/tcp
sudo firewall-cmd --permanent --add-port=8889/tcp
sudo firewall-cmd --reload
```

## 4. NAT 穿透配置

如果服务器在 NAT 后面，需要配置：

### 4.1 STUN 服务器配置

编辑 `run.py`，配置 STUN 服务器：

```python
# STUN 服务器配置（用于 NAT 穿透）
STUN_SERVER = "stun:stun.l.google.com:19302"
```

### 4.2 RTPProxy 配置（推荐）

如果使用 RTPProxy 进行媒体中继，配置：

```python
# RTPProxy 配置
RTPPROXY_UDP_HOST = os.getenv("RTPPROXY_UDP_HOST", "127.0.0.1")
RTPPROXY_UDP_PORT = int(os.getenv("RTPPROXY_UDP_PORT", "7722"))
```

确保 RTPProxy 监听在公网可访问的地址。

## 5. 完整部署示例

### 5.1 使用环境变量部署

```bash
# 1. 设置环境变量
export SERVER_IP=203.0.113.10  # 替换为你的公网 IP
export SERVER_PORT=5060

# 2. 配置外呼服务器
cat > sip_client_config.json << EOF
{
  "server_ip": "203.0.113.10",
  "server_port": 5060,
  "username": "0000",
  "password": "0000",
  "local_ip": "203.0.113.10",
  "local_port": 20000,
  "sdp_ip": "203.0.113.10",
  "media_dir": "media",
  "media_file": "media/default.wav"
}
EOF

# 3. 启动服务器
python run.py
```

### 5.2 使用 systemd 服务部署

创建 `/etc/systemd/system/ims-sip-server.service`：

```ini
[Unit]
Description=IMS SIP Server
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/ims
Environment="SERVER_IP=203.0.113.10"
Environment="SERVER_PORT=5060"
ExecStart=/usr/bin/python3 /path/to/ims/run.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable ims-sip-server
sudo systemctl start ims-sip-server
sudo systemctl status ims-sip-server
```

## 6. 验证配置

### 6.1 检查服务器监听

```bash
# 检查 SIP 端口是否监听
netstat -tuln | grep 5060

# 应该看到：
# udp        0      0 0.0.0.0:5060            0.0.0.0:*
```

### 6.2 测试 SIP 注册

使用 SIP 客户端（如 Linphone）注册到服务器：

- 服务器地址：`your.public.ip.address:5060`
- 用户名：`1001`
- 密码：`1234`（根据 config.json 配置）

### 6.3 测试外呼功能

通过 MML 界面测试外呼：

```bash
# 访问 MML 管理界面
http://your.public.ip.address:8888

# 执行外呼命令
STR CALL SINGLE CALLEE=1002
```

## 7. 常见问题

### Q: 服务器无法接收 SIP 消息？

A: 检查：
1. 防火墙是否开放 5060/UDP 端口
2. SERVER_IP 是否正确配置为公网 IP
3. 服务器是否监听在 `0.0.0.0:5060`（而不是 `127.0.0.1:5060`）

### Q: 外呼失败？

A: 检查：
1. `sip_client_config.json` 中的 `server_ip` 是否与 SERVER_IP 一致
2. `local_ip` 和 `sdp_ip` 是否配置为公网 IP
3. 外呼客户端是否能成功注册到服务器

### Q: 媒体（音频/视频）无法传输？

A: 检查：
1. RTP 端口范围（10000-20000/UDP）是否开放
2. 如果使用 RTPProxy，确保 RTPProxy 配置正确
3. SDP 中的媒体地址是否正确（`sdp_ip` 配置）

## 8. 安全建议

1. **使用强密码**：修改默认用户密码
2. **启用 TLS**：如果支持，使用 SIP over TLS（SIPS）
3. **限制访问**：使用防火墙规则限制 SIP 端口访问来源
4. **定期更新**：保持系统和依赖库更新
5. **监控日志**：定期检查日志文件，发现异常访问

## 9. 相关文件

- `run.py`: 主服务器文件，包含 SERVER_IP 配置
- `config/config.json`: 服务器配置文件
- `sip_client_config.json`: 外呼客户端配置文件
- `docs/CLOUDFLARE_TUNNEL.md`: Cloudflare 隧道配置（可选）
