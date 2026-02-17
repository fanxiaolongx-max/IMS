# sipcore/media_relay.py
"""
媒体中继模块 (B2BUA Media Relay)
实现 RTP/RTCP 的转发功能，支持对称RTP (Symmetric RTP)

功能：
1. RTP 端口分配管理
2. SDP 解析和修改
3. RTP 转发引擎
4. 媒体会话生命周期管理
"""

import socket
import threading
import re
import time
import asyncio
import sys
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass, field


@dataclass
class MediaSession:
    """媒体会话信息"""
    call_id: str
    # 主叫侧 (A-leg) - 音频端口（必须有，无默认值）
    a_leg_rtp_port: int
    a_leg_rtcp_port: int
    # 被叫侧 (B-leg) - 音频端口（必须有，无默认值）
    b_leg_rtp_port: int
    b_leg_rtcp_port: int
    
    # 主叫侧 (A-leg) - 视频端口（可选，有默认值）
    a_leg_video_rtp_port: Optional[int] = None
    a_leg_video_rtcp_port: Optional[int] = None
    # 被叫侧 (B-leg) - 视频端口（可选，有默认值）
    b_leg_video_rtp_port: Optional[int] = None
    b_leg_video_rtcp_port: Optional[int] = None
    
    # 主叫侧 - 音频信息（可选，有默认值）
    a_leg_remote_addr: Optional[Tuple[str, int]] = None  # 从SDP提取的音频地址
    a_leg_actual_addr: Optional[Tuple[str, int]] = None  # 对称RTP学习到的地址
    a_leg_sdp: Optional[str] = None  # 原始SDP
    a_leg_signaling_addr: Optional[Tuple[str, int]] = None  # 信令来源地址（优先使用）
    
    # 主叫侧 - 视频信息（可选，有默认值）
    a_leg_video_remote_addr: Optional[Tuple[str, int]] = None  # 从SDP提取的视频地址
    a_leg_video_actual_addr: Optional[Tuple[str, int]] = None  # 对称RTP学习到的视频地址
    
    # 被叫侧 - 音频信息（可选，有默认值）
    b_leg_remote_addr: Optional[Tuple[str, int]] = None
    b_leg_actual_addr: Optional[Tuple[str, int]] = None
    b_leg_sdp: Optional[str] = None
    b_leg_signaling_addr: Optional[Tuple[str, int]] = None  # 信令来源地址（优先使用）
    
    # 被叫侧 - 视频信息（可选，有默认值）
    b_leg_video_remote_addr: Optional[Tuple[str, int]] = None  # 从SDP提取的视频地址
    b_leg_video_actual_addr: Optional[Tuple[str, int]] = None  # 对称RTP学习到的视频地址
    
    # 状态（可选，有默认值）
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    
    # 统计（可选，有默认值）
    a_to_b_bytes: int = 0
    b_to_a_bytes: int = 0
    a_to_b_packets: int = 0
    b_to_a_packets: int = 0
    
    # 主被叫号码（可选，有默认值）
    caller_number: Optional[str] = None  # 主叫号码 (A-leg)
    callee_number: Optional[str] = None  # 被叫号码 (B-leg)
    
    def get_a_leg_target_addr(self) -> Optional[Tuple[str, int]]:
        """获取A-leg目标地址（优先使用信令地址）"""
        # 优先使用信令地址（NAT后的真实地址）
        if self.a_leg_signaling_addr:
            return self.a_leg_signaling_addr
        # 其次使用SDP地址
        return self.a_leg_remote_addr

    def get_a_leg_rtp_target_addr(self) -> Optional[Tuple[str, int]]:
        """获取发往 A-leg 的 RTP 目标地址（媒体必须发到 SDP 声明的 RTP 端口，不能发到信令端口）"""
        if not self.a_leg_remote_addr:
            return self.get_a_leg_target_addr()
        rtp_ip = self.a_leg_remote_addr[0]
        rtp_port = self.a_leg_remote_addr[1]
        # NAT 场景：使用信令侧的公网 IP + SDP 里的 RTP 端口
        if self.a_leg_signaling_addr:
            rtp_ip = self.a_leg_signaling_addr[0]
        return (rtp_ip, rtp_port)

    def get_b_leg_rtp_target_addr(self) -> Optional[Tuple[str, int]]:
        """获取发往 B-leg 的 RTP 目标地址（媒体必须发到 SDP 声明的 RTP 端口）"""
        if not self.b_leg_remote_addr:
            return self.get_b_leg_target_addr()
        rtp_ip = self.b_leg_remote_addr[0]
        rtp_port = self.b_leg_remote_addr[1]
        if self.b_leg_signaling_addr:
            rtp_ip = self.b_leg_signaling_addr[0]
        return (rtp_ip, rtp_port)
    
    def get_b_leg_target_addr(self) -> Optional[Tuple[str, int]]:
        """获取B-leg目标地址（优先使用信令地址）"""
        # 优先使用信令地址（NAT后的真实地址）
        if self.b_leg_signaling_addr:
            return self.b_leg_signaling_addr
        # 其次使用SDP地址
        return self.b_leg_remote_addr
    
    def get_a_leg_video_rtp_target_addr(self) -> Optional[Tuple[str, int]]:
        """获取发往 A-leg 的视频 RTP 目标地址"""
        if not self.a_leg_video_remote_addr:
            return None
        video_rtp_ip = self.a_leg_video_remote_addr[0]
        video_rtp_port = self.a_leg_video_remote_addr[1]
        # NAT 场景：使用信令侧的公网 IP + SDP 里的视频 RTP 端口
        if self.a_leg_signaling_addr:
            video_rtp_ip = self.a_leg_signaling_addr[0]
        return (video_rtp_ip, video_rtp_port)
    
    def get_b_leg_video_rtp_target_addr(self) -> Optional[Tuple[str, int]]:
        """获取发往 B-leg 的视频 RTP 目标地址"""
        if not self.b_leg_video_remote_addr:
            return None
        video_rtp_ip = self.b_leg_video_remote_addr[0]
        video_rtp_port = self.b_leg_video_remote_addr[1]
        # NAT 场景：使用信令侧的公网 IP + SDP 里的视频 RTP 端口
        if self.b_leg_signaling_addr:
            video_rtp_ip = self.b_leg_signaling_addr[0]
        return (video_rtp_ip, video_rtp_port)


