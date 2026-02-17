# 媒体NAT处理详解

本文档详细说明如何使用RTPProxy处理媒体NAT穿透。

## RTPProxy的NAT处理机制

### 1. 对称RTP（Symmetric RTP）

RTPProxy的核心特性是**对称RTP**，这是处理NAT的关键机制：

**工作原理**：
1. RTPProxy从第一个收到的RTP包中学习真实的源地址和端口
2. 使用学习到的地址作为目标地址发送RTP包
3. 自动处理双向RTP转发

**优势**：
- ✅ 自动处理NAT穿透，无需手动配置
- ✅ 支持对称NAT（最严格的NAT类型）
- ✅ 低延迟，高性能

### 2. NAT处理流程

```
1. SIP信令阶段：
   - 客户端发送INVITE，SDP中包含私网IP（如192.168.1.100）
   - 服务器通过NAT Helper修正SDP为公网IP（如113.44.149.111）
   - 转发给被叫

2. RTPProxy会话创建：
   - 服务器创建RTPProxy会话
   - 传递信令地址（NAT后的公网IP）+ SDP中的RTP端口
   - RTPProxy分配媒体端口（如20000）

3. 媒体流建立：
   - 客户端发送RTP到RTPProxy的媒体端口（20000）
   - RTPProxy从第一个RTP包学习真实的源地址（如192.168.1.100:10000）
   - RTPProxy更新目标地址，实现NAT穿透
   - 双向RTP转发自动建立
```

## 实现细节

### 地址选择策略

**关键原则**：使用信令地址（NAT后的公网IP）+ SDP中的RTP端口

```python
# 获取A-leg目标地址
a_leg_target = session.get_a_leg_rtp_target_addr()
# 返回: (信令IP, SDP中的RTP端口)
# 例如: ('113.44.149.111', 10000)

# 获取B-leg目标地址
b_leg_target = session.get_b_leg_rtp_target_addr()
# 返回: (信令IP, SDP中的RTP端口)
# 例如: ('113.44.149.112', 20000)
```

**为什么这样选择**：
1. **信令IP**：客户端在NAT后的公网IP，RTP包会从这个IP发出
2. **SDP端口**：客户端实际监听的RTP端口
3. **RTPProxy学习**：即使地址不完全准确，RTPProxy也会从第一个RTP包中学习真实地址

### RTPProxy会话创建

```python
# 创建RTPProxy会话
session_id = rtpproxy.create_session(
    call_id=call_id,
    from_tag=from_tag,
    to_tag=to_tag,
    from_addr=a_leg_target,  # (信令IP, SDP端口)
    to_addr=b_leg_target,     # (信令IP, SDP端口)
    flags="s"  # 对称RTP模式（默认启用）
)
```

**标志说明**：
- `s` - 对称RTP模式（默认启用，显式指定更清晰）
- `r` - 录制模式
- `w` - 写入模式

### 对称RTP学习过程

```
时间线：

T0: RTPProxy会话创建
    - 初始目标: A-leg -> (113.44.149.111, 10000)
    - 初始目标: B-leg -> (113.44.149.112, 20000)

T1: 客户端A发送第一个RTP包
    - 源地址: (192.168.1.100, 10000) [私网地址]
    - 到达RTPProxy: (113.44.149.111, 10000) [NAT后的公网地址]
    - RTPProxy学习: 真实的源地址是 (192.168.1.100, 10000)
    - RTPProxy更新: A-leg目标 -> (192.168.1.100, 10000)

T2: 客户端B发送第一个RTP包
    - 源地址: (192.168.1.200, 20000) [私网地址]
    - 到达RTPProxy: (113.44.149.112, 20000) [NAT后的公网地址]
    - RTPProxy学习: 真实的源地址是 (192.168.1.200, 20000)
    - RTPProxy更新: B-leg目标 -> (192.168.1.200, 20000)

T3: 双向RTP转发建立
    - A -> RTPProxy -> B: 正常工作
    - B -> RTPProxy -> A: 正常工作
```

## 与SIP信令NAT处理的配合

### 完整的NAT处理方案

```
SIP信令NAT处理（NAT Helper）:
├── fix_contact() - 修正Contact头
└── fix_nated_sdp() - 修正SDP中的IP

媒体NAT处理（RTPProxy）:
├── 对称RTP学习 - 自动学习真实的RTP源地址
├── 双向转发 - 自动建立双向RTP转发
└── NAT穿透 - 自动处理各种NAT类型
```

### 工作流程

