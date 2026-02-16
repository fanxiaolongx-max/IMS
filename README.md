# IMS SIP Server

基于 RFC 3261 标准实现的 SIP B2BUA（Back-to-Back User Agent）服务器，提供用户注册、呼叫控制、媒体中继、CDR 话单、外呼服务和 Web 管理功能。

## 快速开始

### 环境要求
- Python 3.11+
- 可选依赖：websockets、psutil（MML 管理界面）

### 安装和启动

#### 方式 1：直接运行

```bash
# 1. 克隆项目
git clone <repository-url>
cd ims

# 2. 安装依赖（可选，MML 管理界面需要）
pip install -r requirements.txt

# 3. 启动服务
python run.py
```

#### 方式 2：Docker 部署（推荐）

**Linux（host 网络，推荐生产环境）：**

```bash
# 构建镜像
docker build -t ims:latest .

# 运行（指定服务器 IP）
docker run -d --name ims --network host \
  -e SERVER_IP=192.168.1.100 \
  -e LOCAL_NETWORK_CIDR=192.168.0.0/16 \
  ims:latest

# 或进入容器手动配置
docker run -d --name ims --network host \
  --entrypoint /bin/sh \
  ims:latest \
  -c "tail -f /dev/null"
docker exec -it ims /bin/bash
cd /app
export SERVER_IP=192.168.1.100
python run.py
```

**macOS/Windows（端口映射，仅用于调试）：**

```bash
docker run -d --name ims \
  -p 8888:8888/tcp \
  -p 8889:8889/tcp \
  -p 5060:5060/udp \
  -p 10000-10100:10000-10100/udp \
  -e SERVER_IP=192.168.100.8 \
  ims:latest
```

**注意**：WebSocket 端口（8889）用于实时日志推送，如果使用 host 网络模式则不需要映射。

### 配置说明

#### 环境变量

- `SERVER_IP` - 服务器 IP 地址（默认自动检测）
- `LOCAL_NETWORK_CIDR` - 局域网网段（默认 `192.168.0.0/16`）

#### 启动后服务监听
- SIP: UDP 5060（绑定到 `0.0.0.0`，对外宣告使用 `SERVER_IP`）
- MML 管理界面: HTTP 8888

### 访问管理界面

浏览器打开：http://localhost:8888 或 http://<服务器IP>:8888

## 核心功能

### SIP 协议支持

| 方法 | 功能 | 状态 | RFC 3261 合规性 |
|------|------|------|----------------|
| REGISTER | 用户注册/注销 | ✓ | ✓ |
| INVITE | 呼叫建立 | ✓ | ✓ |
| ACK | 呼叫确认（2xx/非2xx） | ✓ | ✓ |
| BYE | 呼叫释放 | ✓ | ✓ |
| CANCEL | 呼叫取消 | ✓ | ✓ |
| OPTIONS | 能力查询 | ✓ | ✓ |
| MESSAGE | 即时消息 | ✓ | ✓ |

### B2BUA + 媒体中继

**功能特性**：
- **媒体中继模式**：RTP/RTCP 流经服务器转发，解决 NAT 穿越问题
- **媒体透传模式**：SDP 原样透传，RTP 直连（仅同网段可用，用于调试）
- **对称 RTP 学习（Latching）**：自动学习 NAT 后的真实媒体地址
- **SRTP 支持**：保留并转发 SRTP 加密参数（`RTP/SAVP`、`a=crypto`）
- **RTP 端口管理**：自动分配和回收 RTP/RTCP 端口（20000-30000）
- **媒体诊断**：实时监控媒体流状态、包统计、地址学习情况

**配置方式**：
```python
# run.py
MEDIA_MODE = "relay"  # "relay"=媒体中继, "passthrough"=透传
```

**工作原理**：
```
主叫 (1002) ←── SIP ──→ 服务器 ←── SIP ──→ 被叫 (1001)
     ↑                                    ↑
     │ SDP: SERVER_IP:20000              │ SDP: SERVER_IP:20002
     │                                    │
     └────────── RTP ──→ 服务器 ←── RTP ──┘
                    (20000↔20002)
```