class RTPPortManager:
    """RTP端口管理器"""
    
    # RTP端口范围 (偶数端口给RTP，奇数端口给RTCP)，常规媒体端口 20000 起
    RTP_PORT_START = 20000
    RTP_PORT_END = 30000
    
    def __init__(self):
        self._lock = threading.Lock()
        self._available_ports: List[int] = list(range(
            self.RTP_PORT_START, self.RTP_PORT_END, 2
        ))
        self._allocated_ports: Dict[int, str] = {}  # port -> call_id
        
    def allocate_port_pair(self, call_id: str) -> Optional[Tuple[int, int]]:
        """
        分配一对RTP/RTCP端口
        
        Returns:
            (rtp_port, rtcp_port) 或 None（端口耗尽）
        """
        with self._lock:
            if not self._available_ports:
                return None
            
            rtp_port = self._available_ports.pop(0)
            rtcp_port = rtp_port + 1
            
            self._allocated_ports[rtp_port] = call_id
            self._allocated_ports[rtcp_port] = call_id
            
            return rtp_port, rtcp_port
    
    def release_port_pair(self, rtp_port: int, rtcp_port: int):
        """释放端口对"""
        with self._lock:
            if rtp_port in self._allocated_ports:
                del self._allocated_ports[rtp_port]
            if rtcp_port in self._allocated_ports:
                del self._allocated_ports[rtcp_port]
            
            # 归还到可用池
            if rtp_port not in self._available_ports:
                self._available_ports.append(rtp_port)
                self._available_ports.sort()
    
    def get_stats(self) -> Dict:
        """获取端口使用统计"""
        with self._lock:
            total = (self.RTP_PORT_END - self.RTP_PORT_START) // 2
            used = len(self._allocated_ports) // 2
            return {
                'total_pairs': total,
                'used_pairs': used,
                'available_pairs': total - used
            }


class SDPProcessor:
    """SDP处理器"""
    
    @staticmethod
    def extract_media_info(sdp_body: str) -> Optional[Dict]:
        """
        从SDP中提取媒体信息（支持音频和视频）
        
        Returns:
            {
                'connection_ip': str,  # c= 行中的IP（会话级别）
                'audio_port': int,     # m=audio 行中的端口
                'audio_payloads': List[str],  # 音频支持的payload类型
                'audio_connection_ip': str,  # 音频媒体级别的c=行（如果有）
                'video_port': int,     # m=video 行中的端口
                'video_payloads': List[str],  # 视频支持的payload类型
                'video_connection_ip': str,  # 视频媒体级别的c=行（如果有）
                'codec_info': Dict[str, str]  # payload -> codec
            }
        """
        if not sdp_body:
            return None
        
        result = {
            'connection_ip': None,
            'audio_port': None,
            'audio_payloads': [],
            'audio_connection_ip': None,
            'video_port': None,
            'video_payloads': [],
            'video_connection_ip': None,
            'codec_info': {}
        }
        
        lines = sdp_body.split('\r\n') if '\r\n' in sdp_body else sdp_body.split('\n')
        
        current_media = None  # 跟踪当前处理的媒体类型 (audio/video)
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # 解析 c= 行 (连接信息)
            # 格式: c=IN IP4 192.168.1.100
            if line.startswith('c='):
                parts = line[2:].split()
                if len(parts) >= 3 and parts[1] == 'IP4':
                    ip_addr = parts[2]
                    if current_media == 'audio':
                        result['audio_connection_ip'] = ip_addr
                    elif current_media == 'video':
                        result['video_connection_ip'] = ip_addr
                    elif current_media is None:
                        # 会话级别的 c= 行（在第一个 m= 行之前）
                        result['connection_ip'] = ip_addr
            
            # 解析 m=audio 行 (音频媒体描述)
            # 格式: m=audio 49170 RTP/AVP 0 8 18
            elif line.startswith('m=audio '):
                current_media = 'audio'
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        result['audio_port'] = int(parts[1])
                        result['audio_payloads'] = parts[3:]
                    except ValueError:
                        pass
            
            # 解析 m=video 行 (视频媒体描述)
            # 格式: m=video 51372 RTP/AVP 96 97
            elif line.startswith('m=video '):
                current_media = 'video'
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        result['video_port'] = int(parts[1])
                        result['video_payloads'] = parts[3:]
                    except ValueError:
                        pass
            
            # 解析 a=rtpmap 行 (编解码映射)
            # 格式: a=rtpmap:0 PCMU/8000 或 a=rtpmap:96 H264/90000
            elif line.startswith('a=rtpmap:'):
                match = re.match(r'a=rtpmap:(\d+)\s+(.+)', line)
                if match:
                    payload = match.group(1)
                    codec_info = match.group(2)
                    result['codec_info'][payload] = codec_info
        
        # 如果没有音频端口，认为无效
        return result if result['audio_port'] else None
    
    @staticmethod
    def modify_sdp(sdp_body: str, new_ip: str, new_audio_port: int, 
                   new_video_port: Optional[int] = None, force_plain_rtp: bool = False) -> str:
        """
        修改SDP中的IP地址和端口（支持音频和视频）
        
        Args:
            sdp_body: 原始SDP
            new_ip: 新的IP地址
            new_audio_port: 新的音频RTP端口
            new_video_port: 新的视频RTP端口（可选，如果SDP包含视频流）
            force_plain_rtp: 是否强制使用普通RTP（移除SRTP加密行）
                             默认 False: 保持原始的 RTP/SAVP 或 RTP/AVP 不变（推荐）
                             True: 强制改为 RTP/AVP 并删除 crypto 行（会导致 SRTP 终端无法通话）
            
        Returns:
            修改后的SDP
            
        业界最佳实践：
        - B2BUA 做媒体中继时，只修改 c= (IP) 和 m= (端口号)，保持协议类型不变
        - 保留 RTP/SAVP 和 a=crypto 行，让两端直接协商加密参数
        - 服务器只做 UDP 包转发，不需要理解 SRTP 加密内容
        - RTP 包头（SSRC、sequence、timestamp 等）也无需修改，直接透传
        """
        if not sdp_body:
            return sdp_body
        
        lines = sdp_body.split('\r\n') if '\r\n' in sdp_body else sdp_body.split('\n')
        new_lines = []
        
        for line in lines:
            line = line.rstrip()
            if not line:
                continue
            
            # 修改 c= 行（只改 IP 地址）
            if line.startswith('c='):
                parts = line[2:].split()
                if len(parts) >= 3 and parts[1] == 'IP4':
                    line = f"c=IN IP4 {new_ip}"
            
            # 修改 m=audio 行（只改端口号，保留原始协议类型 RTP/AVP 或 RTP/SAVP）
            elif line.startswith('m=audio '):
                parts = line.split()
                if len(parts) >= 4:
                    # 保持原始协议类型（RTP/AVP 或 RTP/SAVP），只修改端口
                    proto = parts[2]  # 保留原始协议: RTP/AVP 或 RTP/SAVP
                    payloads = ' '.join(parts[3:])
                    if force_plain_rtp:
                        proto = "RTP/AVP"  # 强制降级（不推荐）
                    line = f"m=audio {new_audio_port} {proto} {payloads}"
            
            # 修改 m=video 行（只改端口号，保留原始协议类型）
            elif line.startswith('m=video '):
                parts = line.split()
                if len(parts) >= 4 and new_video_port is not None:
                    # 保持原始协议类型，只修改端口
                    proto = parts[2]  # 保留原始协议: RTP/AVP 或 RTP/SAVP
                    payloads = ' '.join(parts[3:])
                    if force_plain_rtp:
                        proto = "RTP/AVP"  # 强制降级（不推荐）
                    line = f"m=video {new_video_port} {proto} {payloads}"
            
            # 跳过 SRTP 加密属性行（仅在强制使用普通RTP时）
            elif force_plain_rtp and (line.startswith('a=crypto:') or line.startswith('a=fingerprint:')):
                continue
            
            new_lines.append(line)
        
        # 确保使用 \r\n 作为行分隔符 (SIP标准)
        return '\r\n'.join(new_lines) + '\r\n'


