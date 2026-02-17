# 数据包抓取功能使用指南

## 功能概述

MML Web界面集成了基于tcpdump的实时数据包抓取功能，支持：
- ✅ 实时抓包显示
- ✅ 过滤表达式（tcpdump格式）
- ✅ 显示过滤（前端过滤）
- ✅ 多协议支持（SIP、UDP、TCP、ICMP等）
- ✅ 自动识别SIP消息

## 使用方法

### 1. 访问抓包界面

1. 打开MML Web界面：`http://服务器IP:8888`
2. 点击顶部的"📡 数据包抓取"标签页

### 2. 配置抓包参数

**网络接口**：
- `any` - 抓取所有网络接口（推荐）
- `eth0`, `eth1` - 指定网络接口
- `lo` - 本地回环接口

**过滤表达式**（tcpdump格式）：
- `port 5060` - 只抓取SIP端口
- `host 192.168.1.1` - 只抓取指定主机
- `udp port 5060` - UDP协议的5060端口
- `tcp port 5060` - TCP协议的5060端口
- `host 192.168.1.1 and port 5060` - 组合条件
- 留空 - 抓取所有数据包

**常用过滤表达式示例**：
```
port 5060                    # SIP端口
udp port 5060                # UDP SIP
host 192.168.1.100           # 指定IP
net 192.168.1.0/24           # 指定网段
port 5060 or port 5061       # 多个端口
not port 22                  # 排除SSH
```

### 3. 开始抓包

1. 选择网络接口
2. 输入过滤表达式（可选）
3. 点击"开始抓包"按钮
4. 数据包将实时显示在列表中

### 4. 显示过滤

在"显示过滤"输入框中输入关键词，可以过滤已显示的数据包：
- `sip` - 只显示SIP相关数据包
- `invite` - 只显示INVITE消息
- `192.168.1.100` - 只显示包含该IP的数据包
- `port 5060` - 只显示5060端口的数据包

### 5. 停止抓包

点击"停止抓包"按钮停止抓包。

### 6. 清空列表

点击"清空"按钮清空已显示的数据包列表。

## 数据包显示

### 数据包信息

每个数据包显示：
- **时间戳** - 数据包捕获时间
- **协议** - IP、UDP、TCP、ICMP等
- **源地址:端口** → **目标地址:端口**
- **长度** - 数据包大小（字节）
- **SIP方法** - 如果是SIP消息，显示方法（INVITE、ACK等）
- **原始数据** - tcpdump的原始输出

### 颜色标识

- **蓝色边框** - SIP消息
- **橙色边框** - UDP数据包
- **浅蓝色边框** - TCP数据包
- **紫色边框** - ICMP数据包

## 技术实现

### 后端

- **tcpdump** - 底层抓包工具（系统自带）
- **subprocess** - 实时读取tcpdump输出
- **WebSocket** - 实时传输数据包到前端

### 前端

- **WebSocket** - 接收实时数据包
- **JavaScript** - 解析和显示数据包
- **CSS** - 样式和颜色标识

## 权限要求

抓包功能需要root权限或CAP_NET_RAW能力：

```bash
# 方式1: 使用root运行
sudo python3 run.py

# 方式2: 设置CAP_NET_RAW能力
sudo setcap cap_net_raw,cap_net_admin=eip /usr/bin/tcpdump
```

## 故障排查

### tcpdump未安装

**错误**：`tcpdump: command not found`

**解决**：
```bash
# Ubuntu/Debian
apt-get install tcpdump

# CentOS/RHEL
yum install tcpdump
```

### 权限不足

**错误**：`tcpdump: socket: Operation not permitted`

**解决**：
- 使用root权限运行服务器
- 或设置tcpdump的CAP_NET_RAW能力

### WebSocket连接失败

**错误**：无法连接到WebSocket

**排查**：
1. 检查WebSocket端口是否开放（HTTP端口+1）
2. 检查防火墙设置
3. 查看浏览器控制台错误信息

### 数据包不显示

**排查**：
1. 检查过滤表达式是否正确
2. 检查网络接口是否选择正确
3. 查看浏览器控制台是否有错误
4. 检查WebSocket连接是否正常

## 性能优化

### 限制数据包数量

默认保留最近1000个数据包，避免内存占用过大。

### 过滤表达式优化

使用精确的过滤表达式可以减少数据包数量，提高性能：
- ✅ `port 5060` - 精确过滤
- ❌ 不过滤，然后前端过滤 - 性能较差

## 安全注意事项

1. **权限控制**：抓包功能需要root权限，确保只有授权用户可以使用
2. **数据隐私**：抓包可能包含敏感信息，注意数据保护
3. **性能影响**：大量抓包可能影响服务器性能，建议使用过滤表达式

## 参考资源

- **tcpdump文档**: `man tcpdump`
- **tcpdump过滤表达式**: https://www.tcpdump.org/manpages/pcap-filter.7.html
- **WebSocket API**: https://developer.mozilla.org/en-US/docs/Web/API/WebSocket