```
1. REGISTER请求：
   - NAT Helper修正Contact头（私网IP -> 公网IP）
   - 存储修正后的地址

2. INVITE请求：
   - NAT Helper修正SDP中的IP（私网IP -> 公网IP）
   - 转发给被叫

3. 200 OK响应：
   - NAT Helper修正SDP中的IP（私网IP -> 公网IP）
   - 创建RTPProxy会话（使用信令IP + SDP端口）
   - RTPProxy通过对称RTP学习真实的RTP源地址
   - 双向媒体转发建立
```

## 配置和优化

### RTPProxy启动参数

```bash
# 基本启动
rtpproxy -l <SERVER_IP> -s udp:127.0.0.1:7722 -F

# 优化参数
rtpproxy \
  -l <SERVER_IP> \              # 公网IP（用于SDP）
  -s udp:127.0.0.1:7722 \       # 控制socket
  -F \                          # 前台运行
  -d DBUG \                     # 调试级别（可选）
  -f \                          # 前台运行
  -m 10000-20000 \              # 媒体端口范围（可选）
  -M 10000-20000                # RTCP端口范围（可选）
```

### 环境变量配置

```bash
# RTPProxy地址
export RTPPROXY_TCP_HOST=127.0.0.1
export RTPPROXY_TCP_PORT=7722

# 服务器IP
export SERVER_IP=113.44.149.111

# 本地网络（用于NAT检测）
export LOCAL_NETWORK_CIDR="192.168.0.0/16,10.0.0.0/8,172.16.0.0/12"
```

## 故障排查

### 媒体单向问题

**症状**：只能听到一方声音

**排查步骤**：
1. 检查RTPProxy会话是否创建成功
   ```bash
   # 查看RTPProxy日志
   tail -f /var/log/rtpproxy.log
   ```

2. 检查RTP包是否到达RTPProxy
   ```bash
   # 使用tcpdump抓包
   tcpdump -i any -n udp port 10000-20000
   ```

3. 检查对称RTP学习是否成功
   - 查看日志中的"学习"信息
   - 确认RTPProxy是否更新了目标地址

4. 检查NAT修正是否生效
   - 确认SDP中的IP是否已修正为公网IP
   - 确认Contact头是否已修正

### RTPProxy连接失败

**错误**：
```
[RTPProxy-ERROR] RTPProxy客户端初始化失败: Connection refused
```

**解决**：
1. 检查RTPProxy是否运行
   ```bash
   ps aux | grep rtpproxy
   ```

2. 检查socket地址
   ```bash
   netstat -tuln | grep 7722
   ```

3. 检查防火墙
   ```bash
   iptables -L -n | grep 7722
   ```

### 对称RTP学习失败

**症状**：RTP包无法建立双向转发

**可能原因**：
1. 防火墙阻止了RTP包
2. NAT类型过于严格（对称NAT）
3. RTPProxy配置不正确

**解决**：
1. 检查防火墙规则
2. 确认RTPProxy端口范围配置
3. 查看RTPProxy调试日志

## 最佳实践

### 1. 使用信令地址作为初始目标

```python
# ✅ 正确：使用信令地址（NAT后的公网IP）
a_leg_target = (session.a_leg_signaling_addr[0], session.a_leg_remote_addr[1])

# ❌ 错误：使用SDP中的私网IP
a_leg_target = session.a_leg_remote_addr  # 可能包含私网IP
```

### 2. 启用对称RTP模式

```python
# ✅ 显式启用对称RTP
flags = "s"

# ✅ 也可以使用默认（已启用）
flags = ""
```

### 3. 监控RTPProxy会话

```python
# 查询会话状态
session_info = rtpproxy.query_session(call_id, from_tag, to_tag)
if session_info:
    print(f"会话状态: {session_info}")
```

### 4. 日志记录

```python
# 记录关键信息
print(f"[RTPProxy] 创建会话: {call_id}")
print(f"  A-leg目标: {a_leg_target}")
print(f"  B-leg目标: {b_leg_target}")
print(f"  对称RTP: 启用")
```

## 总结

RTPProxy通过**对称RTP**机制自动处理媒体NAT穿透：

1. ✅ **自动学习**：从第一个RTP包中学习真实的源地址
2. ✅ **自动更新**：更新目标地址，实现NAT穿透
3. ✅ **双向转发**：自动建立双向RTP转发
4. ✅ **支持所有NAT类型**：包括最严格的对称NAT

配合NAT Helper的SIP信令NAT处理，形成完整的NAT穿透解决方案。
