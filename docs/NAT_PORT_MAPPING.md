# NAT端口映射配置指南

## 问题说明

当服务器部署在NAT后（如家庭宽带、企业内网）时，可能出现以下情况：
- **内网端口**: 服务监听在 `5060/UDP`
- **公网端口**: NAT设备将内网5060映射到公网的其他端口（如 `12345`）

这种情况下，SIP客户端需要使用**公网IP:公网端口**来连接，而不是内网端口。

## 解决方案

### 1. 自动检测NAT端口映射（推荐）

使用启动脚本自动检测：

```bash
./scripts/start_with_public_ip.sh pm2
```

脚本会自动：
1. 获取公网IP
2. 通过STUN服务器检测NAT端口映射
3. 更新配置文件中的 `SERVER_PUBLIC_PORT`
4. 设置环境变量 `SERVER_PUBLIC_PORT`

### 2. 手动检测端口映射

```bash
# 检测5060端口的NAT映射
python3 scripts/get_public_port.py --port 5060

# 只输出端口号
python3 scripts/get_public_port.py --port 5060 --format port

# 输出IP:端口
python3 scripts/get_public_port.py --port 5060 --format both
```

### 3. 手动配置公网端口

#### 方式一：环境变量

```bash
export SERVER_IP=your.public.ip.address
export SERVER_PUBLIC_PORT=12345  # NAT映射后的公网端口
pm2 start ecosystem.config.js
```

#### 方式二：配置文件

编辑 `config/config.json`:

```json
{
    "SERVER_ADDR": "your.public.ip.address",
    "SERVER_PORT": 5060,
    "SERVER_PUBLIC_PORT": 12345,
    ...
}
```

#### 方式三：内网穿透服务

如果使用内网穿透（如ngrok、frp），端口映射由穿透服务管理：

```bash
# ngrok示例
ngrok udp 5060
# 输出: Forwarding udp://0.tcp.ngrok.io:12345 -> localhost:5060
# 使用 0.tcp.ngrok.io:12345 作为公网地址
```

## 配置说明

### SERVER_PORT vs SERVER_PUBLIC_PORT

- **SERVER_PORT**: 服务实际监听的端口（内网端口，如5060）
- **SERVER_PUBLIC_PORT**: NAT映射后的公网端口（如12345）

### 代码中的使用

在 `run.py` 中：

```python
SERVER_PORT = 5060  # 内网监听端口
SERVER_PUBLIC_PORT = 12345  # 公网端口（如果配置）

def advertised_sip_port():
    """返回对外宣告的端口（优先使用公网端口）"""
    return SERVER_PUBLIC_PORT or SERVER_PORT
```

SIP消息中的 `Via`、`Contact`、`Record-Route` 等头部会使用 `advertised_sip_port()` 返回的端口。

## 验证配置

### 1. 检查配置

```bash
# 查看配置文件
cat config/config.json | grep -E "SERVER_ADDR|SERVER_PORT|SERVER_PUBLIC_PORT"

# 查看环境变量
pm2 env ims-server | grep SERVER
```

### 2. 测试端口映射

```bash
# 检测端口映射
python3 scripts/get_public_port.py --port 5060

# 从公网测试连接
nc -uv your.public.ip.address 12345  # 使用公网端口
```

### 3. 查看日志

启动服务后，查看日志确认端口配置：

```bash
pm2 logs ims-server | grep -E "SERVER|PORT"
```

应该看到类似输出：
```
[CONFIG] SERVER_ADDR from config: your.public.ip.address
[CONFIG] 使用配置的公网地址: your.public.ip.address（内网IP: 192.168.1.100）
[CONFIG] SERVER_PUBLIC_PORT: 12345
```

## 常见问题

### Q: STUN检测失败怎么办？

A: STUN检测可能因为以下原因失败：
1. 防火墙阻止UDP出站
2. 对称NAT（Symmetric NAT）不支持STUN检测
3. STUN服务器不可达

**解决方案**：
- 手动配置公网端口（通过路由器管理界面查看端口映射）
- 使用内网穿透服务（自动处理端口映射）

### Q: 如何查看路由器的端口映射？

A: 
1. 登录路由器管理界面
2. 查找"端口转发"或"虚拟服务器"设置
3. 查看5060端口的映射规则

### Q: 端口映射会变化吗？

A: 
- **静态NAT**: 端口映射固定，不会变化
- **动态NAT**: 端口映射可能变化（重启路由器后）
- **内网穿透**: 每次启动可能分配不同端口（免费服务）

建议使用DDNS + 静态端口映射，或使用付费的内网穿透服务固定端口。

## 相关文件

- `scripts/get_public_port.py` - NAT端口映射检测工具
- `scripts/start_with_public_ip.sh` - 自动启动脚本（包含端口检测）
- `config/config.json` - 配置文件
- `run.py` - 主程序（使用 `SERVER_PUBLIC_PORT`）
