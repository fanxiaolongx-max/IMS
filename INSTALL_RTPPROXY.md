# RTPProxy 安装和配置指南

本文档说明如何安装和配置RTPProxy，以替代自定义的RTP转发代码。

## 1. 安装 RTPProxy

### Ubuntu/Debian
```bash
apt-get update
apt-get install rtpproxy
```

### CentOS/RHEL
```bash
yum install rtpproxy
# 或
dnf install rtpproxy
```

### 从源码编译
```bash
git clone https://github.com/sippy/rtpproxy.git
cd rtpproxy
./configure
make
make install
```

## 2. 启动 RTPProxy

### 方式1: 使用TCP socket（推荐用于测试）
```bash
rtpproxy -l <服务器IP> -s udp:127.0.0.1:7722 -F
```

例如：
```bash
rtpproxy -l 113.44.149.111 -s udp:127.0.0.1:7722 -F
```

### 方式2: 使用Unix socket（推荐用于生产环境）
```bash
rtpproxy -l <服务器IP> -s unix:/var/run/rtpproxy.sock -F
```

例如：
```bash
rtpproxy -l 113.44.149.111 -s unix:/var/run/rtpproxy.sock -F
```

### 参数说明
- `-l <IP>`: 监听IP地址（服务器公网IP）
- `-s <socket>`: 控制socket（udp:IP:PORT 或 unix:PATH）
- `-F`: 前台运行（生产环境建议使用systemd管理）

## 3. 使用 systemd 管理（生产环境推荐）

创建 `/etc/systemd/system/rtpproxy.service`:

```ini
[Unit]
Description=RTPProxy RTP Proxy Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/rtpproxy -l <服务器IP> -s unix:/var/run/rtpproxy.sock -F
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
```

启动服务：
```bash
systemctl daemon-reload
systemctl enable rtpproxy
systemctl start rtpproxy
systemctl status rtpproxy
```

## 4. 修改代码使用 RTPProxy

在 `run.py` 中，将：

```python
from sipcore.media_relay import init_media_relay, get_media_relay
```

替换为：

```python
from sipcore.rtpproxy_media_relay import init_media_relay, get_media_relay
```

并在初始化时指定rtpproxy地址：

```python
# 使用TCP socket
media_relay = init_media_relay(
    server_ip=SERVER_IP,
    rtpproxy_tcp=('127.0.0.1', 7722)
)

# 或使用Unix socket
media_relay = init_media_relay(
    server_ip=SERVER_IP,
    rtpproxy_socket='/var/run/rtpproxy.sock'
)
```

## 5. 验证安装

检查rtpproxy是否运行：
```bash
ps aux | grep rtpproxy
netstat -tuln | grep 7722  # 如果使用TCP socket
ls -l /var/run/rtpproxy.sock  # 如果使用Unix socket
```

## 6. 故障排查

### rtpproxy无法启动
- 检查端口是否被占用
- 检查socket文件权限
- 查看rtpproxy日志

### Python无法连接rtpproxy
- 确认rtpproxy已启动
- 检查socket路径或TCP地址是否正确
- 检查防火墙设置

### 媒体无法转发
- 检查rtpproxy日志
- 确认服务器IP配置正确
- 检查RTP端口是否开放

## 7. RTPProxy 优势

相比自定义RTP转发代码，RTPProxy提供：
- ✅ 成熟稳定，广泛用于生产环境
- ✅ 自动处理NAT穿透和对称RTP
- ✅ 高性能，低延迟
- ✅ 支持ICE、SRTP等高级特性
- ✅ 完善的错误处理和日志

## 参考链接

- RTPProxy官方文档: https://www.rtpproxy.org/
- GitHub仓库: https://github.com/sippy/rtpproxy
- Kamailio集成: https://kamailio.org/docs/modules/devel/modules/rtpproxy.html
