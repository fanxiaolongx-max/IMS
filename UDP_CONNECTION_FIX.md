# RTPProxy UDP连接修复

## 问题诊断

**错误**: `[Errno 111] Connection refused`

**根本原因**: 
- RTPProxy使用UDP控制socket (`-s udp:127.0.0.1:7722`)
- 但客户端代码尝试使用TCP连接 (`socket.SOCK_STREAM`)
- 导致连接失败

## 已修复的问题

1. ✅ **添加UDP连接支持**: `RTPProxyClient` 现在支持UDP连接
2. ✅ **更新配置**: `run.py` 使用 `RTPPROXY_UDP` 而不是 `RTPPROXY_TCP`
3. ✅ **更新初始化**: `init_media_relay` 传递 `rtpproxy_udp` 参数

## 代码修改

### 1. `sipcore/rtpproxy_client.py`
- 添加 `udp_addr` 参数
- `_connect()` 方法支持UDP socket连接

### 2. `sipcore/rtpproxy_media_relay.py`
- 添加 `rtpproxy_udp` 参数支持
- 更新错误提示信息

### 3. `run.py`
- 添加 `RTPPROXY_UDP` 配置
- 使用 `rtpproxy_udp` 而不是 `rtpproxy_tcp`

## 验证

UDP连接测试已通过：
```
[RTPProxy] 已连接到UDP: 127.0.0.1:7722
UDP连接测试成功
```

## 下一步

重启SIP服务器以应用修复：

```bash
pm2 restart ims-serv
```

重启后，日志应该显示：
```
[B2BUA] RTPProxy媒体中继已初始化，服务器IP: 113.44.149.111
[B2BUA] RTPProxy地址: 127.0.0.1:7722 (UDP)
[RTPProxy] 已连接到UDP: 127.0.0.1:7722
[RTPProxyMediaRelay] RTPProxy客户端初始化成功
```

## 总结

问题已修复：RTPProxy使用UDP控制socket，代码现在正确使用UDP连接而不是TCP连接。
