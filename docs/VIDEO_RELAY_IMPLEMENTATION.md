# 视频转发功能实现说明

## 概述

已成功实现视频流（Video）的媒体中继转发功能，现在系统可以同时处理音频和视频流。

## 实现细节

### 1. MediaSession 扩展

**新增字段**：
- `a_leg_video_rtp_port` / `a_leg_video_rtcp_port`：主叫侧视频端口
- `b_leg_video_rtp_port` / `b_leg_video_rtcp_port`：被叫侧视频端口
- `a_leg_video_remote_addr`：主叫视频媒体地址（从SDP提取）
- `b_leg_video_remote_addr`：被叫视频媒体地址（从SDP提取）
- `a_leg_video_actual_addr`：对称RTP学习到的主叫视频地址
- `b_leg_video_actual_addr`：对称RTP学习到的被叫视频地址

**新增方法**：
- `get_a_leg_video_rtp_target_addr()`：获取发往主叫的视频目标地址
- `get_b_leg_video_rtp_target_addr()`：获取发往被叫的视频目标地址

### 2. SDPProcessor 增强

#### extract_media_info() 扩展
现在可以提取：
- **音频流**：`audio_port`, `audio_payloads`, `audio_connection_ip`
- **视频流**：`video_port`, `video_payloads`, `video_connection_ip`
- **会话级别 IP**：`connection_ip`（如果没有媒体级别的 c= 行）
- **编解码信息**：`codec_info`（payload → codec映射）

支持：
- 会话级别的 `c=` 行（所有媒体共享）
- 媒体级别的 `c=` 行（每个媒体流独立）
- `m=audio` 和 `m=video` 行解析

#### modify_sdp() 扩展
新增参数：
- `new_video_port`：可选，用于修改视频流端口

功能：
- 修改 `m=audio` 行的端口
- 修改 `m=video` 行的端口（如果提供）
- 修改所有 `c=` 行的IP地址
- 保留原始协议类型（RTP/AVP 或 RTP/SAVP）

### 3. MediaRelay 视频支持

#### process_invite_to_callee() 增强
- 检测 SDP 中是否包含 `m=video` 行
- 动态分配视频端口对（A-leg 和 B-leg）
- 提取视频媒体信息（IP + 端口）
- 修改 SDP 以指向服务器的视频端口

日志输出示例：
```
[MediaRelay] 检测到视频流，分配视频端口:
  A-leg视频: RTP=20004, RTCP=20005
  B-leg视频: RTP=20006, RTCP=20007
[MediaRelay] A-leg视频信息: ('192.168.1.100', 51372)
```

#### process_answer_sdp() 增强
- 提取被叫的视频媒体信息
- 修改 200 OK 的 SDP 以指向服务器的视频端口

#### start_media_forwarding() 增强
在音频转发器启动后，检查是否有视频流：
- 如果有视频流，创建额外的视频转发器（VIDEO-RTP 和 VIDEO-RTCP）
- 使用单端口模式（主叫和被叫共享同一个端口）
- 发送视频 NAT 打洞包
- 支持对称 RTP 学习真实视频源地址

日志输出示例：
```
[MediaRelay] 启动视频转发: abc123
  主叫(1001)视频: ('192.168.1.100', 51372)
  被叫(1002)视频: ('192.168.1.200', 52480)
  共享视频RTP端口: 20006
[MediaRelay] 视频转发已启动: abc123
```

#### stop_media_forwarding() / end_session() 增强
- 停止视频转发器（video-rtp 和 video-rtcp）
- 释放视频端口资源

### 4. RTPProxyMediaRelay 视频支持

与 MediaRelay 类似的增强：
- `process_invite_to_callee()`：检测视频、分配端口、提取信息
- `process_answer_sdp()`：提取被叫视频信息
- `end_session()`：释放视频端口

## 端口分配策略

### 音频流（每个呼叫）
- A-leg 音频：RTP=20000, RTCP=20001
- B-leg 音频：RTP=20002, RTCP=20003

### 视频流（每个呼叫，按需分配）
- A-leg 视频：RTP=20004, RTCP=20005
- B-leg 视频：RTP=20006, RTCP=20007

**总计**：每个音视频通话占用 **8 个端口**（4对）

## NAT 穿透机制

视频流与音频流使用相同的 NAT 穿透策略：

1. **对称 RTP（Symmetric RTP）**
   - 从第一个收到的 RTP 包中学习真实的源地址和端口
   - 自动适应 NAT 映射的端口（可能与 SDP 声明不同）

2. **NAT 打洞（Hole Punching）**
   - 启动转发后立即发送 20 个打洞包
   - 如果主叫未 LATCH，持续发送打洞包（每2秒一次，最多30次）

