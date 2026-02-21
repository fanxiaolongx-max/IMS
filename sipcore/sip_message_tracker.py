"""
SIP 消息跟踪系统

记录所有 SIP 消息（请求/响应），提供查询、过滤、导出等功能。
用于调试、监控、故障排查。
"""

import time
import threading
from typing import Dict, List, Optional, Tuple, Set, Callable
from dataclasses import dataclass, asdict
from datetime import datetime
import re

from .message import SIPMessage
from .logger import get_logger

log = get_logger()


@dataclass
class SIPMessageRecord:
    """SIP 消息记录"""
    id: int  # 自增 ID
    timestamp: float  # 时间戳（秒）
    direction: str  # "RX"（接收）或 "TX"（发送）或 "FWD"（转发）
    method: str  # SIP 方法（INVITE, REGISTER, 200 OK, 401 Unauthorized 等）
    call_id: str  # Call-ID
    from_user: str  # From 头中的用户名（如 "1001"）
    to_user: str  # To 头中的用户名（如 "1002"）
    from_tag: str  # From tag（如果有）
    to_tag: str  # To tag（如果有）
    src_ip: str  # 源 IP（NAT 后，UDP 数据包源地址）
    src_port: int  # 源端口（NAT 后，UDP 数据包源端口）
    dst_ip: str  # 目标 IP（NAT 后，UDP 数据包目标地址）
    dst_port: int  # 目标端口（NAT 后，UDP 数据包目标端口）
    status_code: str  # 响应状态码（如 "200", "401"，请求则为 ""）
    cseq: str  # CSeq 值（如 "1 INVITE"）
    content_length: int  # Content-Length
    has_sdp: bool  # 是否包含 SDP
    full_message: str  # 完整 SIP 消息内容
    via_count: int  # Via 头数量
    route_count: int  # Route 头数量
    contact: str  # Contact 头（如果有）
    user_agent: str  # User-Agent（如果有）
    registered_user: str  # 注册用户（REGISTER 时）
    callee: str  # 被叫号码（INVITE 时）
    sdp_info: str  # SDP 媒体地址与端口（如 192.168.1.1:49170 audio, 192.168.1.1:51372 video）
    is_retransmission: bool  # 是否为重传消息
    src_ip_nat: str = ""  # 源 IP（NAT 前，Contact 头或 SDP 中的地址）
    src_port_nat: int = 0  # 源端口（NAT 前，Contact 头或 SDP 中的端口）
    dst_ip_nat: str = ""  # 目标 IP（NAT 前，Contact 头或 SDP 中的地址）
    dst_port_nat: int = 0  # 目标端口（NAT 前，Contact 头或 SDP 中的端口）
    audio_codecs: str = ""  # 音频编解码+PT，如 "PCMU/0, PCMA/8"
    video_codecs: str = ""  # 视频编解码+PT，如 "H264/96"


