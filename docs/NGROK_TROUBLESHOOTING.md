# ngrok 故障排查指南

## 常见问题

### 1. 无法获取ngrok地址

**症状**：
```
[ERROR] 无法获取ngrok地址，请检查ngrok是否正常启动
```

**解决方法**：

1. **检查ngrok是否已安装**
   ```bash
   which ngrok
   ngrok version
   ```

2. **检查ngrok配置**
   ```bash
   # macOS
   cat ~/Library/Application\ Support/ngrok/ngrok.yml
   
   # Linux
   cat ~/.config/ngrok/ngrok.yml
   ```

3. **手动测试ngrok**
   ```bash
   # 启动一个简单的HTTP隧道测试
   ngrok http 8888
   
   # 在另一个终端查看
   curl http://localhost:4040/api/tunnels
   ```

4. **查看ngrok日志**
   ```bash
   tail -50 /tmp/ngrok.log
   ```

### 2. ngrok配置未找到

**症状**：
```
[WARN] 未找到ngrok配置，可能需要先运行: ngrok config add-authtoken YOUR_TOKEN
```

**解决方法**：

1. **添加authtoken**
   ```bash
   ngrok config add-authtoken YOUR_TOKEN
   ```

2. **验证配置位置**
   ```bash
   # macOS
   ls -la ~/Library/Application\ Support/ngrok/
   
   # Linux
   ls -la ~/.config/ngrok/
   ```

### 3. 端口4040被占用

**症状**：
```
[WARN] ngrok Web界面端口4040已被占用，可能已有ngrok在运行
```

**解决方法**：

1. **查找占用端口的进程**
   ```bash
   lsof -i :4040
   ```

2. **停止现有ngrok进程**
   ```bash
   pkill ngrok
   # 或
   killall ngrok
   ```

3. **使用不同的端口**
   ```bash
   ngrok http 8888 --log stdout --log-format logfmt --log-level debug
   ```

### 4. 项目配置文件问题

**症状**：ngrok启动失败，日志显示配置错误

**解决方法**：

1. **检查项目配置文件**
   ```bash
   cat ngrok.yml
   ```

2. **使用系统默认配置**
   ```bash
   # 删除项目配置文件，使用系统配置
   rm ngrok.yml
   ./scripts/start_with_tunnel.sh ngrok pm2
   ```

3. **手动创建配置文件**
   ```yaml
   version: "2"
   authtoken: YOUR_TOKEN
   tunnels:
     sip-udp:
       proto: udp
       addr: 5060
     sip-tcp:
       proto: tcp
       addr: 5060
     web:
       proto: http
       addr: 8888
   ```

## 调试步骤

### 步骤1：验证ngrok安装

```bash
ngrok version
```

应该显示版本号，如：`ngrok version 3.x.x`

### 步骤2：验证配置

```bash
# macOS
cat ~/Library/Application\ Support/ngrok/ngrok.yml

# Linux  
cat ~/.config/ngrok/ngrok.yml
```

应该包含 `authtoken` 字段。

### 步骤3：手动启动测试

```bash
# 启动一个简单的HTTP隧道
ngrok http 8888
```

在另一个终端：
```bash
# 检查API
curl http://localhost:4040/api/tunnels | python3 -m json.tool
```

### 步骤4：使用项目脚本

```bash
./scripts/start_with_tunnel.sh ngrok pm2
```

### 步骤5：查看详细日志

```bash
# ngrok日志
tail -f /tmp/ngrok.log

# PM2日志
pm2 logs ims-server
```

## 快速测试脚本

创建 `test_ngrok.sh`：

```bash
#!/bin/bash
echo "1. 检查ngrok安装..."
which ngrok || { echo "ngrok未安装"; exit 1; }

echo "2. 检查配置..."
if [ -f ~/Library/Application\ Support/ngrok/ngrok.yml ]; then
    echo "找到macOS配置"
elif [ -f ~/.config/ngrok/ngrok.yml ]; then
    echo "找到Linux配置"
else
    echo "未找到配置，请运行: ngrok config add-authtoken YOUR_TOKEN"
    exit 1
fi

echo "3. 测试ngrok启动..."
ngrok http 8888 > /tmp/ngrok_test.log 2>&1 &
NGROK_PID=$!
sleep 5

echo "4. 检查API..."
if curl -s http://localhost:4040/api/tunnels > /dev/null; then
    echo "✅ ngrok正常工作"
    curl -s http://localhost:4040/api/tunnels | python3 -m json.tool
else
    echo "❌ ngrok无法访问"
    cat /tmp/ngrok_test.log
fi

kill $NGROK_PID 2>/dev/null
```

运行：
```bash
chmod +x test_ngrok.sh
./test_ngrok.sh
```

## 替代方案

如果ngrok无法正常工作，可以使用其他免费方案：

### Cloudflare Tunnel（推荐）

```bash
# 安装
brew install cloudflared  # macOS

# 启动
./scripts/start_with_tunnel.sh cloudflare pm2
```

### 其他方案

- **localtunnel**: `./scripts/start_with_tunnel.sh localtunnel pm2`
- **bore**: `./scripts/start_with_tunnel.sh bore pm2`
- **frp**: `./scripts/start_with_tunnel.sh frp pm2`

详见 `docs/FREE_TUNNEL_SOLUTIONS.md`

## 相关文件

- `scripts/start_with_tunnel.sh` - 隧道启动脚本
- `ngrok.yml` - ngrok项目配置文件（如果存在）
- `/tmp/ngrok.log` - ngrok日志文件
- `docs/FREE_TUNNEL_SOLUTIONS.md` - 免费方案对比