3. **信令地址优先**
   - 优先使用信令来源地址（NAT 后的公网 IP）
   - 结合 SDP 中的端口号作为初始目标

## 工作流程

### INVITE 阶段
```
1. 主叫(1001) → 服务器: INVITE (SDP: audio=10000, video=10002)
2. 服务器检测到视频流，分配视频端口
3. 服务器 → 被叫(1002): INVITE (SDP: audio=20002, video=20006)
```

### 200 OK 阶段
```
1. 被叫(1002) → 服务器: 200 OK (SDP: audio=12000, video=12002)
2. 服务器提取被叫视频信息
3. 服务器 → 主叫(1001): 200 OK (SDP: audio=20002, video=20006)
```

### 媒体转发阶段
```
音频流：
  主叫 RTP(10000) → 服务器(20002) → 被叫(12000)
  被叫 RTP(12000) → 服务器(20002) → 主叫(10000)

视频流：
  主叫 RTP(10002) → 服务器(20006) → 被叫(12002)
  被叫 RTP(12002) → 服务器(20006) → 主叫(10002)
```

## 兼容性

### 向后兼容
- **纯音频通话**：完全兼容，不分配视频端口
- **音视频通话**：自动检测并处理视频流
- **SDP 协议**：保留原始协议类型（RTP/AVP 或 RTP/SAVP）

### 支持的场景
- ✅ 纯音频通话
- ✅ 音频 + 视频通话
- ✅ NAT 后的终端
- ✅ SRTP 加密（透传模式）
- ✅ 多编解码协商

### 不支持的场景
- ❌ 多视频流（同一个呼叫中多个视频轨）
- ❌ 动态媒体流添加（需要 re-INVITE 支持）

## 日志识别

### 视频流检测
```
[MediaRelay] 检测到视频流，分配视频端口:
[MediaRelay] A-leg视频信息: ('IP', PORT)
[MediaRelay] B-leg视频信息: ('IP', PORT)
```

### 视频转发启动
```
[MediaRelay] 启动视频转发: CALL_ID
[MediaRelay] 共享视频RTP端口: PORT
[MediaRelay] 视频转发已启动: CALL_ID
```

### 转发状态
```
[RTP-FWDOK] 1001↔1002-VIDEO(20006): A→B 发送成功
[RTP-LATCH] 1001↔1002-VIDEO: 主叫LATCH成功 IP:PORT
```

## 性能考虑

### 端口消耗
- 纯音频通话：4 个端口 / 呼叫
- 音视频通话：8 个端口 / 呼叫
- 端口范围：20000-30000（5000对，支持 1250 个音视频通话）

### 带宽估算
- 音频（G.711）：~80 Kbps（双向）
- 视频（720p H.264）：~1-2 Mbps（双向）
- 每个音视频通话：~2 Mbps

### CPU 负载
- 单端口模式：减少 50% socket 数量
- UDP 转发：低 CPU 开销（纯包转发）
- 对称 RTP 学习：首包处理，后续零开销

## 测试建议

### 基本功能测试
1. 纯音频通话（确保向后兼容）
2. 音频+视频通话（测试视频流）
3. 长时间通话（测试稳定性）

### NAT 穿透测试
1. 两端都在 NAT 后
2. 一端在 NAT 后
3. 对称 NAT 场景

### 压力测试
1. 并发音视频通话（测试端口管理）
2. 频繁呼叫/挂断（测试资源释放）
3. 带宽饱和测试

## 故障排查

### 视频无法显示
1. 检查 SDP 是否包含 `m=video` 行
2. 查看是否成功分配视频端口
3. 检查防火墙是否允许视频端口
4. 查看是否有 VIDEO LATCH 日志

### 视频卡顿
1. 检查网络带宽（至少 2 Mbps）
2. 查看丢包率（RTCP 报告）
3. 检查 CPU 使用率
4. 查看日志中的转发统计

### 单向视频
1. 检查 NAT 类型（对称 NAT 可能需要 TURN）
2. 查看是否双向 LATCH 成功
3. 检查防火墙规则
4. 验证 SDP 地址是否正确

## 配置要求

### 最低要求
- 端口范围：20000-30000（开放 UDP）
- 带宽：2 Mbps / 音视频通话
- CPU：多核处理器（推荐）

### 推荐配置
- 端口范围：20000-40000（扩展容量）
- 带宽：10 Mbps / 5 个并发音视频通话
- CPU：4核或更高
- 内存：2 GB 或更高

## 未来增强

1. **多视频流支持**：同一呼叫中支持多个视频轨（屏幕共享等）
2. **带宽控制**：QoS 和带宽限制
3. **转码支持**：不同编解码之间转换
4. **录制功能**：音视频通话录制
5. **统计增强**：视频流质量指标（帧率、分辨率、丢包率）

## 更新日期

2026-02-18