**NAT 穿越机制**：
- 使用信令来源地址（NAT 后的公网 IP）作为初始目标
- 通过对称 RTP 学习（Latching）自动更新为实际媒体地址
- 支持跨网络场景（Wi-Fi、移动网络、不同 NAT）

### 外呼服务（Auto Dialer）

- **单次外呼**：发起单个号码的外呼，支持媒体文件播放
- **批量外呼**：支持号码列表和号码范围（如 `1000-1005`），并发执行
- **自动注册**：外呼终端自动注册到服务器
- **资源管理**：自动清理残留注册，释放端口资源

**MML 命令：**
```
STR CALL SINGLE CALLEE=1009 MEDIA_FILE=media/default.wav DURATION=10
STR CALL BATCH NUMBERS=1000-1005 MEDIA_FILE=media/default.wav DURATION=10
STP CALL                              # 停止外呼服务
DSP DIALSVC                           # 查询外呼服务状态
DSP CALL STAT                         # 查询呼叫统计
DSP DIALSVC CFG                       # 查询外呼配置
```

### CDR 话单系统

- 自动记录所有呼叫、注册、消息
- 按日期分文件夹归档（`CDR/YYYY-MM-DD/`）
- CSV 格式，包含主被叫、时长、状态、媒体类型、编解码等字段
- 支持通过 MML 查询、导出、清理

### 用户管理

- 用户增删改查（MML 命令或 Web 界面）
- 用户状态管理（ACTIVE/INACTIVE/SUSPENDED）
- 服务类型分级（BASIC/PREMIUM/VIP/ENTERPRISE）
- 支持批量导入（JSON 格式）

### MML 管理界面

基于 WebSocket 的实时管理界面，支持：

**命令管理**
- 用户管理：`DSP USER`, `ADD USER`, `MOD USER`, `RMV USER`
- 注册管理：`DSP REG`, `RMV REG`, `CLR REG`
- 呼叫管理：`DSP CALL`, `RMV CALL`, `CLR CALL`
- CDR 管理：`DSP CDR`, `EXP CDR`, `CLR CDR`
- 配置管理：`DSP CFG`, `SET CFG`, `EXP CFG`
- 外呼管理：`STR CALL SINGLE`, `STR CALL BATCH`, `STP CALL`, `DSP DIALSVC`
- 性能监控：`DSP PERF` (CPU/MEM/NET/MSG)
- 日志管理：`DSP LOG`, `SET LOG`

**实时监控**
- 活跃呼叫数、注册用户数
- 实时日志推送（WebSocket）
- 系统性能指标（CPU、内存、网络）
- 命令历史记录

## 目录结构

```
ims/
├── run.py                  # 主程序入口
├── requirements.txt        # 依赖列表
├── Dockerfile             # Docker 镜像构建文件
├── README.md              # 本文档
│
├── sipcore/               # SIP 协议核心
│   ├── parser.py         # 消息解析
│   ├── transport_udp.py  # UDP 传输
│   ├── auth.py           # Digest 认证
│   ├── cdr.py            # CDR 记录
│   ├── user_manager.py   # 用户管理
│   ├── logger.py         # 日志系统
│   ├── sdp_parser.py      # SDP 解析
│   ├── media_relay.py    # B2BUA 媒体中继
│   └── timers.py         # RFC 3261 定时器
│
├── web/                   # MML 管理界面
│   ├── mml_server.py     # MML 后端服务
│   └── mml_interface.html # Web 前端
│
├── config/               # 配置管理
│   ├── config_manager.py # 配置管理器
│   └── config.json       # 配置文件
│
├── data/                 # 数据文件
│   └── users.json        # 用户数据
│
├── tests/                # 测试代码
│   ├── test_sip_scenarios.py  # SIP 场景测试
│   ├── test_cdr.py            # CDR 测试
│   ├── test_cdr_merged.py     # CDR 合并模式测试
│   └── quick_test.sh           # 快速测试脚本
│
├── tools/                # 工具脚本
│   └── cdr_viewer.py     # CDR 查看器
│
├── autodialer_manager.py # 外呼服务管理器
├── sip_client_standalone.py # 独立 SIP 客户端（用于外呼）
├── sip_client_config.json  # 外呼客户端配置
│
├── CDR/                  # 话单数据（按日期）
│   └── YYYY-MM-DD/
│       └── cdr_YYYY-MM-DD.csv
│
├── logs/                 # 日志文件（按日期）
│   └── YYYY-MM-DD/
│       └── ims-sip-server.log
│
├── media/                # 媒体文件（用于外呼播放）
│   └── default.wav
│
└── docs/                 # 文档
    ├── archive/          # 归档文档
    ├── QUICK_START.md    # 快速开始指南
    ├── MML_GUIDE.md      # MML 使用指南
    └── ...
```

