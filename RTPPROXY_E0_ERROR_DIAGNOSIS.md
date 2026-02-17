# RTPProxy E0错误诊断报告

## 问题描述

WiFi环境下通话单通，日志显示媒体转发启动失败：
```
[B2BUA] 媒体转发启动结果: dEokXLzlj5, result=False
```

## 诊断结果

### 1. RTPProxy连接正常
- RTPProxy进程运行正常：`rtpproxy -l 113.44.149.111 -s udp:127.0.0.1:7722`
- UDP控制socket连接成功
- Python客户端可以连接到RTPProxy

### 2. 协议格式问题

测试结果显示RTPProxy返回E0错误：

**V命令测试**：
```
命令: Vtestcall123 tagfrom123 tagto456
响应: 'Vtestcall123 E0\n'
```

**U命令测试**：
```
命令: Utestcall123 tagfrom123 tagto456 192.168.1.100:10000 192.168.1.200:20000
响应: 'Utestcall123 E5\n'
```

### 3. 可能的原因

根据RTPProxy文档和错误代码：
- **E0**: 参数错误或命令格式不正确
- **E5**: 命令格式错误或参数不完整

可能的问题：
1. RTPProxy 3.1.1可能需要两步协议（先offer后answer），但offer命令也返回E0
2. 协议格式可能不同（不是简单的V或U命令）
3. 可能需要SDP内容而不是简单的call-id和tag
4. RTPProxy配置可能不正确

### 4. 已尝试的修复

1. ✅ 实现两步协议（先offer后answer）
2. ✅ 清理call-id和tag中的特殊字符
3. ✅ 尝试U命令格式（带IP地址参数）
4. ✅ 添加详细的错误日志

### 5. 下一步建议

1. **检查RTPProxy版本和配置**：
   ```bash
   rtpproxy -V
   rtpproxy -v
   ```

2. **查看RTPProxy详细日志**：
   ```bash
   pkill rtpproxy
   rtpproxy -l 113.44.149.111 -s udp:127.0.0.1:7722 -F -d DBUG
   ```

3. **检查RTPProxy源码或文档**：
   - 查看RTPProxy的实际协议格式
   - 确认E0和E5错误代码的含义
   - 检查是否需要其他参数或配置

4. **尝试其他RTPProxy实现**：
   - 考虑使用其他RTPProxy版本或实现
   - 或者使用其他媒体中继方案（如Sippy B2BUA的媒体处理）

5. **临时解决方案**：
   - 如果RTPProxy无法正常工作，可以考虑：
     - 使用自定义媒体转发（之前的实现）
     - 或者暂时禁用媒体中继，让客户端直接通信（如果网络允许）

## 当前状态

- ✅ RTPProxy服务运行正常
- ✅ UDP控制socket连接正常
- ❌ RTPProxy协议命令返回E0/E5错误
- ❌ 媒体转发无法启动
- ❌ WiFi环境下通话单通

## 参考

- RTPProxy文档: https://www.rtpproxy.org/doc/master/user_manual.html
- RTPProxy源码: https://github.com/sippy/rtpproxy
- RTPProxy错误代码: 需要查看源码或文档确认E0和E5的含义
