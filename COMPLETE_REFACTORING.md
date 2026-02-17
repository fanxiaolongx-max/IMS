# 完全重构指南 - 使用开源成熟方案

本文档说明如何将项目完全迁移到开源成熟的信令和媒体处理方案。

## 重构概述

### 重构目标
- ✅ **媒体中继**：RTPProxy（成熟稳定的RTP代理）
- ✅ **NAT处理**：服务器端NAT处理（基于Kamailio/OpenSIPS最佳实践）
- ⏳ **SIP信令**：Sippy B2BUA（RFC3261完全兼容，可选）

### 架构对比

#### 原版本
```
自定义SIP信令处理
    ↓
自定义RTP转发 + 自定义NAT处理
    ↓
UA <---> 服务器 <---> UA
```

#### 重构版本
```
SIP信令处理（保留自定义，可选Sippy B2BUA）
    ↓
RTPProxy媒体中继 + NAT Helper服务器端NAT处理
    ↓
UA <---> RTPProxy <---> UA
```

## 核心组件

### 1. RTPProxy - 媒体中继

**特性**：
- ✅ 高性能RTP代理，广泛用于生产环境
- ✅ 自动处理NAT穿透和对称RTP
- ✅ 支持ICE、SRTP等高级特性
- ✅ 低延迟、低丢包率

**使用**：
```bash
# 安装
apt-get install rtpproxy

# 启动
rtpproxy -l <SERVER_IP> -s udp:127.0.0.1:7722 -F
```

### 2. NAT Helper - 服务器端NAT处理

**特性**：
- ✅ 基于Kamailio/OpenSIPS最佳实践
- ✅ `fix_contact()` - 重写Contact头为源地址:端口
- ✅ `fix_nated_sdp()` - 修正SDP中的IP/端口
- ✅ 自动检测NAT并处理

**实现**：
- `sipcore/nat_helper.py` - NAT处理模块
- 自动检测客户端是否在NAT后
- 自动修正Contact头和SDP

### 3. Sippy B2BUA - SIP信令（可选）

**特性**：
- ✅ RFC3261完全兼容
- ✅ 自动处理SIP事务和对话
- ✅ 支持5000-10000并发会话
- ✅ 完善的错误处理

**使用**：
```bash
# 安装
pip install sippy
```

## 快速开始

### 步骤1: 安装依赖

```bash
# 安装RTPProxy
apt-get update
apt-get install rtpproxy

# 安装Sippy（可选）
pip install sippy
```

### 步骤2: 启动RTPProxy

```bash
# 获取服务器IP
export SERVER_IP=113.44.149.111

# 启动RTPProxy
rtpproxy -l $SERVER_IP -s udp:127.0.0.1:7722 -F
```

### 步骤3: 使用重构版本

```bash
# 方式1: 使用RTPProxy + NAT Helper（推荐）
cp run_sippy.py run.py

# 方式2: 使用RTPProxy（基础版本）
cp run_refactored.py run.py

# 重启服务器
pm2 restart ims-server
```

## 版本对比

### run_refactored.py（基础版本）
- ✅ RTPProxy媒体中继
- ✅ 保留自定义SIP信令处理
- ✅ 基础NAT处理

### run_sippy.py（完整版本）
- ✅ RTPProxy媒体中继
- ✅ NAT Helper服务器端NAT处理
- ✅ 保留自定义SIP信令处理（可迁移到Sippy）
- ✅ 完整的NAT检测和修正

## NAT处理详解

### 完整的NAT处理方案

本项目实现了**双重NAT处理**：

1. **SIP信令NAT处理**（NAT Helper模块）
   - 修正Contact头
   - 修正SDP中的IP

2. **媒体NAT处理**（RTPProxy）
   - 对称RTP自动学习
   - 自动NAT穿透
   - 双向媒体转发

### SIP信令NAT处理（服务器端最佳实践）

#### 1. Contact头修正（fix_contact）

**问题**：客户端在NAT后，Contact头中的IP是私网地址，无法直接访问。

**解决**：将Contact头中的地址替换为实际的源地址:端口。

```python
# 原Contact头
Contact: <sip:1001@192.168.1.100:5060>

# 修正后（源地址是公网IP）
Contact: <sip:1001@113.44.149.111:5060>
```

#### 2. SDP修正（fix_nated_sdp）

**问题**：SDP中的连接IP是私网地址，媒体无法建立。

**解决**：将SDP中的连接IP替换为实际的源地址IP。

```python
# 原SDP
c=IN IP4 192.168.1.100
m=audio 10000 RTP/AVP 0

# 修正后
c=IN IP4 113.44.149.111
m=audio 10000 RTP/AVP 0
```

#### 3. NAT检测

**逻辑**：
- Contact IP是私网地址，但源地址是公网地址 → 在NAT后
- Contact IP与源地址IP不同 → 可能在NAT后

### 媒体NAT处理（RTPProxy对称RTP）

RTPProxy通过**对称RTP**机制自动处理媒体NAT穿透：

**工作原理**：
1. RTPProxy从第一个收到的RTP包中学习真实的源地址
2. 使用学习到的地址作为目标地址发送RTP包
3. 自动处理双向RTP转发

**关键点**：
- ✅ 使用信令地址（NAT后的公网IP）+ SDP中的RTP端口作为初始目标
- ✅ RTPProxy自动学习真实的RTP源地址（即使客户端在NAT后）
- ✅ 支持所有NAT类型，包括最严格的对称NAT

详细说明请参考：`docs/MEDIA_NAT_HANDLING.md`

### 使用示例