## 典型场景

### 呼叫流程

```
成功呼叫:
INVITE -> 100 Trying -> 180 Ringing -> 200 OK -> ACK -> [通话] -> BYE -> 200 OK

取消呼叫:
INVITE -> 100 Trying -> 180 Ringing -> CANCEL -> 200 OK -> 487 Request Terminated -> ACK

拒绝呼叫:
INVITE -> 100 Trying -> 486 Busy Here -> ACK
```

### 外呼使用示例

**单次外呼：**
```
STR CALL SINGLE CALLEE=1009 MEDIA_FILE=media/default.wav DURATION=30
```

**批量外呼（号码范围）：**
```
STR CALL BATCH NUMBERS=1000-1005 MEDIA_FILE=media/default.wav DURATION=30
```

**批量外呼（逗号分隔）：**
```
STR CALL BATCH NUMBERS=1001,1002,1003,1004 MEDIA_FILE=media/default.wav DURATION=30
```

### CDR 查询

通过 MML 界面：

```
DSP CDR                           # 查询今天的 CDR
DSP CDR DATE=2025-11-01           # 查询指定日期
DSP CDR TYPE=CALL LIMIT=50        # 查询呼叫类型，限制 50 条
EXP CDR DATE=2025-11-01 TYPE=CALL # 导出到 CSV
```

### 用户管理

```
DSP USER                                  # 查询所有用户
DSP USER USERNAME=1001                    # 查询指定用户
ADD USER USERNAME=1004 PASSWORD=1004      # 添加用户
MOD USER USERNAME=1004 STATUS=INACTIVE     # 修改用户状态
RMV USER USERNAME=1004 CONFIRM=YES        # 删除用户
```

## 配置说明

### 服务器配置

**方式 1：环境变量（推荐）**

```bash
# 指定服务器 IP
export SERVER_IP=192.168.1.100

# 指定局域网网段
export LOCAL_NETWORK_CIDR=192.168.0.0/16

# 启动服务
python run.py
```

**方式 2：自动检测（默认）**

如果不设置环境变量，程序会自动检测本机 IP 地址。

**方式 3：通过 MML 命令动态查询/修改**

```
DSP CFG                    # 查询所有配置
SET CFG KEY=LOG.LEVEL VALUE=INFO  # 修改日志级别
EXP CFG                    # 导出配置
```

### SIP 客户端配置

以 Linphone/Zoiper 为例：

```
Domain: <SERVER_IP>
Port: 5060
Username: 1001
Password: 1001
Transport: UDP
```

默认用户（`data/users.json`）：
- 1001/1001
- 1002/1002
- 1003/1003

## RFC 3261 合规性

本实现严格遵循 RFC 3261 标准：

