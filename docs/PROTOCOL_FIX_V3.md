# RTPProxy 3.1.1 协议格式修复

## 问题诊断

根据错误日志：
```
ERR:GLOBAL:rtpp_command_pre_parse:258: unknown command "t"
ERR:GLOBAL:rtpp_command_split:454: command syntax error
```

**问题原因**：
- RTPProxy 3.1.1对命令格式非常严格
- call-id或tag中包含空格或特殊字符导致解析错误
- RTPProxy把"t"（可能是"test-call-id"中的"t"）当作命令了

## 已修复的问题

1. ✅ **清理call-id和tag**: 移除空格、换行等特殊字符
2. ✅ **命令格式**: 确保`V`后无空格，call-id和tag之间有空格
3. ✅ **错误处理**: 改进错误响应解析

## RTPProxy 3.1.1 协议格式

### 命令格式（严格）
```
V<call-id> <from-tag> <to-tag>
```

**重要规则**：
- `V`和`call-id`之间**无空格**
- `call-id`和`from-tag`之间**有空格**
- `from-tag`和`to-tag`之间**有空格**
- `call-id`和`tag`中**不能包含空格**
- `call-id`和`tag`中**不能包含换行符**

### 响应格式
- **成功**: `<port_number>` (RTPProxy分配的端口号)
- **失败**: `V E<error_code>` 或包含`ERR:`的错误信息

## 代码修改

### 修改文件
- `sipcore/rtpproxy_client.py` - `create_offer` 和 `create_answer` 方法

### 修改内容
1. 清理call-id和tag：移除空格、换行符、制表符
2. 空格替换为下划线：避免解析错误
3. 确保命令格式正确：`V`后无空格

## 测试

重启RTPProxy并测试：

```bash
# 重启RTPProxy
pkill rtpproxy
rtpproxy -l 113.44.149.111 -s udp:127.0.0.1:7722 -F -d INFO

# 重启SIP服务器
pm2 restart ims-serv
```

## 如果仍有问题

如果RTPProxy仍然返回错误，可能需要：

1. **检查call-id格式**: 确保call-id不包含特殊字符
   ```python
   # 在run.py中检查call-id格式
   call_id = msg.get("call-id")
   print(f"Call-ID: {repr(call_id)}")
   ```

2. **查看RTPProxy详细日志**: 启用DBUG级别日志
   ```bash
   rtpproxy -l 113.44.149.111 -s udp:127.0.0.1:7722 -F -d DBUG
   ```

3. **测试简单call-id**: 使用简单的call-id测试
   ```python
   # 测试命令
   python3 -c "
   import socket
   s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
   s.connect(('127.0.0.1', 7722))
   s.sendall(b'Vabc123 tag1 tag2\n')
   print(s.recv(1024).decode())
   "
   ```

4. **检查RTPProxy版本兼容性**: RTPProxy 3.1.1可能使用不同的协议格式

## 参考

- RTPProxy版本: 3.1.1c8206f9
- RTPProxy文档: https://www.rtpproxy.org/doc/master/user_manual.html
- RTPProxy源码: https://github.com/sippy/rtpproxy
