# ngrok v3 配置说明

## 重要变更

ngrok v3 相比 v2 有重大变化：

### 1. 配置格式变更

**v2 格式**：
```yaml
version: "2"
tunnels:
  sip-tcp:
    proto: tcp
    addr: 5060
```

**v3 格式**：
```yaml
version: 3
endpoints:
  - name: sip-tcp
    upstream:
      url: tcp://localhost:5060
```

### 2. UDP 支持

**ngrok v3 可能不支持 UDP 端点**，或需要特殊配置。

**解决方案**：
- 使用 **TCP 模式**（SIP over TCP）
- 或使用其他支持 UDP 的方案：
  - **frp** - 完全支持 UDP
  - **Cloudflare Tunnel** - 不支持 UDP，但支持 TCP

### 3. 启动命令变更

**v2**：
```bash
ngrok start --all --config ngrok.yml
```

**v3**：
```bash
ngrok start --config ngrok.yml --all
# 或指定端点名称
ngrok start --config ngrok.yml sip-tcp web
```

## 推荐配置

### 仅TCP和HTTP（推荐）

```yaml
version: 3
endpoints:
  - name: sip-tcp
    upstream:
      url: tcp://localhost:5060
  - name: web
    upstream:
      url: http://localhost:8888
```

### 如果需要UDP支持

1. **降级到 ngrok v2**（如果可用）
2. **使用 frp**（推荐）
3. **使用 Cloudflare Tunnel + TCP**

## 验证配置

```bash
# 检查ngrok版本
ngrok version

# 测试配置
ngrok start --config ngrok.yml --all

# 查看隧道信息
curl http://localhost:4040/api/tunnels | python3 -m json.tool
```

## 相关文档

- ngrok v3 文档: https://ngrok.com/docs/agent/config/v3/
- UDP 支持: 可能需要付费计划或使用其他方案
