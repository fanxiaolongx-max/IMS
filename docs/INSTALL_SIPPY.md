# Sippy B2BUA 安装和配置指南

本文档说明如何安装和配置Sippy B2BUA，以替代自定义SIP信令处理代码。

## 1. 什么是Sippy B2BUA

Sippy是一个成熟的Python SIP B2BUA库，具有以下特性：

- ✅ **RFC3261完全兼容** - 符合SIP标准
- ✅ **自动事务管理** - 自动处理SIP事务和对话
- ✅ **RTPProxy集成** - 内置RTPProxy支持
- ✅ **高性能** - 支持5000-10000并发会话
- ✅ **生产级** - 广泛用于生产环境
- ✅ **完善的错误处理** - 自动处理各种异常情况

## 2. 安装

### 方式1: 从PyPI安装（推荐）

```bash
pip install sippy
```

### 方式2: 从GitHub安装最新版本

```bash
pip install git+https://github.com/sippy/b2bua
```

### 方式3: 安装特定版本

```bash
pip install sippy==2.2.3
```

## 3. 依赖项

Sippy需要以下依赖（会自动安装）：

- Python 3.6+
- Twisted（异步网络框架）
- 其他标准库

## 4. 基本使用

### 4.1 简单B2BUA服务器

```python
from sipcore.sippy_b2bua import SippyB2BUAServer

# 创建服务器
server = SippyB2BUAServer(
    server_ip='113.44.149.111',
    server_port=5060,
    rtpproxy_tcp=('127.0.0.1', 7722)  # 或使用Unix socket
)

# 启动服务器
server.start()

# 服务器会一直运行，直到调用stop()
```

### 4.2 集成CDR和注册管理

```python
from sipcore.sippy_b2bua import SippyB2BUAServer

def cdr_callback(event_type, data):
    """CDR回调函数"""
    if event_type == 'CALL_START':
        print(f"呼叫开始: {data['call_id']}, {data['caller']} -> {data['callee']}")
    elif event_type == 'CALL_END':
        print(f"呼叫结束: {data['call_id']}, 持续时间={data['duration']:.2f}秒")

# 创建服务器（带CDR回调）
server = SippyB2BUAServer(
    server_ip='113.44.149.111',
    server_port=5060,
    rtpproxy_tcp=('127.0.0.1', 7722),
    registrations=REG_BINDINGS,  # 注册信息字典
    cdr_callback=cdr_callback
)

server.start()
```

## 5. 与现有代码集成

### 5.1 替换run.py中的SIP处理

在`run.py`中，将现有的SIP处理逻辑替换为：

```python
from sipcore.sippy_b2bua import SippyB2BUAServer

# 创建B2BUA服务器
sippy_server = SippyB2BUAServer(
    server_ip=SERVER_IP,
    server_port=SERVER_PORT,
    rtpproxy_tcp=('127.0.0.1', 7722),  # 或使用Unix socket
    registrations=REG_BINDINGS,
    cdr_callback=lambda event, data: cdr.record_call(...)  # 集成CDR
)

# 启动服务器
sippy_server.start()
```

### 5.2 保持现有功能

Sippy B2BUA会自动处理：
- ✅ SIP消息解析和验证
- ✅ 事务管理（INVITE, ACK, BYE等）
- ✅ 对话管理
- ✅ NAT穿透
- ✅ RTPProxy集成
- ✅ 错误处理和重传

## 6. 配置选项

### 6.1 RTPProxy配置

**使用TCP socket:**
```python
rtpproxy_tcp=('127.0.0.1', 7722)
```

**使用Unix socket:**
```python
rtpproxy_socket='/var/run/rtpproxy.sock'
```

### 6.2 服务器配置

```python
server = SippyB2BUAServer(
    server_ip='113.44.149.111',      # 服务器IP
    server_port=5060,                # 服务器端口
    registrations=REG_BINDINGS,      # 注册信息
    cdr_callback=cdr_handler         # CDR回调
)
```

## 7. 高级功能

### 7.1 获取会话信息

```python
# 获取特定会话
session = server.get_session('call-id-123')
if session:
    print(f"主叫: {session['caller']}")
    print(f"被叫: {session['callee']}")
    print(f"持续时间: {time.time() - session['started_at']:.2f}秒")

# 获取所有活跃会话
all_sessions = server.handler.get_all_sessions()
print(f"活跃呼叫数: {len(all_sessions)}")
```

### 7.2 获取统计信息

```python
stats = server.get_stats()
print(f"活跃呼叫: {stats['active_calls']}")
print(f"总通话时长: {stats['total_duration']:.2f}秒")
```

## 8. 故障排查

### 8.1 导入错误

如果遇到`ImportError: No module named 'sippy'`：

```bash
pip install sippy
# 或
pip install git+https://github.com/sippy/b2bua
```

### 8.2 RTPProxy连接失败

确保RTPProxy已启动：

```bash
# 检查rtpproxy是否运行
ps aux | grep rtpproxy

# 启动rtpproxy
rtpproxy -l <服务器IP> -s udp:127.0.0.1:7722 -F
```

### 8.3 SIP消息处理问题

查看Sippy日志：

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 9. 性能优化

### 9.1 并发处理

Sippy使用Twisted异步框架，自动处理并发：

- 支持5000-10000并发会话
- 150-400呼叫建立/拆除每秒
- 低延迟、高吞吐量

### 9.2 资源管理

Sippy自动管理：
- SIP事务超时
- 对话清理
- 内存回收

## 10. 迁移步骤

### 步骤1: 安装Sippy

```bash
pip install sippy
```

### 步骤2: 备份现有代码

```bash
cp run.py run.py.backup
```

### 步骤3: 修改代码使用Sippy

参考第5节"与现有代码集成"

### 步骤4: 测试

```bash
# 启动服务器
python run.py

# 测试呼叫
# 观察日志，确认SIP消息正确处理
```

### 步骤5: 逐步迁移功能

- 先迁移基本呼叫功能
- 再迁移注册管理
- 最后迁移CDR和其他功能

## 11. 优势对比

### 自定义代码 vs Sippy B2BUA

| 特性 | 自定义代码 | Sippy B2BUA |
|------|-----------|-------------|
| RFC3261兼容 | 需要手动实现 | ✅ 完全兼容 |
| 事务管理 | 手动处理 | ✅ 自动处理 |
| 错误处理 | 需要大量代码 | ✅ 内置完善 |
| NAT穿透 | 需要手动处理 | ✅ 自动处理 |
| RTPProxy集成 | 需要手动集成 | ✅ 内置支持 |
| 性能 | 取决于实现 | ✅ 高性能 |
| 维护成本 | 高 | ✅ 低 |
| 生产就绪 | 需要大量测试 | ✅ 已验证 |

## 12. 参考资源

- **GitHub仓库**: https://github.com/sippy/b2bua
- **PyPI包**: https://pypi.org/project/sippy/
- **文档**: https://github.com/sippy/b2bua/tree/master/docs
- **示例代码**: https://github.com/sippy/b2bua/tree/master/apps

## 13. 支持

如遇问题，可以：

1. 查看Sippy GitHub Issues: https://github.com/sippy/b2bua/issues
2. 查看Sippy文档和示例
3. 检查日志输出
