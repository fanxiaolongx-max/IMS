# 局域网版本配置说明

## 当前配置

项目已恢复为局域网版本，所有IP配置使用 `AUTO_DETECT`，会自动检测并使用内网IP。

### 配置文件状态

- ✅ `config/config.json`: `SERVER_ADDR` = `"AUTO_DETECT"`
- ✅ `sip_client_config.json`: `server_ip`, `local_ip`, `sdp_ip` = `"AUTO_DETECT"`
- ✅ `ecosystem.config.js`: `SERVER_IP` = `'AUTO_DETECT'`

### 自动检测的内网IP

服务会自动检测并使用内网IP：**192.168.100.8**

## 使用方法

### 启动服务

```bash
# 使用PM2启动
pm2 restart ecosystem.config.js

# 或直接启动
python3 run.py
```

### 客户端配置

SIP客户端需要配置：
- **服务器地址**: `192.168.100.8`（或使用检测到的内网IP）
- **端口**: `5060`
- **传输协议**: UDP（默认）或TCP（如果启用了）

## 停止ngrok

如果之前使用了ngrok，可以使用以下方法停止：

### 方法1：使用停止脚本

```bash
./scripts/stop_ngrok.sh
```

### 方法2：手动停止

```bash
# 停止所有ngrok进程
pkill -f ngrok

# 或通过端口停止
lsof -ti :4040 | xargs kill
```

### 方法3：查看并停止

```bash
# 查看ngrok进程
ps aux | grep ngrok

# 停止特定进程
kill <PID>
```

## 恢复到局域网版本

如果配置了公网IP，可以使用恢复脚本：

```bash
./scripts/restore_to_local.sh
```

脚本会自动：
1. 恢复所有配置文件为 `AUTO_DETECT`
2. 停止所有隧道服务（ngrok、cloudflare等）
3. 重启PM2服务

## 验证配置

### 检查当前IP

```bash
# 查看服务使用的IP
pm2 logs ims-server | grep "SERVER_IP\|SERVER_ADDR"

# 或查看日志
tail -f logs/ims-sip-server.log | grep CONFIG
```

### 测试连接

```bash
# 测试UDP连接
nc -uv 192.168.100.8 5060

# 测试TCP连接（如果启用）
nc -v 192.168.100.8 5060
```

## 局域网访问

### 同一局域网内的客户端

可以直接使用内网IP访问：
- SIP服务器: `192.168.100.8:5060`
- Web管理界面: `http://192.168.100.8:8888`

### 不同网段

如果需要跨网段访问：
1. 配置路由器端口转发
2. 或使用VPN
3. 或使用内网穿透方案（见 `docs/FREE_TUNNEL_SOLUTIONS.md`）

## 相关脚本

- `scripts/restore_to_local.sh` - 恢复到局域网版本
- `scripts/stop_ngrok.sh` - 停止ngrok
- `scripts/start_with_public_ip.sh` - 使用公网IP启动（如果需要）

## 注意事项

1. **内网IP可能变化**: 如果DHCP分配了新IP，服务会自动检测
2. **防火墙**: 确保局域网内可以访问5060端口
3. **跨网段**: 如果需要跨网段访问，需要配置路由或使用VPN