```python
from sipcore.nat_helper import init_nat_helper, get_nat_helper

# 初始化NAT助手（SIP信令NAT处理）
nat_helper = init_nat_helper(
    server_ip="113.44.149.111",
    local_networks=["192.168.0.0/16", "10.0.0.0/8"]
)

# 处理REGISTER请求（修正Contact头）
nat_helper.process_register_contact(msg, source_addr)

# 处理INVITE请求的SDP（修正SDP中的IP）
nat_helper.process_invite_sdp(msg, source_addr)

# 处理200 OK响应的SDP（修正SDP中的IP）
nat_helper.process_response_sdp(msg, source_addr)

# RTPProxy自动处理媒体NAT（无需额外代码）
# RTPProxy会通过对称RTP自动学习真实的RTP源地址
```

## 配置说明

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `SERVER_IP` | 自动检测 | 服务器公网IP |
| `RTPPROXY_TCP_HOST` | 127.0.0.1 | RTPProxy TCP地址 |
| `RTPPROXY_TCP_PORT` | 7722 | RTPProxy TCP端口 |
| `LOCAL_NETWORK_CIDR` | 192.168.0.0/16,10.0.0.0/8,172.16.0.0/12 | 本地网络CIDR列表 |

### RTPProxy配置

**UDP Socket（默认）**：
```bash
rtpproxy -l <server_ip> -s udp:127.0.0.1:7722 -F
```

**Unix Socket（推荐，性能更好）**：
```bash
rtpproxy -l <server_ip> -s unix:/var/run/rtpproxy.sock -F
```

## 验证安装

### 1. 检查RTPProxy

```bash
ps aux | grep rtpproxy
netstat -tuln | grep 7722
```

### 2. 检查日志

启动服务器后，应该看到：

```
[NAT] NAT助手已初始化，本地网络: ['192.168.0.0/16', '10.0.0.0/8', '172.16.0.0/12']
[B2BUA] RTPProxy媒体中继已初始化，服务器IP: 113.44.149.111
[B2BUA] RTPProxy地址: 127.0.0.1:7722
```

### 3. 测试呼叫

进行测试呼叫，检查：
- ✅ 音频双向正常
- ✅ 日志显示NAT修正
- ✅ 日志显示RTPProxy会话创建
- ✅ CDR记录正常

## NAT处理流程

### REGISTER请求

```
1. 客户端发送REGISTER（Contact: sip:1001@192.168.1.100:5060）
2. 服务器检测NAT（Contact IP是私网，源地址是公网）
3. 修正Contact头（Contact: sip:1001@113.44.149.111:5060）
4. 存储修正后的Contact地址
```

### INVITE请求

```
1. 客户端发送INVITE（SDP: c=IN IP4 192.168.1.100）
2. 服务器检测NAT（SDP IP是私网，源地址是公网）
3. 修正SDP（c=IN IP4 113.44.149.111）
4. 转发给被叫
```

### 200 OK响应

```
1. 被叫发送200 OK（SDP: c=IN IP4 192.168.1.200）
2. 服务器检测NAT（SDP IP是私网，源地址是公网）
3. 修正SDP（c=IN IP4 113.44.149.111）
4. 通过RTPProxy创建媒体会话
5. 转发给主叫
```

## 故障排查

### RTPProxy连接失败

**错误**：
```
[RTPProxy-ERROR] RTPProxy客户端初始化失败: Connection refused
```

**解决**：
1. 检查RTPProxy是否运行：`ps aux | grep rtpproxy`
2. 检查socket地址是否正确
3. 检查防火墙设置

### NAT修正不生效

**症状**：Contact头或SDP中的IP仍然是私网地址

**排查**：
1. 检查NAT助手是否初始化
2. 查看日志中的NAT修正信息
3. 检查本地网络配置是否正确

### 媒体单向问题

**症状**：只能听到一方声音

**排查**：
1. 检查RTPProxy会话是否创建成功
2. 查看日志中的媒体诊断信息
3. 检查NAT修正是否生效
4. 检查防火墙和NAT设置

## 后续迁移计划

### 阶段1: 媒体中继和NAT处理（当前）✅
- ✅ RTPProxy媒体中继
- ✅ NAT Helper服务器端NAT处理

### 阶段2: SIP信令迁移（可选）⏳
- ⏳ 研究Sippy B2BUA API
- ⏳ 创建Sippy集成代码
- ⏳ 逐步迁移SIP方法
- ⏳ 测试和验证

### 阶段3: 完全迁移（未来）⏳
- ⏳ 使用Sippy B2BUA处理所有SIP信令
- ⏳ 移除自定义SIP处理代码
- ⏳ 简化代码结构

## 参考资源

- **RTPProxy文档**: `INSTALL_RTPPROXY.md`, `RTPPROXY_QUICKSTART.md`
- **NAT处理**: `sipcore/nat_helper.py`
- **重构指南**: `REFACTORING_GUIDE.md`
- **RTPProxy GitHub**: https://github.com/sippy/rtpproxy
- **Sippy GitHub**: https://github.com/sippy/b2bua
- **Kamailio NAT模块**: https://kamailio.org/docs/modules/stable/modules/nathelper.html
- **OpenSIPS NAT模块**: https://opensips.org/docs/modules/2.3.x/nat_traversal.html

## 总结

本次完全重构实现了：
1. ✅ **RTPProxy媒体中继**：使用成熟稳定的RTP代理
2. ✅ **服务器端NAT处理**：基于Kamailio/OpenSIPS最佳实践
3. ✅ **完整的NAT检测和修正**：自动处理Contact头和SDP
4. ✅ **功能完整保留**：CDR、用户管理、MML等功能全部保留

所有代码已就绪，可以直接使用！
