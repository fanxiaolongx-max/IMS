# RTPProxy媒体转发诊断报告

## 问题描述
音频双不通，检查媒体转发器是否真的能转发RTP和RTCP报文。

## 问题根源
**RTPProxy服务未运行**，导致无法创建RTP会话，因此RTP和RTCP报文无法转发。

### 证据
从终端日志（`/root/.cursor/projects/root/terminals/1.txt:25-986`）可以看到：
```
[RTPProxy-ERROR] 命令执行失败: b'VXr33ihdemD Tals06l6k hJBBNSa', 错误: [Errno 111] Connection refused
[RTPProxy-ERROR] 创建answer异常: Xr33ihdemD, 错误=[Errno 111] Connection refused
[RTPProxyMediaRelay] 媒体转发启动失败: Xr33ihdemD
```

`[Errno 111] Connection refused` 表示无法连接到RTPProxy控制socket（127.0.0.1:7722）。

## RTPProxy的作用
RTPProxy是一个成熟的RTP代理服务器，负责：
1. **RTP报文双向转发**：在主叫（A-leg）和被叫（B-leg）之间转发RTP音频数据包
2. **RTCP报文双向转发**：转发RTCP控制报文（用于QoS统计、同步等）
3. **NAT穿透**：通过对称RTP自动学习真实的RTP源地址，实现NAT穿透
4. **端口管理**：自动分配和管理媒体端口

## 解决方案

### 1. 随 IMS 主程序一起启动（推荐）
IMS 默认会**随主程序自动启动 RTPProxy**，无需单独启动。只要正常启动 IMS（如 `python run.py`），RTPProxy 会在检测到本机未运行 RTPProxy 时自动拉起，并在 IMS 退出时一并停止。

- 关闭自动启动：设置环境变量 `RTPPROXY_AUTO_START=0` 后启动 IMS，再自行启动 rtpproxy。
- 若本机已在 127.0.0.1:7722 运行 RTPProxy，IMS 会检测到并跳过自动启动，不会重复起进程。

### 2. 单独启动 RTPProxy（可选）
若使用 `RTPPROXY_AUTO_START=0` 或希望单独管理 RTPProxy，可手动启动：
```bash
cd /root/IMS
SERVER_IP=$(python3 -c "import json; print(json.load(open('config/config.json'))['SERVER_ADDR'])")
rtpproxy -l $SERVER_IP -s udp:127.0.0.1:7722 -F -d INFO
```

**参数说明**：
- `-l $SERVER_IP`：指定RTPProxy监听的IP地址（用于RTP媒体流）
- `-s udp:127.0.0.1:7722`：指定控制socket地址（UDP模式，用于接收控制命令）
- `-F`：前台运行（用于调试）
- `-d INFO`：日志级别

### 3. 验证RTPProxy运行状态
```bash
# 检查进程
ps aux | grep rtpproxy | grep -v grep

# 检查端口
netstat -tuln | grep 7722

# 运行诊断脚本
python3 /root/IMS/check_rtpproxy.py
```

### 4. 确保RTPProxy持续运行（可选）
若未使用“随 IMS 启动”，可选用以下方式之一。

**选项A：使用 systemd 同时管理 IMS 与 RTPProxy**
创建 `/etc/systemd/system/rtpproxy.service`：
```ini
[Unit]
Description=RTPProxy Media Relay Server
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/rtpproxy -l 113.44.149.111 -s udp:127.0.0.1:7722 -F
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

然后启动服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable rtpproxy
sudo systemctl start rtpproxy
sudo systemctl status rtpproxy
```

**选项B：使用screen/tmux（临时方案）**
```bash
screen -S rtpproxy
cd /root/IMS
SERVER_IP=$(python3 -c "import json; print(json.load(open('config/config.json'))['SERVER_ADDR'])")
rtpproxy -l $SERVER_IP -s udp:127.0.0.1:7722 -F
# 按 Ctrl+A 然后 D 退出screen
```

## RTPProxy工作流程

### 1. INVITE阶段（创建offer）
```
SIP服务器 → RTPProxy: V<call_id> <from_tag>
RTPProxy → SIP服务器: <port_number>
```
RTPProxy分配一个媒体端口用于接收主叫的RTP流。

### 2. 200 OK阶段（创建answer）
```
SIP服务器 → RTPProxy: V<call_id> <from_tag> <to_tag>
RTPProxy → SIP服务器: <port_number>
```
RTPProxy分配第二个媒体端口用于接收被叫的RTP流，并建立双向转发。

### 3. RTP/RTCP转发
一旦会话建立，RTPProxy自动：
- 接收主叫发送到第一个端口的RTP/RTCP → 转发到被叫
- 接收被叫发送到第二个端口的RTP/RTCP → 转发到主叫

### 4. BYE阶段（删除会话）
```
SIP服务器 → RTPProxy: D<call_id> <from_tag> <to_tag>
RTPProxy → SIP服务器: OK
```
RTPProxy释放分配的端口和会话资源。

## 验证RTP/RTCP转发

### 方法1：检查RTPProxy日志
RTPProxy会记录所有RTP会话的创建和删除。查看日志确认会话是否成功创建。

### 方法2：使用tcpdump/wireshark抓包
```bash
# 抓取RTP流量（端口范围通常是10000-20000）
tcpdump -i any -n udp portrange 10000-20000 -w rtp_capture.pcap

# 分析抓包文件
wireshark rtp_capture.pcap
```

### 方法3：检查SIP服务器日志
查看SIP服务器日志中是否有以下成功消息：
```
[RTPProxyMediaRelay] 媒体转发已启动: <call_id>
[RTPProxy] 创建answer成功: <call_id>, RTP端口=<port>
```

## 当前状态
✅ **RTPProxy已启动并运行**
- 进程ID: 233941
- 监听地址: 113.44.149.111
- 控制socket: udp:127.0.0.1:7722
- 状态: 运行中

## 注意事项
1. **RTPProxy必须持续运行**：如果RTPProxy停止，所有正在进行的通话的媒体流都会中断
2. **防火墙配置**：确保RTPProxy分配的媒体端口（通常10000-20000）在防火墙中开放
3. **资源监控**：监控RTPProxy的内存和CPU使用情况，特别是在高并发场景下
4. **日志级别**：生产环境建议使用 `-d WARN` 或 `-d ERROR` 以减少日志量

## 相关文件
- RTPProxy客户端代码: `/root/IMS/sipcore/rtpproxy_client.py`
- 媒体中继代码: `/root/IMS/sipcore/rtpproxy_media_relay.py`
- 诊断脚本: `/root/IMS/check_rtpproxy.py`
- 验证脚本: `/root/IMS/verify_rtpproxy_forwarding.py`
- SIP服务器主程序: `/root/IMS/run.py`

## 总结
**问题已解决**：RTPProxy服务已启动，现在应该能够正常转发RTP和RTCP报文。如果仍然出现音频双不通的问题，请检查：
1. SIP服务器的日志，确认RTPProxy会话是否成功创建
2. 网络连接，确保客户端能够访问RTPProxy分配的媒体端口
3. 防火墙规则，确保媒体端口已开放