- ✓ **Record-Route 处理**：初始 INVITE 自动添加 Record-Route
- ✓ **Via 头管理**：正确处理逗号分隔的 Via 头，支持多跳代理
- ✓ **ACK 路由**：正确区分 2xx 和非 2xx ACK，非 2xx ACK 复用 INVITE branch
- ✓ **NAT 检测和修正**：自动修正 Contact 和 Via 头中的 NAT 地址
- ✓ **Digest 认证**：支持 MD5 和 SHA256 算法
- ✓ **呼叫状态机**：完整的 INVITE 事务状态管理
- ✓ **re-INVITE 支持**：支持媒体切换（hold/resume/add video）
- ✓ **CANCEL 处理**：复用 INVITE branch，确保兼容性
- ✓ **资源清理**：按协议标准延迟清理 DIALOGS，等待 ACK 确认
- ✓ **B2BUA 模式**：作为 Back-to-Back User Agent，终结并重新发起 SIP 会话
- ✓ **媒体中继**：RTP/RTCP 转发，支持对称 RTP 学习（RFC 4961）
- ✓ **SRTP 支持**：保留并转发 SRTP 参数，不强制降级为 RTP

## Docker 部署

### 构建镜像

```bash
docker build -t ims:latest .
```

### 运行（Linux host 网络）

```bash
# 指定 IP 地址
docker run -d --name ims --network host \
  -e SERVER_IP=192.168.1.100 \
  -e LOCAL_NETWORK_CIDR=192.168.0.0/16 \
  ims:latest

# 自动检测 IP（不传 SERVER_IP）
docker run -d --name ims --network host \
  ims:latest
```

### 运行（macOS/Windows 端口映射）

```bash
docker run -d --name ims \
  -p 8888:8888/tcp \
  -p 8889:8889/tcp \
  -p 5060:5060/udp \
  -p 10000-10100:10000-10100/udp \
  -e SERVER_IP=192.168.100.8 \
  ims:latest
```

**注意**：WebSocket 端口（8889）用于实时日志推送，必须映射才能使用该功能。

### 进入容器手动配置

```bash
# 1. 启动容器（保持运行）
docker run -d --name ims --network host \
  --entrypoint /bin/sh \
  ims:latest \
  -c "tail -f /dev/null"

# 2. 进入容器
docker exec -it ims /bin/bash

# 3. 设置环境变量并运行
export SERVER_IP=192.168.1.100
cd /app
python run.py
```

## 日志管理

### 日志级别

- DEBUG: 详细调试信息
- INFO: 一般信息（默认）
- WARNING: 警告信息
- ERROR: 错误信息

修改日志级别：

```
# 方法 1: MML 命令
SET CFG KEY=LOG.LEVEL VALUE=DEBUG

# 方法 2: 编辑 config.json
{
  "LOG_LEVEL": "DEBUG"
}
```

### 日志查看

```bash
# 实时查看
tail -f logs/2025-11-01/ims-sip-server.log

# 查看错误
grep ERROR logs/2025-11-01/ims-sip-server.log

# MML 查询
DSP LOG RECENT LINES=100
```

## 性能特性

- 并发注册支持：1000+
- 呼叫建立延迟：<100ms (LAN)
- 内存占用：~50MB (空闲)，~100MB (100并发呼叫)
- 日志限制：1000 条/页面 (MML)
- CDR 自动归档：按日期分文件夹
- 外呼并发：支持批量并发外呼（可配置）
- 媒体中继：支持双向 RTP/RTCP 转发，自动 NAT 穿越
- RTP 端口范围：20000-30000（自动分配和回收）

## 安全说明

**当前实现**：
- 密码明文存储（data/users.json）⚠️
- 无 TLS 加密传输 ⚠️
- MML 界面无认证 ⚠️
- 无请求频率限制 ⚠️

**建议**：
- 仅用于内网测试环境
- 生产部署前需完善安全机制
- 使用防火墙限制访问
- 定期备份数据

## 测试

### 自动化测试

测试文件位于 `tests/` 目录：

```bash
# 快速测试（推荐新手）
./tests/quick_test.sh

# 运行所有测试场景
python3 tests/test_sip_scenarios.py

# 运行单个场景
python3 tests/test_sip_scenarios.py 6  # 注册注销（最简单）
python3 tests/test_sip_scenarios.py 5  # 即时消息
python3 tests/test_sip_scenarios.py 1  # 正常呼叫
```

### 使用 SIP 客户端测试

