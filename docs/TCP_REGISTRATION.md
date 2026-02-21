# TCP 注册支持

项目支持 **SIP over TCP** 注册，允许客户端通过TCP连接进行SIP注册。

## 启用TCP服务器

### 方法1：环境变量（推荐）

```bash
# 启用TCP服务器
export ENABLE_TCP=1

# 启动服务
python run.py
# 或
pm2 restart ecosystem.config.js
```

### 方法2：PM2配置

编辑 `ecosystem.config.js`:

```javascript
env: {
  SERVER_IP: 'AUTO_DETECT',
  ENABLE_TCP: '1',  // 启用TCP服务器
  NODE_ENV: 'production'
}
```

### 方法3：使用内网穿透脚本

使用ngrok或Cloudflare Tunnel时，TCP服务器会自动启用：

```bash
# ngrok（自动启用TCP）
./scripts/start_with_tunnel.sh ngrok pm2

# Cloudflare Tunnel（自动启用TCP）
./scripts/start_with_tunnel.sh cloudflare pm2
```

## 验证TCP服务器

启动后，日志中应该看到：

```
[SIP/TCP] TCP服务器已启动，监听 0.0.0.0:5060
```

## 客户端配置

### SIP客户端设置

1. **服务器地址**: 你的服务器IP或域名
2. **端口**: 5060
3. **传输协议**: **TCP**（重要！）
4. **用户名/密码**: 配置的用户凭据

### 示例配置

**Linphone**:
- 传输: TCP
- 服务器: your-server.com:5060

**Zoiper**:
- Protocol: TCP
- Server: your-server.com
- Port: 5060

**sip_client_standalone.py**:
```python
# 注意：当前客户端只支持UDP，需要修改为TCP
# 或使用支持TCP的客户端库
```

## TCP vs UDP

| 特性 | UDP | TCP |
|------|-----|-----|
| **连接方式** | 无连接 | 面向连接 |
| **可靠性** | 不保证 | 保证 |
| **NAT穿透** | 需要保活 | 更容易 |
| **防火墙** | 可能被阻止 | 通常允许 |
| **性能** | 更快 | 稍慢 |
| **内网穿透** | 需要UDP支持 | 大多数支持 |

## 使用场景

### 1. 内网穿透（推荐）

使用ngrok或Cloudflare Tunnel时，TCP是唯一选择：

```bash
# ngrok TCP隧道
./scripts/start_with_tunnel.sh ngrok pm2

# Cloudflare Tunnel（只支持TCP）
./scripts/start_with_tunnel.sh cloudflare pm2
```

### 2. NAT环境

TCP在NAT环境下更容易穿透，不需要频繁的UDP保活。

### 3. 防火墙限制

某些网络环境可能阻止UDP，但允许TCP。

## 注意事项

1. **同时支持UDP和TCP**: 启用TCP后，UDP仍然可用
2. **端口相同**: TCP和UDP都监听5060端口
3. **处理逻辑相同**: TCP和UDP使用相同的消息处理逻辑
4. **连接管理**: TCP需要管理连接状态，UDP是无状态的

## 故障排查

### TCP服务器未启动

检查日志：
```bash
pm2 logs ims-server | grep TCP
```

应该看到：
```
[SIP/TCP] TCP服务器已启动，监听 0.0.0.0:5060
```

如果没有，检查：
1. 环境变量是否正确设置
2. 端口5060是否被占用
3. 查看错误日志

### 客户端无法连接

1. **检查防火墙**: 确保TCP 5060端口开放
2. **检查服务器地址**: 使用正确的IP或域名
3. **检查传输协议**: 客户端必须选择TCP
4. **查看服务器日志**: 检查是否有连接尝试

### 测试TCP连接

```bash
# 使用telnet测试TCP连接
telnet your-server.com 5060

# 或使用nc
nc -v your-server.com 5060
```

## 相关文档

- [内网穿透方案](FREE_TUNNEL_SOLUTIONS.md)
- [Cloudflare隧道](CLOUDFLARE_TUNNEL.md)
- [动态IP解决方案](DYNAMIC_IP_SOLUTION.md)
