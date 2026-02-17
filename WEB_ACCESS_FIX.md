# Web界面访问问题排查

## 当前状态

✅ **服务器正常运行**:
- 端口8888正在监听 (`0.0.0.0:8888`)
- HTTP服务器正常响应（返回302重定向到 `/login.html`）
- 本地访问正常

## 可能的问题

### 1. 防火墙/安全组未开放8888端口

**检查方法**:
```bash
# 检查本地防火墙
ufw status | grep 8888
# 或
iptables -L -n | grep 8888

# 检查云服务器安全组规则（需要在云控制台检查）
```

**解决方法**:
- **华为云/阿里云/腾讯云**: 在控制台的安全组中添加规则，允许TCP 8888端口入站
- **本地防火墙**: 
  ```bash
  ufw allow 8888/tcp
  # 或
  iptables -A INPUT -p tcp --dport 8888 -j ACCEPT
  ```

### 2. 服务器只监听本地接口

**检查**:
```bash
netstat -tulpn | grep 8888
```

**应该显示**: `0.0.0.0:8888` （监听所有接口）
**如果显示**: `127.0.0.1:8888` （只监听本地）

**解决方法**: 代码中已经设置为 `0.0.0.0`，如果显示 `127.0.0.1`，需要重启服务器。

### 3. 浏览器缓存问题

**解决方法**:
- 清除浏览器缓存
- 使用无痕模式访问
- 尝试不同的浏览器

### 4. 网络问题

**检查方法**:
```bash
# 从外部测试
curl -v http://113.44.149.111:8888/

# 检查DNS解析
nslookup 113.44.149.111
```

## 快速修复步骤

### 步骤1: 检查安全组规则

在云服务器控制台（华为云/阿里云/腾讯云）：
1. 进入"安全组"或"防火墙"设置
2. 添加入站规则：
   - 协议: TCP
   - 端口: 8888
   - 源地址: 0.0.0.0/0（或你的IP地址）
   - 动作: 允许

### 步骤2: 检查本地防火墙

```bash
# Ubuntu/Debian
sudo ufw status
sudo ufw allow 8888/tcp

# CentOS/RHEL
sudo firewall-cmd --list-ports
sudo firewall-cmd --permanent --add-port=8888/tcp
sudo firewall-cmd --reload
```

### 步骤3: 重启服务器（如果需要）

```bash
pm2 restart ims-serv
```

### 步骤4: 测试访问

```bash
# 从服务器本地测试
curl http://127.0.0.1:8888/

# 从外部测试（需要另一台机器）
curl http://113.44.149.111:8888/
```

## 验证

访问 `http://113.44.149.111:8888/` 应该看到登录页面。

如果仍然无法访问，检查：
1. 服务器日志: `tail -f logs/ims-sip-server.log`
2. 系统日志: `journalctl -u ims-serv` 或 `dmesg | tail`
3. 网络连接: `tcpdump -i any port 8888`
