#!/usr/bin/env python3
"""
独立的 SIP 客户端程序
用于自动外呼系统，完全独立于服务器代码
支持：注册、呼叫、RTP 媒体播放

使用纯 Python 标准库实现，无需外部依赖
"""

import socket
import time
import hashlib
import random
import re
import threading
import json
import os
from typing import Dict, Optional, Tuple, Callable, List
from dataclasses import dataclass
from pathlib import Path


# ====== 配置 ======
import os

def get_default_config():
    """获取默认配置，支持从环境变量读取"""
    # 从环境变量读取 SERVER_IP，如果没有则使用默认值
    server_ip = os.getenv("SERVER_IP", "192.168.100.8")
    local_ip = os.getenv("SERVER_IP", server_ip)  # local_ip 默认与 server_ip 相同
    
    return {
        "server_ip": server_ip,
        "server_port": 5060,
        "username": "0000",
        "password": "0000",
        "local_ip": local_ip,  # 与服务器同一台机器
        "local_port": 10000,
        "media_dir": "media",
        "media_file": "media/default.wav",
    }

DEFAULT_CONFIG = get_default_config()


# ====== 数据结构 ======
@dataclass
class SIPCall:
    """SIP 呼叫状态"""
    call_id: str
    from_tag: str
    to_tag: Optional[str] = None
    local_cseq: int = 1
    remote_cseq: int = 0
    dialog_established: bool = False
    sdp_offer: Optional[str] = None
    sdp_answer: Optional[str] = None
    remote_rtp_addr: Optional[Tuple[str, int]] = None  # (ip, port)
    local_rtp_port: Optional[int] = None
    route_header: Optional[str] = None  # Route 头（用于 in-dialog 请求）
    contact_header: Optional[str] = None  # Contact 头（用于 in-dialog 请求）
    callee: Optional[str] = None  # 被叫号码（用于 in-dialog 请求的 Request-URI）


@dataclass
class CallTask:
    """外呼任务"""
    callee: str
    media_file: str
    status: str = "PENDING"  # PENDING, DIALING, RINGING, ANSWERED, FAILED, COMPLETED
    error_message: Optional[str] = None
    created_at: float = 0.0
    started_at: Optional[float] = None
    answered_at: Optional[float] = None
    completed_at: Optional[float] = None


