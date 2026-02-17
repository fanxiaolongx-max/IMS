# RTPProxy快速启动指南

## 问题诊断

根据日志显示：
```
[B2BUA] RTPProxy媒体中继初始化失败: [Errno 111] Connection refused
```

这说明RTPProxy服务未运行。

## 快速解决方案

### 方式1: 使用自动安装脚本（推荐）

```bash
cd /root/fanxiaolongx-max/IMS
./install_and_start_rtpproxy.sh
```

脚本会：
1. 检查RTPProxy是否已安装
2. 如果未安装，提供安装选项
3. 启动RTPProxy服务

### 方式2: 手动安装和启动

#### 步骤1: 安装RTPProxy

**从源码编译（推荐）**：
```bash
cd /usr/src
git clone https://github.com/sippy/rtpproxy.git
cd rtpproxy
git submodule update --init --recursive
./configure
make clean all
make install
```

**或使用包管理器（如果可用）**：
```bash
# Debian/Ubuntu (如果仓库中有)
apt-get update
apt-get install rtpproxy

# CentOS/RHEL
yum install rtpproxy
```

#### 步骤2: 启动RTPProxy

根据你的服务器IP（从日志看是 `113.44.149.111`）：

**UDP socket模式（推荐用于测试）**：
```bash
rtpproxy -l 113.44.149.111 -s udp:127.0.0.1:7722 -F -d INFO
```

**Unix socket模式（推荐用于生产）**：
```bash
rtpproxy -l 113.44.149.111 -s unix:/var/run/rtpproxy.sock -F -d INFO
```

#### 步骤3: 验证RTPProxy运行

```bash
# 检查进程
ps aux | grep rtpproxy

# 运行诊断脚本
python3 check_rtpproxy.py
```

#### 步骤4: 重启SIP服务器

重启你的SIP服务器（如使用PM2）：
```bash
pm2 restart ims-serv
# 或
pm2 restart ims-server
```

## 验证

启动RTPProxy后，查看日志应该看到：
```
[B2BUA] RTPProxy媒体中继已初始化，服务器IP: 113.44.149.111
[B2BUA] RTPProxy地址: 127.0.0.1:7722
```

## 常见问题

### Q1: RTPProxy启动失败

**错误**: `rtpproxy: command not found`

**解决**: RTPProxy未安装，按照"方式2"的步骤1安装

### Q2: 权限错误

**错误**: `Permission denied` 或无法创建socket

**解决**: 
```bash
# 确保有权限创建socket文件
sudo mkdir -p /var/run
sudo chmod 777 /var/run
```

### Q3: 端口被占用

**错误**: `Address already in use`

**解决**: 
```bash
# 查找占用端口的进程
lsof -i :7722
# 或
netstat -tulpn | grep 7722

# 停止占用进程或使用其他端口
```

### Q4: 媒体转发仍然失败

**检查清单**:
1. ✅ RTPProxy是否运行: `ps aux | grep rtpproxy`
2. ✅ RTPProxy是否响应: `python3 check_rtpproxy.py`
3. ✅ SIP服务器日志中是否有RTPProxy初始化成功的消息
4. ✅ 防火墙是否允许RTP端口（通常10000-20000范围）

## 后台运行（生产环境）

使用systemd服务（推荐）：

创建 `/etc/systemd/system/rtpproxy.service`:
```ini
[Unit]
Description=RTPProxy media server
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/rtpproxy -l 113.44.149.111 -s udp:127.0.0.1:7722 -F -d INFO
Restart=always
RestartSec=5

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

## 下一步

1. 启动RTPProxy后，测试WiFi下的通话
2. 观察日志确认媒体转发是否正常
3. 如果仍有问题，检查RTPProxy日志: `tail -f /var/log/rtpproxy.log`
