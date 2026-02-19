# Sippy B2BUA 快速开始指南

## 概述

已创建基于成熟开源Sippy B2BUA的SIP信令处理实现，替代自定义SIP处理代码。

## 文件说明

- `sipcore/sippy_b2bua.py` - Sippy B2BUA包装器（兼容现有功能）
- `INSTALL_SIPPY.md` - 详细安装配置文档

## 快速开始（4步）

### 步骤1: 安装Sippy

```bash
pip install sippy
```

### 步骤2: 确保RTPProxy已运行

```bash
# 检查rtpproxy
ps aux | grep rtpproxy

# 如果未运行，启动它
rtpproxy -l 113.44.149.111 -s udp:127.0.0.1:7722 -F
```

### 步骤3: 修改代码使用Sippy

在`run.py`中，添加：

```python
from sipcore.sippy_b2bua import SippyB2BUAServer

# 在main()函数中，替换现有的SIP处理逻辑
sippy_server = SippyB2BUAServer(
    server_ip=SERVER_IP,
    server_port=SERVER_PORT,
    rtpproxy_tcp=('127.0.0.1', 7722),  # 或使用Unix socket
    registrations=REG_BINDINGS,
    cdr_callback=lambda event, data: handle_cdr(event, data)
)

# 启动服务器
sippy_server.start()
```

### 步骤4: 重启服务器

```bash
pm2 restart ims-server
```

## 验证

1. 检查Sippy是否加载：
   ```
   [SippyB2BUA] 初始化完成: ...
   [SippyB2BUA] 服务器已启动: ...
   ```

2. 测试呼叫，观察日志：
   ```
   [SippyB2BUA] 呼叫开始: ...
   [SippyB2BUA] 呼叫结束: ...
   ```

## 优势

相比自定义代码，Sippy B2BUA提供：

✅ **RFC3261兼容** - 完全符合SIP标准  
✅ **自动事务管理** - 无需手动处理SIP事务  
✅ **完善的错误处理** - 自动处理各种异常  
✅ **高性能** - 支持5000-10000并发会话  
✅ **RTPProxy集成** - 内置媒体中继支持  
✅ **易于维护** - 无需维护复杂的SIP逻辑  

## 故障排查

### Sippy未安装
```bash
pip install sippy
```

### RTPProxy连接失败
- 确认rtpproxy已启动
- 检查socket路径或TCP地址

### SIP消息处理问题
- 查看Sippy日志
- 检查配置是否正确

## 更多信息

详细文档请参考：`INSTALL_SIPPY.md`
