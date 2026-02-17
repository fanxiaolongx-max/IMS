# RTPProxy协议格式修复总结

## 问题诊断

根据测试结果，RTPProxy返回 `E0` 错误，说明协议格式不正确。

## 已修复的问题

1. ✅ **协议格式修复**: 从 `U` 命令改为 `V` 命令格式
2. ✅ **命令格式**: `V<call-id> <from-tag> <to-tag>`（call-id和from-tag之间无空格）

## RTPProxy协议说明

RTPProxy使用rtpp协议，命令格式：

### 创建会话（200 OK阶段）
```
V<call-id> <from-tag> <to-tag>
```

**注意**：
- `V` 和 `call-id` 之间**无空格**
- `call-id` 和 `from-tag` 之间**有空格**
- `from-tag` 和 `to-tag` 之间**有空格**

### 响应格式
- **成功**: `<port_number>` (RTPProxy分配的端口号)
- **失败**: `V E<error_code>` 或 `U E<error_code>`

## 代码修改

### 修改文件
- `sipcore/rtpproxy_client.py` - `create_session` 方法

### 修改内容
1. 从 `U` 命令改为 `V` 命令
2. 移除了IP:port参数（RTPProxy会自动学习）
3. 改进了错误处理和响应解析

## 下一步

1. **重启SIP服务器**: 让代码更改生效
2. **测试通话**: 在WiFi环境下测试通话
3. **检查日志**: 确认RTPProxy会话创建成功

## 如果仍有问题

如果RTPProxy仍然返回错误，可能需要：

1. **检查RTPProxy版本**: 不同版本可能使用不同的协议格式
   ```bash
   rtpproxy -V
   ```

2. **查看RTPProxy日志**: 启用详细日志
   ```bash
   rtpproxy -l <server_ip> -s udp:127.0.0.1:7722 -F -d DBUG
   ```

3. **尝试两步协议**: RTPProxy可能需要先发送offer，再发送answer
   - INVITE阶段：`V<call-id> <from-tag>` - 返回端口
   - 200 OK阶段：`V<call-id> <from-tag> <to-tag>` - 完成会话

4. **检查call-id和tag格式**: 确保call-id和tag中没有特殊字符

## 参考

- RTPProxy文档: https://www.rtpproxy.org/doc/master/user_manual.html
- RTPProxy源码: https://github.com/sippy/rtpproxy
