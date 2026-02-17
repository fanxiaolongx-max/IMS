# run.py
import asyncio, time, re, socket
import os

from sipcore.transport_udp import UDPServer
from sipcore.parser import parse
from sipcore.message import SIPMessage
from sipcore.utils import gen_tag, sip_date
from sipcore.auth import make_401, check_digest
from sipcore.logger import init_logging
from sipcore.timers import create_timers
from sipcore.cdr import init_cdr, get_cdr
from sipcore.user_manager import init_user_manager, get_user_manager
from sipcore.sdp_parser import extract_sdp_info
# 使用RTPProxy媒体中继（替代自定义媒体转发）
from sipcore.rtpproxy_media_relay import init_media_relay, get_media_relay
from sipcore.stun_server import init_stun_server

# 初始化日志系统
log = init_logging(level="DEBUG", log_file="logs/ims-sip-server.log")

# 初始化配置管理器
from config.config_manager import init_config_manager
config_mgr = init_config_manager("config/config.json")

# 初始化 CDR 系统（日志输出已移到 init_cdr 内部）
cdr = init_cdr(base_dir="CDR")

# 初始化用户管理系统（日志输出已移到 init_user_manager 内部）
user_mgr = init_user_manager(data_file="data/users.json")

# ====== 配置区 ======
# SERVER_IP: 从环境变量读取，如果没有则自动获取本机IP，最后回退到默认值
def is_private_ip(ip: str) -> bool:
    """检查是否为私网IP"""
    import ipaddress
    try:
        addr = ipaddress.ip_address(ip)
        return addr.is_private
    except ValueError:
        return False

def get_server_ip():
    """获取服务器IP地址，优先级：环境变量 > 自动检测 > 默认值"""
    # 1. 优先从环境变量读取
    server_ip = os.getenv("SERVER_IP")
    if server_ip:
        log.info(f"[CONFIG] SERVER_IP from environment: {server_ip}")
        return server_ip
    
    # 2. 自动获取本机IP（连接到外部地址，获取本地IP）
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        server_ip = s.getsockname()[0]
        s.close()
        
        # 检查是否是私网IP，给出警告
        if is_private_ip(server_ip):
            log.warning(f"[CONFIG] Auto-detected PRIVATE IP: {server_ip}")
            log.warning(f"[CONFIG] For cloud servers, set SERVER_IP env var to public IP")
            log.warning(f"[CONFIG] Example: export SERVER_IP=113.44.149.111")
        else:
            log.info(f"[CONFIG] SERVER_IP auto-detected (public): {server_ip}")
        return server_ip
    except Exception as e:
        log.warning(f"[CONFIG] Failed to auto-detect IP: {e}, using default")
    
    # 3. 回退到默认值
    default_ip = "192.168.100.8"
    log.warning(f"[CONFIG] SERVER_IP using default: {default_ip}")
    return default_ip

SERVER_IP = get_server_ip()
SERVER_PORT = 5060
# UDP 绑定地址：始终使用 0.0.0.0（监听所有接口），但对外宣告使用 SERVER_IP
UDP_BIND_IP = "0.0.0.0"
SERVER_URI = f"sip:{SERVER_IP}:{SERVER_PORT};lr"   # 用于Record-Route
ALLOW = "INVITE, ACK, CANCEL, BYE, OPTIONS, PRACK, UPDATE, REFER, NOTIFY, SUBSCRIBE, MESSAGE, REGISTER"

# 网络环境配置
# LOCAL_NETWORKS: 本机或局域网内的网络地址列表，这些地址不需要转换
# 如果是真实部署，服务器IP应该是局域网地址（如 192.168.1.100）
LOCAL_NETWORKS = [
    "127.0.0.1",          # 本机
    "localhost",          # 本机别名
    SERVER_IP,            # 服务器地址（动态获取）
]
# 如果需要支持局域网，可以添加：
# 从环境变量读取局域网网段，如果没有则使用默认值
LOCAL_NETWORK_CIDR = os.getenv("LOCAL_NETWORK_CIDR", "192.168.0.0/16")
LOCAL_NETWORKS.extend([LOCAL_NETWORK_CIDR])

# FORCE_LOCAL_ADDR: 强制使用本地地址（仅用于单机测试）
# 设置为 False 时，支持真实的多机网络环境
FORCE_LOCAL_ADDR = False   # True: 本机测试模式 | False: 真实网络模式

# 注册绑定: AOR -> list of bindings: [{"contact": "sip:1001@ip:port", "expires": epoch}]
REG_BINDINGS: dict[str, list[dict]] = {}

# 请求追踪：Call-ID -> 原始发送地址
PENDING_REQUESTS: dict[str, tuple[str, int]] = {}

# 对话追踪：Call-ID -> (主叫地址, 被叫地址)
DIALOGS: dict[str, tuple[tuple[str, int], tuple[str, int]]] = {}

# 事务追踪：Call-ID -> 服务器添加的 Via branch（用于 CANCEL 匹配）
# INVITE 事务的 branch 需要被 CANCEL 复用，以满足某些非标准客户端（如 Zoiper 2.x）的要求
INVITE_BRANCHES: dict[str, str] = {}

# 最后响应状态追踪：Call-ID -> 最后响应状态码（用于区分 2xx 和非 2xx ACK）
# 当收到 INVITE 的最终响应时，记录状态码，用于后续 ACK 类型判断
LAST_RESPONSE_STATUS: dict[str, str] = {}

# CANCEL 转发去重：Call-ID -> 上次转发时间戳
# 避免对同一 CANCEL 重传进行重复转发，产生无意义的流量
CANCEL_FORWARDED: dict[str, float] = {}

# B2BUA 媒体模式：
#   "relay"    - 媒体中继模式：使用RTPProxy进行媒体转发（推荐）
#   "passthrough" - 媒体透传模式：SDP 原样透传，RTP 直接在主被叫间传输（用于排查终端问题）
#   False      - 禁用，使用普通 Proxy 模式
MEDIA_MODE = "passthrough"  # relay=媒体中继(使用RTPProxy), passthrough=透传(仅同网段可用)
ENABLE_MEDIA_RELAY = (MEDIA_MODE == "relay")  # 只有 relay 模式才启用媒体中继，passthrough 模式应该透传 SDP

# RTPProxy配置
# 注意：RTPProxy使用UDP控制socket，不是TCP
RTPPROXY_UDP_HOST = os.getenv("RTPPROXY_UDP_HOST", "127.0.0.1")
RTPPROXY_UDP_PORT = int(os.getenv("RTPPROXY_UDP_PORT", "7722"))
RTPPROXY_UDP = (RTPPROXY_UDP_HOST, RTPPROXY_UDP_PORT)
# 保留TCP配置用于兼容性（如果将来需要）
RTPPROXY_TCP_HOST = os.getenv("RTPPROXY_TCP_HOST", "127.0.0.1")
RTPPROXY_TCP_PORT = int(os.getenv("RTPPROXY_TCP_PORT", "7722"))
RTPPROXY_TCP = (RTPPROXY_TCP_HOST, RTPPROXY_TCP_PORT)

# ====== STUN 配置 ======
# STUN 服务器配置（用于 NAT 穿透辅助）
ENABLE_STUN = True                # 是否启用 STUN 服务器
STUN_BIND_IP = "0.0.0.0"        # STUN 绑定地址
STUN_PORT = 3478                  # STUN 端口（标准端口）
STUN_USERNAME = "123"            # STUN 认证用户名
STUN_PASSWORD = "123"            # STUN 认证密码
STUN_REALM = "ims.stun.server"   # STUN 认证域

# ====== 安全防护配置 ======
# IP 黑名单（已知攻击源）
IP_BLACKLIST: set[str] = set()

# 尝试计数器：IP -> (失败次数, 首次失败时间)
# 用于速率限制和自动黑名单
ATTEMPT_COUNTER: dict[str, tuple[int, float]] = {}

# 安全配置
SECURITY_CONFIG = {
    "ENABLE_IP_BLACKLIST": True,           # 启用 IP 黑名单
    "ENABLE_RATE_LIMIT": True,             # 启用速率限制
    "RATE_LIMIT_THRESHOLD": 10,            # 10 次失败请求/分钟
    "RATE_LIMIT_WINDOW": 60,               # 时间窗口（秒）
    "AUTO_BLACKLIST_THRESHOLD": 50,        # 自动加入黑名单的阈值
    "BLOCK_NON_LOCAL_USERS": False,        # 是否只允许本地网络用户
}

