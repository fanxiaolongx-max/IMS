# 核心代码重构指南

本文档说明如何使用开源成熟的组件重构IMS SIP Server的核心代码。

## 重构概述

### 重构目标
- ✅ 使用RTPProxy替代自定义媒体转发代码
- ✅ 保留所有现有功能（CDR、用户管理、MML等）
- ✅ 代码结构清晰，便于后续迁移到Sippy B2BUA

### 重构内容

#### 1. 媒体中继：RTPProxy（已完成）
- **替换前**：自定义RTP转发代码（`sipcore/media_relay.py`）
- **替换后**：RTPProxy（成熟稳定的开源RTP代理）
- **优势**：
  - ✅ 高性能、低延迟
  - ✅ 自动处理NAT穿透
  - ✅ 广泛用于生产环境（Kamailio、OpenSIPS等）

#### 2. SIP信令：保留现有实现（后续可迁移到Sippy）
- **当前**：保留自定义SIP处理逻辑（已工作稳定）
- **未来**：可迁移到Sippy B2BUA（RFC3261完全兼容）
- **原因**：Sippy集成需要深入研究API，先解决媒体问题

## 快速开始

### 步骤1: 安装RTPProxy

```bash
# Ubuntu/Debian
apt-get update
apt-get install rtpproxy

# 或使用安装脚本
./install_dependencies.sh
```

### 步骤2: 启动RTPProxy

```bash
# 获取服务器IP（替换为实际IP）
export SERVER_IP=113.44.149.111

# 启动RTPProxy（使用UDP socket）
rtpproxy -l $SERVER_IP -s udp:127.0.0.1:7722 -F

# 或使用Unix socket（推荐）
rtpproxy -l $SERVER_IP -s unix:/var/run/rtpproxy.sock -F
```

### 步骤3: 配置环境变量（可选）

```bash
# 设置服务器IP
export SERVER_IP=113.44.149.111

# 设置RTPProxy地址（如果使用非默认端口）
export RTPPROXY_TCP_HOST=127.0.0.1
export RTPPROXY_TCP_PORT=7722
```

### 步骤4: 使用重构版本

```bash
# 备份原版本
cp run.py run.py.backup

# 使用重构版本
cp run_refactored.py run.py

# 重启服务器
pm2 restart ims-server
```

## 验证安装

### 1. 检查RTPProxy是否运行

```bash
ps aux | grep rtpproxy
# 应该看到rtpproxy进程

# 检查端口
netstat -tuln | grep 7722
```

### 2. 检查日志

启动服务器后，应该看到：

```
[B2BUA] RTPProxy媒体中继已初始化，服务器IP: 113.44.149.111
[B2BUA] RTPProxy地址: 127.0.0.1:7722
```

### 3. 测试呼叫

进行测试呼叫，检查：
- ✅ 音频双向正常
- ✅ 日志显示RTPProxy会话创建
- ✅ CDR记录正常

## 架构说明

### 媒体中继流程

```
主叫UA                   服务器                   被叫UA
  |                        |                        |
  |-- INVITE (SDP A) ---->|                        |
  |                        |-- 修改SDP指向B-leg -->|
  |                        |-- INVITE (SDP B) ---->|
  |                        |                        |
  |                        |<-- 200 OK (SDP C) ----|
  |<-- 200 OK (SDP D) ----|                        |
  |                        |                        |
  |-- RTP (A-leg) -------->|                        |
  |                        |-- RTP转发 (B-leg) ---->|
  |                        |<-- RTP (B-leg) --------|
  |<-- RTP (A-leg) --------|                        |
```

### RTPProxy工作原理

1. **INVITE处理**：
   - 服务器收到主叫的INVITE，提取SDP中的媒体地址
   - 修改SDP指向服务器的B-leg端口
   - 转发给被叫

2. **200 OK处理**：
   - 服务器收到被叫的200 OK，提取SDP中的媒体地址
   - 修改SDP指向服务器的B-leg端口
   - 通过RTPProxy创建媒体会话
   - 转发给主叫

3. **媒体转发**：
   - RTPProxy自动处理双向RTP转发
   - 自动学习实际的RTP源地址（NAT穿透）
   - 低延迟、低丢包率

## 配置说明

### RTPProxy配置

**UDP Socket（默认）**：
```bash
rtpproxy -l <server_ip> -s udp:127.0.0.1:7722 -F
```

**Unix Socket（推荐）**：
```bash
rtpproxy -l <server_ip> -s unix:/var/run/rtpproxy.sock -F
```

**参数说明**：
- `-l <server_ip>`: 服务器公网IP（用于SDP）
- `-s <socket>`: 控制socket（UDP或Unix）
- `-F`: 前台运行（生产环境建议使用systemd）

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `SERVER_IP` | 自动检测 | 服务器公网IP |
| `RTPPROXY_TCP_HOST` | 127.0.0.1 | RTPProxy TCP地址 |
| `RTPPROXY_TCP_PORT` | 7722 | RTPProxy TCP端口 |

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

### 媒体单向问题

**症状**：只能听到一方声音

**排查**：
1. 检查RTPProxy会话是否创建成功
2. 查看日志中的媒体诊断信息
3. 检查NAT设置

### 性能问题

**症状**：呼叫延迟高、丢包

**优化**：
1. 使用Unix socket替代UDP socket（性能更好）
2. 调整RTPProxy参数（`-d`调试模式查看详情）
3. 检查网络延迟和带宽

## 后续迁移计划

### 阶段1: 媒体中继迁移（当前）
- ✅ 使用RTPProxy替代自定义媒体转发
- ✅ 保留所有现有功能

### 阶段2: SIP信令迁移（可选）
- ⏳ 研究Sippy B2BUA API
- ⏳ 创建Sippy集成代码
- ⏳ 逐步迁移SIP方法
- ⏳ 测试和验证

### 阶段3: 完全迁移（未来）
- ⏳ 使用Sippy B2BUA处理所有SIP信令
- ⏳ 移除自定义SIP处理代码
- ⏳ 简化代码结构

## 回退方案

如果重构版本出现问题，可以快速回退：

```bash
# 恢复原版本
cp run.py.backup run.py

# 重启服务器
pm2 restart ims-server
```

## 参考文档

- **RTPProxy文档**: `INSTALL_RTPPROXY.md`, `RTPPROXY_QUICKSTART.md`
- **Sippy文档**: `INSTALL_SIPPY.md`, `SIPPY_QUICKSTART.md`
- **迁移指南**: `MIGRATION_GUIDE.md`
- **RTPProxy GitHub**: https://github.com/sippy/rtpproxy
- **Sippy GitHub**: https://github.com/sippy/b2bua

## 总结

本次重构主要完成了：
1. ✅ **媒体中继迁移到RTPProxy**：解决音频单向问题，提高稳定性
2. ✅ **代码结构优化**：清晰的分层，便于维护和扩展
3. ✅ **功能完整保留**：CDR、用户管理、MML等功能全部保留

后续可以根据需要逐步迁移SIP信令到Sippy B2BUA，实现完全基于开源组件的架构。
