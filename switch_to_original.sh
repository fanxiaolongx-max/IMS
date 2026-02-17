#!/bin/bash
# 切换回原版本的脚本

set -e

echo "=========================================="
echo "切换回原版本"
echo "=========================================="
echo ""

# 查找最新的备份文件
BACKUP_FILES=$(ls -t run.py.backup.* 2>/dev/null | head -1)

if [ -z "$BACKUP_FILES" ]; then
    echo "错误: 未找到备份文件 run.py.backup.*"
    echo "请手动恢复 run.py"
    exit 1
fi

# 备份当前版本
if [ -f "run.py" ]; then
    CURRENT_BACKUP="run.py.refactored.$(date +%Y%m%d_%H%M%S)"
    cp run.py "$CURRENT_BACKUP"
    echo "✓ 已备份当前版本到: $CURRENT_BACKUP"
fi

# 恢复原版本
cp "$BACKUP_FILES" run.py
echo "✓ 已恢复原版本: $BACKUP_FILES"

echo ""
echo "=========================================="
echo "切换完成！"
echo "=========================================="
echo ""
echo "下一步："
echo "1. 重启服务器: pm2 restart ims-server"
echo "2. 查看日志确认服务正常"