class SIPClient:
    """
    独立的 SIP 客户端
    基于 RFC 3261 标准实现
    """
    
    def __init__(self, username: str, password: str, server_ip: str,
                 server_port: int = 5060, local_ip: str = None, local_port: int = 10000,
                 sdp_ip: str = None, sip_domain: str = None, contact_ip: str = None):
        """
        初始化 SIP 客户端
        
        Args:
            username: SIP 用户名
            password: SIP 密码
            server_ip: 连接目标（发送 UDP 的地址）
            server_port: SIP 服务器端口（默认 5060）
            local_ip: 本地 IP 地址（如果为 None，则自动检测）
            local_port: 本地端口（默认 10000）
            sdp_ip: SDP 中使用的 IP 地址（用于 NAT 场景，默认为 server_ip）
            sip_domain: Request-URI/To/From 中的域（AOR 域）。不传则用 server_ip。内嵌时用 SERVER_IP 以便与 REG_BINDINGS 一致。
            contact_ip: Via/Contact 头中使用的 IP 地址（如果为 None，则使用 local_ip）
        """
        self.username = username
        self.password = password
        self.server_ip = server_ip
        self.server_port = server_port
        self.local_port = local_port
        self.sdp_ip = sdp_ip  # SDP 中使用的 IP 地址
        self.sip_domain = sip_domain if sip_domain else server_ip  # AOR 域，用于 INVITE/To/From 等查找
        
        # 绑定地址：用于 socket.bind()
        if local_ip:
            self.local_ip = local_ip
        else:
            self.local_ip = self._get_local_ip()
        # Via/Contact 中使用的地址：如果指定了contact_ip则使用，否则使用local_ip
        if contact_ip:
            self.contact_ip = contact_ip
        elif not self.local_ip or self.local_ip in ("", "0.0.0.0"):
            self.contact_ip = "127.0.0.1"
        else:
            self.contact_ip = self.local_ip
        
        # Socket 延迟创建（在需要时创建）
        self.sock = None
        
        # 状态
        self.registered = False
        self.current_call: Optional[SIPCall] = None
        self.branch_counter = 0
        
        # 响应回调
        self.response_callbacks: Dict[str, Callable] = {}
        
        # 监听线程
        self._listener_thread = None
        self._running = False
        self._lock = threading.Lock()
    
    def _get_local_ip(self) -> str:
        """自动检测本地 IP 地址"""
        try:
            # 连接到外部地址（不实际发送数据）
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception:
            return "127.0.0.1"
    
    def _gen_branch(self) -> str:
        """生成 Via branch（RFC 3261）"""
        self.branch_counter += 1
        return f"z9hG4bK-{random.randint(100000, 999999)}-{self.branch_counter}"
    
    def _gen_tag(self) -> str:
        """生成 SIP tag"""
        return f"{random.randint(100000, 999999)}"
    
    def _gen_call_id(self) -> str:
        """生成 Call-ID"""
        return f"{random.randint(100000, 999999)}-{int(time.time())}"
    
    def _compute_response(self, username: str, realm: str, password: str, 
                         uri: str, method: str, nonce: str, 
                         qop: str = "", cnonce: str = "", nc: str = "00000001") -> str:
        """计算 Digest 认证响应（RFC 2617）"""
        ha1 = hashlib.md5(f"{username}:{realm}:{password}".encode()).hexdigest()
        ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
        
        if qop:
            # 带 qop 的认证（RFC 2617）
            response = hashlib.md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}".encode()).hexdigest()
        else:
            # 不带 qop 的认证（RFC 2069）
            response = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
        
        return response
    
    def _parse_response(self, data: bytes) -> Dict:
        """解析 SIP 响应"""
        try:
            text = data.decode('utf-8')
            lines = text.split('\r\n')
            
            # 解析状态行
            status_line = lines[0]
            parts = status_line.split(maxsplit=2)
            status_code = int(parts[1]) if len(parts) > 1 else 0
            status_text = parts[2] if len(parts) > 2 else ""
            
            # 解析头部
            headers = {}
            body_start = False
            body_lines = []
            
            for i, line in enumerate(lines[1:], 1):
                if body_start:
                    body_lines.append(line)
                elif line == "":
                    body_start = True
                elif ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip().lower()
                    value = value.strip()
                    headers[key] = value
            
            body = '\r\n'.join(body_lines) if body_lines else ""
            
            return {
                'status_code': status_code,
                'status_text': status_text,
                'headers': headers,
                'body': body,
                'raw': text
            }
        except Exception as e:
            return {'error': str(e), 'raw': data.decode('utf-8', errors='ignore')}
    
    def _parse_request(self, data: bytes) -> Dict:
        """解析 SIP 请求"""
        try:
            text = data.decode('utf-8')
            lines = text.split('\r\n')
            
            # 解析请求行：METHOD Request-URI SIP/2.0
            request_line = lines[0]
            parts = request_line.split(maxsplit=2)
            method = parts[0] if len(parts) > 0 else ""
            request_uri = parts[1] if len(parts) > 1 else ""
            
            # 解析头部（处理多行头部，如 Via）
            headers = {}
            body_start = False
            body_lines = []
            current_header = None
            current_value = None
            
            for i, line in enumerate(lines[1:], 1):
                if body_start:
                    body_lines.append(line)
                elif line == "":
                    body_start = True
                    # 保存最后一个头部
                    if current_header and current_value:
                        headers[current_header] = current_value
                        current_header = None
                        current_value = None
                elif line.startswith(' ') or line.startswith('\t'):
                    # 这是多行头部的继续行（RFC 3261）
                    if current_header and current_value:
                        current_value += ' ' + line.strip()
                elif ':' in line:
                    # 保存之前的头部
                    if current_header and current_value:
                        headers[current_header] = current_value
                    
                    # 解析新的头部
                    key, value = line.split(':', 1)
                    key = key.strip().lower()
                    value = value.strip()
                    
                    # 对于某些头部（如 Via），可能需要合并多个值
                    if key in headers:
                        # 如果头部已存在，追加（如多个 Via 头）
                        headers[key] = headers[key] + ', ' + value
                    else:
                        current_header = key
                        current_value = value
            
            # 保存最后一个头部（如果还有未保存的）
            if current_header and current_value and not body_start:
                headers[current_header] = current_value
            
            body = '\r\n'.join(body_lines) if body_lines else ""
            
            return {
                'method': method,
                'request_uri': request_uri,
                'headers': headers,
                'body': body,
                'raw': text
            }
        except Exception as e:
            return {'error': str(e), 'raw': data.decode('utf-8', errors='ignore')}
    
    def _handle_request(self, data: bytes, addr: Tuple[str, int]):
        """处理收到的 SIP 请求（如 BYE）"""
        try:
            req = self._parse_request(data)
            method = req.get('method', '')
            call_id = req.get('headers', {}).get('call-id', '')
            
            if not method:
                # 可能是格式错误，不处理
                return
            
            if method == 'BYE':
                # 处理 BYE 请求：发送 200 OK
                if self.current_call and call_id == self.current_call.call_id:
                    print(f"[SIP] 收到 BYE 请求，准备响应 200 OK (来源: {addr})")
                    self._send_bye_response(req, addr)
                else:
                    print(f"[SIP] 警告: 收到未匹配的 BYE 请求 (Call-ID: {call_id}, 当前: {self.current_call.call_id if self.current_call else 'None'})")
            # 可以处理其他请求（如 INVITE, ACK 等）
            elif method in ('INVITE', 'ACK', 'CANCEL', 'MESSAGE', 'OPTIONS', 'REGISTER'):
                print(f"[SIP] 收到未处理的请求: {method} (Call-ID: {call_id})")
            else:
                print(f"[SIP] 收到未知请求: {method}")
        except Exception as e:
            print(f"[SIP] 处理请求失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _send_bye_response(self, req: Dict, addr: Tuple[str, int]):
        """发送 BYE 请求的 200 OK 响应"""
        if not self.current_call:
            return
        
        call_id = req.get('headers', {}).get('call-id', '')
        
        # 防止重复响应（检查是否已经响应过这个 BYE）
        if not hasattr(self.current_call, '_bye_responded'):
            self.current_call._bye_responded = set()
        
        cseq_header = req.get('headers', {}).get('cseq', '')
        cseq_key = f"{call_id}:{cseq_header}"
        
        if cseq_key in self.current_call._bye_responded:
            print(f"[SIP] 警告: 已响应过此 BYE 请求 (CSeq: {cseq_header})，忽略重复")
            return
        
        from_header = req.get('headers', {}).get('from', '')
        to_header = req.get('headers', {}).get('to', '')
        via_header = req.get('headers', {}).get('via', '')
        
        # 提取 From tag（用于 To 头）
        from_tag_match = re.search(r'tag=([^;>\s]+)', from_header)
        from_tag = from_tag_match.group(1) if from_tag_match else ""
        
        # 提取 To tag（用于 From 头）
        to_tag_match = re.search(r'tag=([^;>\s]+)', to_header)
        to_tag = to_tag_match.group(1) if to_tag_match else ""
        
        # 解析 Via 头（可能有多个，取第一个/顶层 Via）
        # RFC 3261: 响应必须通过顶层 Via 头路由回去
        # 服务器转发 BYE 时会添加服务器的 Via 头到顶层（第一个位置）
        via_sent_by = ""
        if via_header:
            # 打印所有 Via 头以便调试
            print(f"[SIP] 收到的 Via 头（原始）: {via_header[:200]}...")
            
            # Via 头可能有多个（用逗号分隔）
            # 取第一个 Via 头（顶层 Via），这是服务器添加的 Via，响应应该发回这里
            via_parts = [part.strip() for part in via_header.split(',')]
            print(f"[SIP] 解析到 {len(via_parts)} 个 Via 头")
            
            if via_parts:
                # 第一个 Via 应该是服务器的 Via（顶层）
                first_via = via_parts[0]
                print(f"[SIP] 顶层 Via: {first_via[:150]}...")
                
                # 解析 Via sent-by（格式：SIP/2.0/UDP host:port;branch=xxx）
                via_match = re.search(r'SIP/2\.0/UDP\s+([^;]+)', first_via)
                if via_match:
                    via_sent_by = via_match.group(1).strip()
                    print(f"[SIP] 提取 sent-by: {via_sent_by}")
                    
                    # 检查是否是服务器地址
                    if ':' in via_sent_by:
                        host, port_str = via_sent_by.rsplit(':', 1)
                        if host == self.server_ip:
                            print(f"[SIP] ✓ Via 头指向服务器地址: {via_sent_by}")
                        else:
                            print(f"[SIP] ⚠ Via 头指向非服务器地址: {via_sent_by} (期望: {self.server_ip})")
                    else:
                        if via_sent_by == self.server_ip:
                            print(f"[SIP] ✓ Via 头指向服务器地址: {via_sent_by}")
                        else:
                            print(f"[SIP] ⚠ Via 头指向非服务器地址: {via_sent_by} (期望: {self.server_ip})")
                else:
                    print(f"[SIP] 警告: 无法解析顶层 Via 头: {first_via[:100]}...")
            else:
                # 没有逗号分隔，可能是单个 Via
                first_via = via_header.strip()
                print(f"[SIP] 单个 Via 头: {first_via[:150]}...")
                
                via_match = re.search(r'SIP/2\.0/UDP\s+([^;]+)', first_via)
                if via_match:
                    via_sent_by = via_match.group(1).strip()
                    print(f"[SIP] 提取 sent-by: {via_sent_by}")
        
        # 如果无法从 Via 头解析地址，或 Via 头指向非服务器地址，使用请求来源地址
        # 请求来源地址（addr）应该是服务器实际发送的地址，最可靠
        if not via_sent_by or (via_sent_by and ':' in via_sent_by and via_sent_by.split(':')[0] != self.server_ip):
            if addr[0] == self.server_ip:
                # 来源地址是服务器地址，直接使用
                via_sent_by = f"{addr[0]}:{addr[1]}"
                print(f"[SIP] 使用请求来源地址（服务器）: {via_sent_by}")
            else:
                # 如果来源地址也不是服务器，使用服务器配置的地址
                via_sent_by = f"{self.server_ip}:{self.server_port}"
                print(f"[SIP] 警告: 使用服务器配置地址: {via_sent_by}")
        
        # 构建 200 OK 响应（按 SIP 标准顺序，确保格式正确）
        response_lines = []
        
        # 状态行
        response_lines.append("SIP/2.0 200 OK")
        
        # Via 头（必须保留，用于响应路由）
        if via_header:
            response_lines.append(f"Via: {via_header}")
        
        # From 头（必须保留原样）
        if from_header:
            response_lines.append(f"From: {from_header}")
        
        # To 头（必须保留原样）
        if to_header:
            response_lines.append(f"To: {to_header}")
        
        # Call-ID 头
        response_lines.append(f"Call-ID: {call_id}")
        
        # CSeq 头（必须保留原样）
        if cseq_header:
            response_lines.append(f"CSeq: {cseq_header}")
        
        # Content-Length 头
        response_lines.append("Content-Length: 0")
        
        # 空行（分隔头部和消息体）
        response_lines.append("")
        
        # 确保格式正确：用 \r\n 分隔，最后必须有 \r\n
        response_msg = '\r\n'.join(response_lines)
        
        # 调试：打印响应消息（截断）
        if len(response_msg) > 200:
            debug_msg = response_msg[:200] + "..."
        else:
            debug_msg = response_msg
        print(f"[SIP] BYE 200 OK 响应内容:\n{debug_msg}")
        
        # 发送响应
        try:
            # BYE 响应路由策略（RFC 3261）：
            # 1. 优先使用请求来源地址（addr），因为这是服务器实际发送的地址
            # 2. 如果来源地址是服务器地址，直接使用
            # 3. 如果 Via 头解析成功且指向服务器地址，也可以使用
            # 4. 否则使用服务器配置的地址
            
            # 首先检查请求来源地址是否是服务器地址
            if addr[0] == self.server_ip:
                # 来源地址是服务器地址，优先使用
                target_addr = addr
                print(f"[SIP] 使用请求来源地址（服务器）: {target_addr}")
            elif via_sent_by:
                # 尝试使用 Via 头解析的地址
                # 解析 Via sent-by（格式：host:port）
                if ':' in via_sent_by:
                    host, port = via_sent_by.rsplit(':', 1)
                    try:
                        port = int(port)
                    except ValueError:
                        port = 5060
                else:
                    host = via_sent_by
                    port = 5060
                
                # 检查解析出的地址是否是服务器地址
                if host == self.server_ip:
                    target_addr = (host, port)
                    print(f"[SIP] 通过 Via 头路由（服务器地址）: {via_sent_by} -> {target_addr}")
                else:
                    # Via 头指向的不是服务器地址（可能是被叫地址），使用来源地址
                    target_addr = addr
                    print(f"[SIP] 警告: Via 头指向非服务器地址 ({via_sent_by})，使用请求来源地址: {target_addr}")
            else:
                # 如果 Via 头解析失败，使用服务器配置的地址
                target_addr = (self.server_ip, self.server_port)
                print(f"[SIP] 警告: Via 头解析失败，使用服务器配置地址: {target_addr}")
            
            # 发送响应（确保使用 UTF-8 编码）
            response_bytes = response_msg.encode('utf-8')
            self.sock.sendto(response_bytes, target_addr)
            print(f"[SIP] ✓ BYE 200 OK 已发送到 {target_addr} ({len(response_bytes)} 字节)")
            
            # 标记已响应（防止重复）
            self.current_call._bye_responded.add(cseq_key)
            
            # 清除 dialog 状态
            if self.current_call:
                self.current_call.dialog_established = False
                print(f"[SIP] 呼叫已正常挂断（收到 BYE 请求）")
        except Exception as e:
            print(f"[SIP] 错误: 发送 BYE 响应失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _ensure_socket(self):
        """确保 socket 已创建并绑定"""
        if self.sock is None:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind((self.local_ip, self.local_port))
            self.sock.settimeout(5.0)
            print(f"[SIP] Socket 已绑定: {self.local_ip}:{self.local_port}")
    
    def register(self, expires: int = 3600) -> bool:
        """
        注册到 SIP 服务器
        
        Args:
            expires: 注册过期时间（秒）
        
        Returns:
            注册是否成功
        """
        print(f"[SIP] 正在注册用户 {self.username}...")
        
        # 创建临时 socket 用于注册
        temp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        try:
            # 尝试绑定到指定端口（如果端口被占用，使用临时端口）
            try:
                temp_sock.bind((self.local_ip, self.local_port))
            except OSError as e:
                if e.errno == 48 or e.errno == 98:  # Address already in use (macOS=48, Linux=98)
                    # 端口被占用，使用临时端口（让系统自动分配）
                    temp_sock.bind((self.local_ip, 0))
                    actual_port = temp_sock.getsockname()[1]
                    print(f"[SIP] 端口 {self.local_port} 被占用，使用临时端口: {actual_port}")
                    self.local_port = actual_port  # 更新本地端口
                else:
                    raise
            
            temp_sock.settimeout(20.0)  # 20 秒超时
            
            call_id = self._gen_call_id()
            from_tag = self._gen_tag()
            branch = self._gen_branch()
            
            # 第一次 REGISTER（无认证）
            register_msg = (
                f"REGISTER sip:{self.server_ip} SIP/2.0\r\n"
                f"Via: SIP/2.0/UDP {self.contact_ip}:{self.local_port};branch={branch}\r\n"
                f"From: <sip:{self.username}@{self.sip_domain}>;tag={from_tag}\r\n"
                f"To: <sip:{self.username}@{self.sip_domain}>\r\n"
                f"Call-ID: {call_id}\r\n"
                f"CSeq: 1 REGISTER\r\n"
                f"Contact: <sip:{self.username}@{self.contact_ip}:{self.local_port}>\r\n"
                f"Expires: {expires}\r\n"
                f"Max-Forwards: 70\r\n"
                f"Content-Length: 0\r\n"
                f"\r\n"
            )
            
            # 发送 REGISTER
            temp_sock.sendto(register_msg.encode('utf-8'), (self.server_ip, self.server_port))
            print(f"[SIP] REGISTER 已发送，等待响应...")
            
            # 接收响应
            try:
                data, addr = temp_sock.recvfrom(4096)
            except socket.timeout:
                print(f"[ERROR] 等待响应超时（20秒内未收到）")
                return False
            
            resp = self._parse_response(data)
            status_code = resp.get('status_code', 0)
            
            if status_code == 401:
                # 需要认证
                auth_header = resp['headers'].get('www-authenticate', '')
                
                realm_match = re.search(r'realm="([^"]+)"', auth_header)
                nonce_match = re.search(r'nonce="([^"]+)"', auth_header)
                qop_match = re.search(r'qop="([^"]+)"', auth_header)
                
                if not realm_match or not nonce_match:
                    print(f"[ERROR] 无法解析认证头")
                    return False
                
                realm = realm_match.group(1)
                nonce = nonce_match.group(1)
                qop = qop_match.group(1) if qop_match else ""
                
                # 第二次 REGISTER（带认证，Digest uri 须与 Request-URI 一致）
                uri = f"sip:{self.server_ip}"
                
                if qop:
                    cnonce = f"{random.randint(100000, 999999)}"
                    nc = "00000001"
                    response = self._compute_response(self.username, realm, self.password, 
                                                      uri, "REGISTER", nonce, qop, cnonce, nc)
                    auth_value = f'Digest username="{self.username}", realm="{realm}", nonce="{nonce}", uri="{uri}", response="{response}", qop={qop}, nc={nc}, cnonce="{cnonce}"'
                else:
                    response = self._compute_response(self.username, realm, self.password, 
                                                      uri, "REGISTER", nonce)
                    auth_value = f'Digest username="{self.username}", realm="{realm}", nonce="{nonce}", uri="{uri}", response="{response}"'
                
                register_msg = (
                    f"REGISTER sip:{self.server_ip} SIP/2.0\r\n"
                    f"Via: SIP/2.0/UDP {self.contact_ip}:{self.local_port};branch={self._gen_branch()}\r\n"
                    f"From: <sip:{self.username}@{self.sip_domain}>;tag={from_tag}\r\n"
                    f"To: <sip:{self.username}@{self.sip_domain}>\r\n"
                    f"Call-ID: {call_id}\r\n"
                    f"CSeq: 2 REGISTER\r\n"
                    f"Authorization: {auth_value}\r\n"
                    f"Contact: <sip:{self.username}@{self.contact_ip}:{self.local_port}>\r\n"
                    f"Expires: {expires}\r\n"
                    f"Max-Forwards: 70\r\n"
                    f"Content-Length: 0\r\n"
                    f"\r\n"
                )
                
                # 发送带认证的 REGISTER
                temp_sock.sendto(register_msg.encode('utf-8'), (self.server_ip, self.server_port))
                print(f"[SIP] 带认证的 REGISTER 已发送，等待最终响应...")
                
                # 接收最终响应
                try:
                    data, addr = temp_sock.recvfrom(4096)
                except socket.timeout:
                    print(f"[ERROR] 等待最终响应超时")
                    return False
                
                resp = self._parse_response(data)
                final_status = resp.get('status_code', 0)
                
                if final_status == 200:
                    self.registered = True
                    print(f"[SIP] ✓ 注册成功！")
                    return True
                else:
                    print(f"[ERROR] 注册失败，状态码: {final_status}")
                    return False
            
            elif status_code == 200:
                self.registered = True
                print(f"[SIP] ✓ 注册成功（无需认证）！")
                return True
            else:
                print(f"[ERROR] 注册失败，状态码: {status_code}")
                return False
                
        except Exception as e:
            print(f"[ERROR] 注册异常: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            temp_sock.close()
    
    def start_listener(self):
        """启动响应监听线程"""
        if self._running:
            return
        
        self._ensure_socket()
        self._running = True
        self._listener_thread = threading.Thread(target=self._listen_responses, daemon=True)
        self._listener_thread.start()
        print(f"[SIP] 响应监听线程已启动")
    
    def stop_listener(self):
        """停止响应监听线程"""
        if not self._running:
            return
        
        self._running = False
        
        # 尝试唤醒 recvfrom
        if self.sock:
            try:
                temp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                temp_sock.sendto(b"STOP", (self.contact_ip, self.local_port))
                temp_sock.close()
            except:
                pass
        
        if self._listener_thread:
            self._listener_thread.join(timeout=2.0)
        
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
        
        print(f"[SIP] 响应监听线程已停止")
    
    def _listen_responses(self):
        """监听 SIP 响应和请求（后台线程）"""
        while self._running:
            try:
                if self.sock is None:
                    break
                
                data, addr = self.sock.recvfrom(4096)
                
                # 忽略 STOP 消息
                if data == b"STOP":
                    continue
                
                # 判断是请求还是响应（响应以 "SIP/2.0" 开头）
                text = data.decode('utf-8', errors='ignore')
                first_line = text.split('\r\n')[0] if text else ""
                
                if first_line.startswith('SIP/2.0'):
                    # 这是响应
                    resp = self._parse_response(data)
                    resp['_source_addr'] = addr  # 保存源地址（用于 NAT 修正）
                    call_id = resp.get('headers', {}).get('call-id', '')
                else:
                    # 这是请求（如 BYE）
                    self._handle_request(data, addr)
                    continue
                
                call_id = resp.get('headers', {}).get('call-id', '')
                
                # 忽略 REGISTER 响应（由 register 方法处理）
                cseq_header = resp.get('headers', {}).get('cseq', '')
                if 'REGISTER' in cseq_header.upper():
                    continue
                
                # 处理 INVITE 和 BYE 响应
                if call_id and self.current_call and call_id == self.current_call.call_id:
                    status_code = resp.get('status_code', 0)
                    cseq_header = resp.get('headers', {}).get('cseq', '').upper()
                    
                    # 处理 BYE 响应（200 OK）
                    # 注意：BYE 响应的 CSeq 头包含 BYE 方法名
                    if status_code == 200 and ('BYE' in cseq_header or self.current_call.local_cseq > 1):
                        # 检查是否是 BYE 响应：CSeq 包含 BYE 或 local_cseq > 1（说明发送过 BYE）
                        cseq_num = cseq_header.split()[0] if cseq_header else ""
                        if 'BYE' in cseq_header or (cseq_num.isdigit() and int(cseq_num) == self.current_call.local_cseq):
                            print(f"[SIP] ✓ BYE 响应: {status_code} {resp.get('status_text', '')} (CSeq: {cseq_header})")
                            if self.current_call:
                                self.current_call.dialog_established = False
                                print(f"[SIP] 呼叫已正常挂断")
                                continue  # 跳过后续的 INVITE 处理
                    # 处理 INVITE 响应（包括 100/180/183/200）
                    elif 'INVITE' in cseq_header and status_code in (100, 180, 183, 200):
                        self.handle_invite_response(resp)
                    # 如果状态码是 200 但没有明确的 CSeq 或 CSeq 为空，也尝试处理（可能是 INVITE 200 OK）
                    elif status_code == 200 and (not cseq_header or 'INVITE' not in cseq_header and 'BYE' not in cseq_header):
                        print(f"[SIP] 警告: 收到 200 OK 但 CSeq 不明确，尝试处理为 INVITE 响应 (CSeq: {cseq_header})")
                        self.handle_invite_response(resp)
                
                # 触发回调（只在第一次收到 200 OK 时触发，避免重复）
                if call_id and call_id in self.response_callbacks:
                    status_code = resp.get('status_code', 0)
                    # 只在收到 200 OK 且对话已建立时触发回调，然后清除回调避免重复
                    if status_code == 200:
                        if self.current_call and self.current_call.dialog_established:
                            callback = self.response_callbacks.pop(call_id)  # 弹出并移除，防止重复调用
                            try:
                                callback(resp)
                            except Exception as e:
                                print(f"[ERROR] 回调执行失败: {e}")
                    elif status_code >= 400:
                        # 错误响应也清除回调
                        if call_id in self.response_callbacks:
                            self.response_callbacks.pop(call_id)
                    
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    print(f"[ERROR] 监听响应异常: {e}")
                time.sleep(0.1)
    
    def create_sdp_offer(self, local_rtp_port: int, codec: str = "PCMU") -> str:
        """创建 SDP Offer（RFC 4566）"""
        # 使用 sdp_ip（外部可路由地址）或 local_ip
        # sdp_ip 用于 NAT 场景，让对方知道该往哪个公网地址发送 RTP
        sdp_ip = getattr(self, 'sdp_ip', None) or self.contact_ip
        # 如果 sdp_ip 是 0.0.0.0，使用 server_ip
        if sdp_ip == "0.0.0.0":
            sdp_ip = self.server_ip
        
        sdp = (
            f"v=0\r\n"
            f"o=- {int(time.time())} {int(time.time())} IN IP4 {sdp_ip}\r\n"
            f"s=Auto Dialer Call\r\n"
            f"c=IN IP4 {sdp_ip}\r\n"
            f"t=0 0\r\n"
            f"m=audio {local_rtp_port} RTP/AVP 0\r\n"
            f"a=rtpmap:0 {codec}/8000\r\n"
            f"a=sendrecv\r\n"
        )
        return sdp
    
    def _is_private_ip(self, ip: str) -> bool:
        """检查是否是内网地址（RFC 1918）"""
        import ipaddress
        try:
            addr = ipaddress.ip_address(ip)
            # 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
            return addr.is_private
        except:
            return False
    
    def parse_sdp_answer(self, sdp_body: str, actual_remote_addr: Optional[Tuple[str, int]] = None) -> Optional[Tuple[str, int]]:
        """解析 SDP Answer，提取 RTP 地址和端口
        
        Args:
            sdp_body: SDP 内容
            actual_remote_addr: 实际的信令地址（用于 NAT 修正）
        """
        try:
            lines = sdp_body.split('\r\n')
            
            # 查找 c= 行
            connection_ip = None
            for line in lines:
                if line.startswith('c=IN IP4 '):
                    connection_ip = line.split()[2]
                    break
            
            # 查找 m=audio 行
            rtp_port = None
            for line in lines:
                if line.startswith('m=audio '):
                    parts = line.split()
                    if len(parts) >= 2:
                        rtp_port = int(parts[1])
                    break
            
            if connection_ip and rtp_port:
                # NAT 修正：仅当响应直接来自对端（非环回）时，用信令源替换 SDP 内网地址。
                # 外呼场景下 200 OK 由服务器转发，信令源为 127.0.0.1，不能替换，否则 RTP 发错导致无声音。
                use_signal_addr = (
                    actual_remote_addr
                    and actual_remote_addr[0] not in ("127.0.0.1", "::1")
                    and self._is_private_ip(connection_ip)
                )
                if use_signal_addr:
                    print(f"[RTP] NAT 修正: SDP 中的 {connection_ip} 是内网地址，使用信令地址 {actual_remote_addr[0]}")
                    connection_ip = actual_remote_addr[0]
                
                return (connection_ip, rtp_port)
            
            return None
        except Exception as e:
            print(f"[ERROR] SDP 解析失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def invite(self, callee: str, local_rtp_port: int, codec: str = "PCMU", 
               timeout: float = 30.0, on_response: Optional[Callable] = None) -> bool:
        """
        发起 INVITE 呼叫
        
        Args:
            callee: 被叫用户号码
            local_rtp_port: 本地 RTP 端口
            codec: 音频编解码器（PCMU/PCMA）
            timeout: 超时时间（秒）
            on_response: 响应回调函数
        
        Returns:
            呼叫是否成功建立
        """
        if not self.registered:
            print(f"[ERROR] 未注册，无法发起呼叫")
            return False
        
        self._ensure_socket()
        
        call_id = self._gen_call_id()
        from_tag = self._gen_tag()
        branch = self._gen_branch()
        
        # 创建 SDP Offer
        sdp_offer = self.create_sdp_offer(local_rtp_port, codec)
        
        # 创建 INVITE 请求
        invite_msg = (
            f"INVITE sip:{callee}@{self.sip_domain} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {self.contact_ip}:{self.local_port};branch={branch}\r\n"
            f"From: <sip:{self.username}@{self.sip_domain}>;tag={from_tag}\r\n"
            f"To: <sip:{callee}@{self.sip_domain}>\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: 1 INVITE\r\n"
            f"Contact: <sip:{self.username}@{self.contact_ip}:{self.local_port}>\r\n"
            f"Content-Type: application/sdp\r\n"
            f"Content-Length: {len(sdp_offer.encode('utf-8'))}\r\n"
            f"Max-Forwards: 70\r\n"
            f"\r\n"
            f"{sdp_offer}"
        )
        
        # 保存呼叫状态
        self.current_call = SIPCall(
            call_id=call_id,
            from_tag=from_tag,
            sdp_offer=sdp_offer,
            local_rtp_port=local_rtp_port,
            callee=callee  # 保存被叫号码
        )
        
        # 注册响应回调
        if on_response:
            self.response_callbacks[call_id] = on_response
        
        # 发送 INVITE
        self.sock.sendto(invite_msg.encode('utf-8'), (self.server_ip, self.server_port))
        print(f"[SIP] INVITE 已发送到 {callee}")
        
        # 等待响应（由监听线程处理）
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.current_call and self.current_call.dialog_established:
                return True
            if self.current_call and self.current_call.to_tag and self.current_call.remote_rtp_addr:
                return True
            time.sleep(0.1)
        
        return False
    
    def handle_invite_response(self, resp: Dict):
        """处理 INVITE 响应"""
        if not self.current_call:
            return
        
        status_code = resp.get('status_code', 0)
        call_id = resp.get('headers', {}).get('call-id', '')
        
        if call_id != self.current_call.call_id:
            return
        
        # 防止重复处理（如果已经处理过，直接返回）
        if status_code == 200 and self.current_call.dialog_established:
            return
        
        if status_code == 180 or status_code == 183:
            print(f"[SIP] {status_code} {resp.get('status_text', '')}")
        
        elif status_code == 200:
            # 200 OK - 呼叫接通
            to_header = resp.get('headers', {}).get('to', '')
            tag_match = re.search(r'tag=([^;>\s]+)', to_header)
            if tag_match:
                self.current_call.to_tag = tag_match.group(1)
            
            # 保存 Route 和 Contact 头（用于 in-dialog 请求）
            route_header = resp.get('headers', {}).get('record-route', '')
            if route_header:
                self.current_call.route_header = route_header
                print(f"[SIP] 保存 Route: {route_header}")
            
            contact_header = resp.get('headers', {}).get('contact', '')
            if contact_header:
                self.current_call.contact_header = contact_header
                print(f"[SIP] 保存 Contact: {contact_header}")
            
            # 解析 SDP Answer
            sdp_body = resp.get('body', '')
            actual_remote_addr = resp.get('_source_addr')  # 获取实际信令地址（用于 NAT 修正）
            if sdp_body:
                remote_rtp_addr = self.parse_sdp_answer(sdp_body, actual_remote_addr)
                if remote_rtp_addr:
                    self.current_call.remote_rtp_addr = remote_rtp_addr
                    if not self.current_call.dialog_established:
                        # 只在第一次建立对话时设置
                        self.current_call.dialog_established = True
                        print(f"[SIP] ✓ 呼叫已接通，RTP 地址: {remote_rtp_addr}")
                    
                    # 确保每次收到 200 OK 都发送 ACK（防止重复发送但需要确认收到）
                    if not hasattr(self.current_call, '_ack_sent') or not self.current_call._ack_sent:
                        if self.send_ack():
                            self.current_call._ack_sent = True
                    else:
                        # 如果已经发送过 ACK，再次发送（服务器可能没收到）
                        print(f"[SIP] 重传 ACK（服务器可能未收到）")
                        self.send_ack()
        
        elif status_code >= 400:
            print(f"[SIP] ✗ 呼叫失败: {status_code} {resp.get('status_text', '')}")
    
    def send_ack(self):
        """发送 ACK（2xx ACK，使用 Route 头路由）"""
        if not self.current_call or not self.current_call.to_tag:
            print(f"[SIP] 警告: 无法发送 ACK（呼叫状态不完整）")
            return False
        
        if not self.sock:
            print(f"[SIP] 错误: Socket 未初始化，无法发送 ACK")
            return False
        
        call_id = self.current_call.call_id
        to_tag = self.current_call.to_tag
        
        # ACK 的 Request-URI（RFC 3261）：
        # 1. 如果有 Route 头，Request-URI 是最后一个 Route 的地址（被叫地址），Route 头用于路由
        # 2. 如果没有 Route 头，使用 Contact 头中的地址（被叫的实际地址）
        # 3. 如果都没有，使用被叫号码@服务器地址（由服务器转发）
        ack_ruri = None
        route_headers = ""
        
        if self.current_call.route_header:
            # 解析 Record-Route 头，反转顺序（最后一个在最前面）
            # Record-Route 格式：<sip:ip:port;lr>, <sip:ip2:port2;lr> 或 sip:ip:port;lr, sip:ip2:port2;lr
            routes = []
            for route in self.current_call.route_header.split(','):
                route = route.strip()
                if route:
                    routes.append(route)
            
            if routes:
                routes.reverse()  # 反转顺序（Record-Route 顺序 -> Route 顺序）
                route_headers = '\r\n'.join([f"Route: {route}" for route in routes])
                
                # 检查 Route 头的数量和内容
                # 如果只有一个 Route 且是服务器地址，Request-URI 应该使用 Contact 头的地址（被叫地址）
                # 如果 Route 头有多个，最后一个 Route 的地址作为 Request-URI（被叫地址）
                # RFC 3261: 当 Route 头只有一个代理时，Request-URI 指向最终目标（被叫），Route 用于路由
                if len(routes) == 1:
                    # 只有一个 Route（通常是服务器地址）
                    # 检查是否是服务器地址
                    route_uri = routes[0]
                    route_match = re.search(r'<?(sip:[^>;]+)', route_uri)
                    if route_match:
                        route_addr = route_match.group(1)
                        # 解析地址（格式：sip:ip:port 或 sip:user@ip:port）
                        addr_match = re.search(r'sip:(?:[^@]+@)?([^:;]+)(?::(\d+))?', route_addr)
                        if addr_match:
                            route_host = addr_match.group(1)
                            route_port = int(addr_match.group(2)) if addr_match.group(2) else 5060
                            # 如果是服务器地址，使用 Contact 头的地址作为 Request-URI
                            if route_host == self.server_ip and route_port == self.server_port:
                                # 使用 Contact 头的地址（被叫地址）
                                if self.current_call.contact_header:
                                    contact_match = re.search(r'<?(sip:[^>]+)', self.current_call.contact_header)
                                    if contact_match:
                                        ack_ruri = contact_match.group(1)
                                        print(f"[SIP] 单个 Route（服务器地址），使用 Contact 头作为 ACK Request-URI: {ack_ruri}")
                                    else:
                                        # 如果无法解析 Contact，使用最后一个 Route（由服务器转发）
                                        ack_ruri = route_addr
                                        print(f"[SIP] 单个 Route（服务器地址），Contact 解析失败，使用 Route: {ack_ruri}")
                                else:
                                    # 如果没有 Contact，使用最后一个 Route（由服务器转发）
                                    ack_ruri = route_addr
                                    print(f"[SIP] 单个 Route（服务器地址），无 Contact，使用 Route: {ack_ruri}")
                            else:
                                # 不是服务器地址，使用 Route 地址
                                ack_ruri = route_addr
                                print(f"[SIP] 单个 Route（非服务器地址），使用 Route 作为 ACK Request-URI: {ack_ruri}")
                        else:
                            # 无法解析地址，使用 Route 本身
                            ack_ruri = route_addr if route_match else route_uri
                            print(f"[SIP] Route 地址解析失败，使用原值: {ack_ruri}")
                    else:
                        # 无法解析 Route URI，使用 Route 本身
                        ack_ruri = route_uri
                        print(f"[SIP] Route URI 解析失败，使用原值: {ack_ruri}")
                else:
                    # 多个 Route，使用最后一个 Route 的地址（被叫地址）
                    last_route = routes[-1]
                    route_match = re.search(r'<?(sip:[^>;]+)', last_route)
                    if route_match:
                        ack_ruri = route_match.group(1)
                        print(f"[SIP] 多个 Route，使用最后一个 Route 作为 ACK Request-URI: {ack_ruri}")
                    else:
                        ack_ruri = last_route
                        print(f"[SIP] 多个 Route，最后一个 Route 解析失败，使用原值: {ack_ruri}")
        
        # 如果没有 Route 头，尝试使用 Contact 头
        if not ack_ruri and self.current_call.contact_header:
            # 从 Contact 头提取地址（格式：<sip:user@ip:port> 或 sip:user@ip:port）
            contact_match = re.search(r'<?(sip:[^>]+)', self.current_call.contact_header)
            if contact_match:
                ack_ruri = contact_match.group(1)
                print(f"[SIP] 使用 Contact 头作为 ACK Request-URI: {ack_ruri}")
        
        # 如果还是没有，使用被叫号码@服务器地址（由服务器转发）
        if not ack_ruri:
            callee = self.current_call.callee or "unknown"
            ack_ruri = f"sip:{callee}@{self.sip_domain}"
            print(f"[SIP] 使用被叫号码@服务器作为 ACK Request-URI: {ack_ruri}")
        
        # 获取被叫号码（用于 To 头）
        callee = self.current_call.callee or "unknown"
        
        # 构建 ACK 消息
        ack_lines = [
            f"ACK {ack_ruri} SIP/2.0",
            f"Via: SIP/2.0/UDP {self.contact_ip}:{self.local_port};branch={self._gen_branch()}",
            f"From: <sip:{self.username}@{self.sip_domain}>;tag={self.current_call.from_tag}",
            f"To: <sip:{callee}@{self.sip_domain}>;tag={to_tag}",
            f"Call-ID: {call_id}",
            f"CSeq: 1 ACK",
            f"Max-Forwards: 70",
            f"Content-Length: 0",
            ""
        ]
        
        if route_headers:
            # 插入 Route 头（在 Via 之后）
            ack_lines.insert(2, route_headers)
        
        ack_msg = '\r\n'.join(ack_lines)
        
        try:
            self.sock.sendto(ack_msg.encode('utf-8'), (self.server_ip, self.server_port))
            print(f"[SIP] ✓ ACK 已发送 (R-URI: {ack_ruri})")
            return True
        except Exception as e:
            print(f"[SIP] 错误: 发送 ACK 失败: {e}")
            return False
    
    def bye(self, timeout: float = 5.0) -> bool:
        """发送 BYE 挂断（in-dialog 请求，使用 Route 头路由）"""
        if not self.current_call or not self.current_call.to_tag:
            return False
        
        call_id = self.current_call.call_id
        to_tag = self.current_call.to_tag
        self.current_call.local_cseq += 1
        
        # BYE 的 Request-URI（RFC 3261）：
        # 1. 如果有 Route 头，Request-URI 是最后一个 Route 的地址（被叫地址），Route 头用于路由
        # 2. 如果没有 Route 头，使用 Contact 头中的地址（被叫的实际地址）
        # 3. 如果都没有，使用被叫号码@服务器地址（由服务器转发）
        bye_ruri = None
        route_headers = ""
        
        if self.current_call.route_header:
            # 解析 Record-Route 头，反转顺序（最后一个在最前面）
            # Record-Route 格式：<sip:ip:port;lr>, <sip:ip2:port2;lr> 或 sip:ip:port;lr, sip:ip2:port2;lr
            routes = []
            for route in self.current_call.route_header.split(','):
                route = route.strip()
                if route:
                    routes.append(route)
            
            if routes:
                routes.reverse()  # 反转顺序（Record-Route 顺序 -> Route 顺序）
                route_headers = '\r\n'.join([f"Route: {route}" for route in routes])
                
                # 检查 Route 头的数量和内容
                # 如果只有一个 Route 且是服务器地址，Request-URI 应该使用 Contact 头的地址（被叫地址）
                # 如果 Route 头有多个，最后一个 Route 的地址作为 Request-URI（被叫地址）
                # RFC 3261: 当 Route 头只有一个代理时，Request-URI 指向最终目标（被叫），Route 用于路由
                if len(routes) == 1:
                    # 只有一个 Route（通常是服务器地址）
                    # 检查是否是服务器地址
                    route_uri = routes[0]
                    route_match = re.search(r'<?(sip:[^>;]+)', route_uri)
                    if route_match:
                        route_addr = route_match.group(1)
                        # 解析地址（格式：sip:ip:port 或 sip:user@ip:port）
                        addr_match = re.search(r'sip:(?:[^@]+@)?([^:;]+)(?::(\d+))?', route_addr)
                        if addr_match:
                            route_host = addr_match.group(1)
                            route_port = int(addr_match.group(2)) if addr_match.group(2) else 5060
                            # 如果是服务器地址，使用 Contact 头的地址作为 Request-URI
                            if route_host == self.server_ip and route_port == self.server_port:
                                # 使用 Contact 头的地址（被叫地址）
                                if self.current_call.contact_header:
                                    contact_match = re.search(r'<?(sip:[^>]+)', self.current_call.contact_header)
                                    if contact_match:
                                        bye_ruri = contact_match.group(1)
                                        print(f"[SIP] 单个 Route（服务器地址），使用 Contact 头作为 BYE Request-URI: {bye_ruri}")
                                    else:
                                        # 如果无法解析 Contact，使用最后一个 Route（由服务器转发）
                                        bye_ruri = route_addr
                                        print(f"[SIP] 单个 Route（服务器地址），Contact 解析失败，使用 Route: {bye_ruri}")
                                else:
                                    # 如果没有 Contact，使用最后一个 Route（由服务器转发）
                                    bye_ruri = route_addr
                                    print(f"[SIP] 单个 Route（服务器地址），无 Contact，使用 Route: {bye_ruri}")
                            else:
                                # 不是服务器地址，使用 Route 地址
                                bye_ruri = route_addr
                                print(f"[SIP] 单个 Route（非服务器地址），使用 Route 作为 BYE Request-URI: {bye_ruri}")
                        else:
                            # 无法解析地址，使用 Route 本身
                            bye_ruri = route_addr if route_match else route_uri
                            print(f"[SIP] Route 地址解析失败，使用原值: {bye_ruri}")
                    else:
                        # 无法解析 Route URI，使用 Route 本身
                        bye_ruri = route_uri
                        print(f"[SIP] Route URI 解析失败，使用原值: {bye_ruri}")
                else:
                    # 多个 Route，使用最后一个 Route 的地址（被叫地址）
                    last_route = routes[-1]
                    route_match = re.search(r'<?(sip:[^>;]+)', last_route)
                    if route_match:
                        bye_ruri = route_match.group(1)
                        print(f"[SIP] 多个 Route，使用最后一个 Route 作为 BYE Request-URI: {bye_ruri}")
                    else:
                        bye_ruri = last_route
                        print(f"[SIP] 多个 Route，最后一个 Route 解析失败，使用原值: {bye_ruri}")
        
        # 如果没有 Route 头，尝试使用 Contact 头
        if not bye_ruri and self.current_call.contact_header:
            # 从 Contact 头提取地址（格式：<sip:user@ip:port> 或 sip:user@ip:port）
            contact_match = re.search(r'<?(sip:[^>]+)', self.current_call.contact_header)
            if contact_match:
                bye_ruri = contact_match.group(1)
                print(f"[SIP] 使用 Contact 头作为 BYE Request-URI: {bye_ruri}")
        
        # 如果还是没有，使用被叫号码@服务器地址（由服务器转发）
        if not bye_ruri:
            callee = self.current_call.callee or "unknown"
            bye_ruri = f"sip:{callee}@{self.sip_domain}"
            print(f"[SIP] 使用被叫号码@服务器作为 BYE Request-URI: {bye_ruri}")
        
        # 获取被叫号码（用于 To 头）
        callee = self.current_call.callee or "unknown"
        
        # 构建 BYE 消息
        bye_lines = [
            f"BYE {bye_ruri} SIP/2.0",
            f"Via: SIP/2.0/UDP {self.contact_ip}:{self.local_port};branch={self._gen_branch()}",
            f"From: <sip:{self.username}@{self.sip_domain}>;tag={self.current_call.from_tag}",
            f"To: <sip:{callee}@{self.sip_domain}>;tag={to_tag}",
            f"Call-ID: {call_id}",
            f"CSeq: {self.current_call.local_cseq} BYE",
            f"Max-Forwards: 70",
            f"Content-Length: 0",
            ""
        ]
        
        if route_headers:
            # 插入 Route 头（在 Via 之后）
            bye_lines.insert(2, route_headers)
        
        bye_msg = '\r\n'.join(bye_lines)
        
        print(f"[SIP] 发送 BYE 请求... (R-URI: {bye_ruri})")
        self.sock.sendto(bye_msg.encode('utf-8'), (self.server_ip, self.server_port))
        
        # 等待 200 OK（由监听线程处理）
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not self.current_call or not self.current_call.dialog_established:
                print(f"[SIP] ✓ BYE 已确认（dialog_established=False）")
                return True
            time.sleep(0.1)
        
        # 超时后也清除 dialog 状态
        if self.current_call:
            self.current_call.dialog_established = False
            print(f"[SIP] 警告: BYE 响应超时，强制清除 dialog 状态")
        
        return False
    
    def _do_unregister_with_sock(self, sock) -> None:
        """使用给定 socket 发送 Expires=0 的 REGISTER 并等待响应，成功后置 self.registered = False。"""
        sock.settimeout(5.0)
        call_id = self._gen_call_id()
        from_tag = self._gen_tag()
        branch = self._gen_branch()
        register_msg = (
            f"REGISTER sip:{self.server_ip} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {self.contact_ip}:{self.local_port};branch={branch}\r\n"
            f"From: <sip:{self.username}@{self.sip_domain}>;tag={from_tag}\r\n"
            f"To: <sip:{self.username}@{self.sip_domain}>\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: 1 REGISTER\r\n"
            f"Contact: <sip:{self.username}@{self.contact_ip}:{self.local_port}>\r\n"
            f"Expires: 0\r\n"
            f"Max-Forwards: 70\r\n"
            f"Content-Length: 0\r\n"
            f"\r\n"
        )
        sock.sendto(register_msg.encode('utf-8'), (self.server_ip, self.server_port))
        try:
            data, _ = sock.recvfrom(4096)
            resp = self._parse_response(data)
            status_code = resp.get('status_code', 0)
            if status_code == 401:
                auth_header = resp['headers'].get('www-authenticate', '')
                realm_match = re.search(r'realm="([^"]+)"', auth_header)
                nonce_match = re.search(r'nonce="([^"]+)"', auth_header)
                qop_match = re.search(r'qop="([^"]+)"', auth_header)
                if realm_match and nonce_match:
                    realm = realm_match.group(1)
                    nonce = nonce_match.group(1)
                    qop = qop_match.group(1) if qop_match else ""
                    uri = f"sip:{self.server_ip}"
                    if qop:
                        cnonce = f"{random.randint(100000, 999999)}"
                        nc = "00000001"
                        response = self._compute_response(self.username, realm, self.password,
                                                          uri, "REGISTER", nonce, qop, cnonce, nc)
                        auth_value = f'Digest username="{self.username}", realm="{realm}", nonce="{nonce}", uri="{uri}", response="{response}", qop={qop}, nc={nc}, cnonce="{cnonce}"'
                    else:
                        response = self._compute_response(self.username, realm, self.password, uri, "REGISTER", nonce)
                        auth_value = f'Digest username="{self.username}", realm="{realm}", nonce="{nonce}", uri="{uri}", response="{response}"'
                    register_msg = (
                        f"REGISTER sip:{self.server_ip} SIP/2.0\r\n"
                        f"Via: SIP/2.0/UDP {self.contact_ip}:{self.local_port};branch={self._gen_branch()}\r\n"
                        f"From: <sip:{self.username}@{self.sip_domain}>;tag={from_tag}\r\n"
                        f"To: <sip:{self.username}@{self.sip_domain}>\r\n"
                        f"Call-ID: {call_id}\r\n"
                        f"CSeq: 2 REGISTER\r\n"
                        f"Authorization: {auth_value}\r\n"
                        f"Contact: <sip:{self.username}@{self.contact_ip}:{self.local_port}>\r\n"
                        f"Expires: 0\r\n"
                        f"Max-Forwards: 70\r\n"
                        f"Content-Length: 0\r\n"
                        f"\r\n"
                    )
                    sock.sendto(register_msg.encode('utf-8'), (self.server_ip, self.server_port))
                    try:
                        data, _ = sock.recvfrom(4096)
                        resp = self._parse_response(data)
                        if resp.get('status_code', 0) == 200:
                            self.registered = False
                            print(f"[SIP] ✓ 注销成功")
                            return
                    except socket.timeout:
                        pass
            elif status_code == 200:
                self.registered = False
                print(f"[SIP] ✓ 注销成功（无需认证）")
                return
        except socket.timeout:
            pass
        self.registered = False
        print(f"[SIP] 注销请求已发送（未收到响应）")
    
    def unregister(self):
        """注销注册（发送 Expires=0 的 REGISTER）"""
        if not self.registered:
            return
        try:
            print(f"[SIP] 正在注销用户 {self.username}...")
            if self.sock is not None:
                self._do_unregister_with_sock(self.sock)
                return
            temp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                try:
                    temp_sock.bind((self.local_ip, self.local_port))
                except OSError as e:
                    if e.errno in (48, 98):
                        temp_sock.bind((self.local_ip, 0))
                    else:
                        raise
                self._do_unregister_with_sock(temp_sock)
            finally:
                temp_sock.close()
        except Exception as e:
            print(f"[WARNING] 注销异常（已忽略）: {e}")
            self.registered = False
    
    def close(self):
        """关闭客户端"""
        # 先停止监听，再注销（这样 unregister 可用 self.sock 收发，避免临时 socket 端口冲突导致未发送）
        self.stop_listener()
        try:
            self.unregister()
        except Exception as e:
            print(f"[WARNING] 注销时异常（已忽略）: {e}")
        
        # 关闭 socket
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None


class RTPPlayer:
    """RTP 媒体播放器（简化版）
    
    支持对称 RTP（Symmetric RTP）：等待对端先发送 RTP 包，
    获取 NAT 穿透后的真实地址，然后往该地址发送媒体。
    """
    
    def __init__(self, local_port: int, remote_addr: Tuple[str, int], codec: str = "PCMU",
                 symmetric_rtp: bool = True, symmetric_timeout: float = 2.0):
        """
        初始化 RTP 播放器
        
        Args:
            local_port: 本地 RTP 端口
            remote_addr: 对端 RTP 地址 (ip, port)（来自 SDP）
            codec: 编解码器（默认 PCMU）
            symmetric_rtp: 是否启用对称 RTP（等待对端先发包）
            symmetric_timeout: 等待对端 RTP 的超时时间（秒）
        """
        self.local_port = local_port
        self.remote_addr = remote_addr  # SDP 中声明的地址
        self.actual_remote_addr = remote_addr  # 实际发送地址（可能被对称 RTP 更新）
        self.codec = codec
        self.symmetric_rtp = symmetric_rtp
        self.symmetric_timeout = symmetric_timeout
        
        self.rtp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rtp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.rtp_sock.bind(("0.0.0.0", local_port))
        except OSError as e:
            if e.errno in (48, 98):  # Address already in use (macOS=48, Linux=98)
                self.rtp_sock.close()
                raise OSError(e.errno, f"RTP 端口 {local_port} 已被占用，请稍后重试或重启外呼服务") from e
            raise
        
        self.ssrc = int(time.time()) % (2**32)  # SSRC 也是 32-bit
        self.seq_num = 0
        # RTP timestamp 是 32-bit 无符号整数，需要限制在范围内
        # 使用随机起始值（避免与其他流冲突）
        self.timestamp = random.randint(0, 2**32 - 1) % (2**32)
        self.playing = False
    
    def _wait_for_symmetric_rtp(self) -> bool:
        """
        等待对端发送第一个 RTP 包（对称 RTP）
        
        Returns:
            是否收到对端 RTP 包并更新地址
        """
        if not self.symmetric_rtp:
            return False
        
        print(f"[RTP] 等待对端 RTP 包（对称 RTP，超时 {self.symmetric_timeout}s）...")
        
        # 设置非阻塞模式
        self.rtp_sock.setblocking(False)
        
        start_time = time.time()
        while time.time() - start_time < self.symmetric_timeout:
            try:
                data, addr = self.rtp_sock.recvfrom(2048)
                if len(data) >= 12:  # RTP 头至少 12 字节
                    # 收到对端 RTP 包，更新实际地址
                    old_addr = self.actual_remote_addr
                    self.actual_remote_addr = addr
                    print(f"[RTP] ✓ 收到对端 RTP 包，更新地址: {old_addr} -> {addr}")
                    return True
            except BlockingIOError:
                time.sleep(0.01)
            except Exception as e:
                pass
        
        # 超时，恢复阻塞模式，使用 SDP 中的地址
        print(f"[RTP] 对称 RTP 等待超时，使用 SDP 地址: {self.actual_remote_addr}")
        self.rtp_sock.setblocking(True)
        return False
    
    def play_wav_file(self, wav_file: str, duration: float = 0.0):
        """
        播放 WAV 文件
        
        注意：这是一个基础实现。完整的实现需要：
        1. 解析 WAV 文件头
        2. 提取 PCM 音频数据
        3. 转换为 PCMU (G.711 μ-law) 或 PCMA (G.711 A-law)
        4. 打包成 RTP 数据包（RFC 3550）
        5. 按 20ms 间隔发送 RTP 包
        
        当前实现：使用 wave 库读取 WAV，转换为 PCMU，发送 RTP 包
        """
        if not os.path.exists(wav_file):
            print(f"[RTP] 警告: 媒体文件不存在: {wav_file}")
            return
        
        print(f"[RTP] 开始播放媒体: {wav_file}")
        
        # 对称 RTP：等待对端先发送 RTP 包（解决 NAT 穿透问题）
        if self.symmetric_rtp:
            self._wait_for_symmetric_rtp()
        
        try:
            import wave
            import struct
            
            # 打开 WAV 文件
            wf = wave.open(wav_file, 'rb')
            sample_rate = wf.getframerate()
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            frames = wf.getnframes()
            
            print(f"[RTP] WAV 信息: {sample_rate}Hz, {channels}ch, {sample_width*8}bit, {frames}帧")
            
            # RTP 参数：PCMU @ 8kHz = 160 字节/包（20ms）
            target_sample_rate = 8000
            packets_sent = 0
            bytes_sent = 0
            packet_interval = 0.020  # 20ms
            samples_per_packet = 160  # 20ms @ 8kHz
            
            # 计算实际需要播放的帧数（基于目标采样率8kHz）
            # 如果指定了duration，计算目标采样率下的采样数
            if duration > 0:
                # 计算8kHz下的总采样数
                target_samples_needed = int(target_sample_rate * duration)
                # 计算原始采样率下需要读取的帧数
                source_samples_needed = int(sample_rate * duration)
                frames_to_read = min(frames, source_samples_needed)
                print(f"[RTP] 播放时长限制: {duration}秒 -> 需要 {target_samples_needed} 个8kHz采样（{source_samples_needed} 个原始采样）")
            else:
                frames_to_read = frames
                target_samples_needed = None
            
            # 检查是否需要重采样
            need_resample = (sample_rate != target_sample_rate)
            if need_resample:
                print(f"[RTP] 需要重采样: {sample_rate}Hz -> {target_sample_rate}Hz（使用线性插值）")
                # 预先读取需要播放的音频数据进行重采样
                print(f"[RTP] 正在读取并重采样音频数据...")
                all_audio_data = wf.readframes(frames_to_read)
                wf.close()
                
                # 转换为采样列表并重采样
                resampled_samples = self._resample_audio(
                    all_audio_data, sample_width, channels, sample_rate, target_sample_rate
                )
                
                # 如果指定了duration，确保重采样后的采样数不超过目标
                if duration > 0 and len(resampled_samples) > target_samples_needed:
                    resampled_samples = resampled_samples[:target_samples_needed]
                    print(f"[RTP] 重采样后数据被截断到 {target_samples_needed} 个采样（匹配播放时长）")
                
                # 计算实际需要的包数
                total_packets_needed = (len(resampled_samples) + samples_per_packet - 1) // samples_per_packet
                
                print(f"[RTP] 重采样完成: {len(resampled_samples)} 个采样，将发送 {total_packets_needed} 个 RTP 包")
            else:
                # 不需要重采样，直接使用原采样率
                resampled_samples = None
                # 计算实际需要的包数（基于8kHz）
                samples_needed = target_samples_needed if duration > 0 else (frames_to_read * target_sample_rate // sample_rate)
                total_packets_needed = (samples_needed + samples_per_packet - 1) // samples_per_packet
                print(f"[RTP] 不需要重采样，将发送 {total_packets_needed} 个 RTP 包")
            
            # 读取并发送音频数据（每次 160 采样 = 20ms）
            # 使用精确的定时器来保证RTP包的均匀发送
            import time as time_module
            
            self.playing = True  # 标记正在播放
            
            sample_count = 0
            start_time = time_module.time()
            next_packet_time = start_time
            
            while self.playing and packets_sent < total_packets_needed:
                # 检查是否达到播放时长（在读取数据前检查，避免发送多余包）
                if duration > 0:
                    elapsed = time_module.time() - start_time
                    if elapsed >= duration:
                        print(f"[RTP] 达到播放时长限制 ({duration}秒)，停止播放")
                        break
                
                # 检查是否还有数据要发送
                if need_resample:
                    # 使用重采样后的数据
                    if sample_count >= len(resampled_samples):
                        print(f"[RTP] 重采样数据已用完，停止播放（已发送 {packets_sent} 包）")
                        break
                    samples_to_send = resampled_samples[sample_count:sample_count + samples_per_packet]
                    if len(samples_to_send) < samples_per_packet:
                        # 最后一包不足 160 采样，用静音填充
                        samples_to_send.extend([0] * (samples_per_packet - len(samples_to_send)))
                    
                    # 转换为 PCMU
                    pcmu_data = self._samples_to_pcmu(samples_to_send)
                    sample_count += samples_per_packet
                else:
                    # 直接从 WAV 文件读取
                    frames_to_read = samples_per_packet
                    audio_data = wf.readframes(frames_to_read)
                    if not audio_data or len(audio_data) == 0:
                        print(f"[RTP] 音频文件已读取完毕，停止播放（已发送 {packets_sent} 包）")
                        break
                    
                    # 转换为 PCMU（G.711 μ-law）
                    pcmu_data = self._pcm_to_pcmu(audio_data, sample_width, channels, sample_rate, warn_once=False)
                
                # 确保正好是 160 字节（20ms PCMU）
                if len(pcmu_data) > 160:
                    pcmu_data = pcmu_data[:160]
                elif len(pcmu_data) < 160:
                    # 不足 160 字节，用静音填充（μ-law的静音是0x7f）
                    pcmu_data += b'\x7f' * (160 - len(pcmu_data))
                
                # 打包 RTP 数据包（RFC 3550）
                rtp_header = self._create_rtp_header()
                rtp_packet = rtp_header + pcmu_data
                
                # 等待到下一个包的发送时间（精确控制）
                current_time = time_module.time()
                if next_packet_time > current_time:
                    sleep_time = next_packet_time - current_time
                    if sleep_time > 0:
                        time_module.sleep(sleep_time)
                
                # 发送 RTP 包（使用对称 RTP 后的实际地址）
                try:
                    self.rtp_sock.sendto(rtp_packet, self.actual_remote_addr)
                    packets_sent += 1
                    bytes_sent += len(rtp_packet)
                except Exception as e:
                    print(f"[RTP] 发送错误: {e}")
                    break
                
                # 更新下一个包的发送时间（累积，避免误差累积）
                next_packet_time = start_time + (packets_sent * packet_interval)
                
                # 更新 RTP 头部参数（下一个包）
                self.seq_num = (self.seq_num + 1) % 65536
                self.timestamp = (self.timestamp + 160) % (2**32)
            
            self.playing = False  # 标记播放结束
            
            if not need_resample:
                wf.close()
            
            # 计算实际播放时长
            actual_duration = time_module.time() - start_time
            expected_duration = packets_sent * packet_interval
            
            print(f"[RTP] 播放完成: 发送 {packets_sent} 个 RTP 包，共 {bytes_sent} 字节")
            print(f"[RTP] 实际播放时长: {actual_duration:.2f}秒，预期: {expected_duration:.2f}秒")
            
            # 如果指定了duration且还未达到，说明数据已用完
            if duration > 0 and actual_duration < duration - 0.1:
                print(f"[RTP] 警告: 音频数据不足，提前结束（预期 {duration}秒，实际 {actual_duration:.2f}秒）")
            
        except ImportError:
            print(f"[RTP] 警告: wave 库不可用，使用简化模式（仅等待）")
            print(f"[RTP] 提示: 安装 wave 库（Python 标准库）以启用音频播放")
            time.sleep(duration)
            print(f"[RTP] 播放完成（简化模式）")
        except Exception as e:
            print(f"[RTP] 播放错误: {e}")
            import traceback
            traceback.print_exc()
    
    def _create_rtp_header(self) -> bytes:
        """创建 RTP 数据包头（RFC 3550）"""
        # RTP 头部：12 字节
        # 版本(2bit) + 填充(1bit) + 扩展(1bit) + CC(4bit) = V=2, P=0, X=0, CC=0 = 0x80
        # 标记(1bit) + 负载类型(7bit) = M=0, PT=0 (PCMU) = 0x00
        version_padding_extension_cc = 0x80  # V=2, P=0, X=0, CC=0
        marker_payload_type = 0x00  # M=0, PT=0 (PCMU)
        
        # 确保所有值都在有效范围内（防止溢出）
        seq_num = self.seq_num % 65536  # 16-bit
        timestamp = self.timestamp % (2**32)  # 32-bit
        ssrc = self.ssrc % (2**32)  # 32-bit
        
        seq_num_bytes = seq_num.to_bytes(2, byteorder='big')
        timestamp_bytes = timestamp.to_bytes(4, byteorder='big')
        ssrc_bytes = ssrc.to_bytes(4, byteorder='big')
        
        return bytes([version_padding_extension_cc, marker_payload_type]) + seq_num_bytes + timestamp_bytes + ssrc_bytes
    
    def _pcm_to_samples(self, pcm_data: bytes, sample_width: int, channels: int) -> List[int]:
        """
        将 PCM 音频数据转换为采样值列表
        
        Args:
            pcm_data: PCM 音频数据
            sample_width: 采样位宽（字节数，如 2 表示 16-bit）
            channels: 声道数（1=单声道，2=立体声）
        
        Returns:
            采样值列表（16-bit PCM，范围：-32768 到 32767）
        """
        import struct
        
        samples = []
        
        if channels == 2 and sample_width == 2:
            # 16-bit 立体声：每 4 字节是一个采样对（左、右），只取左声道
            for i in range(0, len(pcm_data), 4):
                if i + 3 < len(pcm_data):
                    samples.append(struct.unpack('<h', pcm_data[i:i+2])[0])
        elif sample_width == 2:
            # 16-bit 单声道
            samples = list(struct.unpack(f'<{len(pcm_data)//2}h', pcm_data))
        elif sample_width == 1:
            # 8-bit PCM：转换为 16-bit（乘以 256）
            samples = [struct.unpack('<b', bytes([b]))[0] * 256 for b in pcm_data]
        else:
            # 其他格式，尝试转换
            for i in range(0, len(pcm_data), sample_width):
                if i + sample_width <= len(pcm_data):
                    try:
                        if sample_width == 2:
                            val = struct.unpack('<h', pcm_data[i:i+2])[0]
                        elif sample_width == 1:
                            val = struct.unpack('<b', pcm_data[i:i+1])[0] * 256
                        else:
                            val = 0
                        samples.append(val)
                    except:
                        samples.append(0)
        
        return samples
    
    def _resample_audio(self, pcm_data: bytes, sample_width: int, channels: int, 
                       source_rate: int, target_rate: int) -> List[int]:
        """
        使用线性插值重采样音频
        
        Args:
            pcm_data: 原始 PCM 音频数据
            sample_width: 采样位宽（字节数）
            channels: 声道数（1=单声道，2=立体声）
            source_rate: 源采样率（Hz）
            target_rate: 目标采样率（Hz）
        
        Returns:
            重采样后的采样值列表
        """
        # 首先提取采样值
        source_samples = self._pcm_to_samples(pcm_data, sample_width, channels)
        
        if source_rate == target_rate:
            return source_samples
        
        # 计算重采样率
        ratio = source_rate / target_rate  # 反向计算：源采样率/目标采样率
        target_length = int(len(source_samples) / ratio)
        
        # 线性插值重采样
        resampled = []
        source_len = len(source_samples)
        
        for i in range(target_length):
            # 计算源采样中的位置（浮点数）
            source_pos = i * ratio
            
            # 获取相邻的两个采样点
            pos_low = int(source_pos)
            pos_high = min(pos_low + 1, source_len - 1)
            
            # 确保索引有效
            if pos_low < 0:
                pos_low = 0
            if pos_high >= source_len:
                pos_high = source_len - 1
            
            # 线性插值
            if pos_low == pos_high or pos_high >= source_len:
                # 边界情况：使用最近的采样
                sample_idx = min(pos_low, source_len - 1)
                resampled.append(source_samples[sample_idx])
            else:
                # 计算插值权重
                weight = source_pos - pos_low
                # 线性插值
                interpolated = source_samples[pos_low] * (1.0 - weight) + source_samples[pos_high] * weight
                # 四舍五入并限制范围
                interpolated = int(round(interpolated))
                interpolated = max(-32768, min(32767, interpolated))
                resampled.append(interpolated)
        
        return resampled
    
    def _samples_to_pcmu(self, samples: List[int]) -> bytes:
        """
        将采样值列表转换为 PCMU 编码
        
        Args:
            samples: 采样值列表（16-bit PCM）
        
        Returns:
            PCMU 编码后的数据（字节）
        """
        pcmu_data = bytearray()
        for sample in samples:
            pcmu_byte = self._linear_to_ulaw(sample)
            pcmu_data.append(pcmu_byte)
        return bytes(pcmu_data)
    
    def _pcm_to_pcmu(self, pcm_data: bytes, sample_width: int, channels: int, 
                     sample_rate: int, warn_once: bool = True) -> bytes:
        """
        将 PCM 音频转换为 G.711 PCMU (μ-law)
        
        Args:
            pcm_data: PCM 音频数据
            sample_width: 采样位宽（字节数，如 2 表示 16-bit）
            channels: 声道数（1=单声道，2=立体声）
            sample_rate: 采样率（Hz）
            warn_once: 是否只警告一次（避免重复打印）
        
        Returns:
            PCMU 编码后的数据（字节）
        """
        try:
            # 提取采样值
            pcm_samples = self._pcm_to_samples(pcm_data, sample_width, channels)
            
            # 如果采样率不是 8kHz，需要重采样
            # 注意：这应该在调用前就完成重采样，这里保留作为兼容
            if sample_rate != 8000 and warn_once:
                # 只在第一次警告
                if not hasattr(self, '_resample_warned'):
                    print(f"[RTP] 警告: WAV 采样率为 {sample_rate}Hz，需要重采样到 8kHz")
                    print(f"[RTP] 建议: 在 play_wav_file 中预先重采样以提高音质")
                    self._resample_warned = True
                # 简单降采样（音质较差，仅作为兼容）
                if sample_rate > 8000:
                    ratio = sample_rate // 8000
                    pcm_samples = pcm_samples[::ratio]
            
            # 转换为 PCMU
            return self._samples_to_pcmu(pcm_samples)
            
        except Exception as e:
            print(f"[RTP] PCM 转换错误: {e}")
            import traceback
            traceback.print_exc()
            # 降级：返回静音
            return b'\x7f' * 160  # 发送静音（μ-law 的 0）
    
    def _linear_to_ulaw(self, sample: int) -> int:
        """
        G.711 μ-law 编码算法
        将 16-bit 线性 PCM 转换为 8-bit μ-law
        
        Args:
            sample: 16-bit PCM 采样值（-32768 到 32767）
        
        Returns:
            8-bit μ-law 编码值（0 到 255）
        """
        # 限制范围
        if sample > 32767:
            sample = 32767
        elif sample < -32768:
            sample = -32768
        
        # 获取符号位
        sign = 0 if sample >= 0 else 0x80
        sample = abs(sample)
        
        # μ-law 编码算法
        # 添加偏置（bias）
        sample += 0x84
        
        # 查找分段（segment）
        if sample >= 0x1000:
            exp = 7
            sample = (sample >> 4) - 0x20
        elif sample >= 0x800:
            exp = 6
            sample = (sample >> 3) - 0x20
        elif sample >= 0x400:
            exp = 5
            sample = (sample >> 2) - 0x20
        elif sample >= 0x200:
            exp = 4
            sample = (sample >> 1) - 0x20
        elif sample >= 0x100:
            exp = 3
            sample = sample - 0x20
        elif sample >= 0x80:
            exp = 2
            sample = (sample << 1) - 0x20
        elif sample >= 0x40:
            exp = 1
            sample = (sample << 2) - 0x20
        else:
            exp = 0
            sample = (sample << 3) - 0x20
        
        # 限制范围并组合
        mantissa = sample & 0x0f
        ulaw = sign | (exp << 4) | mantissa
        
        # μ-law 是反转的（实际发送时需要反转）
        return 0xff - ulaw
    
    def close(self):
        """关闭 RTP 播放器"""
        # 立即停止播放
        self.playing = False
        if self.rtp_sock:
            try:
                self.rtp_sock.close()
            except:
                pass


class AutoDialerClient:
    """
    独立的自动外呼客户端
    完全独立于服务器代码，可以单独运行
    """
    
    def __init__(self, config_file: str = "sip_client_config.json", server_globals: Optional[Dict] = None):
        """
        初始化自动外呼客户端
        
        Args:
            config_file: 配置文件路径
            server_globals: 服务器全局变量（含 SERVER_IP）。内嵌在 IMS 进程时传入，用于改用 127.0.0.1 注册，确保服务器能把 INVITE 发回本机。
        """
        self.server_globals = server_globals or {}
        self.config = self._load_config(config_file)
        # 内嵌在 IMS 进程时：socket连接用 127.0.0.1，但Via/Contact头用SERVER_IP，AOR 域用 SERVER_IP
        # 这样服务器能把 INVITE 发回本机，同时信令地址显示为SERVER_IP（与服务器一致）
        if self.server_globals.get("SERVER_IP") is not None:
            server_ip = self.server_globals["SERVER_IP"]
            self.config["server_ip"] = "127.0.0.1"  # socket连接用127.0.0.1
            self.config["local_ip"] = "127.0.0.1"  # socket绑定用127.0.0.1
            self.config["sip_domain"] = server_ip  # AOR域用SERVER_IP
            # Via/Contact头地址：使用SERVER_IP（与服务器一致）
            self.config["contact_ip"] = server_ip
            if "sdp_ip" not in self.config or not self.config["sdp_ip"]:
                self.config["sdp_ip"] = server_ip  # SDP 用对外宣告的 IP
        self.client: Optional[SIPClient] = None
        self.tasks: List[CallTask] = []
        self.stats = {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
        }
        self._rtp_port_counter = 30001  # RTP 端口 30001-40000，与 SIP 端口 20000-30000 错开
        self._active_calls = {}  # 保存活跃的呼叫状态：{call_id: call_info}
        self._sip_port_range = (20000, 30000)  # 外呼 SIP 端口随机范围
        self._port_lock = threading.Lock()  # 端口分配锁（线程安全）
    
    def _load_config(self, config_file: str) -> Dict:
        """加载配置文件"""
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                config = DEFAULT_CONFIG.copy()
                config.update(user_config)
                # 如果配置文件中没有 server_ip 或为默认值，从环境变量读取
                if not config.get("server_ip") or config.get("server_ip") == "192.168.100.8":
                    env_server_ip = os.getenv("SERVER_IP")
                    if env_server_ip:
                        config["server_ip"] = env_server_ip
                        config["local_ip"] = env_server_ip  # local_ip 也更新为相同的值
                return config
            except Exception as e:
                print(f"[WARNING] 无法加载配置文件 {config_file}: {e}")
                return DEFAULT_CONFIG.copy()
        else:
            # 创建默认配置文件
            self._save_config(DEFAULT_CONFIG, config_file)
            return DEFAULT_CONFIG.copy()
    
    def _save_config(self, config: Dict, config_file: str):
        """保存配置文件"""
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[WARNING] 无法保存配置文件 {config_file}: {e}")
    
    def register(self) -> bool:
        """注册到 SIP 服务器"""
        username = self.config.get("username")
        password = self.config.get("password")
        server_ip = self.config.get("server_ip")
        server_port = self.config.get("server_port")
        local_ip = self.config.get("local_ip")
        local_port = self.config.get("local_port")
        
        self.client = SIPClient(
            username=username,
            password=password,
            server_ip=server_ip,
            server_port=server_port,
            local_ip=local_ip,
            local_port=local_port,
            sdp_ip=self.config.get("sdp_ip") or server_ip,
            sip_domain=self.config.get("sip_domain"),
            contact_ip=self.config.get("contact_ip"),  # 传递contact_ip配置
        )
        
        # 注册
        if self.client.register(expires=3600):
            # 启动监听线程
            self.client.start_listener()
            return True
        else:
            self.client = None
            return False
    
    def dial(self, callee: str, media_file: Optional[str] = None, 
             duration: float = 0.0) -> bool:
        """
        发起外呼
        
        Args:
            callee: 被叫用户号码
            media_file: 媒体文件路径（None 表示使用默认）
            duration: 播放时长（秒），0表示播放完整文件
        
        Returns:
            呼叫是否成功
        """
        if not self.client or not self.client.registered:
            print(f"[ERROR] 未注册，无法发起呼叫")
            return False
        
        # 分配唯一的 RTP 端口（避免端口冲突）
        rtp_port = self._rtp_port_counter
        self._rtp_port_counter += 1
        if self._rtp_port_counter > 40000:
            self._rtp_port_counter = 30001  # 重置端口范围
        
        # 发起呼叫
        media_file_path = media_file or self.config.get("media_file")
        
        # 使用线程锁防止重复调用
        call_handled = threading.Event()
        played_media = False
        call_id = None  # 保存当前呼叫的 Call-ID
        current_call_ref = None  # 保存当前呼叫状态的引用
        
        def on_response(resp: Dict):
            # 防止重复调用
            if call_handled.is_set():
                return
            
            status_code = resp.get('status_code', 0)
            if status_code == 200:
                # 检查呼叫状态
                if not self.client or not self.client.current_call or not self.client.current_call.remote_rtp_addr:
                    return
                
                # 保存当前呼叫的引用（避免被后续呼叫覆盖）
                nonlocal call_id, current_call_ref
                call_id = self.client.current_call.call_id
                current_call_ref = self.client.current_call
                
                # 保存到活跃呼叫字典
                self._active_calls[call_id] = {
                    'call': current_call_ref,
                    'callee': callee,
                    'rtp_port': rtp_port,
                    'remote_rtp_addr': current_call_ref.remote_rtp_addr
                }
                
                # 标记为已处理，防止重复
                call_handled.set()
                
                # 呼叫接通，开始播放媒体（在独立线程中执行，避免阻塞）
                def play_media():
                    # 使用实例变量而非全局变量，避免冲突
                    nonlocal played_media, call_id, current_call_ref
                    if played_media:
                        return
                    played_media = True
                    
                    try:
                        # 使用保存的呼叫状态引用，而不是 self.client.current_call（可能被后续呼叫覆盖）
                        if call_id not in self._active_calls:
                            print(f"[ERROR] 呼叫状态已丢失 (Call-ID: {call_id})")
                            return
                        
                        call_info = self._active_calls[call_id]
                        remote_rtp_addr = call_info['remote_rtp_addr']
                        
                        print(f"[RTP] 准备播放媒体: {media_file_path} (Call-ID: {call_id})")
                        rtp_player = RTPPlayer(rtp_port, remote_rtp_addr, symmetric_rtp=True, symmetric_timeout=3.0)
                        
                        # 播放音频（如果duration为0，播放完整文件）
                        # 注意：duration=0表示播放整个文件，>0表示限制播放时长
                        play_duration = duration if duration > 0 else 0
                        print(f"[RTP] 准备播放，时长限制: {play_duration if play_duration > 0 else '完整文件'}")
                        rtp_player.play_wav_file(media_file_path, play_duration)
                        
                        # 立即停止播放（确保不再发送任何包）
                        rtp_player.playing = False
                        
                        # 关闭 RTP socket（立即停止发送）
                        rtp_player.close()
                        
                        # 播放完成后立即挂断（不需要额外等待）
                        import time as time_module
                        # 使用保存的呼叫状态引用
                        if call_id in self._active_calls:
                            call_info = self._active_calls[call_id]
                            # 临时恢复 current_call（用于 bye）
                            original_call = self.client.current_call
                            self.client.current_call = call_info['call']
                            
                            try:
                                print(f"[SIP] 播放完成，正在挂断... (Call-ID: {call_id})")
                                self.client.bye()
                                # 短暂等待BYE响应（减少延迟）
                                time_module.sleep(0.2)
                                print(f"[SIP] 呼叫已挂断 (Call-ID: {call_id})")
                            finally:
                                # 恢复 original_call（如果有后续呼叫）
                                self.client.current_call = original_call
                                # 清理活跃呼叫
                                if call_id in self._active_calls:
                                    del self._active_calls[call_id]
                    except Exception as e:
                        print(f"[ERROR] 媒体播放失败: {e} (Call-ID: {call_id})")
                        import traceback
                        traceback.print_exc()
                        # 即使播放失败也要挂断
                        try:
                            if call_id in self._active_calls:
                                call_info = self._active_calls[call_id]
                                original_call = self.client.current_call
                                self.client.current_call = call_info['call']
                                try:
                                    self.client.bye()
                                finally:
                                    self.client.current_call = original_call
                                    if call_id in self._active_calls:
                                        del self._active_calls[call_id]
                        except:
                            pass
                
                # 在独立线程中播放媒体
                play_thread = threading.Thread(target=play_media, daemon=True)
                play_thread.start()
        
        success = self.client.invite(callee, rtp_port, timeout=30.0, on_response=on_response)
        
        if success:
            self.stats["successful_calls"] += 1
        else:
            self.stats["failed_calls"] += 1
        
        self.stats["total_calls"] += 1
        
        return success
    
    def dial_concurrent(self, callee: str, media_file: Optional[str] = None, 
                        duration: float = 0.0, local_port: Optional[int] = None) -> bool:
        """
        并发发起外呼（使用独立的客户端实例）
        
        Args:
            callee: 被叫用户号码
            media_file: 媒体文件路径（None 表示使用默认）
            duration: 播放时长（秒），0表示播放完整文件
            local_port: 本地 SIP 端口（如果为 None，使用随机端口）
        
        Returns:
            呼叫是否成功
        """
        client = None
        play_thread = None
        
        try:
            # 创建独立的客户端实例（避免状态冲突）
            username = self.config.get("username")
            password = self.config.get("password")
            server_ip = self.config.get("server_ip")
            server_port = self.config.get("server_port")
            local_ip = self.config.get("local_ip")
            
            # 如果没有指定本地端口，在 20000-30000 范围内随机（与 RTP 30001-40000 错开）
            if local_port is None:
                low, high = self._sip_port_range
                local_port = random.randint(low, high)
            
            # 创建独立的客户端（使用分配的端口）
            # 获取 sdp_ip、sip_domain（内嵌时 sip_domain=SERVER_IP，否则 AOR 查找会失败）
            sdp_ip = self.config.get("sdp_ip") or server_ip
            sip_domain = self.config.get("sip_domain")
            
            client = SIPClient(
                username=username,
                password=password,
                server_ip=server_ip,
                server_port=server_port,
                local_ip=local_ip,
                local_port=local_port,  # 使用分配的端口
                sdp_ip=sdp_ip,
                sip_domain=sip_domain,
            )
            
            # 注册（如果端口被占用，会自动使用临时端口）
            if not client.register(expires=3600):
                print(f"[ERROR] [{callee}] 注册失败")
                return False
            
            # 如果注册时使用了临时端口，更新 local_port（虽然在并发模式下可能不太重要）
            # 注意：register() 已经自动更新了 client.local_port
            
            # 启动监听线程
            client.start_listener()
            
            # 分配唯一的 RTP 端口（线程安全，30001-40000）
            with self._port_lock:
                rtp_port = self._rtp_port_counter
                self._rtp_port_counter += 1
                if self._rtp_port_counter > 40000:
                    self._rtp_port_counter = 30001  # 重置端口范围
            
            # 发起呼叫
            media_file_path = media_file or self.config.get("media_file")
            
            call_handled = threading.Event()
            played_media = False
            cleanup_done = threading.Event()
            
            def on_response(resp: Dict):
                if call_handled.is_set():
                    return
                
                status_code = resp.get('status_code', 0)
                if status_code == 200:
                    if not client.current_call or not client.current_call.remote_rtp_addr:
                        return
                    
                    call_handled.set()
                    
                    def play_media():
                        nonlocal played_media
                        if played_media:
                            return
                        played_media = True
                        
                        rtp_player = None
                        try:
                            remote_rtp_addr = client.current_call.remote_rtp_addr
                            print(f"[RTP] [{callee}] 准备播放媒体: {media_file_path}")
                            rtp_player = RTPPlayer(rtp_port, remote_rtp_addr, symmetric_rtp=True, symmetric_timeout=3.0)
                            
                            # duration < 0 表示不自动挂断（保持通话直到对方挂断）
                            if duration < 0:
                                print(f"[RTP] [{callee}] 保持通话模式（不自动挂断），不播放媒体")
                                # 保持通话，等待对方挂断
                                while client and client.current_call:
                                    import time as time_module
                                    time_module.sleep(1.0)
                                print(f"[SIP] [{callee}] 对方已挂断")
                            else:
                                play_duration = duration if duration > 0 else 0
                                print(f"[RTP] [{callee}] 准备播放，时长限制: {play_duration if play_duration > 0 else '完整文件'}")
                                rtp_player.play_wav_file(media_file_path, play_duration)
                                
                                rtp_player.playing = False
                                rtp_player.close()
                                
                                import time as time_module
                                if client and client.current_call:
                                    print(f"[SIP] [{callee}] 播放完成，正在挂断...")
                                    client.bye()
                                    time_module.sleep(0.2)
                                    print(f"[SIP] [{callee}] 呼叫已挂断")
                        except Exception as e:
                            print(f"[ERROR] [{callee}] 媒体播放失败: {e}")
                            import traceback
                            traceback.print_exc()
                            try:
                                if client and client.current_call:
                                    client.bye()
                            except Exception as bye_err:
                                print(f"[WARNING] [{callee}] BYE 失败: {bye_err}")
                        finally:
                            # 确保 RTP 播放器关闭
                            if rtp_player:
                                try:
                                    rtp_player.close()
                                except:
                                    pass
                            
                            # 关闭客户端（会注销注册）
                            if client:
                                try:
                                    client.close()
                                except Exception as close_err:
                                    print(f"[WARNING] [{callee}] 关闭客户端失败: {close_err}")
                            
                            cleanup_done.set()
                    
                    play_thread = threading.Thread(target=play_media, daemon=True)
                    play_thread.start()
            
            # 发起呼叫（带超时保护）
            try:
                success = client.invite(callee, rtp_port, timeout=30.0, on_response=on_response)
                
                # 如果呼叫失败，立即清理资源
                if not success:
                    print(f"[WARNING] [{callee}] 呼叫失败，等待清理...")
                    # 等待最多 2 秒让清理完成
                    cleanup_done.wait(timeout=2.0)
                    if client:
                        try:
                            client.close()
                        except:
                            pass
                    return False
                
                # 等待呼叫完成或超时（最多等待 120 秒）
                if not cleanup_done.wait(timeout=120.0):
                    print(f"[WARNING] [{callee}] 呼叫超时，强制清理...")
                    if client:
                        try:
                            client.close()
                        except:
                            pass
                
            except Exception as invite_err:
                print(f"[ERROR] [{callee}] INVITE 异常: {invite_err}")
                import traceback
                traceback.print_exc()
                if client:
                    try:
                        client.close()
                    except:
                        pass
                return False
            
            # 更新统计
            if success:
                self.stats["successful_calls"] += 1
            else:
                self.stats["failed_calls"] += 1
            
            self.stats["total_calls"] += 1
            
            return success
            
        except Exception as e:
            # 任何异常都要确保资源清理
            print(f"[ERROR] [{callee}] 呼叫异常: {e}")
            import traceback
            traceback.print_exc()
            
            if client:
                try:
                    client.close()
                except:
                    pass
            
            self.stats["failed_calls"] += 1
            self.stats["total_calls"] += 1
            return False
    
    def close(self):
        """关闭客户端"""
        if self.client:
            self.client.close()
            self.client = None


def main():
    """主函数"""
    import sys
    
    print("=" * 60)
    print("独立的 SIP 自动外呼客户端")
    print("=" * 60)
    print()
    
    # 创建客户端
    client = AutoDialerClient()
    
    # 注册
    print("[1/3] 正在注册到 SIP 服务器...")
    if not client.register():
        print("[ERROR] 注册失败，程序退出")
        sys.exit(1)
    
    print()
    print("[2/3] 注册成功！")
    print()
    
    # 交互式菜单
    while True:
        print("\n" + "=" * 60)
        print("自动外呼系统 - 命令菜单")
        print("=" * 60)
        print("1. 发起单次外呼")
        print("2. 批量外呼")
        print("3. 查看统计")
        print("4. 退出")
        print()
        
        choice = input("请选择操作 (1-4): ").strip()
        
        if choice == "1":
            callee = input("请输入被叫号码: ").strip()
            if callee:
                print(f"\n正在呼叫 {callee}...")
                client.dial(callee)
        
        elif choice == "2":
            callees_str = input("请输入被叫号码列表（用逗号分隔）: ").strip()
            if callees_str:
                callees = [c.strip() for c in callees_str.split(',') if c.strip()]
                if not callees:
                    print("[ERROR] 没有有效的被叫号码")
                    continue
                
                print(f"\n正在批量呼叫 {len(callees)} 个号码（并发模式）...")
                
                # 使用线程池并发执行
                import concurrent.futures
                import time as time_module
                
                def dial_single(callee: str) -> tuple:
                    """单个呼叫函数"""
                    try:
                        print(f"[{callee}] 开始呼叫...")
                        success = client.dial_concurrent(callee)
                        return (callee, success)
                    except Exception as e:
                        print(f"[ERROR] [{callee}] 呼叫异常: {e}")
                        return (callee, False)
                
                # 使用 ThreadPoolExecutor 并发执行
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(callees), 10)) as executor:
                    # 提交所有呼叫任务
                    futures = {executor.submit(dial_single, callee): callee for callee in callees}
                    
                    # 等待所有呼叫完成
                    completed = 0
                    for future in concurrent.futures.as_completed(futures):
                        completed += 1
                        callee, success = future.result()
                        status = "成功" if success else "失败"
                        print(f"[{completed}/{len(callees)}] {callee} - {status}")
                
                print(f"\n批量呼叫完成: 总计 {len(callees)} 个")
        
        elif choice == "3":
            print("\n统计信息:")
            print(f"  总呼叫数: {client.stats['total_calls']}")
            print(f"  成功: {client.stats['successful_calls']}")
            print(f"  失败: {client.stats['failed_calls']}")
        
        elif choice == "4":
            break
        
        else:
            print("[ERROR] 无效选择")
    
    # 关闭客户端
    print("\n正在关闭客户端...")
    client.close()
    print("已退出")


if __name__ == "__main__":
    main()

