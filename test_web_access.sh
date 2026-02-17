#!/bin/bash
# MML Web界面访问测试脚本

echo "=========================================="
echo "MML Web界面访问诊断"
echo "=========================================="
echo ""

# 1. 检查端口监听
echo "[1] 检查端口监听状态..."
if netstat -tulpn | grep -q ":8888"; then
    echo "✅ 端口8888正在监听"
    netstat -tulpn | grep ":8888"
else
    echo "❌ 端口8888未监听"
    exit 1
fi
echo ""

# 2. 检查进程
echo "[2] 检查HTTP服务器进程..."
if ps aux | grep -q "python.*run.py"; then
    echo "✅ HTTP服务器进程正在运行"
    ps aux | grep "python.*run.py" | grep -v grep | head -1
else
    echo "❌ HTTP服务器进程未运行"
    exit 1
fi
echo ""

# 3. 测试本地访问
echo "[3] 测试本地访问..."
if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8888/login.html | grep -q "200"; then
    echo "✅ 本地访问正常 (HTTP 200)"
else
    echo "❌ 本地访问失败"
    exit 1
fi
echo ""

# 4. 测试公网访问
echo "[4] 测试公网IP访问..."
PUBLIC_IP=$(hostname -I | awk '{print $1}' || echo "113.44.149.111")
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://${PUBLIC_IP}:8888/login.html)
if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ 公网访问正常 (HTTP 200)"
else
    echo "⚠️  公网访问返回 HTTP $HTTP_CODE"
    echo "   这可能是安全组/防火墙问题"
fi
echo ""

# 5. 检查login.html文件
echo "[5] 检查login.html文件..."
if [ -f "web/login.html" ]; then
    echo "✅ login.html文件存在"
    FILE_SIZE=$(stat -c%s web/login.html 2>/dev/null || stat -f%z web/login.html 2>/dev/null)
    echo "   文件大小: $FILE_SIZE 字节"
else
    echo "❌ login.html文件不存在"
    exit 1
fi
echo ""

# 6. 测试API接口
echo "[6] 测试API接口..."
API_RESPONSE=$(curl -s http://127.0.0.1:8888/api/check_auth)
if echo "$API_RESPONSE" | grep -q "authenticated"; then
    echo "✅ API接口正常响应"
    echo "   响应: $API_RESPONSE"
else
    echo "⚠️  API接口响应异常"
    echo "   响应: $API_RESPONSE"
fi
echo ""

# 7. 检查防火墙
echo "[7] 检查防火墙规则..."
if command -v ufw >/dev/null 2>&1; then
    UFW_STATUS=$(ufw status | grep -i "8888" || echo "未找到8888端口规则")
    echo "   UFW状态: $UFW_STATUS"
elif command -v firewall-cmd >/dev/null 2>&1; then
    FIREWALL_PORTS=$(firewall-cmd --list-ports 2>/dev/null | grep -i "8888" || echo "未找到8888端口规则")
    echo "   FirewallD端口: $FIREWALL_PORTS"
else
    echo "   未找到防火墙管理工具"
fi
echo ""

# 8. 总结
echo "=========================================="
echo "诊断完成"
echo "=========================================="
echo ""
echo "如果服务器端测试都通过，但浏览器仍无法访问："
echo "1. 检查云服务器安全组规则（TCP 8888端口）"
echo "2. 清除浏览器缓存，使用无痕模式"
echo "3. 按F12查看浏览器控制台错误信息"
echo "4. 尝试使用不同浏览器"
echo ""
echo "访问地址: http://${PUBLIC_IP}:8888/"
echo "默认账号: admin / admin"
