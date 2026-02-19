# RTPProxy修复指南

## 问题诊断

根据诊断脚本，发现以下问题：

1. ✅ **代码已切换**: `run.py` 已从 `media_relay` 切换到 `rtpproxy_media_relay`
2. ❌ **RTPProxy未运行**: RTPProxy服务未启动
3. ⚠️ **协议格式待确认**: 当前使用 `U` 命令，需要确认RTPProxy实际协议格式

## 解决方案

### 步骤1: 启动RTPProxy

首先需要启动RTPProxy服务。根据你的服务器IP配置：

```bash
# 获取服务器IP（替换为实际IP）
SERVER_IP=$(hostname -I | awk '{print $1}')

# 方式A: UDP socket（推荐用于测试）
rtpproxy -l $SERVER_IP -s udp:127.0.0.1:7722 -F -d INFO

# 方式B: Unix socket（推荐用于生产）
rtpproxy -l $SERVER_IP -s unix:/var/run/rtpproxy.sock -F -d INFO
```

### 步骤2: 验证RTPProxy运行

运行诊断脚本：

```bash
python3 check_rtpproxy.py
```

如果看到 `[成功] RTPProxy正在运行并响应命令`，说明RTPProxy已正常启动。

### 步骤3: 检查协议格式

如果RTPProxy启动后仍然无法创建会话，可能需要调整协议格式。

当前代码使用 `U` 命令格式：
```
U<call_id> <from_tag> <to_tag> <from_ip>:<from_port> <to_ip>:<to_port> <flags>
```

RTPProxy可能使用 `V` 命令格式（更简单）：
```
V<call_id> <from_tag> <to_tag>
```

### 步骤4: 测试WiFi下的媒体转发

1. **确保RTPProxy已启动**
2. **检查日志**：查看是否有以下日志
   ```
   [RTPProxyMediaRelay] RTPProxy客户端初始化成功
   [RTPProxy] 创建会话成功: <call_id>
   [RTPProxyMediaRelay] 媒体转发已启动: <call_id>
   ```

3. **检查RTPProxy日志**：如果RTPProxy以 `-d INFO` 启动，会显示详细的会话创建和RTP转发日志

4. **使用tcpdump抓包**：验证RTP包是否到达RTPProxy
   ```bash
   tcpdump -i any -n udp port 10000-20000
   ```

## 常见问题

### Q1: RTPProxy启动失败

**错误**: `rtpproxy: command not found`

**解决**: 安装RTPProxy
```bash
apt-get update
apt-get install rtpproxy
```

### Q2: 媒体转发失败

**可能原因**:
1. RTPProxy未启动
2. 协议格式不正确
3. 防火墙阻止UDP端口
4. SDP中的IP地址不正确

**排查步骤**:
1. 运行 `check_rtpproxy.py` 确认RTPProxy运行状态
2. 检查日志中的错误信息
3. 使用 `tcpdump` 抓包验证RTP包是否到达服务器
4. 检查SDP中的IP地址是否为公网IP（NAT后的IP）

### Q3: WiFi下媒体无法转发

**可能原因**:
1. 客户端在NAT后，SDP中的IP是私网IP
2. RTPProxy未正确学习真实的RTP源地址

**解决方案**:
1. 确保使用 `NATHelper` 修正SDP中的IP（已在 `run.py` 中集成）
2. 确保RTPProxy使用对称RTP模式（`flags="s"`，已默认启用）
3. 检查传递给RTPProxy的地址是否正确（应使用信令地址+NAT后的公网IP）

## 下一步

1. **启动RTPProxy**: 按照步骤1启动RTPProxy服务
2. **运行诊断**: 运行 `python3 check_rtpproxy.py` 确认RTPProxy运行
3. **测试通话**: 在WiFi环境下测试通话，观察日志
4. **如果仍有问题**: 检查日志中的错误信息，可能需要调整协议格式

## 协议格式参考

如果 `U` 命令格式不正确，可能需要修改 `sipcore/rtpproxy_client.py` 中的 `create_session` 方法。

RTPProxy的标准协议格式（根据Kamailio/OpenSIPS使用方式）：
- **V命令**: `V<call_id> <from_tag> <to_tag>` - 创建会话（简单格式）
- **U命令**: `U<call_id> <from_tag> <to_tag> <from_ip>:<from_port> <to_ip>:<to_port> <flags>` - 创建会话（完整格式）
- **D命令**: `D<call_id> <from_tag> <to_tag>` - 删除会话

当前代码使用 `U` 命令，如果RTPProxy不支持，需要改为 `V` 命令格式。
