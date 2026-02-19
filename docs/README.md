# IMS SIP Server - 文档索引

技术文档导航和快速链接。

## 快速导航

### 📚 用户文档

| 文档 | 说明 | 适合 |
|------|------|------|
| [MML 管理界面](MML_GUIDE.md) | MML 命令行管理工具使用指南 | 运维人员 |
| [CDR 话单系统](CDR_README.md) | CDR 生成、查询、导出 | 运维/计费 |
| [日志系统](LOGGING.md) | 日志级别、格式、查看方式 | 运维人员 |
| [工具使用](TOOLS.md) | CDR 查看器等实用工具 | 运维/开发 |

### ⚙️ 配置文档

| 文档 | 说明 | 适合 |
|------|------|------|
| [配置管理](CONFIGURATION.md) | 服务器配置、动态配置 | 管理员 |
| [快速开始](QUICK_START.md) | 5 分钟快速启动 | 新用户 |

### 🔧 开发文档

| 文档 | 说明 | 适合 |
|------|------|------|
| [SIP 核心](SIP_CORE_README.md) | SIP 协议实现详情 | 开发人员 |
| [开发指南](DEVELOPMENT.md) | 架构设计、代码规范 | 开发人员 |
| [功能总结](FEATURE_SUMMARY.md) | 已实现功能清单 | 开发/运维 |

### 📝 修复说明

| 文档 | 说明 |
|------|------|
| [CDR 去重机制](CDR_DEDUPLICATION.md) | CDR 防重复记录 |
| [CDR 修复记录](CDR_FIX_NOTES.md) | 480 响应重复修复 |
| [注册 CDR 修复](REGISTER_CDR_FIX.md) | 401 认证合并修复 |
| [网络错误处理](NETWORK_ERROR_HANDLING.md) | 网络异常优雅处理 |
| [日志级别修复](BUG_FIX_LOG_LEVEL.md) | LOG_LEVEL 动态修改 |

### 🌐 Web / 访问与排查

| 文档 | 说明 |
|------|------|
| [Web 故障排查](WEB_TROUBLESHOOTING.md) | MML/Web 界面访问问题 |
| [Web 访问方案](WEB_ACCESS_SOLUTION.md) | 访问方式与配置 |
| [Web 访问修复](WEB_ACCESS_FIX.md) | 访问相关修复说明 |

### 📦 RTPProxy / 媒体

| 文档 | 说明 |
|------|------|
| [RTPProxy 快速开始](RTPPROXY_QUICKSTART.md) | 快速上手 RTPProxy |
| [RTPProxy 快速开始（另）](QUICK_START_RTPPROXY.md) | 另一种快速指南 |
| [RTPProxy 安装](INSTALL_RTPPROXY.md) | 安装步骤 |
| [RTPProxy E0 错误诊断](RTPPROXY_E0_ERROR_DIAGNOSIS.md) | E0 错误排查 |
| [RTPProxy 修复](RTPPROXY_FIX.md) | 修复记录 |
| [视频中继实现](VIDEO_RELAY_IMPLEMENTATION.md) | 视频中继说明 |
| [媒体 NAT 处理](MEDIA_NAT_HANDLING.md) | 媒体与 NAT |
| [媒体中继分析](MEDIA_RELAY_ANALYSIS.md) | 媒体中继分析 |
| [B2BUA 实现](B2BUA_IMPLEMENTATION.md) | B2BUA 实现说明 |

### 📡 抓包与诊断

| 文档 | 说明 |
|------|------|
| [抓包指南](PACKET_CAPTURE_GUIDE.md) | 抓包功能使用 |
| [抓包快速开始](PACKET_CAPTURE_QUICKSTART.md) | 抓包快速上手 |
| [抓包集成](PACKET_CAPTURE_INTEGRATION.md) | 与系统集成说明 |
| [抓包总结](PACKET_CAPTURE_SUMMARY.md) | 抓包功能总结 |

### 🔄 重构 / 迁移 / 协议

| 文档 | 说明 |
|------|------|
| [重构总结](REFACTORING_SUMMARY.md) | 重构说明 |
| [重构指南](REFACTORING_GUIDE.md) | 重构步骤与规范 |
| [完整重构](COMPLETE_REFACTORING.md) | 完整重构记录 |
| [迁移指南](MIGRATION_GUIDE.md) | 迁移说明 |
| [协议修复 V3](PROTOCOL_FIX_V3.md) | 协议修复 v3 |
| [协议修复总结](PROTOCOL_FIX_SUMMARY.md) | 协议修复总结 |
| [UDP 连接修复](UDP_CONNECTION_FIX.md) | UDP 连接相关 |

### 🛠 Sippy / 安装与状态

| 文档 | 说明 |
|------|------|
| [安装 Sippy](INSTALL_SIPPY.md) | Sippy 安装 |
| [Sippy 快速开始](SIPPY_QUICKSTART.md) | Sippy 快速上手 |
| [状态](STATUS.md) | 项目状态 |
| [状态更新](STATUS_UPDATE.md) | 状态更新记录 |
| [C 重写分析](C_REWRITE_ANALYSIS.md) | C 重写分析 |
| [测试场景](TEST_SCENARIOS.md) | 测试场景 |

### 📖 其他文档

| 文档 | 说明 |
|------|------|
| [更新日志](CHANGELOG.md) | 版本历史和功能更新 |
| [路线图](IMS_ROADMAP.md) | 开发计划和优先级 |

## 常用链接

### 新手入门
1. [README.md](../README.md) - 项目概览
2. [QUICK_START.md](QUICK_START.md) - 快速开始
3. [MML_GUIDE.md](MML_GUIDE.md) - MML 界面使用

### 日常运维
1. [MML 命令参考](MML_GUIDE.md#命令参考)
2. [CDR 查询导出](CDR_README.md#查询和导出)
3. [日志查看](LOGGING.md#日志查看)
4. [性能监控](MML_GUIDE.md#性能监控)

### 故障排查
1. [常见问题](../README.md#常见问题)
2. [网络错误处理](NETWORK_ERROR_HANDLING.md)
3. [Web 故障排查](WEB_TROUBLESHOOTING.md)
4. [日志分析](LOGGING.md#日志分析)

### 开发相关
1. [SIP 核心实现](SIP_CORE_README.md)
2. [CDR 系统设计](CDR_README.md)
3. [功能清单](FEATURE_SUMMARY.md)

## 文档维护

### 文档结构
```
docs/
├── README.md                    # 本文件 - 文档导航
├── QUICK_START.md               # 快速开始
├── MML_GUIDE.md, CDR_README.md  # 用户/运维文档
├── CONFIGURATION.md, LOGGING.md # 配置与日志
├── SIP_CORE_README.md, FEATURE_SUMMARY.md  # 开发文档
├── WEB_TROUBLESHOOTING.md, WEB_ACCESS_*.md # Web 与访问
├── RTPPROXY_*.md, MEDIA_*.md    # RTPProxy 与媒体
├── PACKET_CAPTURE_*.md          # 抓包相关
├── REFACTORING_*.md, MIGRATION_GUIDE.md   # 重构与迁移
├── archive/                     # 归档文档
└── 其他修复与说明文档（见上方表格）
```

### 贡献指南
- 新增文档请更新本索引
- 文档使用 Markdown 格式
- 代码示例使用正确的语法高亮
- 保持简洁专业的风格

---

**最后更新**: 2025-10-30

