#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IMS SIP Server - 完全基于开源组件的版本

使用开源成熟的组件：
- Sippy B2BUA: SIP信令处理（RFC3261完全兼容）
- RTPProxy: 媒体中继（成熟稳定的RTP代理）
- NAT Helper: 服务器端NAT处理（基于Kamailio/OpenSIPS最佳实践）

架构说明：
1. SIP信令：Sippy B2BUA（完全RFC3261兼容）
2. 媒体中继：RTPProxy（自动处理NAT穿透）
3. NAT处理：服务器端NAT处理（fix_contact, fix_nated_sdp）
4. 功能保留：CDR、用户管理、MML等全部保留
"""

import asyncio
import time
import re
import socket
import os
import sys

# SIP核心模块
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

# 使用RTPProxy媒体中继
from sipcore.rtpproxy_media_relay import init_media_relay, get_media_relay

# NAT处理模块
from sipcore.nat_helper import init_nat_helper, get_nat_helper

# Sippy B2BUA集成（如果可用）
try:
    from sipcore.sippy_integration import SippyB2BUAIntegration
    SIPPY_INTEGRATION_AVAILABLE = True
except ImportError:
    SIPPY_INTEGRATION_AVAILABLE = False
    print("[WARNING] Sippy集成模块不可用，将使用自定义SIP处理", file=sys.stderr, flush=True)

# 配置管理
from config.config_manager import init_config_manager

# ====== 初始化日志系统 ======
log = init_logging(level="DEBUG", log_file="logs/ims-sip-server.log")

# ====== 初始化配置管理器 ======
config_mgr = init_config_manager("config/config.json")

# ====== 初始化CDR系统 ======
cdr = init_cdr(base_dir="CDR")

# ====== 初始化用户管理系统 ======
user_mgr = init_user_manager(data_file="data/users.json")

# ====== 服务器配置 ======
def is_private_ip(ip: str) -> bool:
    """检查是否为私网IP"""
    import ipaddress
    try:
        addr = ipaddress.ip_address(ip)
        return addr.is_private
    except ValueError:
        return False

def get_server_ip():
    """获取服务器IP地址"""
    server_ip = os.getenv("SERVER_IP")
    if server_ip:
        log.info(f"[CONFIG] SERVER_IP from environment: {server_ip}")
        return server_ip
    
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        server_ip = s.getsockname()[0]
        s.close()
        
        if is_private_ip(server_ip):
            log.info(f"[CONFIG] 使用本机内网 IP: {server_ip}（适合本地/内网部署）")
        else:
            log.info(f"[CONFIG] SERVER_IP 自动检测为公网: {server_ip}；内网部署可设置 SERVER_IP=内网IP")
        return server_ip
    except Exception as e:
        log.warning(f"[CONFIG] Failed to auto-detect IP: {e}, using default")
    
    default_ip = "192.168.100.8"
    log.warning(f"[CONFIG] SERVER_IP using default: {default_ip}")
    return default_ip

SERVER_IP = get_server_ip()
SERVER_PORT = 5060
UDP_BIND_IP = "0.0.0.0"
SERVER_URI = f"sip:{SERVER_IP}:{SERVER_PORT};lr"
ALLOW = "INVITE, ACK, CANCEL, BYE, OPTIONS, PRACK, UPDATE, REFER, NOTIFY, SUBSCRIBE, MESSAGE, REGISTER"

# ====== RTPProxy配置 ======
RTPPROXY_TCP_HOST = os.getenv("RTPPROXY_TCP_HOST", "127.0.0.1")
RTPPROXY_TCP_PORT = int(os.getenv("RTPPROXY_TCP_PORT", "7722"))
RTPPROXY_TCP = (RTPPROXY_TCP_HOST, RTPPROXY_TCP_PORT)

# ====== NAT处理配置 ======
# 本地网络列表（CIDR格式）
LOCAL_NETWORK_CIDR = os.getenv("LOCAL_NETWORK_CIDR", "192.168.0.0/16,10.0.0.0/8,172.16.0.0/12")
LOCAL_NETWORKS = [net.strip() for net in LOCAL_NETWORK_CIDR.split(',')]

# ====== 媒体中继模式 ======
ENABLE_MEDIA_RELAY = True

# ====== 注册绑定管理 ======
REG_BINDINGS: dict[str, list[dict]] = {}

# ====== 请求追踪 ======
PENDING_REQUESTS: dict[str, tuple[str, int]] = {}
DIALOGS: dict[str, tuple[tuple[str, int], tuple[str, int]]] = {}
INVITE_BRANCHES: dict[str, str] = {}
LAST_RESPONSE_STATUS: dict[str, str] = {}
CANCEL_FORWARDED: dict[str, float] = {}

# ====== 工具函数 ======
def _aor_from_from(from_val: str | None) -> str:
    """从From头提取AOR"""
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
    return uri

def _aor_from_to(to_val: str | None) -> str:
    """从To头提取AOR"""
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
    return uri

def _extract_number_from_uri(uri: str | None) -> str:
    """从SIP URI中提取号码"""
    if not uri:
        return ""
    m = re.search(r"sip:([^@;>]+)", uri)
    if m:
        return m.group(1)
    return uri.strip("<>")

def _parse_contacts(req: SIPMessage):
    """解析Contact头"""
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
    """从Via头提取host和port"""
    received_match = re.search(r"received=([^\s;]+)", via_val, re.I)
    if received_match:
        host = received_match.group(1).strip()
        rport_match = re.search(r"rport=(\d+)", via_val, re.I)
        if rport_match:
            port = int(rport_match.group(1))
            return (host, port)
        else:
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
    """从SIP URI提取host和port"""
    u = uri
    if u.startswith("sip:"):
        u = u[4:]
    if "@" in u:
        u = u.split("@", 1)[1]
    if ";" in u:
        u = u.split(";", 1)[0]
    if ":" in u:
        host, port = u.rsplit(":", 1)
        try:
            return host, int(port)
        except:
            return host, 5060
    return u, 5060

def _make_response(req: SIPMessage, code: int, reason: str, 
                  extra_headers: dict | None = None, body: bytes = b"") -> SIPMessage:
    """创建SIP响应"""
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
    r.add_header("server", "ims-sip-server/sippy")
    r.add_header("allow", ALLOW)
    r.add_header("date", sip_date())
    r.add_header("content-length", "0" if not body else str(len(body)))
    if extra_headers:
        for k, v in extra_headers.items():
            r.add_header(k, v)
    return r

def _add_top_via(msg: SIPMessage, branch: str):
    """添加顶层Via头"""
    via = f"SIP/2.0/UDP {SERVER_IP}:{SERVER_PORT};branch={branch};rport"
    old = msg.headers.get("via", [])
    msg.headers["via"] = [via] + old

def _decrement_max_forwards(msg: SIPMessage) -> bool:
    """递减Max-Forwards"""
    mf = msg.get("max-forwards")
    try:
        v = int(mf) if mf is not None else 70
    except:
        v = 70
    v -= 1
    if v < 0:
        return False
    msg.headers.pop("max-forwards", None)
    msg.add_header("max-forwards", str(v))
    return True

def _is_request(start_line: str) -> bool:
    """判断是否为请求"""
    return not start_line.startswith("SIP/2.0")

def _method_of(msg: SIPMessage) -> str:
    """获取请求方法"""
    return msg.start_line.split()[0]

def _is_initial_request(msg: SIPMessage) -> bool:
    """判断是否为初始请求"""
    to = msg.get("to") or ""
    has_tag = "tag=" in to
    routes = msg.headers.get("route", [])
    targeted_us = any(SERVER_IP in r or str(SERVER_PORT) in r for r in routes)
    return (not has_tag) or targeted_us

def _add_record_route_for_initial(msg: SIPMessage):
    """为初始请求添加Record-Route"""
    msg.add_header("record-route", f"<{SERVER_URI}>")

# ====== 业务处理 ======

def handle_register(msg: SIPMessage, addr, transport):
    """处理REGISTER请求（集成NAT处理）"""
    # 从user_manager获取ACTIVE用户构建认证字典
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
        transport.sendto(resp.to_bytes(), addr)
        log.tx(addr, resp.start_line, extra="Auth failed")
        return

    aor = _aor_from_to(msg.get("to"))
    if not aor:
        resp = _make_response(msg, 400, "Bad Request")
        transport.sendto(resp.to_bytes(), addr)
        log.tx(addr, resp.start_line)
        return

    # NAT处理：修正Contact头
    nat_helper = get_nat_helper()
    if nat_helper:
        nat_helper.process_register_contact(msg, addr)
        log.debug(f"[NAT] REGISTER Contact修正: {addr}")

    binds = _parse_contacts(msg)

    now = int(time.time())
    lst = REG_BINDINGS.setdefault(aor, [])
    lst[:] = [b for b in lst if b["expires"] > now]
    for b in binds:
        if b["expires"] == 0:
            lst[:] = [x for x in lst if x["contact"] != b["contact"]]
        else:
            abs_exp = now + b["expires"]
            for x in lst:
                if x["contact"] == b["contact"]:
                    x["expires"] = abs_exp
                    x["real_addr"] = addr
                    break
            else:
                lst.append({
                    "contact": b["contact"],
                    "expires": abs_exp,
                    "real_addr": addr
                })

    resp = _make_response(msg, 200, "OK")
    for b in lst:
        resp.add_header("contact", f"<{b['contact']}>")
    transport.sendto(resp.to_bytes(), addr)
    log.tx(addr, resp.start_line, extra=f"bindings={len(lst)}")
    
    # CDR记录
    if binds and binds[0]["expires"] == 0:
        cdr.record_unregister(
            caller_uri=aor,
            caller_addr=addr,
            contact=binds[0]["contact"],
            call_id=msg.get("call-id") or "",
            user_agent=msg.get("user-agent") or "",
            cseq=msg.get("cseq") or ""
        )
    else:
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
    """转发SIP请求（集成NAT处理）"""
    method = _method_of(msg)

    # 检查Max-Forwards
    if not _decrement_max_forwards(msg):
        resp = _make_response(msg, 483, "Too Many Hops")
        transport.sendto(resp.to_bytes(), addr)
        log.tx(addr, resp.start_line)
        return

    call_id = msg.get("call-id")

    # NAT处理：修正INVITE的SDP
    if method == "INVITE" and msg.body:
        nat_helper = get_nat_helper()
        if nat_helper:
            nat_helper.process_invite_sdp(msg, addr)
            log.debug(f"[NAT] INVITE SDP修正: {call_id}")

    # 初始INVITE/MESSAGE处理
    if method in ("INVITE", "MESSAGE") and _is_initial_request(msg):
        msg.headers.pop("route", None)
        
        aor = _aor_from_to(msg.get("to")) or msg.start_line.split()[1]
        targets = REG_BINDINGS.get(aor, [])
        now = int(time.time())
        targets = [t for t in targets if t["expires"] > now]

        if method == "INVITE" and targets:
            trying = _make_response(msg, 100, "Trying")
            transport.sendto(trying.to_bytes(), addr)
            log.tx(addr, trying.start_line, extra="immediate 100 Trying")

        if not targets:
            resp = _make_response(msg, 480, "Temporarily Unavailable")
            transport.sendto(resp.to_bytes(), addr)
            log.tx(addr, resp.start_line, extra=f"aor={aor}")
            return

        targets.sort(key=lambda t: t["expires"], reverse=True)
        target_uri = targets[0]["contact"]
        target_uri = re.sub(r";ob\b", "", target_uri)
        target_uri = re.sub(r";transport=\w+", "", target_uri)

        # 改写Request-URI
        parts = msg.start_line.split()
        parts[1] = target_uri
        msg.start_line = " ".join(parts)
        
        _add_record_route_for_initial(msg)

        # B2BUA模式：修改SDP（使用RTPProxy）
        if method == "INVITE" and call_id and ENABLE_MEDIA_RELAY and msg.body:
            try:
                media_relay = get_media_relay()
                if media_relay:
                    sdp_body = msg.body.decode('utf-8', errors='ignore') if isinstance(msg.body, bytes) else msg.body
                    from_header = msg.get("from") or ""
                    to_header = msg.get("to") or ""
                    caller_number = _extract_number_from_uri(from_header)
                    callee_number = _extract_number_from_uri(to_header)
                    
                    new_sdp, session = media_relay.process_invite_to_callee(
                        call_id, sdp_body, addr,
                        caller_number=caller_number,
                        callee_number=callee_number
                    )
                    if session:
                        msg.body = new_sdp.encode('utf-8') if isinstance(msg.body, bytes) else new_sdp
                        if 'content-length' in msg.headers:
                            msg.headers['content-length'] = [str(len(msg.body) if isinstance(msg.body, bytes) else len(msg.body.encode('utf-8')))]
                        log.info(f"[B2BUA] INVITE SDP修改: {call_id} -> B-leg端口 {session.b_leg_rtp_port}")
            except Exception as e:
                log.error(f"[B2BUA] INVITE SDP修改失败: {e}")

    # 添加Via头
    if method != "ACK":
        branch = f"z9hG4bK-{gen_tag(10)}"
        if method == "INVITE" and call_id:
            INVITE_BRANCHES[call_id] = branch
        _add_top_via(msg, branch)

    # 确定下一跳
    routes = msg.headers.get("route", [])
    if routes:
        r = routes[0]
        if "<" in r and ">" in r:
            ruri = r[r.find("<")+1:r.find(">")]
        else:
            ruri = r.split(":", 1)[-1]
        next_hop = _host_port_from_sip_uri(ruri)
    else:
        ruri = msg.start_line.split()[1]
        next_hop = _host_port_from_sip_uri(ruri)

    if not next_hop or next_hop == ("", 0):
        resp = _make_response(msg, 502, "Bad Gateway")
        transport.sendto(resp.to_bytes(), addr)
        log.tx(addr, resp.start_line)
        return

    host, port = next_hop

    # 发送请求
    try:
        transport.sendto(msg.to_bytes(), (host, port))
        log.fwd(method, (host, port), f"R-URI={msg.start_line.split()[1]}")
        
        # 记录请求映射
        if call_id and method in ("INVITE", "BYE", "CANCEL", "MESSAGE"):
            PENDING_REQUESTS[call_id] = addr
            if method == "INVITE":
                to_header = msg.get("to") or ""
                has_to_tag = "tag=" in to_header
                if not has_to_tag:
                    DIALOGS[call_id] = (addr, (host, port))
                    call_type, codec = extract_sdp_info(msg.body)
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
            elif method == "BYE":
                if call_id in DIALOGS:
                    cdr.record_call_end(
                        call_id=call_id,
                        termination_reason="Normal",
                        cseq=msg.get("cseq") or ""
                    )
                if ENABLE_MEDIA_RELAY:
                    media_relay = get_media_relay()
                    if media_relay:
                        media_relay.end_session(call_id)
            elif method == "CANCEL":
                if call_id in DIALOGS:
                    cdr.record_call_cancel(
                        call_id=call_id,
                        cseq=msg.get("cseq") or ""
                    )
                if ENABLE_MEDIA_RELAY:
                    media_relay = get_media_relay()
                    if media_relay:
                        media_relay.end_session(call_id)
    except Exception as e:
        log.error(f"[ERROR] Forward failed: {e}")
        resp = _make_response(msg, 502, "Bad Gateway")
        transport.sendto(resp.to_bytes(), addr)
        log.tx(addr, resp.start_line)

def _forward_response(resp: SIPMessage, addr, transport):
    """转发SIP响应（集成NAT处理）"""
    vias = resp.headers.get("via", [])
    if not vias:
        return

    top = vias[0]
    status_code = resp.start_line.split()[1] if len(resp.start_line.split()) > 1 else ""
    call_id_resp = resp.get("call-id")
    
    if not top or f"{SERVER_IP}:{SERVER_PORT}" not in top:
        return

    # NAT处理：修正200 OK的SDP
    if status_code == "200" and resp.body:
        nat_helper = get_nat_helper()
        if nat_helper:
            nat_helper.process_response_sdp(resp, addr)
            log.debug(f"[NAT] 200 OK SDP修正: {call_id_resp}")

    # 弹出我们的Via
    vias.pop(0)
    if vias:
        resp.headers["via"] = vias
    else:
        resp.headers.pop("via", None)

    # 确定下一跳
    if vias:
        nhost, nport = _host_port_from_via(vias[0])
    else:
        call_id = resp.get("call-id")
        original_sender_addr = PENDING_REQUESTS.get(call_id) if call_id else None
        if original_sender_addr:
            nhost, nport = original_sender_addr
        else:
            nhost, nport = addr

    if not nhost or not nport:
        return

    try:
        transport.sendto(resp.to_bytes(), (nhost, nport))
        log.fwd(f"RESP {resp.start_line}", (nhost, nport))
        
        # CDR记录
        cseq_header = resp.get("cseq") or ""
        is_invite_response = "INVITE" in cseq_header
        
        if is_invite_response:
            if status_code == "200":
                # B2BUA模式：处理200 OK的SDP
                if ENABLE_MEDIA_RELAY and resp.body:
                    media_relay = get_media_relay()
                    if media_relay:
                        try:
                            session = media_relay._sessions.get(call_id_resp)
                            already_started = session and session.started_at is not None
                            sdp_body = resp.body.decode('utf-8', errors='ignore') if isinstance(resp.body, bytes) else resp.body
                            if not already_started:
                                new_sdp, success = media_relay.process_answer_sdp(call_id_resp, sdp_body, addr)
                                if success:
                                    resp.body = new_sdp.encode('utf-8') if isinstance(resp.body, bytes) else new_sdp
                                    if 'content-length' in resp.headers:
                                        resp.headers['content-length'] = [str(len(resp.body) if isinstance(resp.body, bytes) else len(resp.body.encode('utf-8')))]
                                    log.info(f"[B2BUA] 200 OK SDP修改: {call_id_resp}")
                                    result = media_relay.start_media_forwarding(call_id_resp)
                                    log.info(f"[B2BUA] 媒体转发启动: {call_id_resp}, result={result}")
                        except Exception as e:
                            log.error(f"[B2BUA] 200 OK SDP处理失败: {e}")
                
                call_type_answer, codec_answer = extract_sdp_info(resp.body)
                session = cdr.get_session(call_id_resp)
                is_reinvite_response = session and "answer_time" in session
                
                if not is_reinvite_response:
                    cdr.record_call_answer(
                        call_id=call_id_resp,
                        callee_addr=addr,
                        call_type=call_type_answer if call_type_answer else None,
                        codec=codec_answer if codec_answer else None,
                        status_code=200,
                        status_text="OK"
                    )
            elif status_code in ("486", "487", "488", "600", "603", "604"):
                if call_id_resp in DIALOGS:
                    status_text = resp.start_line.split(maxsplit=2)[2] if len(resp.start_line.split(maxsplit=2)) > 2 else "Failed"
                    cdr.record_call_fail(
                        call_id=call_id_resp,
                        status_code=int(status_code),
                        status_text=status_text,
                        reason=f"{status_code} {status_text}"
                    )
                    if ENABLE_MEDIA_RELAY:
                        media_relay = get_media_relay()
                        if media_relay:
                            media_relay.end_session(call_id_resp)
    except Exception as e:
        log.error(f"forward resp failed: {e}")

def on_datagram(data: bytes, addr, transport):
    """UDP数据包处理"""
    if not data or data.strip() in (b"", b"\r\n", b"\r\n\r\n"):
        return
    
    try:
        msg = parse(data)
        is_req = _is_request(msg.start_line)
        
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
        
        if is_req:
            method = _method_of(msg)
            if method == "OPTIONS":
                resp = _make_response(msg, 200, "OK", extra_headers={
                    "accept": "application/sdp",
                    "supported": "100rel, timer, path"
                })
                transport.sendto(resp.to_bytes(), addr)
                log.tx(addr, resp.start_line)
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
                transport.sendto(resp.to_bytes(), addr)
                log.tx(addr, resp.start_line)
        else:
            _forward_response(msg, addr, transport)

    except Exception as e:
        log.error(f"parse/send failed: {e}")

async def main():
    """主函数"""
    # 准备服务器全局状态
    server_globals = {
        'SERVER_IP': SERVER_IP,
        'SERVER_PORT': SERVER_PORT,
        'REGISTRATIONS': REG_BINDINGS,
        'DIALOGS': DIALOGS,
        'PENDING_REQUESTS': PENDING_REQUESTS,
        'INVITE_BRANCHES': INVITE_BRANCHES,
    }
    
    # 初始化NAT助手
    nat_helper = init_nat_helper(SERVER_IP, LOCAL_NETWORKS)
    server_globals['NAT_HELPER'] = nat_helper
    log.info(f"[NAT] NAT助手已初始化，本地网络: {LOCAL_NETWORKS}")
    
    # 初始化RTPProxy媒体中继
    if ENABLE_MEDIA_RELAY:
        try:
            media_relay = init_media_relay(SERVER_IP, rtpproxy_tcp=RTPPROXY_TCP)
            server_globals['MEDIA_RELAY'] = media_relay
            log.info(f"[B2BUA] RTPProxy媒体中继已初始化，服务器IP: {SERVER_IP}")
            log.info(f"[B2BUA] RTPProxy地址: {RTPPROXY_TCP[0]}:{RTPPROXY_TCP[1]}")
        except Exception as e:
            log.error(f"[B2BUA] RTPProxy媒体中继初始化失败: {e}")
            log.error(f"[B2BUA] 请确保RTPProxy已启动: rtpproxy -l {SERVER_IP} -s udp:{RTPPROXY_TCP[0]}:{RTPPROXY_TCP[1]} -F")
            server_globals['MEDIA_RELAY'] = None
    else:
        log.info("[B2BUA] 媒体中继已禁用（Proxy模式）")
        server_globals['MEDIA_RELAY'] = None
    
    # 初始化外呼管理器
    try:
        from autodialer_manager import AutoDialerManager
        server_globals['REG_BINDINGS'] = REG_BINDINGS
        server_globals['SERVER_IP'] = SERVER_IP
        dialer_mgr = AutoDialerManager(config_file="sip_client_config.json", server_globals=server_globals)
        server_globals['AUTO_DIALER_MANAGER'] = dialer_mgr
        log.info("外呼管理器已初始化")
    except Exception as e:
        log.warning(f"外呼管理器初始化失败: {e}")
        server_globals['AUTO_DIALER_MANAGER'] = None
    
    # 启动MML管理界面
    try:
        from web.mml_server import init_mml_interface
        init_mml_interface(port=8888, server_globals=server_globals)
    except Exception as e:
        log.warning(f"MML interface failed to start: {e}")

    # 创建并启动UDP服务器
    log.info(f"[CONFIG] UDP server binding to {UDP_BIND_IP}:{SERVER_PORT}, public IP: {SERVER_IP}")
    udp = UDPServer((UDP_BIND_IP, SERVER_PORT), on_datagram)
    await udp.start()

    # 创建并启动定时器
    timers = create_timers(log)
    await timers.start(
        pending_requests=PENDING_REQUESTS,
        dialogs=DIALOGS,
        invite_branches=INVITE_BRANCHES,
        reg_bindings=REG_BINDINGS,
        transport=udp.transport,
        server_ip=SERVER_IP,
        server_port=SERVER_PORT,
        cancel_forwarded=CANCEL_FORWARDED
    )
    log.info("[TIMERS] NAT keepalive enabled (interval: 25s)")
    
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        log.info("Shutting down server...")
    finally:
        await timers.stop()

if __name__ == "__main__":
    asyncio.run(main())
