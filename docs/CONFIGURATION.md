# 配置管理

本目录包含配置管理相关文件。

## 📁 文件说明

### config_manager.py

配置管理器主程序，负责：
- 配置参数定义和验证
- 配置持久化（JSON 格式）
- 动态配置更新
- 配置热加载

**主要功能：**

```python
# 初始化配置管理器
from config.config_manager import init_config_manager
config_mgr = init_config_manager("config/config.json")

# 加载配置
from config.config_manager import load_config
config = load_config("config/config.json")

# 保存配置
from config.config_manager import save_config
save_config("config/config.json", config_data)

# 应用配置更改
from config.config_manager import apply_config_change
success, message = apply_config_change("LOG_LEVEL", "INFO")

# 获取可编辑配置列表
from config.config_manager import get_editable_configs
editable = get_editable_configs()
```

### config.json

配置数据持久化文件（JSON 格式）。

**示例结构：**
```json
{
  "LOG_LEVEL": "INFO",
  "SERVER_PORT": 5060,
  "MAX_FORWARDS": 70,
  "REGISTRATION_EXPIRES": 3600,
  "last_updated": "2025-10-27T12:00:00"
}
```

## 🔧 支持的配置项

| 配置项 | 类型 | 说明 | 生效方式 |
|-------|------|------|----------|
| `LOG_LEVEL` | string | 日志级别 | 立即生效 |
| `SERVER_PORT` | int | SIP 端口 | 重启生效 |
| `MAX_FORWARDS` | int | 最大转发次数 | 立即生效 |
| `REGISTRATION_EXPIRES` | int | 注册过期时间（秒）| 立即生效 |

## 📝 添加新配置项

在 `config_manager.py` 中的 `CONFIG_DEFINITIONS` 添加定义：

```python
CONFIG_DEFINITIONS = {
    "NEW_CONFIG": {
        "type": "int",
        "default": 100,
        "description": "新配置项说明",
        "editable": True,
        "hot_reload": True,  # 是否支持热更新
        "validator": lambda x: x > 0  # 可选的验证函数
    }
}
```

## 📚 相关文档

- [配置编辑指南](WEB_CONFIG_EDIT_GUIDE.md)
- [配置编辑快速指南](CONFIG_EDIT_QUICKSTART.md)

---

**注意**：不要手动编辑 `config.json`，建议通过 Web 界面或 API 修改配置。

