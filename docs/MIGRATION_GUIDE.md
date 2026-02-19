# 迁移到开源方案指南

本文档说明如何将现有的自定义SIP信令和媒体中继代码迁移到成熟的开源方案。

## 迁移策略

### 方案1: 完全替换（推荐）

使用Sippy B2BUA + RTPProxy完全替代现有代码。

**优势：**
- ✅ 完全符合RFC3261标准
- ✅ 自动处理SIP事务和对话
- ✅ 完善的错误处理
- ✅ 高性能、生产就绪
- ✅ 易于维护

**步骤：**

1. **安装依赖**
   ```bash
   pip install sippy
   apt-get install rtpproxy
   ```

2. **启动RTPProxy**
   ```bash
   rtpproxy -l <服务器IP> -s udp:127.0.0.1:7722 -F
   ```

3. **修改代码使用Sippy**
   - 参考 `INSTALL_SIPPY.md`
   - 使用 `sipcore/sippy_b2bua.py` 作为起点
   - 逐步迁移现有功能

4. **测试和验证**
   - 测试基本呼叫功能
   - 测试注册功能
   - 测试CDR记录
   - 测试媒体中继

### 方案2: 渐进式迁移

先迁移媒体中继，再迁移SIP信令。

**步骤：**

1. **第一步：迁移媒体中继到RTPProxy**
   - 使用 `sipcore/rtpproxy_media_relay.py`
   - 参考 `RTPPROXY_QUICKSTART.md`
   - 保持现有SIP信令处理不变

2. **第二步：迁移SIP信令到Sippy**
   - 使用 `sipcore/sippy_b2bua.py`
   - 参考 `INSTALL_SIPPY.md`
   - 逐步迁移各个SIP方法

## 详细迁移步骤

### 阶段1: 准备环境

1. **安装依赖**
   ```bash
   # 安装Sippy
   pip install sippy
   
   # 安装RTPProxy
   apt-get install rtpproxy
   ```

2. **备份现有代码**
   ```bash
   cp run.py run.py.backup.$(date +%Y%m%d)
   cp -r sipcore sipcore.backup.$(date +%Y%m%d)
   ```

3. **启动RTPProxy**
   ```bash
   rtpproxy -l 113.44.149.111 -s udp:127.0.0.1:7722 -F
   ```

### 阶段2: 迁移媒体中继（推荐先做）

1. **修改run.py使用RTPProxy媒体中继**
   ```python
   # 将
   from sipcore.media_relay import init_media_relay
   # 改为
   from sipcore.rtpproxy_media_relay import init_media_relay
   
   # 修改初始化
   media_relay = init_media_relay(
       SERVER_IP,
       rtpproxy_tcp=('127.0.0.1', 7722)
   )
   ```

2. **测试媒体中继**
   - 进行测试呼叫
   - 验证音频双向正常
   - 检查日志

3. **确认媒体中继工作正常后，继续下一步**

### 阶段3: 迁移SIP信令（可选）

**注意：** SIP信令迁移较复杂，建议先完成媒体中继迁移，确认系统稳定后再进行。

1. **研究Sippy API**
   - 查看Sippy文档：https://github.com/sippy/b2bua
   - 查看示例代码：https://github.com/sippy/b2bua/tree/master/apps
   - 理解Sippy的B2BUA模型

2. **创建Sippy集成代码**
   - 使用 `sipcore/sippy_b2bua.py` 作为起点
   - 根据Sippy实际API调整代码
   - 集成现有功能（注册、CDR等）

3. **逐步迁移功能**
   - 先迁移基本呼叫（INVITE/ACK/BYE）
   - 再迁移注册（REGISTER）
   - 最后迁移其他功能（MESSAGE、OPTIONS等）

4. **测试和验证**
   - 全面测试所有功能
   - 对比迁移前后的行为
   - 修复发现的问题

## 推荐方案

### 对于当前情况，推荐方案2（渐进式迁移）

**理由：**
1. 媒体中继问题更紧急（音频单向问题）
2. RTPProxy迁移相对简单，风险较低
3. SIP信令迁移较复杂，需要更多时间
4. 可以先解决媒体问题，再逐步优化信令

### 迁移顺序

1. ✅ **第一步：迁移媒体中继到RTPProxy**（立即执行）
   - 解决音频单向问题
   - 使用成熟稳定的RTPProxy
   - 风险低、收益高

2. ⏳ **第二步：评估SIP信令问题**（后续执行）
   - 如果SIP信令问题不严重，可以保持现有代码
   - 如果问题较多，再考虑迁移到Sippy

3. ⏳ **第三步：迁移SIP信令到Sippy**（可选）
   - 在媒体中继稳定后
   - 有充分时间研究和测试时
   - 逐步迁移，确保稳定性

## 回退方案

如果迁移后出现问题，可以快速回退：

```bash
# 恢复备份
cp run.py.backup.* run.py
cp -r sipcore.backup.* sipcore

# 重启服务器
pm2 restart ims-server
```

## 支持资源

- **RTPProxy文档**: `INSTALL_RTPPROXY.md`, `RTPPROXY_QUICKSTART.md`
- **Sippy文档**: `INSTALL_SIPPY.md`, `SIPPY_QUICKSTART.md`
- **Sippy GitHub**: https://github.com/sippy/b2bua
- **RTPProxy GitHub**: https://github.com/sippy/rtpproxy

## 注意事项

1. **备份重要**：迁移前务必备份代码
2. **测试充分**：每个阶段都要充分测试
3. **逐步迁移**：不要一次性替换所有代码
4. **保持兼容**：迁移过程中保持API兼容，便于回退
5. **文档记录**：记录迁移过程中的问题和解决方案
