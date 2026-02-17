# 数据包抓取功能集成说明

## 功能概述

在MML Web界面中集成了基于tcpdump的实时数据包抓取功能，支持：
- ✅ 实时抓包显示
- ✅ tcpdump过滤表达式
- ✅ 前端显示过滤
- ✅ 多协议支持（SIP、UDP、TCP、ICMP等）
- ✅ 自动识别SIP消息

## 架构设计

### 后端组件

1. **packet_capture.py** - 数据包抓取模块
   - 使用tcpdump进行抓包
   - 解析tcpdump输出
   - 订阅/通知机制

2. **mml_server.py** - Web服务器
   - HTTP API：启动/停止/统计
   - WebSocket：实时传输数据包

### 前端组件

1. **HTML界面** - 抓包面板
   - 控制面板（接口选择、过滤表达式）
   - 数据包列表显示
   - 显示过滤

2. **JavaScript** - 交互逻辑
   - WebSocket连接
   - 数据包解析和显示
   - 过滤功能

## 文件清单

### 新增文件

- `web/packet_capture.py` - 数据包抓取模块
- `web/PACKET_CAPTURE_GUIDE.md` - 使用指南
- `web/PACKET_CAPTURE_INTEGRATION.md` - 本文档

### 修改文件

- `web/mml_server.py` - 添加抓包API和WebSocket支持
- `web/mml_interface.html` - 添加抓包面板和JavaScript

## API接口

### HTTP API

**启动抓包**：
```
GET /api/packet-capture?action=start&interface=any&filter=port 5060
```

**停止抓包**：
```
GET /api/packet-capture?action=stop
```

**获取统计**：
```
GET /api/packet-capture?action=stats
```

### WebSocket API

**连接**：
```
ws://服务器IP:8889/ws/packets
```

**数据格式**：
```json
{
  "timestamp": "12:34:56.789123",
  "protocol": "IP",
  "src_ip": "192.168.1.100",
  "src_port": "5060",
  "dst_ip": "192.168.1.200",
  "dst_port": "5060",
  "length": "123",
  "flags": "",
  "sip_method": "INVITE",
  "raw": "12:34:56.789123 IP 192.168.1.100.5060 > 192.168.1.200.5060: UDP, length 123",
  "packet_num": 1
}
```

## 使用示例

### 1. 抓取SIP流量

1. 打开MML Web界面
2. 点击"📡 数据包抓取"标签
3. 选择接口：`any`
4. 输入过滤：`port 5060`
5. 点击"开始抓包"

### 2. 抓取特定主机

过滤表达式：`host 192.168.1.100`

### 3. 抓取UDP流量

过滤表达式：`udp port 5060`

### 4. 显示过滤

在"显示过滤"框中输入：
- `invite` - 只显示INVITE消息
- `sip` - 只显示SIP相关数据包
- `192.168.1.100` - 只显示包含该IP的数据包

## 技术细节

### tcpdump命令

```bash
tcpdump -i any -n -l -q "port 5060"
```

参数说明：
- `-i any` - 监听所有接口
- `-n` - 不解析主机名
- `-l` - 行缓冲输出
- `-q` - 快速输出（较少信息）
- `port 5060` - 过滤表达式

### 数据包解析

tcpdump输出格式：
```
12:34:56.789123 IP 192.168.1.100.5060 > 192.168.1.200.5060: UDP, length 123
```

解析为：
- 时间戳：`12:34:56.789123`
- 协议：`IP`
- 源地址：`192.168.1.100`
- 源端口：`5060`
- 目标地址：`192.168.1.200`
- 目标端口：`5060`
- 协议：`UDP`
- 长度：`123`

## 权限要求

抓包需要root权限或CAP_NET_RAW能力：

```bash
# 方式1: 使用root运行
sudo python3 run.py

# 方式2: 设置CAP_NET_RAW能力
sudo setcap cap_net_raw,cap_net_admin=eip /usr/bin/tcpdump
```

## 性能考虑

1. **数据包数量限制**：默认保留最近1000个数据包
2. **过滤表达式**：使用精确的过滤表达式减少数据包数量
3. **WebSocket传输**：异步传输，不阻塞主线程

## 安全注意事项

1. **权限控制**：确保只有授权用户可以使用
2. **数据隐私**：抓包可能包含敏感信息
3. **性能影响**：大量抓包可能影响服务器性能

## 故障排查

### tcpdump未安装

```bash
apt-get install tcpdump
```

### 权限不足

使用root权限运行服务器或设置CAP_NET_RAW能力。

### WebSocket连接失败

检查WebSocket端口是否开放（HTTP端口+1）。

## 参考资源

- **tcpdump文档**: `man tcpdump`
- **tcpdump过滤表达式**: https://www.tcpdump.org/manpages/pcap-filter.7.html
- **WebSocket API**: https://developer.mozilla.org/en-US/docs/Web/API/WebSocket