class SIPMessageTracker:
    """SIP 消息跟踪器"""
    
    def __init__(self, max_records: int = 10000):
        """
        初始化跟踪器
        
        Args:
            max_records: 最大记录数（超过后删除最旧的）
        """
        self.max_records = max_records
        self.records: List[SIPMessageRecord] = []
        self._lock = threading.Lock()
        self._id_counter = 0
        self._enabled = True
        self._subscribers: Set[Callable] = set()  # 订阅者集合
    
    def enable(self):
        """启用跟踪"""
        self._enabled = True
    
    def disable(self):
        """禁用跟踪"""
        self._enabled = False
    
    def is_enabled(self) -> bool:
        """是否启用"""
        return self._enabled
    
    def record_message(
        self,
        msg: SIPMessage,
        direction: str,  # "RX", "TX", "FWD"
        src_addr: Tuple[str, int],
        dst_addr: Optional[Tuple[str, int]] = None,
        full_message_bytes: Optional[bytes] = None,
    ):
        """
        记录一条 SIP 消息
        
        Args:
            msg: SIP 消息对象
            direction: 方向（"RX"接收, "TX"发送, "FWD"转发）
            src_addr: 源地址 (ip, port)
            dst_addr: 目标地址 (ip, port)，可选
            full_message_bytes: 完整消息字节（用于保存原始内容）
        """
        if not self._enabled:
            return
        
        record_dict = None
        try:
            with self._lock:
                self._id_counter += 1
                record_id = self._id_counter
                
                # 解析消息基本信息（任意请求方法/响应状态码均从 start_line 自动解析，无需写死）
                start_line = msg.start_line
                is_request = not start_line.startswith("SIP/2.0")
                
                if is_request:
                    method = start_line.split()[0] if start_line else ""
                    status_code = ""
                else:
                    method = ""
                    parts = start_line.split()
                    status_code = parts[1] if len(parts) > 1 else ""
                
                # 提取 From/To 用户
                from_header = msg.get("from") or ""
                to_header = msg.get("to") or ""
                from_user = self._extract_username(from_header)
                to_user = self._extract_username(to_header)
                from_tag = self._extract_tag(from_header)
                to_tag = self._extract_tag(to_header)
                
                # Call-ID
                call_id = msg.get("call-id") or ""
                
                # CSeq
                cseq = msg.get("cseq") or ""
                
                # Contact
                contact = msg.get("contact") or ""
                
                # User-Agent
                user_agent = msg.get("user-agent") or ""
                
                # Via/Route 数量
                via_count = len(msg.headers.get("via", []))
                route_count = len(msg.headers.get("route", []))
                
                # Via 头列表（用于提取响应消息的 NAT 前目标地址）
                via_headers = msg.headers.get("via", [])
                
                # Content-Length
                cl = msg.get("content-length") or "0"
                try:
                    content_length = int(cl)
                except:
                    content_length = len(msg.body) if msg.body else 0
                
                # 是否有 SDP
                has_sdp = content_length > 0 and (
                    b"v=0" in (msg.body if isinstance(msg.body, bytes) else msg.body.encode())
                    or "v=0" in (msg.body.decode('utf-8', errors='ignore') if isinstance(msg.body, bytes) else str(msg.body))
                )
                
                # 注册用户（REGISTER 时）
                registered_user = ""
                if method == "REGISTER":
                    registered_user = from_user
                
                # 被叫号码（INVITE 时）
                callee = ""
                if method == "INVITE":
                    # 从 To 头或 Request-URI 提取
                    callee = to_user or self._extract_username(start_line.split()[1] if len(start_line.split()) > 1 else "")
                
                # SDP 媒体地址与端口（c=IN IP4 + m=audio/video 端口）
                sdp_info = self._extract_sdp_info(msg) if has_sdp else ""
                # 音频/视频编解码与 payload type（从 a=rtpmap 解析）
                audio_codecs, video_codecs = self._extract_sdp_codecs(msg.body) if has_sdp and msg.body else ("", "")
                
                # 完整消息内容
                if full_message_bytes:
                    full_message = full_message_bytes.decode('utf-8', errors='ignore')
                else:
                    full_message = msg.to_bytes().decode('utf-8', errors='ignore')
                
                # 目标地址
                dst_ip, dst_port = dst_addr if dst_addr else (src_addr[0], src_addr[1])
                
                # 提取 NAT 前的地址（从 Contact 头、Via 头或 SDP 中提取）
                # NAT 后地址：UDP/IP 层的地址（数据包的源/目标地址）
                # NAT 前地址：SIP 消息中的地址（Contact 头、Via 头或 SDP 中的地址）
                try:
                    # 提取 Contact 头或 SDP 中的地址
                    contact_ip_nat, contact_port_nat = self._extract_nat_address(contact, msg.body if has_sdp else None)
                    
                    # 对于响应消息，从 Via 头提取 NAT 前的目标地址（RFC 3261：响应沿 Via 路径返回）
                    via_ip_nat, via_port_nat = self._extract_via_address(via_headers) if not is_request and via_headers else ("", 0)
                    
                    # 根据消息方向确定 NAT 前后地址的映射关系
                    if direction == "RX":
                        # 接收消息：Contact 头是发送方的 SIP 地址（NAT 前）
                        # src_addr 是发送方的 UDP 地址（NAT 后）
                        # dst_addr 是服务器的 UDP 地址（NAT 后，通常不需要 NAT）
                        src_ip_nat, src_port_nat = (contact_ip_nat, contact_port_nat)
                        dst_ip_nat, dst_port_nat = ("", 0)  # 服务器地址通常不需要 NAT
                    elif direction == "TX":
                        # 发送响应：Via 头是原始请求的发送方地址（NAT 前目标地址）
                        # Contact 头是响应方的地址（用于后续请求，如 ACK）
                        # src_addr 是服务器的 UDP 地址（NAT 后，通常不需要 NAT）
                        # dst_addr 是接收方的 UDP 地址（NAT 后）
                        src_ip_nat, src_port_nat = ("", 0)  # 服务器地址通常不需要 NAT
                        # 对于响应，NAT 前目标地址应该从 Via 头提取
                        if via_ip_nat:
                            dst_ip_nat, dst_port_nat = (via_ip_nat, via_port_nat)
                        else:
                            dst_ip_nat, dst_port_nat = (contact_ip_nat, contact_port_nat)  # 如果没有 Via，回退到 Contact
                    elif direction == "FWD":
                        # 转发消息
                        if is_request:
                            # 转发请求：Contact 是发送方的 SIP 地址（NAT 前）
                            src_ip_nat, src_port_nat = (contact_ip_nat, contact_port_nat)
                            dst_ip_nat, dst_port_nat = ("", 0)  # 目标地址从注册绑定中获取，通常不需要 NAT
                        else:
                            # 转发响应：Via 头是原始请求的发送方地址（NAT 前目标地址）
                            # Contact 头是响应方的地址
                            src_ip_nat, src_port_nat = ("", 0)  # 源地址是服务器，通常不需要 NAT
                            # 对于响应，NAT 前目标地址应该从 Via 头提取
                            if via_ip_nat:
                                dst_ip_nat, dst_port_nat = (via_ip_nat, via_port_nat)
                            else:
                                dst_ip_nat, dst_port_nat = (contact_ip_nat, contact_port_nat)  # 如果没有 Via，回退到 Contact
                    else:
                        # 未知方向，使用空值
                        src_ip_nat, src_port_nat = ("", 0)
                        dst_ip_nat, dst_port_nat = ("", 0)
                except Exception as e:
                    # 如果提取 NAT 地址失败，使用空值
                    log.debug(f"[SIP-TRACKER] 提取 NAT 地址失败: {e}")
                    src_ip_nat, src_port_nat = ("", 0)
                    dst_ip_nat, dst_port_nat = ("", 0)
                
                # 检测重传：检查最近 2 秒内是否有相同 Call-ID + CSeq + direction + 源地址的记录
                current_time = time.time()
                is_retransmission = False
                if call_id and cseq:
                    # 从后往前查找最近的记录（新记录在末尾）
                    for existing in reversed(self.records):
                        # 超过 2 秒，停止查找（重传通常在 500ms-2s 内）
                        if current_time - existing.timestamp > 2.0:
                            break
                        # 匹配条件：相同 Call-ID、CSeq、方向、源地址
                        if (existing.call_id == call_id and 
                            existing.cseq == cseq and 
                            existing.direction == direction and
                            existing.src_ip == src_addr[0] and
                            existing.src_port == src_addr[1] and
                            existing.method == (method or status_code)):
                            is_retransmission = True
                            break
                
                record = SIPMessageRecord(
                    id=record_id,
                    timestamp=current_time,
                    direction=direction,
                    method=method or status_code,
                    call_id=call_id,
                    from_user=from_user,
                    to_user=to_user,
                    from_tag=from_tag,
                    to_tag=to_tag,
                    src_ip=src_addr[0],
                    src_port=src_addr[1],
                    dst_ip=dst_ip,
                    dst_port=dst_port,
                    status_code=status_code,
                    cseq=cseq,
                    content_length=content_length,
                    has_sdp=has_sdp,
                    full_message=full_message,
                    via_count=via_count,
                    route_count=route_count,
                    contact=contact,
                    user_agent=user_agent,
                    registered_user=registered_user,
                    callee=callee,
                    sdp_info=sdp_info,
                    is_retransmission=is_retransmission,
                    src_ip_nat=src_ip_nat or "",
                    src_port_nat=src_port_nat or 0,
                    dst_ip_nat=dst_ip_nat or "",
                    dst_port_nat=dst_port_nat or 0,
                    audio_codecs=audio_codecs,
                    video_codecs=video_codecs,
                )
                
                self.records.append(record)
                
                # 限制记录数
                if len(self.records) > self.max_records:
                    self.records.pop(0)
                
                # 在锁内构建字典，锁外通知（避免回调阻塞其他 record_message）
                try:
                    record_dict = asdict(record)
                    record_dict['time_str'] = datetime.fromtimestamp(record.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                except RecursionError as re:
                    log.error(f"[SIP-TRACKER] 转换为字典时发生递归错误: {re}，跳过订阅者通知")
                    record_dict = None
                except Exception as e:
                    log.warning(f"[SIP-TRACKER] 转换为字典时发生错误: {e}")
                    record_dict = None
            
            # 锁外通知订阅者，确保 Web 实时推送不因持锁而丢失
            if record_dict is not None:
                try:
                    self._notify_subscribers(record_dict)
                except Exception as e:
                    log.warning(f"[SIP-TRACKER] 通知订阅者时发生错误: {e}")
        
        except Exception as e:
            log.warning(f"[SIP-TRACKER] 记录消息失败: {e}")
            import traceback
            log.debug(f"[SIP-TRACKER] 详细错误: {traceback.format_exc()}")
    
    def _extract_username(self, uri: str) -> str:
        """从 SIP URI 中提取用户名"""
        if not uri:
            return ""
        # 格式: <sip:1001@192.168.1.1> 或 sip:1001@192.168.1.1
        match = re.search(r'(?:sip:|tel:)([^@:;>\s]+)', uri, re.I)
        return match.group(1) if match else ""
    
    def _extract_tag(self, header: str) -> str:
        """从 From/To 头中提取 tag"""
        if not header:
            return ""
        match = re.search(r'tag=([^;>\s]+)', header, re.I)
        return match.group(1) if match else ""
    
    def _extract_via_address(self, via_headers: List[str]) -> Tuple[str, int]:
        """
        从 Via 头中提取地址（用于响应消息的 NAT 前目标地址）
        
        根据 RFC 3261，响应消息应该沿着请求的 Via 路径返回。
        Via 头中的地址是原始请求的发送方地址（NAT 前）。
        
        Args:
            via_headers: Via 头列表
        
        Returns:
            (ip, port) 元组，如果提取失败返回 ("", 0)
        """
        if not via_headers:
            return ("", 0)
        
        # 响应消息：从第一个 Via 头（最上面的）提取原始请求的发送方地址
        # Via 格式: SIP/2.0/UDP host:port;branch=xxx;rport
        # 或: SIP/2.0/UDP host:port;received=ip;rport=port;branch=xxx
        first_via = via_headers[0]
        
        # Via 头格式: SIP/2.0/UDP 192.168.100.104:64327;branch=z9hG4bK.ChCevZrlk;rport
        # 提取主地址（在分号之前）
        via_match = re.search(r'SIP/2\.0/[^;\s]+\s+([^:;\s]+):(\d+)', first_via, re.I)
        if via_match:
            ip = via_match.group(1)
            try:
                port = int(via_match.group(2))
                return (ip, port)
            except ValueError:
                pass
        
        # 如果没有匹配到，尝试更宽松的匹配
        via_match = re.search(r'([\d\.]+):(\d+)', first_via)
        if via_match:
            ip = via_match.group(1)
            try:
                port = int(via_match.group(2))
                return (ip, port)
            except ValueError:
                pass
        
        return ("", 0)
    
    def _extract_nat_address(self, contact_header: str, sdp_body: Optional[bytes] = None) -> Tuple[str, int]:
        """
        从 Contact 头或 SDP 中提取 NAT 前的地址
        
        Args:
            contact_header: Contact 头值
            sdp_body: SDP 消息体（可选）
        
        Returns:
            (ip, port) 元组，如果提取失败返回 ("", 0)
        """
        ip = ""
        port = 0
        
        # 优先从 Contact 头提取
        if contact_header:
            # 匹配格式: sip:user@IP:port 或 <sip:user@IP:port>
            match = re.search(r'@([^:;>]+):(\d+)', contact_header)
            if match:
                ip = match.group(1)
                try:
                    port = int(match.group(2))
                except ValueError:
                    pass
        
        # 如果 Contact 中没有，尝试从 SDP 中提取
        if not ip and sdp_body:
            try:
                text = sdp_body.decode("utf-8", errors="ignore") if isinstance(sdp_body, bytes) else str(sdp_body)
                lines = text.replace("\r\n", "\n").split("\n")
                for line in lines:
                    line = line.strip()
                    if line.startswith("c=IN IP4 "):
                        ip = line[9:].strip()
                        if " " in ip:
                            ip = ip.split()[0]
                        break
                    elif line.startswith("m=") and not port:
                        rest = line[2:].strip()
                        tok = rest.split()
                        if len(tok) >= 2:
                            try:
                                port = int(tok[1])
                            except ValueError:
                                pass
            except Exception:
                pass
        
        return (ip, port)
    
    def _extract_sdp_info(self, msg: "SIPMessage") -> str:
        """从消息体中提取 SDP：一个媒体地址(IP) + 各媒体端口，如 192.168.1.1 49170, 51372"""
        body = msg.body
        if not body:
            return ""
        try:
            text = body.decode("utf-8", errors="ignore") if isinstance(body, bytes) else str(body)
        except Exception:
            return ""
        lines = text.replace("\r\n", "\n").split("\n")
        conn_ip = ""
        ports = []
        for line in lines:
            line = line.strip()
            if line.startswith("c=IN IP4 "):
                conn_ip = line[9:].strip()
                if " " in conn_ip:
                    conn_ip = conn_ip.split()[0]
            elif line.startswith("m="):
                rest = line[2:].strip()
                tok = rest.split()
                if len(tok) >= 2:
                    try:
                        port = int(tok[1])
                        if port and (not ports or port != ports[-1]):
                            ports.append(port)
                    except ValueError:
                        pass
        if not conn_ip and not ports:
            return ""
        if not conn_ip:
            return ",".join(str(p) for p in ports)
        return f"{conn_ip} " + ",".join(str(p) for p in ports)
    
    def _extract_sdp_codecs(self, body) -> Tuple[str, str]:
        """从 SDP 消息体中解析 a=rtpmap，返回 (音频编解码列表, 视频编解码列表)，如 ("PCMU/0, PCMA/8", "H264/96")"""
        audio_list: List[str] = []
        video_list: List[str] = []
        try:
            text = body.decode("utf-8", errors="ignore") if isinstance(body, bytes) else str(body)
        except Exception:
            return ("", "")
        lines = text.replace("\r\n", "\n").split("\n")
        current_media: Optional[str] = None  # "audio" or "video"
        for line in lines:
            line = line.strip()
            if line.startswith("m=audio"):
                current_media = "audio"
            elif line.startswith("m=video"):
                current_media = "video"
            elif line.startswith("m="):
                current_media = None
            elif line.startswith("a=rtpmap:") and current_media:
                # 格式: a=rtpmap:96 H264/90000 或 a=rtpmap:0 PCMU/8000
                match = re.match(r"a=rtpmap:(\d+)\s+(\S+)", line)
                if match:
                    pt = match.group(1)
                    codec_slash = match.group(2)  # 如 H264/90000, PCMU/8000
                    codec = codec_slash.split("/")[0].strip() if "/" in codec_slash else codec_slash
                    entry = f"{codec}/{pt}"
                    if current_media == "audio" and entry not in audio_list:
                        audio_list.append(entry)
                    elif current_media == "video" and entry not in video_list:
                        video_list.append(entry)
        return (", ".join(audio_list), ", ".join(video_list))
    
    def get_records(
        self,
        limit: int = 1000,
        offset: int = 0,
        filters: Optional[Dict[str, str]] = None,
    ) -> Tuple[List[Dict], int]:
        """
        获取消息记录（支持过滤）
        
        Args:
            limit: 返回数量限制
            offset: 偏移量
            filters: 过滤条件 {字段名: 值}，支持部分匹配
        
        Returns:
            (记录列表, 总记录数)
        """
        with self._lock:
            records = list(self.records)
        
        # 应用过滤
        if filters:
            filtered = []
            for record in records:
                match = True
                for field, value in filters.items():
                    if not value:
                        continue
                    record_value = str(getattr(record, field, ""))
                    if value.lower() not in record_value.lower():
                        match = False
                        break
                if match:
                    filtered.append(record)
            records = filtered
        
        total = len(records)
        
        # 按时间戳和ID排序（从新到旧），使 offset=0 时取到的是“最近 limit 条”
        # 否则超过 1000 条时最新记录（如刚转发的 ACK FWD）会落在末尾被截掉，Web 上看不到
        records.sort(key=lambda r: (-r.timestamp, -r.id))
        records = records[offset:offset + limit]
        
        # 转换为字典（兼容旧记录缺少 audio_codecs/video_codecs）
        import dataclasses as dc
        result = []
        for r in records:
            d = {f.name: getattr(r, f.name, "" if f.name in ("audio_codecs", "video_codecs") else None) for f in dc.fields(r)}
            d['time_str'] = datetime.fromtimestamp(r.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            result.append(d)
        
        return result, total
    
    def get_message_by_id(self, msg_id: int) -> Optional[Dict]:
        """根据 ID 获取消息"""
        import dataclasses as dc
        with self._lock:
            for record in self.records:
                if record.id == msg_id:
                    d = {f.name: getattr(record, f.name, "" if f.name in ("audio_codecs", "video_codecs") else None) for f in dc.fields(record)}
                    d['time_str'] = datetime.fromtimestamp(record.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                    return d
        return None
    
    def clear(self):
        """清空所有记录"""
        with self._lock:
            self.records.clear()
            self._id_counter = 0
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._lock:
            total = len(self.records)
            rx_count = sum(1 for r in self.records if r.direction == "RX")
            tx_count = sum(1 for r in self.records if r.direction == "TX")
            fwd_count = sum(1 for r in self.records if r.direction == "FWD")
            
            methods = {}
            for r in self.records:
                m = r.method
                methods[m] = methods.get(m, 0) + 1
        
        return {
            "total": total,
            "rx": rx_count,
            "tx": tx_count,
            "fwd": fwd_count,
            "methods": methods,
        }
    
    def subscribe(self, callback: Callable):
        """订阅新消息通知"""
        with self._lock:
            self._subscribers.add(callback)
    
    def unsubscribe(self, callback: Callable):
        """取消订阅"""
        with self._lock:
            self._subscribers.discard(callback)
    
    def _notify_subscribers(self, record_dict: Dict):
        """通知所有订阅者（在锁外调用，避免死锁）"""
        subscribers = list(self._subscribers)  # 复制列表避免迭代时修改
        for callback in subscribers:
            try:
                callback(record_dict)
            except RecursionError as re:
                log.error(f"[SIP-TRACKER] 订阅者回调发生递归错误: {re}，跳过该订阅者")
                import traceback
                log.debug(f"[SIP-TRACKER] 递归错误详情: {traceback.format_exc()}")
            except Exception as e:
                log.warning(f"[SIP-TRACKER] 通知订阅者失败: {e}")


# 全局跟踪器实例
_tracker: Optional[SIPMessageTracker] = None


def get_tracker() -> Optional[SIPMessageTracker]:
    """获取全局跟踪器实例"""
    return _tracker


def init_tracker(max_records: int = 10000) -> SIPMessageTracker:
    """初始化跟踪器"""
    global _tracker
    _tracker = SIPMessageTracker(max_records=max_records)
    return _tracker