# 从文件加载黑名单
def _load_ip_blacklist():
    """从文件加载 IP 黑名单"""
    blacklist_file = "config/ip_blacklist.txt"
    if os.path.exists(blacklist_file):
        try:
            with open(blacklist_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        IP_BLACKLIST.add(line)
            log.info(f"[SECURITY] 已加载 {len(IP_BLACKLIST)} 个黑名单 IP")
        except Exception as e:
            log.warning(f"[SECURITY] 加载黑名单失败: {e}")

# 保存黑名单到文件
def _save_ip_blacklist():
    """保存 IP 黑名单到文件"""
    blacklist_file = "config/ip_blacklist.txt"
    try:
        os.makedirs("config", exist_ok=True)
        with open(blacklist_file, 'w') as f:
            f.write("# SIP 攻击源 IP 黑名单\n")
            f.write("# 格式: 每行一个 IP 地址\n\n")
            for ip in sorted(IP_BLACKLIST):
                f.write(f"{ip}\n")
    except Exception as e:
        log.warning(f"[SECURITY] 保存黑名单失败: {e}")

# 检查 IP 是否应该被阻止
def _is_ip_blocked(ip: str) -> bool:
    """检查 IP 是否被阻止"""
    if not SECURITY_CONFIG["ENABLE_IP_BLACKLIST"]:
        return False
    
    # 检查黑名单
    if ip in IP_BLACKLIST:
        return True
    
    # 检查速率限制
    if SECURITY_CONFIG["ENABLE_RATE_LIMIT"]:
        now = time.time()
        if ip in ATTEMPT_COUNTER:
            count, first_time = ATTEMPT_COUNTER[ip]
            # 检查是否在时间窗口内
            if now - first_time < SECURITY_CONFIG["RATE_LIMIT_WINDOW"]:
                if count >= SECURITY_CONFIG["RATE_LIMIT_THRESHOLD"]:
                    # 超过阈值，加入黑名单
                    if count >= SECURITY_CONFIG["AUTO_BLACKLIST_THRESHOLD"]:
                        IP_BLACKLIST.add(ip)
                        _save_ip_blacklist()
                        log.warning(f"[SECURITY] IP {ip} 已自动加入黑名单（{count} 次失败请求）")
                    return True
            else:
                # 时间窗口已过，重置计数
                del ATTEMPT_COUNTER[ip]
    
    return False

# 记录失败的请求尝试
def _record_failed_attempt(ip: str):
    """记录失败的请求尝试（用于速率限制）"""
    if not SECURITY_CONFIG["ENABLE_RATE_LIMIT"]:
        return
    
    now = time.time()
    if ip in ATTEMPT_COUNTER:
        count, first_time = ATTEMPT_COUNTER[ip]
        # 检查是否还在时间窗口内
        if now - first_time < SECURITY_CONFIG["RATE_LIMIT_WINDOW"]:
            ATTEMPT_COUNTER[ip] = (count + 1, first_time)
        else:
            # 重置计数
            ATTEMPT_COUNTER[ip] = (1, now)
    else:
        ATTEMPT_COUNTER[ip] = (1, now)

# 加载黑名单
_load_ip_blacklist()

# ====== 工具函数 ======
def _aor_from_from(from_val: str | None) -> str:
    if not from_val:
        return ""
    s = from_val
    if "<sip:" in s and ">" in s:
        uri = s[s.find("<")+1:s.find(">")]
    else:
        p = s.find("sip:")
        uri = s[p:] if p >= 0 else s
    semi = uri.find(";")
    if semi > 0:
        uri = uri[:semi]
    return uri  # e.g., sip:1002@sip.local

def _same_user(uri1: str, uri2: str) -> bool:
    """比较两个 SIP URI 是否同一用户（忽略域名和端口）"""
    import re
    def extract_user(u):
        m = re.search(r"sip:([^@;>]+)", u)
        return m.group(1) if m else u
    return extract_user(uri1) == extract_user(uri2)

def _extract_number_from_uri(uri: str | None) -> str:
    """从 SIP URI 中提取号码（用户部分）
    
    例如:
    - sip:1001@sip.local -> 1001
    - <sip:1002@192.168.1.1:5060>;tag=xxx -> 1002
    - 1003 -> 1003
    """
    if not uri:
        return ""
    import re
    m = re.search(r"sip:([^@;>]+)", uri)
    if m:
        return m.group(1)
    # 如果没有 sip: 前缀，直接返回
    return uri.strip("<>")

def _aor_from_to(to_val: str | None) -> str:
    if not to_val:
        return ""
    s = to_val
    if "<sip:" in s and ">" in s:
        uri = s[s.find("<")+1:s.find(">")]
    else:
        p = s.find("sip:")
        uri = s[p:] if p >= 0 else s
    semi = uri.find(";")
    if semi > 0:
        uri = uri[:semi]
    return uri  # e.g., sip:1001@sip.local

def _parse_contacts(req: SIPMessage):
    out = []
    for c in req.headers.get("contact", []):
        uri = c
        if "<" in c and ">" in c:
            uri = c[c.find("<")+1:c.find(">")]
        exp = 3600
        m = re.search(r"expires=(\d+)", c, re.I)
        if m:
            exp = int(m.group(1))
        else:
            e = req.get("expires")
            if e and e.isdigit():
                exp = int(e)
        out.append({"contact": uri, "expires": exp})
    return out

def _host_port_from_via(via_val: str) -> tuple[str, int]:
    # 例：Via: SIP/2.0/UDP 192.168.1.50:5062;branch=z9hG4bK;rport=5060;received=192.168.1.50
    # 优先使用 received 和 rport 参数（RFC 3261 Section 18.2.2）
    
    # 先检查 received 参数
    received_match = re.search(r"received=([^\s;]+)", via_val, re.I)
    if received_match:
        host = received_match.group(1).strip()
        
        # 检查 rport 参数
        rport_match = re.search(r"rport=(\d+)", via_val, re.I)
        if rport_match:
            port = int(rport_match.group(1))
            return (host, port)
        else:
            # 没有 rport，使用 sent-by 的端口
            sent_by_match = re.search(r"SIP/2\.0/\w+\s+([^;]+)", via_val, re.I)
            if sent_by_match:
                sent_by = sent_by_match.group(1).strip()
                if ":" in sent_by:
                    _, p = sent_by.rsplit(":", 1)
                    try:
                        return (host, int(p))
                    except:
                        return (host, 5060)
            return (host, 5060)
    
    # 没有 received 参数，使用 sent-by
    m = re.search(r"SIP/2\.0/\w+\s+([^;]+)", via_val, re.I)
    if not m:
        return ("", 0)
    sent_by = m.group(1).strip()
    if ":" in sent_by:
        h, p = sent_by.rsplit(":", 1)
        try:
            return (h, int(p))
        except:
            return (h, 5060)
    else:
        return (sent_by, 5060)

def _host_port_from_sip_uri(uri: str) -> tuple[str, int]:
    # 例：sip:1002@192.168.1.60:5066;transport=udp
    # 或 sip:192.168.1.60:5066
    u = uri
    if u.startswith("sip:"):
        u = u[4:]
    # 去掉用户@部分
    if "@" in u:
        u = u.split("@", 1)[1]
    # 去掉参数
    if ";" in u:
        u = u.split(";", 1)[0]
    if ":" in u:
        host, port = u.rsplit(":", 1)
        try:
            return host, int(port)
        except:
            return host, 5060
    return u, 5060

def _ensure_header(msg: SIPMessage, name: str, default: str):
    if not msg.get(name):
        msg.add_header(name, default)

def _decrement_max_forwards(msg: SIPMessage) -> bool:
    mf = msg.get("max-forwards")
    try:
        v = int(mf) if mf is not None else 70
    except:
        v = 70
    v -= 1
    if v < 0:
        return False
    # 覆盖：删除旧的，再加新的
    msg.headers.pop("max-forwards", None)
    msg.add_header("max-forwards", str(v))
    return True

def _add_top_via(msg: SIPMessage, branch: str):
    via = f"SIP/2.0/UDP {SERVER_IP}:{SERVER_PORT};branch={branch};rport"
    # 插入为第一条 Via
    old = msg.headers.get("via", [])
    msg.headers["via"] = [via] + old

def _split_via_header(via_str: str) -> list[str]:
    """
    分割逗号分隔的 Via 头（RFC 3261 允许在同一行用逗号分隔多个 Via）
    
    注意：必须正确处理 Via 头中的参数，逗号可能出现在参数值中
    分割规则：在 sent-by 之后的分号或空格后面的逗号处分割
    """
    if not via_str:
        return []
    
    # Via 头格式：SIP/2.0/TRANSPORT sent-by;param1=value1;param2=value2, SIP/2.0/...
    # 不能简单按逗号分割，因为参数值中可能有逗号
    # 正确方法：找到每个 "SIP/2.0" 的位置，在这些位置分割
    
    parts = []
    current = via_str.strip()
    
    # 如果当前字符串中没有逗号，直接返回
    if "," not in current:
        return [current] if current else []
    
    # 查找所有 "SIP/2.0" 的位置（这些是新的 Via 头的开始）
    import re
    sip_pattern = re.compile(r'\bSIP/2\.0', re.I)
    matches = list(sip_pattern.finditer(current))
    
    if len(matches) <= 1:
        # 只有一个 SIP/2.0，说明这是单个 Via 头（可能有参数值包含逗号）
        return [current] if current else []
    
    # 在多个 SIP/2.0 位置之间分割
    for i in range(len(matches)):
        start_pos = matches[i].start()
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(current)
        
        # 提取当前 Via 头（去掉末尾的逗号和空格）
        part = current[start_pos:end_pos].rstrip(", \t")
        if part:
            parts.append(part)
    
    # 如果没有成功分割，返回原始值
    if not parts:
        return [current] if current else []
    
    return parts

def _pop_top_via(resp: SIPMessage):
    """弹出顶层的 Via 头，正确处理逗号分隔的多个 Via"""
    vias = resp.headers.get("via", [])
    if not vias:
        return
    
    # 处理第一个 Via 头（可能包含逗号分隔的多个）
    first_via = vias[0]
    split_first = _split_via_header(first_via)
    
    if len(split_first) > 1:
        # 第一个元素包含多个 Via，弹出第一个，保留剩余的
        new_first = ",".join(split_first[1:]) if len(split_first) > 1 else ""
        vias[0] = new_first
        # 移除空字符串
        vias = [v for v in vias if v]
        if vias:
            resp.headers["via"] = vias
        else:
            resp.headers.pop("via", None)
    else:
        # 第一个元素是单个 Via，正常弹出
        vias.pop(0)
        if vias:
            resp.headers["via"] = vias
        else:
            resp.headers.pop("via", None)

def _is_request(start_line: str) -> bool:
    return not start_line.startswith("SIP/2.0")

def _method_of(msg: SIPMessage) -> str:
    return msg.start_line.split()[0]

def _is_initial_request(msg: SIPMessage) -> bool:
    # 初始请求：无 "Route" 指向我们，且是新的对话（简单判断：无 "To" tag）
    to = msg.get("to") or ""
    has_tag = "tag=" in to
    routes = msg.headers.get("route", [])
    targeted_us = any(SERVER_IP in r or str(SERVER_PORT) in r for r in routes)
    return (not has_tag) or targeted_us  # 宽松判断即可

def _strip_our_top_route_and_get_next(msg: SIPMessage) -> None:
    routes = msg.headers.get("route", [])
    if not routes:
        return
    top = routes[0]
    if SERVER_IP in top or str(SERVER_PORT) in top:
        routes.pop(0)
        if routes:
            msg.headers["route"] = routes
        else:
            msg.headers.pop("route", None)

def _add_record_route_for_initial(msg: SIPMessage):
    # 在初始请求上插入 RR
    msg.add_header("record-route", f"<{SERVER_URI}>")

def _make_response(req: SIPMessage, code: int, reason: str, extra_headers: dict | None = None, body: bytes = b"") -> SIPMessage:
    r = SIPMessage(start_line=f"SIP/2.0 {code} {reason}")
    for v in req.headers.get("via", []):
        r.add_header("via", v)
    to_val = req.get("to") or ""
    if "tag=" not in to_val and code >= 200:
        to_val = f"{to_val};tag={gen_tag()}"
    r.add_header("to", to_val)
    r.add_header("from", req.get("from") or "")
    r.add_header("call-id", req.get("call-id") or "")
    r.add_header("cseq", req.get("cseq") or "")
    r.add_header("server", "ims-sip-server/0.0.3")
    r.add_header("allow", ALLOW)
    r.add_header("date", sip_date())
    r.add_header("content-length", "0" if not body else str(len(body)))
    if extra_headers:
        for k, v in extra_headers.items():
            r.add_header(k, v)
    return r

# ====== 业务处理 ======

def handle_register(msg: SIPMessage, addr, transport):
    # 从 user_manager 获取 ACTIVE 用户构建认证字典
    try:
        active_users = {
            user['username']: user['password'] 
            for user in user_mgr.get_all_users() 
            if user.get('status') == 'ACTIVE'
        }
    except Exception as e:
        log.error(f"Failed to get users from user_manager: {e}")
        active_users = {}
    
    # 检查认证
    if not check_digest(msg, active_users):
        resp = make_401(msg)
        # 打印完整的 SIP 响应内容（发送前）
        try:
            resp_content = resp.to_bytes().decode('utf-8', errors='ignore')
            log.debug(f"[TX-RESP-FULL] {addr} <- 401 Unauthorized Full SIP response:\n{resp_content}")
        except Exception as e:
            log.debug(f"[TX-RESP-FULL] Failed to decode response: {e}")
        transport.sendto(resp.to_bytes(), addr)
        log.tx(addr, resp.start_line, extra="Auth failed")
        # CDR: 401 是正常的 SIP 认证挑战流程，不记录为失败
        # 只有当客户端多次尝试后仍失败，或返回其他错误码时才记录失败
        return

    aor = _aor_from_to(msg.get("to"))
    if not aor:
        resp = _make_response(msg, 400, "Bad Request")
        transport.sendto(resp.to_bytes(), addr)
        log.tx(addr, resp.start_line)
        return

    binds = _parse_contacts(msg)

    # --- 自动修正 Contact 的 IP/端口 ---
    fixed_binds = []
    for b in binds:
        contact = b["contact"]
        # 提取 sip:user@IP:port
        import re
        contact = re.sub(r"@[^;>]+", f"@{addr[0]}:{addr[1]}", contact)
        b["contact"] = contact
        fixed_binds.append(b)
    binds = fixed_binds
    # ------------------------------------

    now = int(time.time())
    lst = REG_BINDINGS.setdefault(aor, [])
    lst[:] = [b for b in lst if b["expires"] > now]
    for b in binds:
        if b["expires"] == 0:
            lst[:] = [x for x in lst if x["contact"] != b["contact"]]
        else:
            abs_exp = now + b["expires"]
            # 检查是否已有相同contact的绑定
            for x in lst:
                if x["contact"] == b["contact"]:
                    x["expires"] = abs_exp
                    # 更新真实来源地址（NAT场景下可能变化）
                    x["real_addr"] = addr  # (ip, port)
                    break
            else:
                # 新绑定，保存真实来源地址
                lst.append({
                    "contact": b["contact"],
                    "expires": abs_exp,
                    "real_addr": addr  # 保存真实socket地址，用于rport
                })

    resp = _make_response(msg, 200, "OK")
    for b in lst:
        resp.add_header("contact", f"<{b['contact']}>")
    
    # 打印完整的 SIP 响应内容（发送前）
    try:
        resp_content = resp.to_bytes().decode('utf-8', errors='ignore')
        log.debug(f"[TX-RESP-FULL] {addr} <- 200 OK Full SIP response:\n{resp_content}")
    except Exception as e:
        log.debug(f"[TX-RESP-FULL] Failed to decode response: {e}")
    
    transport.sendto(resp.to_bytes(), addr)
    log.tx(addr, resp.start_line, extra=f"bindings={len(lst)}")
    
    # CDR: 记录注册/注销事件
    if binds and binds[0]["expires"] == 0:
        # 注销
        cdr.record_unregister(
            caller_uri=aor,
            caller_addr=addr,
            contact=binds[0]["contact"],
            call_id=msg.get("call-id") or "",
            user_agent=msg.get("user-agent") or "",
            cseq=msg.get("cseq") or ""
        )
    else:
        # 注册成功
        contact = lst[0]["contact"] if lst else ""
        expires = binds[0]["expires"] if binds else 3600
        cdr.record_register(
            caller_uri=aor,
            caller_addr=addr,
            contact=contact,
            expires=expires,
            success=True,
            status_code=200,
            status_text="OK",
            call_id=msg.get("call-id") or "",
            user_agent=msg.get("user-agent") or "",
            cseq=msg.get("cseq") or "",
            server_ip=SERVER_IP,
            server_port=SERVER_PORT
        )

def _forward_request(msg: SIPMessage, addr, transport):
    """
    将请求转发到下一跳：
    - 初始 INVITE：根据 REG_BINDINGS 选择被叫 Contact，改写 R-URI，插入 Record-Route
    - in-dialog（带 Route 指向我们）：弹出顶层 Route
    - 统一：加顶层 Via、递减 Max-Forwards
    """
    method = _method_of(msg)

    # 忽略/丢弃 Max-Forwards<=0
    if not _decrement_max_forwards(msg):
        resp = _make_response(msg, 483, "Too Many Hops")
        transport.sendto(resp.to_bytes(), addr)
        log.tx(addr, resp.start_line)
        return

    # 在删除 Route 之前，先保存 Route 信息（用于 ACK 类型判断）
    call_id = msg.get("call-id")
    original_routes = msg.headers.get("route", [])
    has_route_before_strip = len(original_routes) > 0

    # in-dialog：如果顶层 Route 就是我们，弹掉它
    _strip_our_top_route_and_get_next(msg)

    # 防止重复请求：检查 Call-ID 是否已经在 DIALOGS 中（可能是重发）
    call_id = msg.get("call-id")
    if call_id and call_id in DIALOGS:
        # 区分重发的初始 INVITE 和 re-INVITE
        if method == "INVITE":
            # 通过 To 头的 tag 参数区分：
            # - 初始 INVITE：To 头没有 tag
            # - re-INVITE：To 头有 tag（对话已建立）
            to_header = msg.get("to") or ""
            has_to_tag = "tag=" in to_header
            
            if has_to_tag:
                # re-INVITE：对话内的媒体协商（hold/resume/add video 等）
                log.info(f"[re-INVITE] Detected for Call-ID: {call_id}")
                # 继续处理，不 return
            else:
                # 重发的初始 INVITE：返回 100 Trying，不转发
                log.debug(f"[DUPLICATE] Initial INVITE retransmission for Call-ID: {call_id}")
                resp = _make_response(msg, 100, "Trying")
                transport.sendto(resp.to_bytes(), addr)
                log.tx(addr, resp.start_line, extra="duplicate INVITE handling")
                return
        # 其他 in-dialog 请求（BYE, UPDATE等）继续处理
        log.debug(f"[REQ-TRACK] Call-ID {call_id} is in DIALOGS, treating as in-dialog {method} request")

    # CANCEL/ACK/BYE/UPDATE 请求特殊处理：修正 R-URI（去除外部 IP 和 ;ob 参数，使用本地地址）
    # RFC 3261 重要规则：
    # - CANCEL：R-URI 必须和对应的 INVITE 转发后的 R-URI 一致
    # - 非 2xx 响应的 ACK：R-URI 必须与原始 INVITE 相同，不能修改！
    # - 2xx 响应的 ACK：R-URI 应该使用 Contact 头中的地址，可以修改
    # - BYE/UPDATE：对话内请求，可以修改
    if method == "CANCEL":
        # CANCEL 去重：同一 Call-ID 的 CANCEL 重传只转发一次
        cancel_call_id = msg.get("call-id")
        if cancel_call_id:
            now_f = time.time()
            last_fwd = CANCEL_FORWARDED.get(cancel_call_id)
            if last_fwd and (now_f - last_fwd) < 32.0:
                # 32秒内（Timer F）的重传，回 200 OK 但不再转发
                resp = _make_response(msg, 200, "OK")
                transport.sendto(resp.to_bytes(), addr)
                log.debug(f"[CANCEL-DEDUP] Suppressed retransmission for Call-ID: {cancel_call_id}")
                return
            CANCEL_FORWARDED[cancel_call_id] = now_f

        # CANCEL R-URI 修正逻辑
        # RFC 3261: CANCEL 的 R-URI 必须和对应的 INVITE 一致
        # 由于服务器转发 INVITE 时已经修改了 R-URI，CANCEL 也必须使用相同的修正后的 R-URI
        try:
            ruri = msg.start_line.split()[1]
            # 如果 R-URI 指向服务器地址，需要修正为实际被叫地址
            # 检查 R-URI 是否指向服务器地址或本地地址
            if f"{SERVER_IP}" in ruri or "127.0.0.1" in ruri:
                # 提取被叫 AOR（从 To 头）
                aor = _aor_from_to(msg.get("to"))
                if not aor:
                    # 如果 To 头没有 AOR，从 R-URI 提取
                    aor = _aor_from_to(ruri)
                
                targets = REG_BINDINGS.get(aor, [])
                now = int(time.time())
                targets = [t for t in targets if t["expires"] > now]
                targets.sort(key=lambda t: t["expires"], reverse=True)
                if targets:
                    target_uri = targets[0]["contact"]
                    # 完全移除所有参数（包括 ;ob, transport 等）
                    import re
                    target_uri = re.sub(r";[^,]*", "", target_uri)  # 移除所有 ; 开始的参数
                    target_uri = target_uri.strip()
                    # 改写 R-URI
                    parts = msg.start_line.split()
                    original_ruri = parts[1]
                    parts[1] = target_uri
                    msg.start_line = " ".join(parts)
                    log.debug(f"CANCEL R-URI corrected: {original_ruri} -> {target_uri}")
        except Exception as e:
            log.warning(f"CANCEL R-URI correction failed: {e}")
    elif method in ("BYE", "UPDATE"):
        # BYE 和 UPDATE：对话内请求，可以修正 R-URI
        try:
            ruri = msg.start_line.split()[1]
            # 如果 R-URI 包含外部 IP 或 ;ob 参数，需要修正
            if ";ob" in ruri or "@100." in ruri or "@192." in ruri or "@172." in ruri:
                # 从 To 头获取被叫 AOR
                to_val = msg.get("to")
                to_aor = _aor_from_to(to_val)
                if to_aor:
                    # 查找该 AOR 的本地 contact
                    targets = REG_BINDINGS.get(to_aor, [])
                    if targets:
                        target_uri = targets[0]["contact"]
                        # 完全移除所有参数（包括 ;ob, transport 等）
                        import re
                        # 先清理 URI，提取基本地址
                        target_uri = re.sub(r";[^,]*", "", target_uri)  # 移除所有 ; 开始的参数
                        target_uri = target_uri.strip()
                        # 改写 R-URI
                        parts = msg.start_line.split()
                        parts[1] = target_uri
                        msg.start_line = " ".join(parts)
                        # 清理 Route 和 Record-Route 头，避免 ;ob 和参数问题
                        msg.headers.pop("route", None)
                        msg.headers.pop("record-route", None)
                        log.debug(f"{method} R-URI corrected: {ruri} -> {target_uri}")
        except Exception as e:
            log.warning(f"{method} R-URI correction failed: {e}")
    # ACK 类型判断（用于后续处理）
    is_2xx_ack = False
    if method == "ACK":
        # ACK 特殊处理：区分 2xx 和非 2xx 响应
        # RFC 3261: 
        # - 2xx ACK：通过 Route 头路由（保留 Route）
        # - 非 2xx ACK：透传，保持所有头域不变（包括 R-URI）
        
        # 判断方法：
        # 1. 检查原始 Route 头（删除服务器 Route 之前）：2xx ACK 有 Route
        # 2. 检查 To tag：2xx ACK 必须有 To tag
        # 3. 检查 DIALOGS：Call-ID 在 DIALOGS 说明是已建立的对话
        to_tag = "tag=" in (msg.get("to") or "")
        
        # 改进的 ACK 类型判断：优先使用最后响应状态
        # 1. 如果有最后响应状态记录，直接使用（最准确）
        # 2. 否则，使用 Route 头和有 To tag 的判断（兼容旧逻辑）
        last_status = LAST_RESPONSE_STATUS.get(call_id) if call_id else None
        
        # 详细日志：记录 ACK 类型判断的完整过程
        log.info(f"[ACK-TYPE-CHECK] Call-ID: {call_id} | Last status: {last_status} | To tag: {to_tag} | Has Route: {has_route_before_strip} | In DIALOGS: {call_id in DIALOGS if call_id else False}")
        
        if last_status:
            # 有响应状态记录：根据状态码判断
            if last_status.startswith("2"):
                # 2xx 响应：2xx ACK
                is_2xx_ack = True
                log.info(f"[ACK-TYPE] Determined as 2xx ACK: Last response status={last_status} (from LAST_RESPONSE_STATUS)")
            else:
                # 非 2xx 响应：非 2xx ACK
                is_2xx_ack = False
                log.info(f"[ACK-TYPE] Determined as non-2xx ACK: Last response status={last_status} (from LAST_RESPONSE_STATUS)")
        elif (has_route_before_strip and to_tag) or (to_tag and call_id and call_id in DIALOGS):
            # 没有响应状态记录：使用旧逻辑判断
            # 2xx ACK：有原始 Route 头或 Call-ID 在 DIALOGS
            is_2xx_ack = True
            log.info(f"[ACK-TYPE] Determined as 2xx ACK (fallback): Original Route={has_route_before_strip}, To tag=YES, Dialog={call_id in DIALOGS if call_id else False}")
            log.warning(f"[ACK-TYPE-WARNING] Using fallback logic for Call-ID {call_id}: No LAST_RESPONSE_STATUS record! This may be incorrect if it's a non-2xx ACK.")
            # ACK 成功转发后，可以清理 DIALOGS（会话已确认建立）
            if call_id and call_id in DIALOGS:
                log.debug(f"[ACK-RECEIVED] ACK for Call-ID {call_id}, dialog confirmed")
        else:
            # 非 2xx ACK：透传，不修改任何头域
            is_2xx_ack = False
            log.info(f"[ACK-TYPE] Determined as non-2xx ACK (fallback): Original Route={has_route_before_strip}, To tag={to_tag}")

    # 初始 INVITE/MESSAGE/其他初始请求：查位置，改 R-URI
    if method in ("INVITE", "MESSAGE") and _is_initial_request(msg):
        # --- IMS 模式: 删除 UA 自带的 Route，清理 ;ob 参数 ---
        route_count = len(msg.headers.get("route", []))
        if route_count > 0:
            log.debug(f"[{method}-INITIAL] Deleting {route_count} Route headers")
        msg.headers.pop("route", None)

        # 解析被叫 AOR
        aor = _aor_from_to(msg.get("to")) or msg.start_line.split()[1]
        log.debug(f"[{method}-INITIAL] AOR: {aor} | To: {msg.get('to')}")
        targets = REG_BINDINGS.get(aor, [])
        now = int(time.time())
        targets = [t for t in targets if t["expires"] > now]
        log.debug(f"[{method}-INITIAL] Found {len(targets)} valid bindings for AOR: {aor}")

        # RFC 3261 Section 16.2: 代理收到初始 INVITE 后应立即回 100 Trying
        # 告知 UAC 请求已接收，避免不必要的重传
        if method == "INVITE" and targets:
            trying = _make_response(msg, 100, "Trying")
            # 打印完整的 SIP 响应内容（发送前）
            try:
                resp_content = trying.to_bytes().decode('utf-8', errors='ignore')
                log.debug(f"[TX-RESP-FULL] {addr} <- 100 Trying Full SIP response:\n{resp_content}")
            except Exception as e:
                log.debug(f"[TX-RESP-FULL] Failed to decode response: {e}")
            transport.sendto(trying.to_bytes(), addr)
            log.tx(addr, trying.start_line, extra="immediate 100 Trying")

        if not targets:
            log.warning(f"[{method}-INITIAL] No valid bindings for AOR: {aor}")
            # 记录失败的尝试（用于速率限制和攻击检测）
            client_ip = addr[0]
            _record_failed_attempt(client_ip)
            # 检查是否达到黑名单阈值
            if client_ip in ATTEMPT_COUNTER:
                count, _ = ATTEMPT_COUNTER[client_ip]
                if count >= SECURITY_CONFIG["RATE_LIMIT_THRESHOLD"]:
                    log.warning(f"[SECURITY] IP {client_ip} 请求未注册用户 {aor} 达到 {count} 次，可能被攻击")
            resp = _make_response(msg, 480, "Temporarily Unavailable")
            transport.sendto(resp.to_bytes(), addr)
            log.tx(addr, resp.start_line, extra=f"aor={aor}")
            return

        # ---- 选择最优绑定（优先最近注册的） ----
        # 按 expires 降序排列：expires 最大的是最近更新的绑定
        targets.sort(key=lambda t: t["expires"], reverse=True)

        # 排除与主叫相同地址的绑定（避免回环呼叫自己）
        caller_real = addr  # (ip, port)
        filtered = [t for t in targets if t.get("real_addr") != caller_real]
        if filtered:
            targets = filtered
            log.debug(f"[{method}-INITIAL] Filtered out caller binding, remaining: {len(targets)}")

        import re
        target_uri = targets[0]["contact"]
        target_uri = re.sub(r";ob\b", "", target_uri)
        target_uri = re.sub(r";transport=\w+", "", target_uri)

        log.info(f"[{method}-INITIAL] Selected binding: {target_uri} "
                 f"(real_addr={targets[0].get('real_addr')}, "
                 f"expires_in={targets[0]['expires'] - now}s, "
                 f"total={len(targets)})")

        # 改写 Request-URI
        parts = msg.start_line.split()
        parts[1] = target_uri
        msg.start_line = " ".join(parts)
        # --- 修正 From / To 防环路 ---
        try:
            from_aor = _aor_from_from(msg.get("from"))
            to_aor = _aor_from_to(msg.get("to"))

            # 如果主叫和被叫用户名相同（同一UA呼自己）
            if _same_user(from_aor, to_aor):
                # 强制改写被叫为目标AOR（即被叫注册的Contact）
                same_targets = REG_BINDINGS.get(to_aor, [])
                same_targets = [t for t in same_targets if t["expires"] > now]
                same_targets.sort(key=lambda t: t["expires"], reverse=True)
                if same_targets:
                    target_uri = same_targets[0]["contact"]
                    # 改写Request-URI
                    parts = msg.start_line.split()
                    parts[1] = target_uri
                    msg.start_line = " ".join(parts)
                    # 修正From为主叫AOR
                    for aor_key, binds in REG_BINDINGS.items():
                        for b in binds:
                            ip, port = _host_port_from_sip_uri(b["contact"])
                            if addr[1] == port:
                                msg.headers["from"] = [f"<{aor_key}>;tag={gen_tag()}"]
                                break
        except Exception as e:
            log.warning(f"From/To normalize failed: {e}")

        # 插入 Record-Route（RFC 3261 强制要求）
        # 当代理修改 R-URI 时，必须添加 Record-Route，
        # 这样后续的 in-dialog 请求（如 ACK, BYE）会通过 Route 头路由回代理
        # 注意：passthrough 模式下仍然需要添加 Record-Route，因为：
        # 1. 服务器修改了 R-URI（从 AOR 改为实际 Contact），必须添加 Record-Route
        # 2. 后续的 in-dialog 请求（2xx ACK, BYE）需要通过 Route 头路由回服务器
        # 3. passthrough 模式只是 SDP 透传（媒体直连），信令仍然需要经过服务器
        _add_record_route_for_initial(msg)
        if MEDIA_MODE == "passthrough":
            log.debug(f"[PASSTHROUGH] Added Record-Route (required for in-dialog routing), but SDP will be passed through unchanged")
        else:
            log.debug(f"[RECORD-ROUTE] Added Record-Route for initial INVITE")

    # 顶层 Via（我们）
    # RFC 3261: 
    # - INVITE: 有状态代理，添加服务器 Via，并保存 branch（用于 CANCEL 复用）
    # - CANCEL: 有状态代理，复用对应 INVITE 的 branch（兼容非标准客户端如 Zoiper 2.x）
    # - ACK (非2xx): 有状态代理，复用对应 INVITE 的 branch，添加服务器 Via（确保 Via 栈与 INVITE 一致）
    # - ACK (2xx): 无状态转发，不添加 Via（正常对话建立后的 ACK）
    # - 其他请求: 有状态代理，添加服务器 Via
    # 
    # RFC 3261 Section 9.1 关于 CANCEL:
    # "The CANCEL request uses the same Via headers as the request being cancelled"
    # 标准理解：客户端的 Via 头相同（branch 参数相同），代理可以添加不同的 Via branch
    # 但 Zoiper 2.x 要求整个 Via 栈都匹配，因此需要复用 INVITE 的 branch
    # 
    # RFC 3261 Section 17.2.3 关于非 2xx ACK:
    # "The ACK MUST have the same Via branch identifier and Call-ID as the INVITE
    #  to which it refers, but only the methods differ."
    # 作为有状态代理，为了匹配原始 INVITE 的 Via 栈，需要复用 INVITE 的 branch
    if method != "ACK":
        # 获取 Call-ID
        call_id = msg.get("call-id")
        
        # 为 CANCEL 复用对应 INVITE 的 branch
        if method == "CANCEL" and call_id and call_id in INVITE_BRANCHES:
            branch = INVITE_BRANCHES[call_id]
            log.debug(f"[CANCEL] Reusing INVITE branch: {branch} for Call-ID: {call_id}")
        else:
            # 其他请求生成新的 branch
            branch = f"z9hG4bK-{gen_tag(10)}"
            # 如果是 INVITE，保存 branch 供后续 CANCEL 和 ACK 使用
            if method == "INVITE" and call_id:
                INVITE_BRANCHES[call_id] = branch
                log.debug(f"[INVITE] Saved branch: {branch} for Call-ID: {call_id}")
        
        _add_top_via(msg, branch)

        # 如果没有 Max-Forwards、CSeq 等关键头，给个兜底（少见）
        _ensure_header(msg, "cseq", "1 " + method)
        _ensure_header(msg, "from", msg.get("from") or "<sip:unknown@localhost>;tag=" + gen_tag())
        _ensure_header(msg, "to", msg.get("to") or "<sip:unknown@localhost>")
        _ensure_header(msg, "call-id", msg.get("call-id") or gen_tag() + "@localhost")
        _ensure_header(msg, "via", f"SIP/2.0/UDP {SERVER_IP}:{SERVER_PORT};branch={branch};rport")
    else:
        # ACK 请求：根据 ACK 类型处理 Via
        # 注意：此时 is_2xx_ack 已经在上面判断过了
        call_id = msg.get("call-id")
        if not is_2xx_ack:
            # 非 2xx ACK：检查是否有 INVITE_BRANCHES
            if call_id and call_id in INVITE_BRANCHES:
                # 有状态代理，复用 INVITE 的 branch，添加服务器 Via
                # 确保被叫收到的 ACK 的 Via 栈与原始 INVITE 一致：[服务器Via, 主叫Via]
                branch = INVITE_BRANCHES[call_id]
                _add_top_via(msg, branch)
                log.info(f"[ACK-STATE] Non-2xx ACK: Reusing INVITE branch {branch} and adding server Via (stateful proxy mode)")
            else:
                # 非 2xx ACK 但没有 INVITE_BRANCHES（可能已被清理或 INVITE 未保存）
                log.warning(f"[ACK-WARNING] Non-2xx ACK for Call-ID {call_id} but INVITE_BRANCHES not found! Cannot add server Via. This may cause the callee to not recognize the ACK.")
                log.debug(f"[ACK-STATELESS] Non-2xx ACK: Forwarding without adding Via (INVITE_BRANCHES missing)")
        else:
            # 2xx ACK：无状态转发，不修改 Via（正常对话建立后的 ACK，不需要匹配原始 INVITE）
            log.debug(f"[ACK-STATELESS] 2xx ACK: Forwarding without adding Via (stateless proxy mode)")

    # 确定下一跳：优先 Route，否则用 Request-URI
    next_hop = None
    routes = msg.headers.get("route", [])
    
    # 如果是已知对话的请求，且有 Route 头，弹出我们的 Route
    if call_id in DIALOGS and routes:
        log.debug(f"[ROUTE] In-dialog request with {len(routes)} Route headers")
        _strip_our_top_route_and_get_next(msg)
        routes = msg.headers.get("route", [])
    
    if routes:
        # 取首个 Route 的 URI
        r = routes[0]
        if "<" in r and ">" in r:
            ruri = r[r.find("<")+1:r.find(">")]
        else:
            ruri = r.split(":", 1)[-1]
        nh = _host_port_from_sip_uri(ruri)
        next_hop = nh
        log.debug(f"[ROUTE] Using Route header: {ruri} -> {next_hop}")
    else:
        # 用 Request-URI
        ruri = msg.start_line.split()[1]
        next_hop = _host_port_from_sip_uri(ruri)
        log.debug(f"[ROUTE] Using Request-URI: {ruri} -> {next_hop}")

    if not next_hop or next_hop == ("", 0):
        resp = _make_response(msg, 502, "Bad Gateway")
        transport.sendto(resp.to_bytes(), addr)
        log.tx(addr, resp.start_line, extra="no next hop")
        return

    host, port = next_hop
    
    # 如果是已知对话的请求且检测到环路，尝试从 REG_BINDINGS 获取正确的目标
    is_in_dialog = call_id and call_id in DIALOGS if 'call_id' in locals() else False
    
    # === 🔒 防止自环 ===
    # 注意：ACK 请求的 R-URI 可能是 sip:user@127.0.0.1，会被误判为环路
    # 所以需要检查是否是真正的环路（明确指定了端口 5060）
    if (host == SERVER_IP and port == SERVER_PORT):
        # ACK 请求优先使用 ACK 专用处理逻辑（无论是 2xx 还是非 2xx）
        if method == "ACK":
            # 非 2xx ACK：使用 DIALOGS 或 REG_BINDINGS 找到被叫地址
            # RFC 3261: 非 2xx ACK 的 R-URI 必须和原始 INVITE 相同，不能修改
            # 但服务器需要知道转发给谁（被叫）
            if not is_2xx_ack:
                log.info(f"[ACK-NON2XX] Non-2xx ACK detected (Call-ID: {call_id}), finding target")
                # 优先从 DIALOGS 获取被叫地址
                if call_id and call_id in DIALOGS:
                    caller_addr, callee_addr = DIALOGS[call_id]
                    host, port = callee_addr
                    log.info(f"[ACK-NON2XX] ✓ Routing to callee from DIALOGS: {host}:{port}")
                else:
                    # DIALOGS 已被清理（可能因为 487 响应），使用 REG_BINDINGS 查找被叫地址
                    # 从 To 头获取被叫 AOR，然后查找注册的 contact 地址
                    log.info(f"[ACK-NON2XX] Call-ID {call_id} not in DIALOGS, trying REG_BINDINGS")
                    try:
                        to_header = msg.get("to") or ""
                        log.info(f"[ACK-NON2XX] To header: {to_header}")
                        to_aor = _aor_from_to(to_header)
                        log.info(f"[ACK-NON2XX] Extracted AOR: {to_aor}")
                        if to_aor:
                            targets = REG_BINDINGS.get(to_aor, [])
                            log.info(f"[ACK-NON2XX] Found {len(targets)} bindings for AOR {to_aor}")
                            now = int(time.time())
                            targets = [t for t in targets if t["expires"] > now]
                            log.info(f"[ACK-NON2XX] {len(targets)} valid (not expired) bindings")
                            if targets:
                                b_uri = targets[0]["contact"]
                                log.info(f"[ACK-NON2XX] Using contact: {b_uri}")
                                real_host, real_port = _host_port_from_sip_uri(b_uri)
                                if real_host and real_port:
                                    host, port = real_host, real_port
                                    log.info(f"[ACK-NON2XX] ✓ Routing to callee from REG_BINDINGS: {host}:{port} (AOR: {to_aor})")
                                else:
                                    log.error(f"[ACK-NON2XX] ✗ Invalid contact address for AOR {to_aor}: {b_uri}, cannot route ACK")
                                    return
                            else:
                                log.error(f"[ACK-NON2XX] ✗ No valid bindings for AOR {to_aor}, cannot route ACK")
                                log.info(f"[ACK-NON2XX] All bindings: {REG_BINDINGS.get(to_aor, [])}")
                                return
                        else:
                            log.error(f"[ACK-NON2XX] ✗ Cannot extract AOR from To header: {to_header}, cannot route ACK")
                            return
                    except Exception as e:
                        log.error(f"[ACK-NON2XX] ✗ Failed to find callee address: {e}, cannot route ACK")
                        import traceback
                        log.error(f"[ACK-NON2XX] Traceback: {traceback.format_exc()}")
                        return
            else:
                # 2xx ACK：尝试使用注册表中的 contact 地址
                try:
                    to_aor = _aor_from_to(msg.get("to"))
                    ruri = msg.start_line.split()[1]
                    log.debug(f"[ACK-2XX-CHECK] To AOR: {to_aor} | R-URI: {ruri} | Detected loop: {host}:{port}")
                    
                    if to_aor:
                        targets = REG_BINDINGS.get(to_aor, [])
                        if targets:
                            b_uri = targets[0]["contact"]
                            real_host, real_port = _host_port_from_sip_uri(b_uri)
                            if real_host and real_port:
                                host, port = real_host, real_port
                                log.debug(f"ACK (2xx) using contact address: {b_uri} -> {host}:{port}")
                            else:
                                log.drop(f"ACK (2xx) loop detected: skipping self-forward to {host}:{port}")
                                return
                    else:
                        log.warning(f"ACK (2xx): No To AOR found, R-URI: {ruri}")
                        log.drop(f"ACK (2xx) loop detected: skipping self-forward to {host}:{port}")
                        return
                except Exception as e:
                    log.warning(f"ACK (2xx) loop check failed: {e}")
                    log.drop(f"Loop detected: skipping self-forward to {host}:{port}")
                    return
        # 如果是已知对话的请求且目标指向服务器，尝试使用注册表中的地址（非 ACK）
        elif is_in_dialog:
            try:
                to_aor = _aor_from_to(msg.get("to")) or msg.start_line.split()[1]
                targets = REG_BINDINGS.get(to_aor, [])
                if targets:
                    b_uri = targets[0]["contact"]
                    real_host, real_port = _host_port_from_sip_uri(b_uri)
                    if real_host and real_port and (real_host != SERVER_IP or real_port != SERVER_PORT):
                        host, port = real_host, real_port
                        log.debug(f"[IN-DIALOG] Using contact address from REG_BINDINGS: {host}:{port}")
                    else:
                        log.drop(f"[IN-DIALOG] Loop detected and no valid contact, skipping: {host}:{port}")
                        return
                else:
                    log.drop(f"[IN-DIALOG] Loop detected and no bindings for AOR {to_aor}, skipping: {host}:{port}")
                    return
            except Exception as e:
                log.warning(f"[IN-DIALOG] Loop check failed: {e}")
                log.drop(f"Loop detected: skipping self-forward to {host}:{port}")
                return
        else:
            log.drop(f"Loop detected: skipping self-forward to {host}:{port}")
            return

    # --- NAT/私网修正: 如果 Contact 或 R-URI 的 host 不可达，强制使用我们已知的绑定地址 ---
    # 从 REG_BINDINGS 查找被叫实际的 contact IP
    # 注意：ACK 已经在环路检测中使用了 contact 地址，这里跳过避免重复处理
    if method in ("INVITE", "BYE", "CANCEL", "UPDATE", "PRACK", "MESSAGE", "REFER", "NOTIFY", "SUBSCRIBE"):
        try:
            # B2BUA: BYE 必须转发到对话的另一方，用 DIALOGS 确保对方一定能收到挂断
            bye_routed_by_dialogs = False
            if method == "BYE" and call_id and call_id in DIALOGS:
                caller_addr, callee_addr = DIALOGS[call_id]
                if (addr[0], addr[1]) == (caller_addr[0], caller_addr[1]):
                    host, port = callee_addr[0], callee_addr[1]
                    bye_routed_by_dialogs = True
                    log.info(f"[BYE] Route to callee (other party): {host}:{port}")
                elif (addr[0], addr[1]) == (callee_addr[0], callee_addr[1]):
                    host, port = caller_addr[0], caller_addr[1]
                    bye_routed_by_dialogs = True
                    log.info(f"[BYE] Route to caller (other party): {host}:{port}")
            if not bye_routed_by_dialogs:
                aor = _aor_from_to(msg.get("to")) or msg.start_line.split()[1]
                bindings = REG_BINDINGS.get(aor, [])
                if bindings:
                    # 取第一个绑定的 contact，解析 IP 和端口
                    b_uri = bindings[0]["contact"]
                    real_host, real_port = _host_port_from_sip_uri(b_uri)
                    host, port = real_host, real_port
                    log.debug(f"[{method}] Using registered contact: {b_uri} -> {host}:{port}")
                else:
                    # 没有找到注册绑定，回复 480 Temporarily Unavailable
                    if method in ("MESSAGE", "REFER", "NOTIFY", "SUBSCRIBE"):
                        log.warning(f"[{method}] No bindings found for AOR: {aor}")
                        resp = _make_response(msg, 480, "Temporarily Unavailable")
                        transport.sendto(resp.to_bytes(), addr)
                        log.tx(addr, resp.start_line, extra=f"aor={aor}")
                        return
        except Exception as e:
            log.warning(f"NAT fix skipped: {e}")
    # -------------------------------------------------------------------------------

    # B2BUA 模式：转发 INVITE 前修改 SDP（确保被叫收到普通RTP SDP）
    call_id = msg.get("call-id")
    if method == "INVITE" and call_id and ENABLE_MEDIA_RELAY and msg.body:
        try:
            to_header = msg.get("to") or ""
            has_to_tag = "tag=" in to_header
            if not has_to_tag:
                # 初始 INVITE：修改 SDP 为普通RTP并指向B2BUA媒体B-leg端口（被叫发媒体到这里）
                media_relay = get_media_relay()
                if media_relay:
                    sdp_body = msg.body.decode('utf-8', errors='ignore') if isinstance(msg.body, bytes) else msg.body
                    log.info(f"[B2BUA-DEBUG] 转发INVITE前原始SDP:\n{sdp_body[:500]}...")
                    try:
                        # 提取主被叫号码和from_tag
                        from_header = msg.get("from") or ""
                        caller_number = _extract_number_from_uri(from_header)
                        callee_number = _extract_number_from_uri(to_header)
                        log.info(f"[B2BUA] 提取号码: 主叫={caller_number}, 被叫={callee_number}")
                        
                        # 提取from_tag用于RTPProxy offer命令
                        from_tag = None
                        if "tag=" in from_header:
                            from_tag = from_header.split("tag=")[1].split(";")[0].split(">")[0].strip()
                            log.info(f"[B2BUA] INVITE阶段提取from_tag: {from_tag}")
                        
                        # 使用 process_invite_to_callee 修改SDP指向B-leg端口，同时保存A-leg信息和号码
                        # 在INVITE阶段发送RTPProxy offer命令
                        new_sdp, session = media_relay.process_invite_to_callee(
                            call_id, sdp_body, addr, 
                            caller_number=caller_number, 
                            callee_number=callee_number,
                            from_tag=from_tag
                        )
                        if session:
                            msg.body = new_sdp.encode('utf-8') if isinstance(msg.body, bytes) else new_sdp
                            if 'content-length' in msg.headers:
                                msg.headers['content-length'] = [str(len(msg.body) if isinstance(msg.body, bytes) else len(msg.body.encode('utf-8')))]
                            log.info(f"[B2BUA] INVITE SDP 修改为普通RTP: {call_id} -> B-leg端口 {session.b_leg_rtp_port}")
                            log.info(f"[B2BUA-DEBUG] 转发INVITE后SDP:\n{new_sdp[:500]}...")
                        else:
                            log.error(f"[B2BUA] 会话创建失败: {call_id}")
                    except Exception as inner_e:
                        log.error(f"[B2BUA] process_invite_to_callee异常: {inner_e}")
                        import traceback
                        log.error(traceback.format_exc())
        except Exception as e:
            log.error(f"[B2BUA] 转发INVITE时SDP修改失败: {e}")
    
    try:
        # 详细日志：显示发送前的消息详情
        call_id = msg.get("call-id")
        vias = msg.headers.get("via", [])
        routes = msg.headers.get("route", [])
        log.debug(f"[FWD-DETAIL] Method: {method} | Call-ID: {call_id} | Target: {host}:{port} | Via hops: {len(vias)} | Route: {len(routes)}")
        
        # 打印完整的 SIP 消息内容（转发前）
        try:
            msg_content = msg.to_bytes().decode('utf-8', errors='ignore')
            log.debug(f"[FWD-FULL] {method} -> {host}:{port} Full SIP message:\n{msg_content}")
        except Exception as e:
            log.debug(f"[FWD-FULL] Failed to decode message: {e}")
        
        transport.sendto(msg.to_bytes(), (host, port))
        log.fwd(method, (host, port), f"R-URI={msg.start_line.split()[1]}")
        
        # 记录请求映射：Call-ID -> 原始请求发送者地址（用于响应转发）
        # 注意：这里记录的是 addr（请求发送者），而非 (host, port)（转发目标）
        call_id = msg.get("call-id")
        if call_id and method in ("INVITE", "BYE", "CANCEL", "UPDATE", "PRACK", "MESSAGE", "REFER", "NOTIFY", "SUBSCRIBE"):
            PENDING_REQUESTS[call_id] = addr  # 记录请求发送者地址
            # 记录对话信息：主叫和被叫地址
            if method == "INVITE":
                # 判断是初始 INVITE 还是 re-INVITE
                to_header = msg.get("to") or ""
                has_to_tag = "tag=" in to_header
                
                # 解析 SDP 提取呼叫类型和编解码信息
                call_type, codec = extract_sdp_info(msg.body)
                
                # B2BUA 模式：记录媒体会话信息（SDP已在上面修改过）
                if ENABLE_MEDIA_RELAY and msg.body and has_to_tag:
                    # re-INVITE：更新媒体会话
                    log.info(f"[re-INVITE] Media change - Call-ID: {call_id}, "
                            f"New media: {call_type}, Codec: {codec}")
                
                if not has_to_tag:
                    # 初始 INVITE：建立新对话
                    DIALOGS[call_id] = (addr, (host, port))
                    
                    # CDR: 记录呼叫开始
                    cdr.record_call_start(
                        call_id=call_id,
                        caller_uri=msg.get("from") or "",
                        callee_uri=msg.get("to") or "",
                        caller_addr=addr,
                        callee_ip=host,
                        callee_port=port,
                        call_type=call_type,
                        codec=codec,
                        user_agent=msg.get("user-agent") or "",
                        cseq=msg.get("cseq") or "",
                        server_ip=SERVER_IP,
                        server_port=SERVER_PORT
                    )
                else:
                    # re-INVITE：媒体协商变化
                    log.info(f"[re-INVITE] Media change - Call-ID: {call_id}, "
                            f"New media: {call_type}, Codec: {codec}")
                    
                    # CDR: 记录媒体变化（更新到最终状态）
                    if call_type or codec:
                        cdr.record_media_change(
                            call_id=call_id,
                            new_call_type=call_type,
                            new_codec=codec
                        )
            elif method == "BYE":
                # CDR: 记录呼叫结束（只在第一次收到 BYE 时记录，避免重传导致重复）
                # 通过检查 DIALOGS 是否存在来判断是否是第一次
                if call_id in DIALOGS:
                    cdr.record_call_end(
                        call_id=call_id,
                        termination_reason="Normal",
                        cseq=msg.get("cseq") or ""
                    )
                # B2BUA: 清理媒体会话
                if ENABLE_MEDIA_RELAY:
                    media_relay = get_media_relay()
                    if media_relay:
                        media_relay.end_session(call_id)
            elif method == "CANCEL":
                # CDR: 记录呼叫取消（只在第一次收到时记录）
                if call_id in DIALOGS:
                    cdr.record_call_cancel(
                        call_id=call_id,
                        cseq=msg.get("cseq") or ""
                    )
                # B2BUA: 清理媒体会话
                if ENABLE_MEDIA_RELAY:
                    media_relay = get_media_relay()
                    if media_relay:
                        media_relay.end_session(call_id)
            elif method == "MESSAGE":
                # CDR: 记录短信（MESSAGE 一般不会重传，但为了统一性也加上检查）
                # 使用 CSeq 作为唯一性标识，防止重复记录
                message_id = f"{call_id}-{msg.get('cseq') or ''}"
                # MESSAGE 请求不在 DIALOGS 中，所以直接记录（CDR 层面会防重复）
                cdr.record_message(
                    call_id=message_id,  # 使用 call_id+cseq 作为唯一标识
                    caller_uri=msg.get("from") or "",
                    callee_uri=msg.get("to") or "",
                    caller_addr=addr,
                    message_body=msg.body.decode('utf-8', errors='ignore') if msg.body else "",
                    user_agent=msg.get("user-agent") or "",
                    cseq=msg.get("cseq") or "",
                    server_ip=SERVER_IP,
                    server_port=SERVER_PORT
                )
        # ACK 也需要记录地址（虽然不需要响应，但保留追踪）
        elif call_id and method == "ACK":
            PENDING_REQUESTS[call_id] = addr  # 记录请求发送者地址
            # RFC 3261: 转发非 2xx ACK 后，清理 DIALOGS、INVITE_BRANCHES 和最后响应状态
            # 因为 ACK 确认了收到最终响应，可以安全清理对话信息
            if not is_2xx_ack:
                if call_id in DIALOGS:
                    del DIALOGS[call_id]
                    log.debug(f"[DIALOG-CLEANUP] Cleaned up DIALOGS after forwarding non-2xx ACK for Call-ID: {call_id}")
                # 清理 INVITE branch（非 2xx ACK 转发完成后不再需要）
                if call_id in INVITE_BRANCHES:
                    del INVITE_BRANCHES[call_id]
                    log.debug(f"[BRANCH-CLEANUP] Cleaned up INVITE_BRANCHES after forwarding non-2xx ACK for Call-ID: {call_id}")
            # 清理最后响应状态
            if call_id in LAST_RESPONSE_STATUS:
                del LAST_RESPONSE_STATUS[call_id]
                log.debug(f"[LAST-RESP-STATUS] Cleaned up last response status for Call-ID: {call_id}")
            
    except OSError as e:
        # 网络错误：目标主机不可达
        # errno 65: No route to host (macOS/BSD)
        # errno 113: No route to host (Linux)
        # errno 101: Network is unreachable
        if e.errno in (65, 113, 101):
            log.warning(f"[NETWORK] Target unreachable {host}:{port} - {e}")
            # 根据方法类型返回适当的错误响应
            if method in ("INVITE", "MESSAGE", "REFER", "NOTIFY", "SUBSCRIBE"):
                # 对于需要响应的请求，返回 480 Temporarily Unavailable
                resp = _make_response(msg, 480, "Temporarily Unavailable")
                transport.sendto(resp.to_bytes(), addr)
                log.tx(addr, resp.start_line, extra=f"target unreachable")
            elif method == "BYE":
                # BYE 失败，返回 408 Request Timeout
                resp = _make_response(msg, 408, "Request Timeout")
                transport.sendto(resp.to_bytes(), addr)
                log.tx(addr, resp.start_line, extra=f"target unreachable")
                
                # 清理 DIALOGS，防止重传 BYE 时重复记录 CDR
                if call_id and call_id in DIALOGS:
                    del DIALOGS[call_id]
                    log.debug(f"[DIALOG-CLEANUP] Cleaned up unreachable call: {call_id}")
            # ACK 和 CANCEL 不需要响应
        else:
            # 其他网络错误
            log.error(f"[NETWORK] Send failed to {host}:{port} - {e}")
            resp = _make_response(msg, 503, "Service Unavailable")
            transport.sendto(resp.to_bytes(), addr)
            log.tx(addr, resp.start_line, extra=f"network error")
    except Exception as e:
        # 其他异常
        log.error(f"[ERROR] Forward failed: {e}")
        resp = _make_response(msg, 502, "Bad Gateway")
        transport.sendto(resp.to_bytes(), addr)
        log.tx(addr, resp.start_line, extra=f"forward error")

def _forward_response(resp: SIPMessage, addr, transport):
    """
    响应转发：
    - 如果顶层 Via 是我们，弹出它
    - 将响应发给新的顶层 Via 的 sent-by
    - 若 sent-by 不可达，则优先使用待处理的请求地址，其次用当前addr
    - 停止转发 482/482 等错误响应，避免环路
    """
    vias = resp.headers.get("via", [])
    if not vias:
        return

    # 处理逗号分隔的 Via 头（RFC 3261 允许在同一行用逗号分隔多个 Via）
    # 将每个逗号分隔的 Via 头分割成独立元素
    split_vias = []
    for via_str in vias:
        # 分割逗号分隔的 Via 头（但要小心，逗号可能在参数值中）
        # RFC 3261: Via 头的逗号分隔必须正确处理
        parts = _split_via_header(via_str)
        split_vias.extend(parts)
    
    # 如果没有分割出多个，使用原始值
    if not split_vias:
        split_vias = vias
    
    # 检查顶层Via是否是我们
    top = split_vias[0] if split_vias else ""
    status_code = resp.start_line.split()[1] if len(resp.start_line.split()) > 1 else ""
    call_id_resp = resp.get("call-id")
    
    # 增强日志：记录完整的 Via 头内容
    log.debug(f"[RESP-VIA] Response {status_code} (Call-ID: {call_id_resp}) | Via count: {len(split_vias)} | Top Via: {top[:100]}")
    
    if not top or f"{SERVER_IP}:{SERVER_PORT}" not in top:
        # 调试：记录为什么不转发
        log.debug(f"[RESP-SKIP] Response {status_code} not forwarded: top Via '{top[:100] if top else 'EMPTY'}' does not contain '{SERVER_IP}:{SERVER_PORT}' | Call-ID: {call_id_resp}")
        return
    
    # 如果是错误响应（如 482 Loop Detected），不应该继续转发
    # 这些响应应该直接返回给当前接收方
    status_code = resp.start_line.split()[1] if len(resp.start_line.split()) > 1 else ""
    if status_code in ("482", "483", "502", "503", "504"):
        call_id_resp = resp.get("call-id")
        vias_resp = resp.headers.get("via", [])
        log.warning(f"Dropping error response: {resp.start_line} | Call-ID: {call_id_resp} | Via hops: {len(vias_resp)}")
        # 打印 Via 头内容以便调试
        for i, via in enumerate(vias_resp):
            log.debug(f"  Via[{i}]: {via}")
        return

    # 修正响应中的 Contact 头：根据网络环境处理
    # 模式1：FORCE_LOCAL_ADDR=True（本机测试）- 强制使用 127.0.0.1
    # 模式2：FORCE_LOCAL_ADDR=False（真实网络）- 保持服务器可见地址
    contacts = resp.headers.get("contact", [])
    if contacts and FORCE_LOCAL_ADDR:
        for i, contact_val in enumerate(contacts):
            original = contact_val
            # 提取端口号
            port_match = re.search(r":(\d+)", contact_val)
            port = port_match.group(1) if port_match else "5060"
            
            # 替换所有外部 IP 为 127.0.0.1（仅在本机测试模式）
            # 保留 sip:user@host:port 的格式，只替换 host 部分
            contact_val = re.sub(r"@[^:;>]+", f"@127.0.0.1", contact_val)
            
            if contact_val != original:
                contacts[i] = contact_val
                log.debug(f"[CONTACT-FIX] Contact修正 (本机模式): {original} -> {contact_val}")
        resp.headers["contact"] = contacts
    elif contacts:
        # 真实网络模式：检查是否需要 NAT 修正
        for i, contact_val in enumerate(contacts):
            # 如果 Contact 地址不在本地网络中，可能需要修正
            # 这里保持原样，让实际的网络环境处理
            pass

    # 弹出我们的 Via
    _pop_top_via(resp)
    
    # 重新获取 Via 头（可能已分割）
    vias2 = resp.headers.get("via", [])
    if not vias2:
        # 如果没有 Via 头了，尝试使用 PENDING_REQUESTS 中的原始发送者地址
        call_id = resp.get("call-id")
        original_sender_addr = PENDING_REQUESTS.get(call_id) if call_id else None
        if original_sender_addr:
            log.debug(f"[RESP-ROUTE] No Via left, using PENDING_REQUESTS: {original_sender_addr}")
            nhost, nport = original_sender_addr
        else:
            log.warning(f"[RESP-ROUTE] No Via left and no PENDING_REQUESTS for Call-ID: {call_id}, cannot forward response {status_code}")
            return  # 无上层Via，无法继续转发
    else:
        # 处理可能的逗号分隔的 Via 头
        first_via_str = vias2[0]
        first_via_parts = _split_via_header(first_via_str)
        
        if not first_via_parts:
            # 无法解析，使用兜底方案
            call_id = resp.get("call-id")
            original_sender_addr = PENDING_REQUESTS.get(call_id) if call_id else None
            if original_sender_addr:
                nhost, nport = original_sender_addr
                log.debug(f"[RESP-ROUTE] Failed to parse Via, using PENDING_REQUESTS: {original_sender_addr}")
            else:
                log.warning(f"[RESP-ROUTE] Failed to parse Via and no PENDING_REQUESTS for Call-ID: {call_id}")
                return
        else:
            # 使用第一个 Via 头
            first_via = first_via_parts[0]
            nhost, nport = _host_port_from_via(first_via)
            log.debug(f"[RESP-ROUTE] Via头数量: {len(vias2)}, Via[0] (split): {len(first_via_parts)} parts, First Via: {first_via[:80]}")
            log.debug(f"[RESP-ROUTE] Via解析结果 -> target: {nhost}:{nport}")

    # 获取Call-ID，用于查找原始请求发送者地址
    call_id = resp.get("call-id")
    original_sender_addr = PENDING_REQUESTS.get(call_id) if call_id else None
    log.debug(f"[RESP-ROUTE] Call-ID: {call_id}, Original sender: {original_sender_addr}, Via解析: {nhost}:{nport}")

    # ========== rport 支持 ==========
    # 优先使用原始请求的源地址（从UDP socket读取的真实地址）
    # 这符合 RFC 3581: An Extension to SIP for Symmetric Response Routing
    if original_sender_addr:
        # rport: 使用收到请求的源地址和端口
        real_host, real_port = original_sender_addr
        log.debug(f"[RPORT] 使用rport地址: {real_host}:{real_port}")
        nhost, nport = real_host, real_port
    else:
        # 回退方案：查找REGISTER绑定的真实地址
        for aor, binds in REG_BINDINGS.items():
            for b in binds:
                if "real_addr" in b:
                    host2, port2 = b["real_addr"]
                    if host2 and port2:
                        log.debug(f"[RPORT] 使用REGISTER绑定的真实地址: {host2}:{port2}")
                        nhost, nport = host2, port2
                        break

    # ========== 防止自环 ==========
    # 如果最终地址指向服务器自己，回退到Via头解析的地址
    if (nhost == SERVER_IP and nport == SERVER_PORT):
        log.warning(f"[RPORT] 回退: rport地址指向服务器({nhost}:{nport})，使用Via地址")
        vias = resp.headers.get("via", [])
        if vias:
            first_via_str = vias[0]
            first_via_parts = _split_via_header(first_via_str)
            if first_via_parts:
                nhost, nport = _host_port_from_via(first_via_parts[0])

    # 兜底：如果还是没找到，就用当前addr（收到响应的对端）
    if not nhost or not nport:
        nhost, nport = addr
        log.debug(f"Using fallback address: {addr}")

    # 防止自环
    if (nhost == SERVER_IP and nport == SERVER_PORT):
        log.drop(f"Prevented response loop to self ({nhost}:{nport})")
        return

    # ═══════════════════════════════════════════════════════════════════════
    # RFC 3261 标准路由：所有响应严格按照 Via 头路由
    # ═══════════════════════════════════════════════════════════════════════
    # 
    # 之前的逻辑（已注释）：强制所有 INVITE 响应发给 caller
    # 问题：re-INVITE 可能由 callee 发起，此时响应应该发给 callee，而非 caller
    # 解决：统一使用 Via 路由机制，自动处理所有场景（初始 INVITE、re-INVITE）
    #
    # 注：已有的 NAT 修正逻辑（930-951行）会处理 NAT 穿透问题
    #
    # status_code = resp.start_line.split()[1] if len(resp.start_line.split()) > 1 else ""
    # cseq_header = resp.get("cseq") or ""
    # is_invite_response = "INVITE" in cseq_header
    # 
    # if call_id in DIALOGS and is_invite_response:
    #     caller_addr, callee_addr = DIALOGS[call_id]
    #     log.debug(f"[DIALOG-ROUTE] INVITE response: caller={caller_addr}, callee={callee_addr}, status={status_code}")
    #     # ❌ 这会导致 re-INVITE 响应回环（被叫发起的 re-INVITE 的响应会发回主叫）
    #     if status_code in ("200", "486", "487", "488", "600", "603", "604"):
    #         nhost, nport = caller_addr
    #         log.debug(f"Final INVITE response {status_code} to caller: {caller_addr} (overriding Via route)")
    # elif call_id in DIALOGS:
    #     caller_addr, callee_addr = DIALOGS[call_id]
    #     log.debug(f"[DIALOG-ROUTE] Non-INVITE response ({cseq_header}): using Via route to {nhost}:{nport}")
    
    # 调试日志：显示 Via 路由结果
    status_code = resp.start_line.split()[1] if len(resp.start_line.split()) > 1 else ""
    cseq_header = resp.get("cseq") or ""
    is_invite_response = "INVITE" in cseq_header
    log.debug(f"[VIA-ROUTE] Response {status_code} ({cseq_header}) → {nhost}:{nport}")

    try:
        # 打印完整的 SIP 响应内容（转发前）
        try:
            resp_content = resp.to_bytes().decode('utf-8', errors='ignore')
            log.debug(f"[FWD-RESP-FULL] {status_code} -> {nhost}:{nport} Full SIP response:\n{resp_content}")
        except Exception as e:
            log.debug(f"[FWD-RESP-FULL] Failed to decode response: {e}")
        
        transport.sendto(resp.to_bytes(), (nhost, nport))
        log.fwd(f"RESP {resp.start_line}", (nhost, nport))
        
        # 清理追踪记录
        # RFC 3261: 对于 INVITE 的非 2xx 最终响应（如 487），需要等待 ACK
        # - 2xx 响应(200)：保留 DIALOGS，等待 ACK
        # - 非 2xx 响应(486, 487等)：保留 DIALOGS，等待 ACK（ACK 转发后才清理）
        # CDR: 只在第一次收到响应时记录（避免重传导致重复记录）
        need_cleanup = False
        if status_code in ("486", "487", "488", "600", "603", "604"):
            if call_id in DIALOGS:
                need_cleanup = True  # 第一次收到最终响应（用于 CDR 记录）
            # 清理 PENDING_REQUESTS（不再需要追踪）
            if call_id in PENDING_REQUESTS:
                del PENDING_REQUESTS[call_id]
            # ⚠️ 注意：不立即清理 INVITE_BRANCHES，需要等待 ACK
            # INVITE_BRANCHES 将在收到并转发 ACK 后清理（在 _forward_request 的 ACK 处理中）
            # 因为非 2xx ACK 需要复用 INVITE 的 branch 来匹配原始 Via 栈
            log.debug(f"[BRANCH-WAIT-ACK] Keeping INVITE_BRANCHES for Call-ID {call_id}, waiting for ACK for non-2xx response {status_code}")
            # ⚠️ 注意：不立即清理 DIALOGS，需要等待 ACK
            # DIALOGS 将在收到并转发 ACK 后清理（在 _forward_request 的 ACK 处理中）
            log.debug(f"[DIALOG-WAIT-ACK] Keeping DIALOGS for Call-ID {call_id}, waiting for ACK for non-2xx response {status_code}")
        
        # 记录最后响应状态（用于 ACK 类型判断）
        if is_invite_response and call_id:
            # 只记录最终响应（非 1xx）
            if status_code and not status_code.startswith("1"):
                LAST_RESPONSE_STATUS[call_id] = status_code
                log.debug(f"[LAST-RESP-STATUS] Recorded last response status {status_code} for Call-ID {call_id}")
        
        # CDR: 记录呼叫应答和呼叫失败（只在第一次收到响应时记录，避免重传导致重复）
        if is_invite_response:
            if status_code == "200":
                # 解析 200 OK 响应中的 SDP（被叫可能使用不同的编解码）
                call_type_answer, codec_answer = extract_sdp_info(resp.body)
                
                # B2BUA 模式：修改 200 OK 中的 SDP 并启动媒体转发（同一呼叫只启动一次，避免重传 200 OK 导致主叫收两份 200 转圈）
                if ENABLE_MEDIA_RELAY and resp.body:
                    media_relay = get_media_relay()
                    if media_relay:
                        try:
                            session = media_relay._sessions.get(call_id)
                            already_started = session and session.started_at is not None
                            log.info(f"[B2BUA] 检查媒体转发状态: {call_id}, session存在={session is not None}, started_at={session.started_at if session else None}, already_started={already_started}")
                            sdp_body = resp.body.decode('utf-8', errors='ignore') if isinstance(resp.body, bytes) else resp.body
                            if not already_started:
                                log.info(f"[B2BUA-DEBUG] 原始200OK SDP:\n{sdp_body[:500]}...")
                            new_sdp, success = media_relay.process_answer_sdp(call_id, sdp_body, addr)
                            log.info(f"[B2BUA] process_answer_sdp结果: {call_id}, success={success}")
                            if success:
                                resp.body = new_sdp.encode('utf-8') if isinstance(resp.body, bytes) else new_sdp
                                if 'content-length' in resp.headers:
                                    resp.headers['content-length'] = [str(len(resp.body) if isinstance(resp.body, bytes) else len(resp.body.encode('utf-8')))]
                                log.info(f"[B2BUA] 200 OK SDP 修改: {call_id} -> 共享端口 {media_relay._sessions.get(call_id) and media_relay._sessions[call_id].b_leg_rtp_port}")
                                if not already_started:
                                    log.info(f"[B2BUA-DEBUG] 修改后200OK SDP:\n{new_sdp[:500]}...")
                                    log.info(f"[B2BUA] 准备启动媒体转发: {call_id}, already_started={already_started}")
                                    try:
                                        # 提取from_tag和to_tag用于RTPProxy会话创建
                                        from_header = resp.get("from") or ""
                                        to_header = resp.get("to") or ""
                                        from_tag = None
                                        to_tag = None
                                        if "tag=" in from_header:
                                            from_tag = from_header.split("tag=")[1].split(";")[0].split(">")[0].strip()
                                        if "tag=" in to_header:
                                            to_tag = to_header.split("tag=")[1].split(";")[0].split(">")[0].strip()
                                        
                                        log.info(f"[B2BUA] 提取标签: from_tag={from_tag}, to_tag={to_tag}")
                                        result = media_relay.start_media_forwarding(call_id, from_tag=from_tag, to_tag=to_tag)
                                        log.info(f"[B2BUA] 媒体转发启动结果: {call_id}, result={result}")
                                        media_relay.print_media_diagnosis(call_id)
                                    except Exception as start_e:
                                        log.error(f"[B2BUA] 启动媒体转发异常: {call_id}, error={start_e}")
                                        import traceback
                                        log.error(traceback.format_exc())
                                else:
                                    log.debug(f"[B2BUA] 200 OK 重传，媒体已启动，仅更新 SDP 并转发: {call_id}")
                        except Exception as e:
                            log.error(f"[B2BUA] 200 OK SDP 修改失败: {e}")
                            import traceback
                            log.error(traceback.format_exc())
                
                # 判断是初始 INVITE 还是 re-INVITE 的 200 OK
                # 通过检查会话是否已有 answer_time 来判断
                session = cdr.get_session(call_id)
                is_reinvite_response = session and "answer_time" in session
                
                if not is_reinvite_response:
                    # 初始 INVITE 的 200 OK：记录呼叫接听
                    cdr.record_call_answer(
                        call_id=call_id,
                        callee_addr=addr,
                        call_type=call_type_answer if call_type_answer else None,
                        codec=codec_answer if codec_answer else None,
                        status_code=200,
                        status_text="OK"
                    )
                else:
                    # re-INVITE 的 200 OK：确认媒体变化
                    log.info(f"[re-INVITE-OK] Media change confirmed - Call-ID: {call_id}, "
                            f"Media: {call_type_answer}, Codec: {codec_answer}")
                    
                    # 打印媒体诊断信息
                    if ENABLE_MEDIA_RELAY:
                        media_relay = get_media_relay()
                        if media_relay:
                            media_relay.print_media_diagnosis(call_id)
                    
                    # 更新最终媒体信息（如果有的话）
                    if call_type_answer or codec_answer:
                        cdr.record_media_change(
                            call_id=call_id,
                            new_call_type=call_type_answer,
                            new_codec=codec_answer
                        )
            elif need_cleanup:
                # CDR: 记录呼叫失败（仅在第一次清理时记录）
                status_text = resp.start_line.split(maxsplit=2)[2] if len(resp.start_line.split(maxsplit=2)) > 2 else "Failed"
                cdr.record_call_fail(
                    call_id=call_id,
                    status_code=int(status_code),
                    status_text=status_text,
                    reason=f"{status_code} {status_text}"
                )
                # B2BUA: 清理媒体会话
                if ENABLE_MEDIA_RELAY:
                    media_relay = get_media_relay()
                    if media_relay:
                        media_relay.end_session(call_id)
            elif status_code.startswith(('4', '5', '6')) and status_code not in ("100", "180", "183", "486", "487", "488", "600", "603", "604"):
                # CDR: 记录其他失败响应（如 480, 404 等）
                # 只有当 call_id 还在 DIALOGS 中时才记录（第一次）
                if call_id in DIALOGS:
                    status_text = resp.start_line.split(maxsplit=2)[2] if len(resp.start_line.split(maxsplit=2)) > 2 else "Error"
                    cdr.record_call_fail(
                        call_id=call_id,
                        status_code=int(status_code),
                        status_text=status_text,
                        reason=f"{status_code} {status_text}"
                    )
                    # 立即清理，避免重复记录
                    if call_id in PENDING_REQUESTS:
                        del PENDING_REQUESTS[call_id]
                    if call_id in DIALOGS:
                        del DIALOGS[call_id]
                    if call_id in INVITE_BRANCHES:
                        del INVITE_BRANCHES[call_id]
                    # B2BUA: 清理媒体会话
                    if ENABLE_MEDIA_RELAY:
                        media_relay = get_media_relay()
                        if media_relay:
                            media_relay.end_session(call_id)
        elif status_code == "200":
            # 200 OK：需要区分不同场景
            # - INVITE 200 OK：已在上面处理（保留 DIALOGS 等待 ACK）
            # - BYE 200 OK：应该清理 DIALOGS（呼叫已结束）
            # - CANCEL 200 OK：不应该清理 INVITE_BRANCHES（还需要等待 ACK 匹配原始 INVITE）
            # - 其他方法 200 OK：与 DIALOGS 无关
            if "BYE" in cseq_header and call_id in DIALOGS:
                # BYE 200 OK：清理 dialog
                del DIALOGS[call_id]
                log.debug(f"[DIALOG-CLEANUP] Cleaned up dialog after BYE: {call_id}")
            # 清理其他追踪数据
            if call_id in PENDING_REQUESTS:
                del PENDING_REQUESTS[call_id]
            # ⚠️ 注意：CANCEL 的 200 OK 不应该清理 INVITE_BRANCHES
            # 因为后续的 487 响应的 ACK 需要复用 INVITE 的 branch
            # 只有 BYE 200 OK 才清理 INVITE_BRANCHES（呼叫已完全结束）
            if "BYE" in cseq_header:
                if call_id in INVITE_BRANCHES:
                    del INVITE_BRANCHES[call_id]
                    log.debug(f"[BRANCH-CLEANUP] Cleaned up INVITE branch after BYE 200 OK: {call_id}")
                # B2BUA: 清理媒体会话
                if ENABLE_MEDIA_RELAY:
                    media_relay = get_media_relay()
                    if media_relay:
                        media_relay.end_session(call_id)
            elif "CANCEL" in cseq_header:
                # CANCEL 200 OK：保留 INVITE_BRANCHES，等待 487 响应的 ACK
                log.debug(f"[BRANCH-KEEP] Keeping INVITE_BRANCHES for Call-ID {call_id} after CANCEL 200 OK (waiting for 487 ACK)")
    except OSError as e:
        # UDP发送错误 - 尝试备用地址
        log.error(f"UDP send failed to ({nhost}:{nport}): {e}")
        
        # 如果目标地址失败，尝试使用原始发送者地址
        if original_sender_addr and (nhost, nport) != original_sender_addr:
            try:
                transport.sendto(resp.to_bytes(), original_sender_addr)
                log.fwd(f"RESP {resp.start_line} (retry)", original_sender_addr)
            except Exception as e2:
                log.error(f"Retry also failed: {e2}")
    except Exception as e:
        log.error(f"forward resp failed: {e}")


def on_datagram(data: bytes, addr, transport):
    # 忽略 UA keepalive 空包
    if not data or data.strip() in (b"", b"\r\n", b"\r\n\r\n"):
        return
    
    # 安全检查：IP 黑名单和速率限制
    client_ip = addr[0]
    if _is_ip_blocked(client_ip):
        # 静默丢弃黑名单 IP 的请求（不回复，不记录详细日志，防止放大攻击）
        log.debug(f"[SECURITY] 丢弃黑名单 IP {client_ip} 的请求")
        return
    
    try:
        msg = parse(data)
        is_req = _is_request(msg.start_line)
        
        # 详细日志：显示 Call-ID, To tag, Via 头
        call_id = msg.get("call-id")
        to_val = msg.get("to")
        vias = msg.headers.get("via", [])
        
        if is_req:
            method = _method_of(msg)
            log.info(f"[RX] {addr} -> {msg.start_line} | Call-ID: {call_id} | To tag: {'YES' if 'tag=' in (to_val or '') else 'NO'} | Via: {len(vias)} hops")
        else:
            status = msg.start_line.split()[1] if len(msg.start_line.split()) > 1 else ""
            log.info(f"[RX] {addr} -> {msg.start_line} | Call-ID: {call_id} | Via: {len(vias)} hops")
        
        log.rx(addr, msg.start_line)
        
        # 打印完整的 SIP 消息内容
        try:
            msg_content = msg.to_bytes().decode('utf-8', errors='ignore')
            log.debug(f"[RX-FULL] {addr} -> Full SIP message:\n{msg_content}")
        except Exception as e:
            log.debug(f"[RX-FULL] Failed to decode message: {e}")
        if is_req:
            method = _method_of(msg)
            if method == "OPTIONS":
                resp = _make_response(msg, 200, "OK", extra_headers={
                    "accept": "application/sdp",
                    "supported": "100rel, timer, path"
                })
                # 打印完整的 SIP 响应内容（发送前）
                try:
                    resp_content = resp.to_bytes().decode('utf-8', errors='ignore')
                    log.debug(f"[TX-RESP-FULL] {addr} <- 200 OK (OPTIONS) Full SIP response:\n{resp_content}")
                except Exception as e:
                    log.debug(f"[TX-RESP-FULL] Failed to decode response: {e}")
                transport.sendto(resp.to_bytes(), addr)
                log.tx(addr, resp.start_line)
                # CDR: 记录 OPTIONS 请求（心跳/能力查询）
                cdr.record_options(
                    caller_uri=msg.get("from") or "",
                    callee_uri=msg.get("to") or "",
                    caller_addr=addr,
                    call_id=call_id or "",
                    user_agent=msg.get("user-agent") or "",
                    cseq=msg.get("cseq") or ""
                )
            elif method == "REGISTER":
                handle_register(msg, addr, transport)
            elif method in ("INVITE", "BYE", "CANCEL", "PRACK", "UPDATE", "REFER", "NOTIFY", "SUBSCRIBE", "MESSAGE", "ACK"):
                _forward_request(msg, addr, transport)
            else:
                resp = _make_response(msg, 405, "Method Not Allowed")
                # 打印完整的 SIP 响应内容（发送前）
                try:
                    resp_content = resp.to_bytes().decode('utf-8', errors='ignore')
                    log.debug(f"[TX-RESP-FULL] {addr} <- 405 Method Not Allowed Full SIP response:\n{resp_content}")
                except Exception as e:
                    log.debug(f"[TX-RESP-FULL] Failed to decode response: {e}")
                transport.sendto(resp.to_bytes(), addr)
                log.tx(addr, resp.start_line)
        else:
            # 响应：转发
            _forward_response(msg, addr, transport)

    except Exception as e:
        log.error(f"parse/send failed: {e}")

async def main():
    # 准备服务器全局状态
    server_globals = {
        'SERVER_IP': SERVER_IP,
        'SERVER_PORT': SERVER_PORT,
        'FORCE_LOCAL_ADDR': FORCE_LOCAL_ADDR,
        'REGISTRATIONS': REG_BINDINGS,  # 实际变量名是 REG_BINDINGS
        'DIALOGS': DIALOGS,
        'PENDING_REQUESTS': PENDING_REQUESTS,
        'INVITE_BRANCHES': INVITE_BRANCHES,
    }
    
    # 初始化RTPProxy媒体中继（B2BUA 模式）
    if ENABLE_MEDIA_RELAY:
        try:
            media_relay = init_media_relay(SERVER_IP, rtpproxy_udp=RTPPROXY_UDP)
            server_globals['MEDIA_RELAY'] = media_relay
            log.info(f"[B2BUA] RTPProxy媒体中继已初始化，服务器IP: {SERVER_IP}")
            log.info(f"[B2BUA] RTPProxy地址: {RTPPROXY_UDP[0]}:{RTPPROXY_UDP[1]} (UDP)")
            log.info(f"[B2BUA] 请确保RTPProxy已启动: rtpproxy -l {SERVER_IP} -s udp:{RTPPROXY_UDP[0]}:{RTPPROXY_UDP[1]} -F")
        except Exception as e:
            log.error(f"[B2BUA] RTPProxy媒体中继初始化失败: {e}")
            log.error(f"[B2BUA] 请确保RTPProxy已启动: rtpproxy -l {SERVER_IP} -s udp:{RTPPROXY_UDP[0]}:{RTPPROXY_UDP[1]} -F")
            server_globals['MEDIA_RELAY'] = None
    else:
        log.info("[B2BUA] 媒体中继已禁用（Proxy模式）")
        server_globals['MEDIA_RELAY'] = None
    
    # 初始化外呼管理器
    try:
        from autodialer_manager import AutoDialerManager
        # 添加 REG_BINDINGS 和 SERVER_IP 到 server_globals（用于清理残留注册和传递 IP）
        server_globals['REG_BINDINGS'] = REG_BINDINGS
        server_globals['SERVER_IP'] = SERVER_IP  # 传递服务器 IP 给外呼管理器
        dialer_mgr = AutoDialerManager(config_file="sip_client_config.json", server_globals=server_globals)
        server_globals['AUTO_DIALER_MANAGER'] = dialer_mgr
        log.info("外呼管理器已初始化")
    except Exception as e:
        log.warning(f"外呼管理器初始化失败: {e}")
        server_globals['AUTO_DIALER_MANAGER'] = None
    
    # 启动 MML 管理界面
    try:
        from web.mml_server import init_mml_interface
        init_mml_interface(port=8888, server_globals=server_globals)
    except Exception as e:
        log.warning(f"MML interface failed to start: {e}")

    # 初始化并启动 STUN 服务器（用于 NAT 穿透辅助）
    stun_server = None
    if ENABLE_STUN:
        try:
            stun_server = init_stun_server(
                host=STUN_BIND_IP,
                port=STUN_PORT,
                username=STUN_USERNAME,
                password=STUN_PASSWORD,
                realm=STUN_REALM
            )
            await stun_server.start()
            server_globals['STUN_SERVER'] = stun_server
            log.info(f"[STUN] STUN服务器已启动，监听地址: {STUN_BIND_IP}:{STUN_PORT}")
            log.info(f"[STUN] 认证信息: username={STUN_USERNAME}, password={STUN_PASSWORD}")
        except Exception as e:
            log.error(f"[STUN] STUN服务器启动失败: {e}")
            server_globals['STUN_SERVER'] = None
    else:
        log.info("[STUN] STUN服务器已禁用")
        server_globals['STUN_SERVER'] = None

    # 创建并启动 UDP 服务器
    # 绑定地址使用 0.0.0.0（监听所有接口），但对外宣告使用 SERVER_IP
    log.info(f"[CONFIG] UDP server binding to {UDP_BIND_IP}:{SERVER_PORT}, public IP: {SERVER_IP}")
    udp = UDPServer((UDP_BIND_IP, SERVER_PORT), on_datagram)
    await udp.start()
    # UDP server listening 日志已在 transport_udp.py 中输出，此处不再重复

    # 创建并启动定时器
    timers = create_timers(log)
    await timers.start(
        pending_requests=PENDING_REQUESTS,
        dialogs=DIALOGS,
        invite_branches=INVITE_BRANCHES,
        reg_bindings=REG_BINDINGS,
        transport=udp.transport,  # 传入UDP transport用于NAT保活
        server_ip=SERVER_IP,
        server_port=SERVER_PORT,
        cancel_forwarded=CANCEL_FORWARDED
    )
    log.info("[TIMERS] NAT keepalive enabled (interval: 25s)")
    
    try:
        # 等待服务器运行
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        log.info("Shutting down server...")
    finally:
        # 停止 STUN 服务器
        if stun_server:
            await stun_server.stop()
            log.info("[STUN] STUN服务器已停止")

        # 停止定时器
        await timers.stop()

if __name__ == "__main__":
    asyncio.run(main())