class SinglePortMediaForwarder:
    """
    单端口双向 RTP 转发器（核心改进）
    
    主叫和被叫都向同一个端口发送 RTP，根据源地址区分方向：
    - 来自主叫的包 → 转发给被叫
    - 来自被叫的包 → 转发给主叫
    
    优势（相比双端口模式）：
    1. 避免 A-leg 端口被防火墙/安全组阻断的问题
    2. 两端看到的源端口一致（都是同一个端口），NAT 穿越更简单
    3. 端口消耗减半
    """
    
    SILENCE_RTP = (
        b'\x80\x00'
        b'\x00\x01'
        b'\x00\x00\x00\xa0'
        b'\x00\x00\x00\x00'
        + b'\xff' * 160
    )
    
    def __init__(self, local_port: int,
                 caller_target: Tuple[str, int],
                 callee_target: Tuple[str, int],
                 caller_expected_ip: Optional[str] = None,
                 callee_expected_ip: Optional[str] = None,
                 call_name: str = ""):
        self.local_port = local_port
        self.caller_target = caller_target
        self.callee_target = callee_target
        self.caller_expected_ip = caller_expected_ip
        self.callee_expected_ip = callee_expected_ip
        self.call_name = call_name or f"port-{local_port}"
        
        # 保存目标端口，用于同IP时的端口匹配
        self.caller_target_port = caller_target[1] if caller_target else None
        self.callee_target_port = callee_target[1] if callee_target else None
        
        self.sock: Optional[socket.socket] = None
        self.running = False
        self.thread: Optional[threading.Thread] = None
        
        self.caller_latched = False
        self.callee_latched = False
        self.caller_actual_addr: Optional[Tuple[str, int]] = None
        self.callee_actual_addr: Optional[Tuple[str, int]] = None
        
        self.caller_to_callee_packets = 0
        self.callee_to_caller_packets = 0
        self.unknown_packets = 0
        self.total_bytes = 0
        
        self._last_log_time = 0
        self._last_a2b = 0
        self._last_b2a = 0
        self._last_punch_time = 0
        self._punch_count = 0
    
    def start(self):
        if self.running:
            return
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('0.0.0.0', self.local_port))
        self.sock.settimeout(1.0)
        self.running = True
        self.thread = threading.Thread(target=self._forward_loop, daemon=True)
        self.thread.start()
    
    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
        if self.thread:
            self.thread.join(timeout=2.0)
            self.thread = None
    
    def send_nat_punch(self, count: int = 10, interval: float = 0.02):
        """向两端发送 NAT 打洞包"""
        if not self.sock or not self.running:
            return
        for target, name in [(self.callee_target, "被叫"),
                             (self.caller_target, "主叫")]:
            if not target:
                continue
            print(f"[RTP-PUNCH] {self.call_name}(:{self.local_port}): "
                  f"→{name} {target} x{count}",
                  file=sys.stderr, flush=True)
            for i in range(count):
                try:
                    self.sock.sendto(self.SILENCE_RTP, target)
                    if interval > 0 and i < count - 1:
                        time.sleep(interval)
                except Exception as e:
                    print(f"[RTP-PUNCH-ERR] {self.call_name}: → {target}: {e}",
                          file=sys.stderr, flush=True)
                    break
    
    def send_aggressive_nat_punch(self, base_port: int, port_range: int = 10):
        """
        激进的NAT打洞：尝试多个端口范围
        用于主叫NAT端口映射不确定的情况
        """
        if not self.sock or not self.running or not self.caller_target:
            return
        
        caller_ip = self.caller_target[0]
        base = self.caller_target[1]
        
        print(f"[RTP-PUNCH-AGGR] {self.call_name}: 激进打洞 →主叫 {caller_ip}:{base}±{port_range}",
              file=sys.stderr, flush=True)
        
        # 尝试基础端口和周围端口
        ports_to_try = [base] + [base + i for i in range(1, port_range + 1)] + [base - i for i in range(1, port_range + 1)]
        
        for port in ports_to_try:
            if port < 1024 or port > 65535:
                continue
            try:
                self.sock.sendto(self.SILENCE_RTP, (caller_ip, port))
            except Exception as e:
                pass  # 忽略错误，继续尝试
    
    def update_targets(self, caller_target: Tuple[str, int],
                       callee_target: Tuple[str, int]):
        """更新目标地址（re-INVITE 场景）"""
        self.caller_target = caller_target
        self.callee_target = callee_target
        self.caller_target_port = caller_target[1] if caller_target else None
        self.callee_target_port = callee_target[1] if callee_target else None
        self.caller_latched = False
        self.callee_latched = False
        self.caller_actual_addr = None
        self.callee_actual_addr = None
        print(f"[RTP-RELEARN] {self.call_name}(:{self.local_port}): "
              f"重置LATCH, 新目标: 主叫{caller_target} 被叫{callee_target}",
              file=sys.stderr, flush=True)
    
    def _classify_source(self, addr: Tuple[str, int]) -> str:
        """
        判断 RTP 包来自主叫还是被叫（简化逻辑，更宽松）
        
        策略（按优先级）：
        1. 已 LATCH 的精确地址匹配
        2. 期望 IP 匹配（信令地址）
        3. 排除法（一方已 LATCH，另一方未知则是新的那方）
        4. 首包归被叫（B2BUA 中被叫通常先发 RTP）
        """
        # 精确匹配已学习的地址
        if self.callee_actual_addr and addr == self.callee_actual_addr:
            return "callee"
        if self.caller_actual_addr and addr == self.caller_actual_addr:
            return "caller"
        
        src_ip = addr[0]
        
        # IP 匹配（放宽：只要IP匹配就接受，不要求精确）
        if self.callee_expected_ip and src_ip == self.callee_expected_ip:
            if not self.caller_expected_ip or src_ip != self.caller_expected_ip:
                return "callee"
        if self.caller_expected_ip and src_ip == self.caller_expected_ip:
            if not self.callee_expected_ip or src_ip != self.callee_expected_ip:
                return "caller"
        
        # 排除法：如果一方已LATCH，新包来自另一方
        if self.callee_latched and not self.caller_latched:
            return "caller"
        if self.caller_latched and not self.callee_latched:
            return "callee"
        
        # 首包默认归被叫（被叫通常先发RTP）
        if not self.callee_latched:
            return "callee"
        
        # 如果双方都已LATCH但地址不匹配，记录为未知
        return "unknown"
    
    def _log_stats(self):
        now = time.time()
        if now - self._last_log_time >= 5:
            a2b_diff = self.caller_to_callee_packets - self._last_a2b
            b2a_diff = self.callee_to_caller_packets - self._last_b2a
            cs = "✓" if self.caller_latched else "✗"
            bs = "✓" if self.callee_latched else "✗"
            total = self.caller_to_callee_packets + self.callee_to_caller_packets
            if total > 0 or a2b_diff > 0 or b2a_diff > 0:
                print(f"[RTP-STATS] {self.call_name}(:{self.local_port}): "
                      f"A→B:{self.caller_to_callee_packets}(+{a2b_diff}) "
                      f"B→A:{self.callee_to_caller_packets}(+{b2a_diff}) "
                      f"主叫{cs}{self.caller_actual_addr or self.caller_target} "
                      f"被叫{bs}{self.callee_actual_addr or self.callee_target}",
                      file=sys.stderr, flush=True)
            elif total == 0 and now - self._last_log_time >= 10:
                print(f"[RTP-WARN] {self.call_name}(:{self.local_port}): "
                      f"⚠️ 10s无收包! 主叫{cs}{self.caller_target} "
                      f"被叫{bs}{self.callee_target}",
                      file=sys.stderr, flush=True)
            self._last_log_time = now
            self._last_a2b = self.caller_to_callee_packets
            self._last_b2a = self.callee_to_caller_packets
    
    def _forward_loop(self):
        print(f"[RTP-SINGLE] {self.call_name} 单端口转发器启动: 端口{self.local_port}",
              file=sys.stderr, flush=True)
        print(f"  主叫初始目标: {self.caller_target} (期望IP: {self.caller_expected_ip})",
              file=sys.stderr, flush=True)
        print(f"  被叫初始目标: {self.callee_target} (期望IP: {self.callee_expected_ip})",
              file=sys.stderr, flush=True)
        
        while self.running and self.sock:
            try:
                data, addr = self.sock.recvfrom(2048)
                if len(data) < 12:
                    continue
                
                self.total_bytes += len(data)
                source = self._classify_source(addr)
                
                if source == "callee":
                    if not self.callee_latched:
                        self.callee_actual_addr = addr
                        self.callee_latched = True
                        print(f"[RTP-LATCH] {self.call_name}(:{self.local_port}): "
                              f"✓ 被叫LATCH: {addr}",
                              file=sys.stderr, flush=True)
                    target = self.caller_actual_addr or self.caller_target
                    if target:
                        try:
                            self.sock.sendto(data, target)
                            self.callee_to_caller_packets += 1
                            # 每100包记录一次转发详情（调试用）
                            if self.callee_to_caller_packets % 100 == 0:
                                print(f"[RTP-FWD] {self.call_name}: 被叫→主叫 #{self.callee_to_caller_packets} "
                                      f"目标={target} (LATCH={'✓' if self.caller_latched else '✗'})",
                                      file=sys.stderr, flush=True)
                            
                            # 如果主叫未LATCH，每次转发被叫包时也发送一个打洞包（更激进）
                            if not self.caller_latched and self.callee_to_caller_packets % 50 == 0:
                                try:
                                    self.sock.sendto(self.SILENCE_RTP, self.caller_target)
                                    if self.callee_to_caller_packets % 100 == 0:
                                        print(f"[RTP-PUNCH-AGGR] {self.call_name}: 转发时打洞 →主叫{self.caller_target}",
                                              file=sys.stderr, flush=True)
                                except Exception:
                                    pass
                        except Exception as e:
                            print(f"[RTP-ERROR] {self.call_name}: →主叫{target}: {e}",
                                  file=sys.stderr, flush=True)
                    else:
                        print(f"[RTP-ERROR] {self.call_name}: 被叫包无目标地址！主叫LATCH={self.caller_latched}",
                              file=sys.stderr, flush=True)
                
                elif source == "caller":
                    if not self.caller_latched:
                        self.caller_actual_addr = addr
                        self.caller_latched = True
                        print(f"[RTP-LATCH] {self.call_name}(:{self.local_port}): "
                              f"✓ 主叫LATCH: {addr}",
                              file=sys.stderr, flush=True)
                        # 主叫LATCH成功后，立即更新被叫的转发目标
                        if self.callee_latched:
                            print(f"[RTP-UPDATE] {self.call_name}: 主叫LATCH成功，被叫转发目标已更新为 {addr}",
                                  file=sys.stderr, flush=True)
                    target = self.callee_actual_addr or self.callee_target
                    if target:
                        try:
                            self.sock.sendto(data, target)
                            self.caller_to_callee_packets += 1
                        except Exception as e:
                            print(f"[RTP-ERROR] {self.call_name}: →被叫{target}: {e}",
                                  file=sys.stderr, flush=True)
                
                else:
                    self.unknown_packets += 1
                    # 未知包：尝试根据IP匹配（放宽策略）
                    src_ip = addr[0]
                    if self.caller_expected_ip and src_ip == self.caller_expected_ip:
                        # 可能是主叫（即使IP匹配但之前没LATCH）
                        if not self.caller_latched:
                            self.caller_actual_addr = addr
                            self.caller_latched = True
                            print(f"[RTP-LATCH-AUTO] {self.call_name}(:{self.local_port}): "
                                  f"✓ 主叫自动LATCH（IP匹配）: {addr}",
                                  file=sys.stderr, flush=True)
                            target = self.callee_actual_addr or self.callee_target
                            if target:
                                try:
                                    self.sock.sendto(data, target)
                                    self.caller_to_callee_packets += 1
                                except Exception as e:
                                    print(f"[RTP-ERROR] {self.call_name}: →被叫{target}: {e}",
                                          file=sys.stderr, flush=True)
                    elif self.unknown_packets <= 5:
                        print(f"[RTP-UNKNOWN] {self.call_name}(:{self.local_port}): "
                              f"未知源 {addr}, 已知: 主叫={self.caller_actual_addr}(期望IP:{self.caller_expected_ip}) "
                              f"被叫={self.callee_actual_addr}(期望IP:{self.callee_expected_ip})",
                              file=sys.stderr, flush=True)
                
                self._log_stats()
                
                # 如果主叫未LATCH，持续发送打洞包（每2秒一次，最多30次）
                if not self.caller_latched and self.caller_target:
                    now = time.time()
                    if now - self._last_punch_time >= 2.0 and self._punch_count < 30:
                        self._last_punch_time = now
                        self._punch_count += 1
                        try:
                            self.sock.sendto(self.SILENCE_RTP, self.caller_target)
                            if self._punch_count % 5 == 0:
                                print(f"[RTP-PUNCH-CONT] {self.call_name}: 持续打洞 #{self._punch_count} →主叫{self.caller_target}",
                                      file=sys.stderr, flush=True)
                        except Exception:
                            pass
                
            except socket.timeout:
                self._log_stats()
                
                # timeout时也检查是否需要打洞
                if not self.caller_latched and self.caller_target:
                    now = time.time()
                    if now - self._last_punch_time >= 2.0 and self._punch_count < 30:
                        self._last_punch_time = now
                        self._punch_count += 1
                        try:
                            self.sock.sendto(self.SILENCE_RTP, self.caller_target)
                            if self._punch_count % 5 == 0:
                                print(f"[RTP-PUNCH-CONT] {self.call_name}: 持续打洞 #{self._punch_count} →主叫{self.caller_target}",
                                      file=sys.stderr, flush=True)
                        except Exception:
                            pass
                
                continue
            except Exception as e:
                if self.running:
                    print(f"[RTP-ERROR] {self.call_name}(:{self.local_port}): {e}",
                          file=sys.stderr, flush=True)


