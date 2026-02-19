# 日志文件

本目录存放服务器运行日志。

## 📁 文件说明

### ims-sip-server.log

服务器主日志文件，记录所有 SIP 消息和系统事件。

**日志格式：**
```
2025-10-27 12:00:00 [INFO] UDP server listening on 0.0.0.0:5060
2025-10-27 12:00:01 [RX] 192.168.1.100:5060 -> REGISTER sip:server.com SIP/2.0
2025-10-27 12:00:01 [TX] 192.168.1.100:5060 <- SIP/2.0 200 OK
```

## 📊 日志级别

| 级别 | 说明 | 用途 |
|-----|------|------|
| **DEBUG** | 详细调试信息 | 开发和故障排查 |
| **INFO** | 一般信息 | 生产环境推荐 |
| **WARNING** | 警告信息 | 需要注意的事件 |
| **ERROR** | 错误信息 | 需要处理的错误 |
| **CRITICAL** | 严重错误 | 系统级故障 |

## 🔍 查看日志

### 实时查看
```bash
# 查看所有日志
tail -f logs/ims-sip-server.log

# 只看错误
tail -f logs/ims-sip-server.log | grep ERROR

# 只看 SIP 消息
tail -f logs/ims-sip-server.log | grep -E "\[RX\]|\[TX\]|\[FWD\]"

# 只看 CDR 相关
tail -f logs/ims-sip-server.log | grep CDR
```

### 搜索日志
```bash
# 搜索特定 Call-ID
grep "abc123-callid" logs/ims-sip-server.log

# 搜索特定用户
grep "sip:1001@" logs/ims-sip-server.log

# 搜索错误
grep ERROR logs/ims-sip-server.log

# 搜索网络错误
grep "No route to host" logs/ims-sip-server.log
```

### 统计分析
```bash
# 统计各级别日志数量
grep -o "\[INFO\]\|\[WARNING\]\|\[ERROR\]" logs/ims-sip-server.log | sort | uniq -c

# 统计消息类型
grep -o "INVITE\|REGISTER\|BYE\|CANCEL\|MESSAGE" logs/ims-sip-server.log | sort | uniq -c

# 统计错误次数
grep ERROR logs/ims-sip-server.log | wc -l
```

## 🗑️ 日志清理

### 手动清理
```bash
# 清空日志（服务器运行时）
> logs/ims-sip-server.log

# 备份并清空
mv logs/ims-sip-server.log logs/ims-sip-server.log.$(date +%Y%m%d)
```

### 自动归档（推荐）

创建日志轮转配置（logrotate）：

```bash
# /etc/logrotate.d/ims-sip-server
/path/to/ims/logs/ims-sip-server.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

## ⚙️ 修改日志级别

### 通过 Web 界面（推荐）
1. 访问 http://localhost:8888
2. 在"可编辑配置"中找到 `LOG_LEVEL`
3. 选择新级别（DEBUG/INFO/WARNING/ERROR）
4. 点击"应用"

### 通过配置文件
编辑 `config/config.json`：
```json
{
  "LOG_LEVEL": "INFO"
}
```

### 通过代码
编辑 `run.py`：
```python
log = init_logging(level="INFO", log_file="logs/ims-sip-server.log")
```

## 📝 日志标记说明

| 标记 | 说明 |
|-----|------|
| `[RX]` | 接收到的消息 |
| `[TX]` | 发送的消息 |
| `[FWD]` | 转发的消息 |
| `[DROP]` | 丢弃的消息 |
| `[CDR]` | CDR 相关 |
| `[DIALOG]` | 对话状态 |
| `[TIMER]` | 定时器事件 |
| `[AUTH]` | 认证相关 |
| `[ERROR]` | 错误信息 |

## 📚 相关文档

- [日志系统文档](SIP_CORE_README.md#日志系统)
- [故障排查指南](../README.md#常见问题)

---

**注意**：生产环境建议使用 INFO 或 WARNING 级别，避免日志文件过大。

