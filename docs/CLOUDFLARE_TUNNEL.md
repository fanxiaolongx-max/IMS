# Cloudflare 临时隧道（公网注册）

服务器启动时可自动申请 Cloudflare 临时隧道，获得公网可访问的域名，使**公网用户**也能注册到 IMS。

## 限制说明

- **Quick Tunnel 只支持 TCP/HTTP，不支持 UDP。**
- **信令（SIP）**：通过隧道暴露 **SIP over TCP** 5060，公网用户用隧道域名 + 端口注册即可。
- **媒体（RTP）**：RTP 为 UDP，隧道**无法转发**。若需公网用户与内网/公网用户互通媒体，需满足其一：
  - 服务器有**公网 IP**：设置环境变量 `SERVER_IP=你的公网IP`，SDP 中会带该 IP，RTP 直连或经你方媒体中继。
  - 或使用** TURN 服务器**（需自行部署）做媒体中继。

因此：**仅开隧道时，公网用户能注册、能发信令，但通话媒体可能不通，除非 SERVER_IP 为公网或走 TURN。**

## 使用步骤

### 1. 安装 cloudflared

- macOS: `brew install cloudflared`
- 或从 [Cloudflare 文档](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/) 下载

### 2. 启用隧道启动

```bash
export ENABLE_CF_TUNNEL=1
python run.py
```

启动后会：

- 在本机同时监听 **UDP 5060**（原有）和 **TCP 5060**（SIP over TCP）。
- 启动两条 cloudflared quick tunnel：
  - `tcp://127.0.0.1:5060` → 公网 SIP 地址（如 `xxx.trycloudflare.com:port`）
  - `http://127.0.0.1:8888` → 公网 MML 管理界面（如 `https://yyy.trycloudflare.com`）
- 日志中会打印 **公网信令地址** 和 **公网 MML 地址**。

### 3. 公网用户注册

- 在 SIP 客户端（Linphone、Zoiper 等）中：
  - 服务器/域：填日志里的 **公网信令地址**（如 `xxx.trycloudflare.com`）。
  - 端口：日志里给出的端口（若未显示则尝试 443 或 5060）。
  - 传输：选择 **TCP**（必须，隧道只转发 TCP）。

### 4. 媒体互通（可选）

- 若希望公网用户通话有声音/视频：
  - 方案 A：将 IMS 部署在**有公网 IP 的 VPS** 上，并设置 `SERVER_IP=该公网IP`，再开隧道（隧道仅用于信令也可，或不用隧道直接公网 IP:5060）。
  - 方案 B：部署 TURN 服务器，客户端配置使用 TURN 做媒体中继。

## 环境变量

| 变量 | 说明 |
|------|------|
| `ENABLE_CF_TUNNEL` | 设为 `1`、`true`、`yes` 时启用隧道与 SIP/TCP |
| `SERVER_IP` | 媒体/SDP 使用的 IP；有公网 IP 时设置此项有利于公网媒体 |

## 实现要点

- **sipcore/cloudflare_tunnel.py**：启动 cloudflared、解析 trycloudflare.com 的 host/port。
- **sipcore/transport_tcp.py**：SIP over TCP 监听，按 Content-Length 拆包，复用与 UDP 相同的 `on_datagram` 处理逻辑。
- **run.py**：`ENABLE_CF_TUNNEL=1` 时启动 TCP 服务与隧道，并设置 **信令对外地址**（Via/Contact/Record-Route 使用隧道域名），SDP 仍使用 `SERVER_IP`（若未设则为本机/内网 IP）。