class MediaRelay:
    """
    媒体中继管理器（B2BUA 模式）
    管理所有呼叫的 RTP 转发，使主被叫的媒体都经服务器中继，便于 NAT 穿透。
    
    数据流（只启动一次，由首次 200 OK 触发）：
    - 主叫(A) RTP -> 发到 服务器 A-leg 端口 -> 转发器 A->B -> 发到 被叫(B) 的 RTP 地址（SDP 端口）
    - 被叫(B) RTP -> 发到 服务器 B-leg 端口 -> 转发器 B->A -> 发到 主叫(A) 的 RTP 地址（SDP 端口）
    目标地址必须用 SDP 中的 RTP 端口（get_*_rtp_target_addr），不能用信令端口。
    同一 INVITE 的 200 OK 只触发一次 start_media_forwarding，避免重传 200 导致主叫收两份响应转圈。
    
    NAT 处理策略：
    1. 优先使用信令地址（NAT后的公网IP）作为目标IP
    2. 使用SDP中声明的RTP端口作为目标端口
    3. 支持对称RTP学习，自动学习真实的媒体源地址
    """
    
    def __init__(self, server_ip: str):
        """
        初始化媒体中继
        
        Args:
            server_ip: 服务器IP地址（用于SDP中声明）
        """
        self.server_ip = server_ip
        self.port_manager = RTPPortManager()
        self.sdp_processor = SDPProcessor()
        
        # 会话管理: call_id -> MediaSession
        self._sessions: Dict[str, MediaSession] = {}
        # 端口到会话的映射: port -> (call_id, leg)
        self._port_session_map: Dict[int, Tuple[str, str]] = {}
        
        self._lock = threading.Lock()
        
        # 转发器管理: (call_id, leg, direction) -> RTPForwarder
        self._forwarders: Dict[Tuple[str, str, str], RTPForwarder] = {}
        
        print(f"[MediaRelay] 初始化完成，服务器IP: {server_ip}")
    
    def create_session(self, call_id: str) -> Optional[MediaSession]:
        """
        创建新的媒体会话
        
        Returns:
            MediaSession 对象，如果端口分配失败返回None
        """
        # 分配两对端口（A-leg和B-leg）
        a_ports = self.port_manager.allocate_port_pair(call_id)
        if not a_ports:
            print(f"[MediaRelay] 端口分配失败 (A-leg): {call_id}")
            return None
        
        b_ports = self.port_manager.allocate_port_pair(call_id)
        if not b_ports:
            # 释放A-leg端口
            self.port_manager.release_port_pair(a_ports[0], a_ports[1])
            print(f"[MediaRelay] 端口分配失败 (B-leg): {call_id}")
            return None
        
        session = MediaSession(
            call_id=call_id,
            a_leg_rtp_port=a_ports[0],
            a_leg_rtcp_port=a_ports[1],
            b_leg_rtp_port=b_ports[0],
            b_leg_rtcp_port=b_ports[1]
        )
        
        with self._lock:
            self._sessions[call_id] = session
            self._port_session_map[a_ports[0]] = (call_id, 'a')
            self._port_session_map[a_ports[1]] = (call_id, 'a')
            self._port_session_map[b_ports[0]] = (call_id, 'b')
            self._port_session_map[b_ports[1]] = (call_id, 'b')
        
        print(f"[MediaRelay] 创建会话: {call_id}")
        print(f"  A-leg: RTP={a_ports[0]}, RTCP={a_ports[1]}")
        print(f"  B-leg: RTP={b_ports[0]}, RTCP={b_ports[1]}")
        
        return session
    
    def process_invite_sdp(self, call_id: str, sdp_body: str, 
                           caller_addr: Tuple[str, int]) -> Tuple[str, Optional[MediaSession]]:
        """
        处理INVITE的SDP（主叫侧）
        
        Args:
            call_id: 呼叫ID
            sdp_body: 原始SDP
            caller_addr: 主叫信令地址
            
        Returns:
            (修改后的SDP, MediaSession对象)
        """
        # 获取或创建会话
        session = self._sessions.get(call_id)
        if not session:
            session = self.create_session(call_id)
            if not session:
                return sdp_body, None
        
        # 提取原始媒体信息
        media_info = self.sdp_processor.extract_media_info(sdp_body)
        if media_info:
            session.a_leg_remote_addr = (media_info['connection_ip'], media_info['audio_port'])
            session.a_leg_sdp = sdp_body
            print(f"[MediaRelay] A-leg媒体信息: {session.a_leg_remote_addr}")
        
        # 修改SDP（指向A-leg端口，给主叫用的）
        new_sdp = self.sdp_processor.modify_sdp(
            sdp_body, 
            self.server_ip, 
            session.a_leg_rtp_port
        )
        
        return new_sdp, session
    
    def process_invite_to_callee(self, call_id: str, sdp_body: str,
                                  caller_addr: Tuple[str, int],
                                  caller_number: Optional[str] = None,
                                  callee_number: Optional[str] = None) -> Tuple[str, Optional[MediaSession]]:
        """
        处理转发给被叫的INVITE SDP
        修改SDP指向服务器的B-leg端口，让被叫发送RTP到B-leg端口
        同时保存A-leg的媒体信息和信令地址
        
        Args:
            call_id: 呼叫ID
            sdp_body: 原始SDP
            caller_addr: 主叫信令地址（NAT后的真实地址）
            caller_number: 主叫号码 (A-leg)
            callee_number: 被叫号码 (B-leg)
            
        Returns:
            (修改后的SDP, MediaSession对象)
        """
        # 获取或创建会话
        session = self._sessions.get(call_id)
        if not session:
            session = self.create_session(call_id)
            if not session:
                return sdp_body, None
        
        # 保存主被叫号码
        if caller_number:
            session.caller_number = caller_number
        if callee_number:
            session.callee_number = callee_number
        
        # 保存A-leg信令地址（优先使用，NAT后的真实地址）
        # 使用信令来源端口+1作为RTP端口估计（标准RTP端口是SDP端口+0）
        session.a_leg_signaling_addr = caller_addr
        print(f"[MediaRelay] A-leg信令地址: {caller_addr} (NAT后真实地址)")
        
        # 提取A-leg原始媒体信息（SDP中声明的地址）
        media_info = self.sdp_processor.extract_media_info(sdp_body)
        if media_info:
            # 保存音频信息
            audio_ip = media_info.get('audio_connection_ip') or media_info.get('connection_ip')
            session.a_leg_remote_addr = (audio_ip, media_info['audio_port'])
            session.a_leg_sdp = sdp_body
            print(f"[MediaRelay] A-leg音频信息: {session.a_leg_remote_addr}")
            
            # 检测并处理视频流
            if media_info.get('video_port'):
                # 动态分配视频端口（如果还没有分配）
                if not session.a_leg_video_rtp_port or not session.b_leg_video_rtp_port:
                    a_video_ports = self.port_manager.allocate_port_pair(call_id)
                    b_video_ports = self.port_manager.allocate_port_pair(call_id)
                    
                    if a_video_ports and b_video_ports:
                        session.a_leg_video_rtp_port = a_video_ports[0]
                        session.a_leg_video_rtcp_port = a_video_ports[1]
                        session.b_leg_video_rtp_port = b_video_ports[0]
                        session.b_leg_video_rtcp_port = b_video_ports[1]
                        
                        print(f"[MediaRelay] 检测到视频流，分配视频端口:")
                        print(f"  A-leg视频: RTP={a_video_ports[0]}, RTCP={a_video_ports[1]}")
                        print(f"  B-leg视频: RTP={b_video_ports[0]}, RTCP={b_video_ports[1]}")
                    else:
                        print(f"[MediaRelay-WARNING] 视频端口分配失败，将只处理音频: {call_id}")
                
                # 保存视频信息
                video_ip = media_info.get('video_connection_ip') or media_info.get('connection_ip')
                session.a_leg_video_remote_addr = (video_ip, media_info['video_port'])
                print(f"[MediaRelay] A-leg视频信息: {session.a_leg_video_remote_addr}")
        
        # 修改SDP（指向B-leg端口，给被叫用的）
        new_sdp = self.sdp_processor.modify_sdp(
            sdp_body,
            self.server_ip,
            session.b_leg_rtp_port,
            new_video_port=session.b_leg_video_rtp_port  # 传递视频端口（如果有）
        )
        
        print(f"[MediaRelay] INVITE转发给被叫，SDP修改为B-leg端口: 音频={session.b_leg_rtp_port}", end='')
        if session.b_leg_video_rtp_port:
            print(f", 视频={session.b_leg_video_rtp_port}")
        else:
            print()
        return new_sdp, session
    
    def process_answer_sdp(self, call_id: str, sdp_body: str,
                          callee_addr: Tuple[str, int]) -> Tuple[str, bool]:
        """
        处理200 OK的SDP（被叫侧）
        修改SDP指向服务器的A-leg端口，让主叫发送RTP到A-leg端口
        同时保存B-leg的信令地址
        
        Args:
            call_id: 呼叫ID
            sdp_body: 原始SDP
            callee_addr: 被叫信令地址（NAT后的真实地址）
            
        Returns:
            (修改后的SDP, 是否成功)
        """
        session = self._sessions.get(call_id)
        if not session:
            print(f"[MediaRelay] 会话不存在: {call_id}")
            return sdp_body, False
        
        # 保存B-leg信令地址（优先使用，NAT后的真实地址）
        session.b_leg_signaling_addr = callee_addr
        print(f"[MediaRelay] B-leg信令地址: {callee_addr} (NAT后真实地址)")
        
        # 提取被叫媒体信息（SDP中声明的地址）
        media_info = self.sdp_processor.extract_media_info(sdp_body)
        if media_info:
            # 保存音频信息
            audio_ip = media_info.get('audio_connection_ip') or media_info.get('connection_ip')
            session.b_leg_remote_addr = (audio_ip, media_info['audio_port'])
            session.b_leg_sdp = sdp_body
            print(f"[MediaRelay] B-leg音频信息: {session.b_leg_remote_addr}")
            
            # 检测并处理视频流
            if media_info.get('video_port'):
                video_ip = media_info.get('video_connection_ip') or media_info.get('connection_ip')
                session.b_leg_video_remote_addr = (video_ip, media_info['video_port'])
                print(f"[MediaRelay] B-leg视频信息: {session.b_leg_video_remote_addr}")
        
        # 修改SDP（使用B-leg端口——与INVITE SDP相同端口）
        # 关键改进：主叫和被叫共享同一个RTP端口，避免A-leg端口被防火墙阻断
        new_sdp = self.sdp_processor.modify_sdp(
            sdp_body,
            self.server_ip,
            session.b_leg_rtp_port,
            new_video_port=session.b_leg_video_rtp_port  # 传递视频端口（如果有）
        )
        
        print(f"[MediaRelay] 200OK发给主叫，SDP修改为共享端口: 音频={session.b_leg_rtp_port}", end='')
        if session.b_leg_video_rtp_port:
            print(f", 视频={session.b_leg_video_rtp_port}")
        else:
            print()
        return new_sdp, True
    
    def start_media_forwarding(self, call_id: str):
        """
        启动媒体转发（单端口模式）
        
        核心改进：主叫和被叫共用一个 RTP 端口（B-leg 端口），根据源地址区分方向。
        解决了原双端口模式中 A-leg 端口可能被防火墙/安全组阻断的问题。
        """
        session = self._sessions.get(call_id)
        if not session:
            print(f"[MediaRelay] 无法启动转发，会话不存在: {call_id}", flush=True)
            return False
        
        if not session.a_leg_remote_addr or not session.b_leg_remote_addr:
            print(f"[MediaRelay] 无法启动转发，媒体地址不完整: {call_id}", flush=True)
            print(f"  A-leg地址: {session.a_leg_remote_addr}", flush=True)
            print(f"  B-leg地址: {session.b_leg_remote_addr}", flush=True)
            return False
        
        a_leg_target = session.get_a_leg_rtp_target_addr()
        b_leg_target = session.get_b_leg_rtp_target_addr()
        
        if not a_leg_target or not b_leg_target:
            print(f"[MediaRelay] 无法启动转发，目标地址不完整: {call_id}", flush=True)
            return False
        
        if a_leg_target == b_leg_target:
            print(f"[MediaRelay-ERROR] 目标地址相同，会导致环回！"
                  f" A={a_leg_target} B={b_leg_target}", flush=True)
            return False
        
        # re-INVITE 场景：更新已有转发器的目标
        if session.started_at:
            print(f"[MediaRelay] re-INVITE 更新目标: {call_id}")
            fwd = self._forwarders.get((call_id, 'single', 'rtp'))
            if fwd:
                fwd.update_targets(a_leg_target, b_leg_target)
            fwd_rtcp = self._forwarders.get((call_id, 'single', 'rtcp'))
            if fwd_rtcp:
                fwd_rtcp.update_targets(
                    (a_leg_target[0], a_leg_target[1] + 1),
                    (b_leg_target[0], b_leg_target[1] + 1))
            return True
        
        import sys
        caller = session.caller_number or "A"
        callee = session.callee_number or "B"
        
        a_expected_ip = session.a_leg_signaling_addr[0] if session.a_leg_signaling_addr else (
            session.a_leg_remote_addr[0] if session.a_leg_remote_addr else None)
        b_expected_ip = session.b_leg_signaling_addr[0] if session.b_leg_signaling_addr else (
            session.b_leg_remote_addr[0] if session.b_leg_remote_addr else None)
        
        print(f"[MediaRelay] 启动单端口媒体转发: {call_id}", file=sys.stderr, flush=True)
        print(f"  主叫({caller}): 信令={session.a_leg_signaling_addr}, "
              f"SDP={session.a_leg_remote_addr}, 目标={a_leg_target}",
              file=sys.stderr, flush=True)
        print(f"  被叫({callee}): 信令={session.b_leg_signaling_addr}, "
              f"SDP={session.b_leg_remote_addr}, 目标={b_leg_target}",
              file=sys.stderr, flush=True)
        print(f"  共享RTP端口: {session.b_leg_rtp_port} "
              f"(主叫和被叫都发到此端口)", file=sys.stderr, flush=True)
        
        forwarder = SinglePortMediaForwarder(
            local_port=session.b_leg_rtp_port,
            caller_target=a_leg_target,
            callee_target=b_leg_target,
            caller_expected_ip=a_expected_ip,
            callee_expected_ip=b_expected_ip,
            call_name=f"{caller}↔{callee}"
        )
        forwarder.start()
        
        forwarder_rtcp = SinglePortMediaForwarder(
            local_port=session.b_leg_rtcp_port,
            caller_target=(a_leg_target[0], a_leg_target[1] + 1),
            callee_target=(b_leg_target[0], b_leg_target[1] + 1),
            caller_expected_ip=a_expected_ip,
            callee_expected_ip=b_expected_ip,
            call_name=f"{caller}↔{callee}-RTCP"
        )
        forwarder_rtcp.start()
        
        print(f"[MediaRelay] 发送NAT打洞包（音频）: {call_id}", file=sys.stderr, flush=True)
        forwarder.send_nat_punch(count=20, interval=0.01)  # 增加打洞包数量
        
        self._forwarders[(call_id, 'single', 'rtp')] = forwarder
        self._forwarders[(call_id, 'single', 'rtcp')] = forwarder_rtcp
        
        # 如果有视频流，启动视频转发器
        if (session.b_leg_video_rtp_port and 
            session.a_leg_video_remote_addr and 
            session.b_leg_video_remote_addr):
            
            a_leg_video_target = session.get_a_leg_video_rtp_target_addr()
            b_leg_video_target = session.get_b_leg_video_rtp_target_addr()
            
            if a_leg_video_target and b_leg_video_target:
                print(f"[MediaRelay] 启动视频转发: {call_id}", file=sys.stderr, flush=True)
                print(f"  主叫({caller})视频: {a_leg_video_target}", file=sys.stderr, flush=True)
                print(f"  被叫({callee})视频: {b_leg_video_target}", file=sys.stderr, flush=True)
                print(f"  共享视频RTP端口: {session.b_leg_video_rtp_port}", file=sys.stderr, flush=True)
                
                forwarder_video = SinglePortMediaForwarder(
                    local_port=session.b_leg_video_rtp_port,
                    caller_target=a_leg_video_target,
                    callee_target=b_leg_video_target,
                    caller_expected_ip=a_expected_ip,
                    callee_expected_ip=b_expected_ip,
                    call_name=f"{caller}↔{callee}-VIDEO"
                )
                forwarder_video.start()
                
                forwarder_video_rtcp = SinglePortMediaForwarder(
                    local_port=session.b_leg_video_rtcp_port,
                    caller_target=(a_leg_video_target[0], a_leg_video_target[1] + 1),
                    callee_target=(b_leg_video_target[0], b_leg_video_target[1] + 1),
                    caller_expected_ip=a_expected_ip,
                    callee_expected_ip=b_expected_ip,
                    call_name=f"{caller}↔{callee}-VIDEO-RTCP"
                )
                forwarder_video_rtcp.start()
                
                print(f"[MediaRelay] 发送NAT打洞包（视频）: {call_id}", file=sys.stderr, flush=True)
                forwarder_video.send_nat_punch(count=20, interval=0.01)
                
                self._forwarders[(call_id, 'single', 'video-rtp')] = forwarder_video
                self._forwarders[(call_id, 'single', 'video-rtcp')] = forwarder_video_rtcp
                
                print(f"[MediaRelay] 视频转发已启动: {call_id}", file=sys.stderr, flush=True)
        
        session.started_at = time.time()
        print(f"[MediaRelay] 媒体转发已启动（音频+视频）: {call_id}", file=sys.stderr, flush=True)
        print(f"[MediaRelay] 媒体转发已启动: {call_id}", flush=True)
        
        return True
    
    def stop_media_forwarding(self, call_id: str):
        """停止媒体转发"""
        session = self._sessions.get(call_id)
        if not session:
            return
        
        print(f"[MediaRelay] 停止媒体转发: {call_id}")
        
        # 停止音频和视频转发器
        for key in [(call_id, 'single', 'rtp'), (call_id, 'single', 'rtcp'),
                    (call_id, 'single', 'video-rtp'), (call_id, 'single', 'video-rtcp'),
                    (call_id, 'a', 'rtp'), (call_id, 'b', 'rtp'),
                    (call_id, 'a', 'rtcp'), (call_id, 'b', 'rtcp')]:
            forwarder = self._forwarders.pop(key, None)
            if forwarder:
                forwarder.stop()
        
        session.ended_at = time.time()
    
    def end_session(self, call_id: str):
        """结束媒体会话，释放资源"""
        session = self._sessions.get(call_id)
        if not session:
            return
        
        print(f"[MediaRelay] 结束会话: {call_id}")
        
        # 停止转发
        self.stop_media_forwarding(call_id)
        
        # 释放音频端口
        self.port_manager.release_port_pair(session.a_leg_rtp_port, session.a_leg_rtcp_port)
        self.port_manager.release_port_pair(session.b_leg_rtp_port, session.b_leg_rtcp_port)
        
        # 释放视频端口（如果有）
        if session.a_leg_video_rtp_port and session.a_leg_video_rtcp_port:
            self.port_manager.release_port_pair(session.a_leg_video_rtp_port, session.a_leg_video_rtcp_port)
        if session.b_leg_video_rtp_port and session.b_leg_video_rtcp_port:
            self.port_manager.release_port_pair(session.b_leg_video_rtp_port, session.b_leg_video_rtcp_port)
        
        # 清理映射
        with self._lock:
            ports_to_clean = [session.a_leg_rtp_port, session.a_leg_rtcp_port,
                            session.b_leg_rtp_port, session.b_leg_rtcp_port]
            # 添加视频端口（如果有）
            if session.a_leg_video_rtp_port:
                ports_to_clean.extend([session.a_leg_video_rtp_port, session.a_leg_video_rtcp_port])
            if session.b_leg_video_rtp_port:
                ports_to_clean.extend([session.b_leg_video_rtp_port, session.b_leg_video_rtcp_port])
            
            for port in ports_to_clean:
                self._port_session_map.pop(port, None)
            
            self._sessions.pop(call_id, None)
        
        print(f"[MediaRelay] 会话已清理（包含视频端口）: {call_id}")
    
    def get_session_stats(self, call_id: str) -> Optional[Dict]:
        """获取会话统计信息"""
        session = self._sessions.get(call_id)
        if not session:
            return None
        
        fwd = self._forwarders.get((call_id, 'single', 'rtp'))
        
        return {
            'call_id': call_id,
            'shared_port': session.b_leg_rtp_port,
            'a_to_b_packets': fwd.caller_to_callee_packets if fwd else 0,
            'b_to_a_packets': fwd.callee_to_caller_packets if fwd else 0,
            'caller_latched': fwd.caller_latched if fwd else False,
            'callee_latched': fwd.callee_latched if fwd else False,
            'duration': time.time() - session.started_at if session.started_at else 0
        }
    
    def get_all_stats(self) -> Dict:
        """获取所有统计信息"""
        return {
            'port_stats': self.port_manager.get_stats(),
            'active_sessions': len(self._sessions),
            'sessions': {cid: self.get_session_stats(cid) for cid in self._sessions}
        }
    
    def _check_port_listening(self, port: int) -> bool:
        """检查端口是否正在被监听"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.1)
            result = sock.bind(('0.0.0.0', port))
            sock.close()
            return False  # 绑定成功说明端口没有被监听
        except OSError:
            return True  # 绑定失败说明端口已被监听
    
    def print_media_diagnosis(self, call_id: str):
        """打印媒体诊断信息"""
        session = self._sessions.get(call_id)
        if not session:
            print(f"[MediaRelay-DIAG] 会话不存在: {call_id}")
            return
        
        caller = session.caller_number or "A-leg"
        callee = session.callee_number or "B-leg"
        
        print(f"\n========== 媒体诊断: {call_id} ==========")
        print(f"  模式: 单端口 (共享端口 {session.b_leg_rtp_port})")
        print(f"  主叫({caller}): 信令={session.a_leg_signaling_addr}, SDP={session.a_leg_remote_addr}")
        print(f"  被叫({callee}): 信令={session.b_leg_signaling_addr}, SDP={session.b_leg_remote_addr}")
        print(f"  {caller}和{callee}都应发送到: {self.server_ip}:{session.b_leg_rtp_port}")
        
        fwd = self._forwarders.get((call_id, 'single', 'rtp'))
        if fwd:
            elapsed = time.time() - session.started_at if session.started_at else 0
            print(f"  运行: {'是' if fwd.running else '否'}, 已启动 {elapsed:.1f}s")
            print(f"  主叫LATCH: {'✓ ' + str(fwd.caller_actual_addr) if fwd.caller_latched else '✗'}")
            print(f"  被叫LATCH: {'✓ ' + str(fwd.callee_actual_addr) if fwd.callee_latched else '✗'}")
            print(f"  A→B: {fwd.caller_to_callee_packets} 包, B→A: {fwd.callee_to_caller_packets} 包")
        else:
            print(f"  ❌ 转发器未创建")
        print(f"========================================\n")


# 全局媒体中继实例
_media_relay: Optional[MediaRelay] = None


def init_media_relay(server_ip: str) -> MediaRelay:
    """初始化全局媒体中继"""
    global _media_relay
    _media_relay = MediaRelay(server_ip)
    return _media_relay


def get_media_relay() -> Optional[MediaRelay]:
    """获取全局媒体中继实例"""
    return _media_relay
