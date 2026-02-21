# 动态IP解决方案更新日志

## 更新内容

### 1. 新增工具脚本

- **`scripts/get_public_ip.py`**: 动态获取公网IP地址的工具
  - 支持多个API服务（ipify, ifconfig.me, icanhazip等）
  - 自动选择可用的服务
  - 包含IP格式验证

- **`scripts/start_with_public_ip.sh`**: 自动启动脚本
  - 自动获取公网IP
  - 自动更新所有配置文件
  - 支持PM2和直接启动两种模式

### 2. 配置文件更新

所有硬编码的IP地址 `113.44.149.111` 已替换为 `AUTO_DETECT`：

- ✅ `config/config.json`: `SERVER_ADDR` = `"AUTO_DETECT"`
- ✅ `sip_client_config.json`: `server_ip`, `local_ip`, `sdp_ip` = `"AUTO_DETECT"`
- ✅ `ecosystem.config.js`: `SERVER_IP` = `'AUTO_DETECT'`

### 3. 代码增强

- ✅ `run.py`: 增强 `get_server_ip()` 函数，支持 `AUTO_DETECT` 配置
- ✅ 启动脚本自动处理 `AUTO_DETECT` 值，替换为实际IP

### 4. 文档

- ✅ `docs/DYNAMIC_IP_SOLUTION.md`: 完整的动态IP解决方案文档
  - 方案一：动态获取公网IP
  - 方案二：内网穿透（ngrok/frp/Cloudflare Tunnel）
  - 方案三：动态DNS
  - 方案四：代码增强
  
- ✅ `README_DYNAMIC_IP.md`: 快速使用指南

### 5. 配置模板

- ✅ `config/config.json.template`: 配置模板文件
- ✅ `sip_client_config.json.template`: SIP客户端配置模板

## 使用方法

### 快速开始

```bash
# 使用自动启动脚本（推荐）
./scripts/start_with_public_ip.sh pm2
```

### 手动获取IP

```bash
# 获取公网IP
python3 scripts/get_public_ip.py

# 设置环境变量并启动
export SERVER_IP=$(python3 scripts/get_public_ip.py)
pm2 start ecosystem.config.js
```

## 注意事项

1. **NAT环境**: 如果服务器在NAT后，动态获取IP可能获取到的是出口公网IP，不是服务器的直接IP。建议使用内网穿透方案。

2. **配置文件备份**: 启动脚本会自动备份配置文件（添加时间戳），原配置保存在 `.bak.*` 文件中。

3. **AUTO_DETECT**: 配置文件中使用 `AUTO_DETECT` 表示需要自动检测，启动脚本会自动替换为实际IP。

## 后续建议

1. **生产环境**: 建议使用内网穿透方案（如frp自建服务器）或云服务商的弹性IP
2. **开发测试**: 可以使用ngrok等免费服务
3. **固定域名**: 如果IP会变化，建议配置DDNS服务

## 相关文件

- `scripts/get_public_ip.py` - 获取公网IP工具
- `scripts/start_with_public_ip.sh` - 自动启动脚本
- `docs/DYNAMIC_IP_SOLUTION.md` - 完整解决方案文档
- `README_DYNAMIC_IP.md` - 快速使用指南
