# RTP 媒体传输协议说明

## 核心结论

**RTP 媒体必须使用 UDP，不能使用 TCP。**

## 为什么 RTP 必须使用 UDP？

### 1. RTP 协议设计

RTP (Real-time Transport Protocol) 是专门为实时媒体传输设计的协议：

- **设计目标**: 低延迟、实时性
- **传输层**: 基于 UDP（RFC 3550）
- **特点**: 无连接、不保证顺序、不重传

### 2. TCP vs UDP 对实时媒体的影响

| 特性 | UDP | TCP |
|------|-----|-----|
| **延迟** | 低（毫秒级） | 高（可能数百毫秒） |
| **丢包处理** | 丢弃，继续播放 | 重传，导致延迟累积 |
| **顺序保证** | 不保证（RTP有序列号） | 保证（但会阻塞） |
| **实时性** | ✅ 适合 | ❌ 不适合 |

### 3. TCP 的问题

**延迟累积**：
```
客户端发送包1 → 服务器接收 → TCP确认 → 客户端收到确认 → 发送包2
```
每个包都需要确认，延迟会累积。

**阻塞问题**：
如果包2丢失，TCP会等待重传，导致后续所有包都被阻塞，音频/视频会卡顿。

**UDP的优势**：
```
客户端发送包1,2,3,4... → 服务器接收（可能丢失包2）
→ 继续播放包1,3,4（RTP有序列号，可以检测丢失）
```

## 项目实现

### 当前实现（UDP）

项目中的所有RTP实现都使用UDP：

```python
# sipcore/media_relay.py
self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP
```

```python
# sip_client_standalone.py
self.rtp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP
```

### RTPProxy

RTPProxy也使用UDP进行RTP转发：
- RTP媒体流：UDP
- 控制接口：UDP socket（`-s udp:127.0.0.1:7722`）

## 内网穿透场景

### 问题

大多数内网穿透服务（如Cloudflare Tunnel、localtunnel）**只支持TCP/HTTP**，不支持UDP。

### 解决方案

#### 方案1：服务器有公网IP（推荐）

如果服务器有公网IP，RTP可以直接通过UDP传输：

```
客户端 ←--UDP RTP--→ 服务器（公网IP）←--UDP RTP--→ 客户端
```

配置：
```bash
export SERVER_IP=your.public.ip.address
```

#### 方案2：使用支持UDP的内网穿透

**ngrok**（支持UDP）：
```bash
ngrok udp 5060  # SIP UDP
# RTP端口范围需要单独映射
```

**frp**（完全支持UDP）：
```ini
[sip-udp]
type = udp
local_ip = 127.0.0.1
local_port = 5060
remote_port = 5060

[rtp-range]
type = udp
local_ip = 127.0.0.1
local_port = 10000
remote_port = 10000
```

#### 方案3：TURN服务器（媒体中继）

如果必须使用只支持TCP的隧道（如Cloudflare），可以使用TURN服务器做媒体中继：

```
客户端 ←--UDP RTP--→ TURN服务器 ←--UDP RTP--→ 服务器
```

TURN服务器：
- 支持UDP媒体传输
- 处理NAT穿透
- 需要单独部署

#### 方案4：混合方案

- **信令（SIP）**: 通过TCP隧道（Cloudflare Tunnel、ngrok TCP）
- **媒体（RTP）**: 直接UDP（如果服务器有公网IP）或通过TURN

```
SIP信令: 客户端 ←--TCP--→ 隧道 ←--TCP--→ 服务器
RTP媒体: 客户端 ←--UDP--→ 服务器（公网IP）或TURN
```

## 常见误解

### ❌ 误解1：RTP可以走TCP

**事实**: RTP协议设计为UDP，虽然技术上可以封装在TCP中（RTP over TCP），但：
- 性能很差（延迟高）
- 不是标准做法
- 大多数SIP客户端不支持

### ❌ 误解2：TCP隧道可以转发RTP

**事实**: TCP隧道（如Cloudflare Tunnel）只能转发TCP流量，无法转发UDP的RTP包。

### ✅ 正确理解

- **SIP信令**: 可以使用TCP（SIP over TCP）
- **RTP媒体**: 必须使用UDP（RTP over UDP）

## 项目配置建议

### 场景1：有公网IP

```bash
# 启用TCP（用于SIP信令）
export ENABLE_TCP=1

# 设置公网IP（用于RTP媒体）
export SERVER_IP=your.public.ip.address
```

### 场景2：NAT环境 + ngrok

```bash
# ngrok支持UDP
./scripts/start_with_tunnel.sh ngrok pm2

# 配置ngrok映射RTP端口范围
# 编辑ngrok.yml添加RTP端口映射
```

### 场景3：NAT环境 + Cloudflare Tunnel

```bash
# Cloudflare只支持TCP（SIP信令）
./scripts/start_with_tunnel.sh cloudflare pm2

# RTP媒体需要：
# 1. 服务器有公网IP（设置SERVER_IP）
# 2. 或使用TURN服务器
```

## 总结

| 协议 | 传输层 | 用途 | 是否必须UDP |
|------|--------|------|------------|
| **SIP信令** | TCP或UDP | 呼叫控制 | ❌ 可以使用TCP |
| **RTP媒体** | UDP | 音视频传输 | ✅ **必须UDP** |
| **RTCP** | UDP | 媒体控制 | ✅ **必须UDP** |

**关键点**：
- RTP媒体**必须使用UDP**
- SIP信令可以使用TCP（适合内网穿透）
- 如果使用只支持TCP的隧道，RTP需要服务器有公网IP或使用TURN服务器

## 相关文档

- [TCP注册支持](TCP_REGISTRATION.md)
- [内网穿透方案](FREE_TUNNEL_SOLUTIONS.md)
- [NAT端口映射](NAT_PORT_MAPPING.md)
