# 数据包抓取功能快速开始

## 功能简介

MML Web界面集成了实时数据包抓取功能，基于tcpdump实现，支持：
- ✅ 实时抓包显示
- ✅ tcpdump过滤表达式
- ✅ 前端显示过滤
- ✅ 自动识别SIP消息

## 快速开始（3步）

### 步骤1: 安装tcpdump（如果未安装）

```bash
# Ubuntu/Debian
apt-get install tcpdump

# CentOS/RHEL
yum install tcpdump
```

### 步骤2: 确保服务器有抓包权限

```bash
# 方式1: 使用root运行（推荐）
sudo python3 run.py

# 方式2: 设置CAP_NET_RAW能力
sudo setcap cap_net_raw,cap_net_admin=eip /usr/bin/tcpdump
```

### 步骤3: 使用Web界面抓包

1. 打开MML Web界面：`http://服务器IP:8888`
2. 点击顶部的"📡 数据包抓取"标签页
3. 选择网络接口（默认：any）
4. 输入过滤表达式（可选，如：`port 5060`）
5. 点击"开始抓包"

## 常用过滤表达式

### SIP相关

```
port 5060                    # SIP端口
udp port 5060                # UDP SIP
tcp port 5060                # TCP SIP
port 5060 or port 5061       # 多个SIP端口
```

### 主机过滤

```
host 192.168.1.100           # 指定IP
net 192.168.1.0/24           # 指定网段
src host 192.168.1.100        # 源IP
dst host 192.168.1.100        # 目标IP
```

### 协议过滤

```
udp                          # UDP协议
tcp                          # TCP协议
icmp                         # ICMP协议
```

### 组合过滤

```
host 192.168.1.100 and port 5060    # 指定主机的SIP流量
udp port 5060 and not port 22        # UDP SIP，排除SSH
```

## 显示过滤

在"显示过滤"输入框中可以过滤已显示的数据包：

- `invite` - 只显示INVITE消息
- `ack` - 只显示ACK消息
- `sip` - 只显示SIP相关数据包
- `192.168.1.100` - 只显示包含该IP的数据包
- `port 5060` - 只显示5060端口的数据包

## 界面说明

### 控制面板

- **网络接口**：选择抓包的网络接口
- **过滤表达式**：tcpdump格式的过滤表达式
- **开始抓包**：启动抓包
- **停止抓包**：停止抓包
- **清空**：清空已显示的数据包列表

### 数据包显示

每个数据包显示：
- **时间戳** - 捕获时间
- **协议** - IP、UDP、TCP等
- **源地址:端口 → 目标地址:端口**
- **长度** - 数据包大小（字节）
- **SIP方法** - 如果是SIP消息
- **原始数据** - tcpdump的原始输出

### 颜色标识

- **蓝色边框** - SIP消息
- **橙色边框** - UDP数据包
- **浅蓝色边框** - TCP数据包
- **紫色边框** - ICMP数据包

## 示例场景

### 场景1: 抓取SIP注册流量

1. 接口：`any`
2. 过滤：`port 5060`
3. 显示过滤：`register`（可选）

### 场景2: 抓取特定用户的呼叫

1. 接口：`any`
2. 过滤：`host 192.168.1.100 and port 5060`
3. 显示过滤：`invite`（可选）

### 场景3: 抓取所有UDP流量

1. 接口：`any`
2. 过滤：`udp`
3. 显示过滤：留空

## 故障排查

### tcpdump未安装

**错误**：`tcpdump: command not found`

**解决**：
```bash
apt-get install tcpdump
```

### 权限不足

**错误**：`tcpdump: socket: Operation not permitted`

**解决**：
- 使用root权限运行服务器
- 或设置CAP_NET_RAW能力

### 数据包不显示

**排查**：
1. 检查过滤表达式是否正确
2. 检查网络接口是否选择正确
3. 查看浏览器控制台是否有错误
4. 检查WebSocket连接是否正常

## 性能优化建议

1. **使用精确的过滤表达式**：减少数据包数量
2. **限制显示数量**：使用显示过滤功能
3. **及时停止抓包**：不需要时停止抓包

## 安全提示

⚠️ **重要**：
- 抓包功能需要root权限
- 抓包可能包含敏感信息
- 确保只有授权用户可以使用
- 大量抓包可能影响服务器性能

## 参考文档

- **详细使用指南**: `PACKET_CAPTURE_GUIDE.md`
- **集成说明**: `PACKET_CAPTURE_INTEGRATION.md`
- **tcpdump文档**: `man tcpdump`