**推荐客户端**：
- Linphone (https://www.linphone.org/)
- Zoiper (https://www.zoiper.com/)
- MicroSIP (https://www.microsip.org/)

## 常见问题

**Q: 如何修改服务器端口？**
```python
# 编辑 run.py
SERVER_PORT = 5061
```

**Q: CDR 文件在哪里？**
```
CDR/2025-11-01/cdr_2025-11-01.csv
```

**Q: 如何清理旧日志？**
```bash
rm -rf logs/2025-10-*
```
或通过 MML：
```
CLR CDR BEFORE=2025-10-30 CONFIRM=YES
```

**Q: Docker 部署后无法连接？**
- Linux：确保使用 `--network host` 模式
- macOS/Windows：确保端口映射正确，`SERVER_IP` 设置为宿主机可达 IP
- 检查防火墙是否放行 5060/udp、8888/tcp 和 8889/tcp（WebSocket 实时日志）

**Q: WebSocket 连接失败？**
- 确保 WebSocket 端口（HTTP 端口 + 1，默认 8889）已正确映射
- 使用 host 网络模式时不需要额外配置
- 检查浏览器控制台是否有连接错误信息

**Q: 外呼服务无法启动？**
- 检查 `sip_client_config.json` 配置是否正确
- 确保外呼终端用户名已存在于 `data/users.json`
- 查看日志：`grep "外呼" logs/*/ims-sip-server.log`

**Q: 媒体不通（无声音）？**
- 检查 `MEDIA_MODE` 设置：`"relay"` 用于跨网络，`"passthrough"` 仅同网段
- 查看日志中的 `[RTP-LATCH]` 标记，确认是否学习到 NAT 地址
- 使用 `DSP CALL STAT` 查看媒体统计信息
- 检查防火墙是否放行 RTP 端口范围（20000-30000/udp）
- 确认终端是否支持 SRTP（服务器会保留 SRTP 参数）

**Q: 跨网络（移动网络）媒体不通？**
- 确保使用 `MEDIA_MODE = "relay"`（媒体中继模式）
- 服务器会自动学习 NAT 后的真实地址（对称 RTP）
- 查看日志中的媒体诊断信息，确认地址学习状态

## 开发路线图

**P0 - 阻塞性问题**（商用前必须）：
- [x] 容器化部署（Docker）
- [ ] 密码加密存储（bcrypt + HA1）
- [ ] MML 界面认证
- [ ] NAT 穿越增强（STUN/TURN）
- [ ] 基础监控（健康检查、Prometheus）

**P1 - 高优先级**（商用建议）：
- [ ] SIP 事务层完善
- [ ] REFER/SUBSCRIBE/NOTIFY 支持
- [ ] 并发安全改进
- [ ] 数据库迁移（SQLite/PostgreSQL）
- [ ] 完善文档

**P2 - 中优先级**（增强竞争力）：
- [x] RTP 媒体转发（已实现 B2BUA 媒体中继）
- [ ] TLS/SIPS 支持
- [ ] 多进程架构
- [ ] 计费系统
- [ ] 多租户支持

详见：`docs/IMS_ROADMAP.md`

## 许可证

MIT License

## 版本历史

- v0.6 (2026-02-16): B2BUA + 媒体中继、对称 RTP 学习、SRTP 支持、NAT 穿越增强
- v0.5 (2025-11-XX): 媒体中继基础实现
- v0.4 (2025-11-04): 支持 Docker 部署、环境变量配置、外呼服务增强
- v0.3 (2025-10-30): 完善 MML 管理功能、性能监控、配置管理
- v0.2 (2025-10-29): CDR 增强、re-INVITE 支持、日志优化
- v0.1 (2025-10-27): 初始版本，基础 SIP 功能

## 联系方式

如有问题或建议，请通过以下方式联系：
- Issue Tracker
- Email
- Pull Request

---

**项目状态**: 开发测试中  
**RFC 3261 合规性**: 基础合规  
**B2BUA 模式**: 已实现（媒体中继 + NAT 穿越）  
**更新时间**: 2026-02-16
