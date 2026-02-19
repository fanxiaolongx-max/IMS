# RTPProxy 快速开始指南

## 概述

已创建基于成熟开源RTPProxy的媒体中继实现，替代自定义RTP转发代码。

## 文件说明

- `sipcore/rtpproxy_client.py` - RTPProxy客户端（与rtpproxy通信）
- `sipcore/rtpproxy_media_relay.py` - RTPProxy媒体中继（兼容现有API）
- `INSTALL_RTPPROXY.md` - 详细安装配置文档
- `switch_to_rtpproxy.sh` - 自动切换脚本

## 快速开始（3步）

### 步骤1: 安装rtpproxy

```bash
apt-get update
apt-get install rtpproxy
```

### 步骤2: 启动rtpproxy

**方式A: TCP socket（推荐用于测试）**
```bash
rtpproxy -l 113.44.149.111 -s udp:127.0.0.1:7722 -F
```

**方式B: Unix socket（推荐用于生产）**
```bash
rtpproxy -l 113.44.149.111 -s unix:/var/run/rtpproxy.sock -F
```

### 步骤3: 修改代码使用RTPProxy

在 `run.py` 中，找到：

```python
from sipcore.media_relay import init_media_relay, get_media_relay
```

替换为：

```python
from sipcore.rtpproxy_media_relay import init_media_relay, get_media_relay
```

然后在初始化部分（约1777行），修改为：

```python
# 使用TCP socket
media_relay = init_media_relay(
    SERVER_IP,
    rtpproxy_tcp=('127.0.0.1', 7722)
)

# 或使用Unix socket
media_relay = init_media_relay(
    SERVER_IP,
    rtpproxy_socket='/var/run/rtpproxy.sock'
)
```

### 步骤4: 重启服务器

```bash
pm2 restart ims-server
```

## 验证

1. 检查rtpproxy是否运行：
   ```bash
   ps aux | grep rtpproxy
   ```

2. 检查日志中是否有：
   ```
   [RTPProxy] 已连接到...
   [RTPProxyMediaRelay] 初始化完成...
   ```

3. 测试通话，观察日志：
   ```
   [RTPProxy] 创建会话成功: ...
   [RTPProxyMediaRelay] 媒体转发已启动: ...
   ```

## 优势

相比自定义代码，RTPProxy提供：

✅ **成熟稳定** - 广泛用于Kamailio、OpenSIPS等生产环境  
✅ **自动NAT穿透** - 自动处理对称RTP和NAT问题  
✅ **高性能** - 低延迟、低丢包率  
✅ **功能丰富** - 支持ICE、SRTP、录音等  
✅ **易于维护** - 无需维护复杂的RTP转发逻辑  

## 故障排查

### rtpproxy无法启动
- 检查端口是否被占用
- 检查socket文件权限（Unix socket）
- 查看rtpproxy错误信息

### Python无法连接
- 确认rtpproxy已启动：`ps aux | grep rtpproxy`
- 检查socket路径或TCP地址是否正确
- 查看Python错误日志

### 媒体无法转发
- 检查rtpproxy日志
- 确认服务器IP配置正确
- 检查RTP端口是否开放（防火墙）

## 回退到原代码

如果需要回退：

```bash
# 恢复备份
cp sipcore/media_relay.py.backup.* sipcore/media_relay.py

# 恢复run.py
cp run.py.bak run.py

# 重启服务器
pm2 restart ims-server
```

## 更多信息

详细文档请参考：`INSTALL_RTPPROXY.md`
