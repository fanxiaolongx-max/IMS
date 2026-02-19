# 新方案使用状态

## 当前状态

### ✅ 代码已就绪
- `sipcore/rtpproxy_client.py` - RTPProxy客户端 ✅
- `sipcore/rtpproxy_media_relay.py` - RTPProxy媒体中继 ✅
- `sipcore/sippy_b2bua.py` - Sippy B2BUA包装器 ✅
- 所有代码可以正常导入 ✅

### ⚠️ 需要安装依赖

#### 1. RTPProxy（必需 - 用于媒体中继）
```bash
apt-get update
apt-get install rtpproxy
```

#### 2. Python sippy库（可选 - 用于SIP信令）
```bash
pip3 install sippy
```

## 快速安装

运行安装脚本：
```bash
./install_dependencies.sh
```

或手动安装：
```bash
# 安装RTPProxy
apt-get update
apt-get install rtpproxy

# 安装sippy（可选）
pip3 install sippy
```

## 使用步骤

### 方案A: 只使用RTPProxy媒体中继（推荐，立即可用）

**步骤1: 安装RTPProxy**
```bash
apt-get update
apt-get install rtpproxy
```

**步骤2: 启动RTPProxy**
```bash
rtpproxy -l 113.44.149.111 -s udp:127.0.0.1:7722 -F
```

**步骤3: 修改run.py**

在`run.py`第15行，将：
```python
from sipcore.media_relay import init_media_relay, get_media_relay
```

改为：
```python
from sipcore.rtpproxy_media_relay import init_media_relay, get_media_relay
```

在`run.py`约1777行，修改初始化：
```python
media_relay = init_media_relay(
    SERVER_IP,
    rtpproxy_tcp=('127.0.0.1', 7722)
)
```

**步骤4: 重启服务器**
```bash
pm2 restart ims-server
```

### 方案B: 使用Sippy B2BUA（需要更多配置）

**步骤1: 安装所有依赖**
```bash
./install_dependencies.sh
```

**步骤2: 启动RTPProxy**
```bash
rtpproxy -l 113.44.149.111 -s udp:127.0.0.1:7722 -F
```

**步骤3: 修改代码使用Sippy**
参考 `INSTALL_SIPPY.md`

## 验证安装

### 检查RTPProxy
```bash
which rtpproxy
rtpproxy -v
```

### 检查sippy
```bash
python3 -c "import sippy; print('sippy已安装')"
```

### 检查代码
```bash
python3 -c "from sipcore.rtpproxy_media_relay import RTPProxyMediaRelay; print('代码正常')"
```

## 推荐方案

**立即使用：方案A（RTPProxy媒体中继）**

理由：
- ✅ 只需安装RTPProxy（简单）
- ✅ 解决音频单向问题
- ✅ 风险低、收益高
- ✅ 可以立即使用

**后续考虑：方案B（Sippy B2BUA）**

在媒体中继稳定后，再考虑迁移SIP信令。

## 文档

- 快速开始：`RTPPROXY_QUICKSTART.md`
- 详细文档：`INSTALL_RTPPROXY.md`
- 迁移指南：`MIGRATION_GUIDE.md`
