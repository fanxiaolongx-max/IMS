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

import random
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
    
    # 媒体方向属性（sendrecv, sendonly, recvonly, inactive）
    a_leg_audio_direction: str = 'sendrecv'
    b_leg_audio_direction: str = 'sendrecv'
    a_leg_video_direction: str = 'sendrecv'
    b_leg_video_direction: str = 'sendrecv'
    
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
    """RTP端口管理器：从 20000～30000 随机分配 RTP/RTCP 端口对"""

    RTP_PORT_START = 20000
    RTP_PORT_END = 30000  # 不含 30000，即 20000～29998 的偶数

    def __init__(self):
        self._lock = threading.Lock()
        # 可用 RTP 端口池（偶数），分配时随机取
        self._available_ports: List[int] = list(range(
            self.RTP_PORT_START, self.RTP_PORT_END, 2
        ))
        self._allocated_ports: Dict[int, str] = {}  # port -> call_id

    def allocate_port_pair(self, call_id: str) -> Optional[Tuple[int, int]]:
        """
        随机分配一对 RTP/RTCP 端口（RTP 为偶数，RTCP 为 RTP+1）

        Returns:
            (rtp_port, rtcp_port) 或 None（端口耗尽）
        """
        with self._lock:
            if not self._available_ports:
                return None
            idx = random.randrange(len(self._available_ports))
            rtp_port = self._available_ports.pop(idx)
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
            
            if rtp_port not in self._available_ports:
                self._available_ports.append(rtp_port)
    
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
            'audio_direction': 'sendrecv',  # 默认值：sendrecv, sendonly, recvonly, inactive
            'video_port': None,
            'video_payloads': [],
            'video_connection_ip': None,
            'video_direction': 'sendrecv',  # 默认值：sendrecv, sendonly, recvonly, inactive
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
            
            # 解析媒体方向属性 (a=sendrecv, a=sendonly, a=recvonly, a=inactive)
            # 这些属性通常出现在 m= 行之后，作用域是当前媒体
            elif line.startswith('a=') and current_media:
                direction_line = line[2:].strip().lower()
                if direction_line in ('sendrecv', 'sendonly', 'recvonly', 'receiveonly', 'inactive'):
                    # 标准化：receiveonly -> recvonly
                    if direction_line == 'receiveonly':
                        direction_line = 'recvonly'
                    if current_media == 'audio':
                        result['audio_direction'] = direction_line
                    elif current_media == 'video':
                        result['video_direction'] = direction_line
        
        # 如果没有音频端口，认为无效
        return result if result['audio_port'] else None
    
    @staticmethod
    def modify_sdp(sdp_body: str, new_ip: str, new_audio_port: int,
                   new_video_port: Optional[int] = None,
                   new_audio_rtcp_port: Optional[int] = None,
                   new_video_rtcp_port: Optional[int] = None,
                   force_plain_rtp: bool = False) -> str:
        """
        修改SDP中的IP地址和端口（支持音频、视频及 a=rtcp）
        
        Args:
            sdp_body: 原始SDP
            new_ip: 新的IP地址
            new_audio_port: 新的音频RTP端口
            new_video_port: 新的视频RTP端口（可选）
            new_audio_rtcp_port: 新的音频RTCP端口（可选，默认 new_audio_port+1）
            new_video_rtcp_port: 新的视频RTCP端口（可选，默认 new_video_port+1）
            force_plain_rtp: 是否强制使用普通RTP（移除SRTP加密行）
            
        Returns:
            修改后的SDP（主被叫均能正确向中继发送 RTP 与 RTCP）
        """
        if not sdp_body:
            return sdp_body
        if new_audio_rtcp_port is None:
            new_audio_rtcp_port = new_audio_port + 1
        if new_video_rtcp_port is None and new_video_port is not None:
            new_video_rtcp_port = new_video_port + 1

        lines = sdp_body.split('\r\n') if '\r\n' in sdp_body else sdp_body.split('\n')
        new_lines = []
        # 当前媒体块对应的 RTCP 端口（用于替换 a=rtcp）
        pending_rtcp: Optional[int] = None

        for line in lines:
            line = line.rstrip()
            if not line:
                continue

            # 修改 o= 行（origin，保持格式，只改 IP 地址）
            # 格式: o=<username> <sess-id> <sess-version> <nettype> <addrtype> <unicast-address>
            if line.startswith('o='):
                parts = line[2:].split()
                if len(parts) >= 6 and parts[4] == 'IP4':
                    # 保持前5个字段不变，只修改最后一个 IP 地址字段
                    line = f"o={' '.join(parts[:5])} {new_ip}"
                new_lines.append(line)
                continue

            # 修改 c= 行（connection，只改 IP 地址）
            if line.startswith('c='):
                parts = line[2:].split()
                if len(parts) >= 3 and parts[1] == 'IP4':
                    line = f"c=IN IP4 {new_ip}"
                new_lines.append(line)
                continue

            # 修改 m=audio 行
            if line.startswith('m=audio '):
                if pending_rtcp is not None:
                    new_lines.append(f"a=rtcp:{pending_rtcp} IN IP4 {new_ip}")
                    pending_rtcp = new_audio_rtcp_port
                parts = line.split()
                if len(parts) >= 4:
                    proto = parts[2]
                    payloads = ' '.join(parts[3:])
                    if force_plain_rtp:
                        proto = "RTP/AVP"
                    line = f"m=audio {new_audio_port} {proto} {payloads}"
                new_lines.append(line)
                continue

            # 修改 m=video 行
            if line.startswith('m=video '):
                if pending_rtcp is not None:
                    new_lines.append(f"a=rtcp:{pending_rtcp} IN IP4 {new_ip}")
                    pending_rtcp = new_video_rtcp_port if new_video_port is not None else None
                parts = line.split()
                if len(parts) >= 4 and new_video_port is not None:
                    proto = parts[2]
                    payloads = ' '.join(parts[3:])
                    if force_plain_rtp:
                        proto = "RTP/AVP"
                    line = f"m=video {new_video_port} {proto} {payloads}"
                new_lines.append(line)
                continue

            # 替换 a=rtcp 行（RFC 3605: a=rtcp:port 或 a=rtcp:port nettype addrtype addr）——地址与 c= 一致
            if line.startswith('a=rtcp:'):
                if pending_rtcp is not None:
                    new_lines.append(f"a=rtcp:{pending_rtcp} IN IP4 {new_ip}")
                    pending_rtcp = None
                continue

            if force_plain_rtp and (line.startswith('a=crypto:') or line.startswith('a=fingerprint:')):
                continue

            new_lines.append(line)

        if pending_rtcp is not None:
            new_lines.append(f"a=rtcp:{pending_rtcp} IN IP4 {new_ip}")

        return '\r\n'.join(new_lines) + '\r\n'


class DualPortMediaForwarder:
    """
    双端口 RTP 转发器
    
    主叫和被叫使用不同的端口：
    - A-leg 转发器：监听 A-leg 端口，接收主叫的 RTP，转发给被叫
    - B-leg 转发器：监听 B-leg 端口，接收被叫的 RTP，转发给主叫
    """
    _RECV_BUF = 4096  # 视频 RTP 可能超过 2KB

    SILENCE_RTP = (
        b'\x80\x00'
        b'\x00\x01'
        b'\x00\x00\x00\xa0'
        b'\x00\x00\x00\x00'
        + b'\xff' * 160
    )
    
    def __init__(self, local_port: int,
                 target_addr: Tuple[str, int],
                 expected_ip: Optional[str] = None,
                 call_name: str = ""):
        self.local_port = local_port
        self.target_addr = target_addr
        self.expected_ip = expected_ip
        self.call_name = call_name or f"port-{local_port}"
        
        self.sock: Optional[socket.socket] = None
        self.running = False
        self.thread: Optional[threading.Thread] = None
        
        self.packets_sent = 0
        self.packets_received = 0  # 接收到的包数（从客户端到服务器）
        self.total_bytes = 0
        
        self._last_log_time = 0
        self._last_packets = 0
        self._last_received = 0
    
    def start(self):
        if self.running:
            return
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            buf_size = 512 * 1024  # 512KB，减少视频突发丢包
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, buf_size)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, buf_size)
        except OSError:
            pass
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
        """向目标发送 NAT 打洞包"""
        if not self.sock or not self.running:
            return
        print(f"[RTP-PUNCH] {self.call_name}(:{self.local_port}): "
              f"→目标 {self.target_addr} x{count}",
              file=sys.stderr, flush=True)
        for i in range(count):
            try:
                self.sock.sendto(self.SILENCE_RTP, self.target_addr)
                if interval > 0 and i < count - 1:
                    time.sleep(interval)
            except Exception as e:
                print(f"[RTP-PUNCH-ERR] {self.call_name}: → {self.target_addr}: {e}",
                      file=sys.stderr, flush=True)
                break
    
    def update_target(self, target_addr: Tuple[str, int], reset_stats: bool = False):
        """更新目标地址（re-INVITE 场景）
        
        Args:
            target_addr: 新的目标地址
            reset_stats: 是否重置统计信息（用于视频切换场景）
        """
        self.target_addr = target_addr
        if reset_stats:
            self.packets_sent = 0
            self.packets_received = 0
            self._last_packets = 0
            self._last_received = 0
            print(f"[RTP-UPDATE] {self.call_name}(:{self.local_port}): "
                  f"更新目标并重置统计: {target_addr}",
                  file=sys.stderr, flush=True)
        else:
            print(f"[RTP-UPDATE] {self.call_name}(:{self.local_port}): "
                  f"更新目标: {target_addr}",
                  file=sys.stderr, flush=True)
    
    def _log_stats(self):
        # 降低热路径开销：仅每 100 包检查一次时间，且统计日志间隔改为 15 秒，减少打印造成的卡顿
        if self.packets_sent > 0 and self.packets_sent % 100 != 0:
            return
        now = time.time()
        if now - self._last_log_time >= 15:
            packets_diff = self.packets_sent - self._last_packets
            if self.packets_sent > 0 or packets_diff > 0:
                print(f"[RTP-STATS] {self.call_name}(:{self.local_port}): "
                      f"已转发:{self.packets_sent}(+{packets_diff}) "
                      f"目标={self.target_addr}",
                      file=sys.stderr, flush=True)
            self._last_log_time = now
            self._last_packets = self.packets_sent
    
    def _forward_loop(self):
        print(f"[RTP-DUAL] {self.call_name} 双端口转发器启动: 端口{self.local_port}",
              file=sys.stderr, flush=True)
        print(f"  目标地址: {self.target_addr} (期望IP: {self.expected_ip})",
              file=sys.stderr, flush=True)
        
        # 视频 RTP 可能超过 2KB，使用更大缓冲区减少分片/丢包
        while self.running and self.sock:
            try:
                data, addr = self.sock.recvfrom(self._RECV_BUF)
                if len(data) < 12:
                    continue
                
                self.packets_received += 1
                self.total_bytes += len(data)
                
                if self.target_addr:
                    try:
                        self.sock.sendto(data, self.target_addr)
                        self.packets_sent += 1
                    except Exception as e:
                        print(f"[RTP-ERROR] {self.call_name}: →{self.target_addr}: {e}",
                              file=sys.stderr, flush=True)
                
                self._log_stats()
                
            except socket.timeout:
                self._log_stats()
                continue
            except Exception as e:
                if self.running:
                    print(f"[RTP-ERROR] {self.call_name}(:{self.local_port}): {e}",
                          file=sys.stderr, flush=True)


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
        2. 排除法（一方已 LATCH，另一方未知则是新的那方）- 优先于IP匹配
        3. 期望 IP + 端口匹配（信令地址）
        4. 首包归被叫（B2BUA 中被叫通常先发 RTP）
        """
        # 精确匹配已学习的地址
        if self.callee_actual_addr and addr == self.callee_actual_addr:
            return "callee"
        if self.caller_actual_addr and addr == self.caller_actual_addr:
            return "caller"
        
        # 排除法：如果一方已LATCH，新包来自另一方（优先于IP匹配，解决同IP问题）
        if self.callee_latched and not self.caller_latched:
            # 被叫已LATCH，新包且地址不同，则为主叫
            if addr != self.callee_actual_addr:
                return "caller"
        if self.caller_latched and not self.callee_latched:
            # 主叫已LATCH，新包且地址不同，则为被叫
            if addr != self.caller_actual_addr:
                return "callee"
        
        src_ip = addr[0]
        src_port = addr[1]
        
        # IP + 端口匹配（更精确）
        if self.callee_expected_ip and src_ip == self.callee_expected_ip:
            # 如果被叫期望IP匹配，检查端口是否匹配被叫目标端口
            if self.callee_target_port and src_port == self.callee_target_port:
                return "callee"
            # 如果主叫期望IP也相同，需要进一步判断
            if not self.caller_expected_ip or src_ip != self.caller_expected_ip:
                return "callee"
        if self.caller_expected_ip and src_ip == self.caller_expected_ip:
            # 如果主叫期望IP匹配，检查端口是否匹配主叫目标端口
            if self.caller_target_port and src_port == self.caller_target_port:
                return "caller"
            # 如果被叫期望IP也相同，需要进一步判断
            if not self.callee_expected_ip or src_ip != self.callee_expected_ip:
                return "caller"
        
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
                    # 未知包：尝试根据排除法和IP匹配
                    src_ip = addr[0]
                    src_port = addr[1]
                    
                    # 排除法：如果被叫已LATCH且主叫未LATCH，且地址不同，则认为是主叫
                    if self.callee_latched and not self.caller_latched:
                        if addr != self.callee_actual_addr:
                            self.caller_actual_addr = addr
                            self.caller_latched = True
                            print(f"[RTP-LATCH-AUTO] {self.call_name}(:{self.local_port}): "
                                  f"✓ 主叫自动LATCH（排除法，被叫已LATCH）: {addr}",
                                  file=sys.stderr, flush=True)
                            target = self.callee_actual_addr or self.callee_target
                            if target:
                                try:
                                    self.sock.sendto(data, target)
                                    self.caller_to_callee_packets += 1
                                except Exception as e:
                                    print(f"[RTP-ERROR] {self.call_name}: →被叫{target}: {e}",
                                          file=sys.stderr, flush=True)
                            continue
                    
                    # IP匹配：如果主叫期望IP匹配，且主叫未LATCH
                    if self.caller_expected_ip and src_ip == self.caller_expected_ip:
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
                            continue
                    
                    # 记录未知包（限制日志频率）
                    if self.unknown_packets <= 10:
                        print(f"[RTP-UNKNOWN] {self.call_name}(:{self.local_port}): "
                              f"未知源 {addr}, 已知: 主叫={self.caller_actual_addr or '未LATCH'}(期望IP:{self.caller_expected_ip},目标端口:{self.caller_target_port}) "
                              f"被叫={self.callee_actual_addr or '未LATCH'}(期望IP:{self.callee_expected_ip},目标端口:{self.callee_target_port})",
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
        
        # 修改SDP（指向A-leg端口，给主叫用的；含 RTCP）
        new_sdp = self.sdp_processor.modify_sdp(
            sdp_body,
            self.server_ip,
            session.a_leg_rtp_port,
            new_audio_rtcp_port=session.a_leg_rtcp_port,
        )
        return new_sdp, session
    
    def process_invite_to_callee(self, call_id: str, sdp_body: str,
                                  caller_addr: Tuple[str, int],
                                  caller_number: Optional[str] = None,
                                  callee_number: Optional[str] = None,
                                  from_tag: Optional[str] = None,
                                  forward_to_callee: bool = True) -> Tuple[str, Optional[MediaSession]]:
        """
        处理转发的 INVITE/re-INVITE SDP。
        forward_to_callee=True 用 B-leg，False 用 A-leg（与 RTPProxy 实现一致）。
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
            old_a_audio_direction = session.a_leg_audio_direction
            session.a_leg_audio_direction = media_info.get('audio_direction', 'sendrecv')
            print(f"[MediaRelay] A-leg音频信息: {session.a_leg_remote_addr}, 方向: {session.a_leg_audio_direction}")
            if old_a_audio_direction != session.a_leg_audio_direction:
                print(f"[MediaRelay] A-leg音频方向已改变: {old_a_audio_direction} → {session.a_leg_audio_direction}", file=sys.stderr, flush=True)
            
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
                old_a_leg_video_addr = session.a_leg_video_remote_addr
                session.a_leg_video_remote_addr = (video_ip, media_info['video_port'])
                old_a_video_direction = session.a_leg_video_direction
                session.a_leg_video_direction = media_info.get('video_direction', 'sendrecv')
                print(f"[MediaRelay] A-leg视频信息: {session.a_leg_video_remote_addr}, 方向: {session.a_leg_video_direction}")
                if old_a_leg_video_addr and old_a_leg_video_addr != session.a_leg_video_remote_addr:
                    print(f"[MediaRelay] A-leg视频地址已更新: {old_a_leg_video_addr} → {session.a_leg_video_remote_addr}", file=sys.stderr, flush=True)
                if old_a_video_direction != session.a_leg_video_direction:
                    print(f"[MediaRelay] A-leg视频方向已改变: {old_a_video_direction} → {session.a_leg_video_direction}", file=sys.stderr, flush=True)
        
        audio_port = session.b_leg_rtp_port if forward_to_callee else session.a_leg_rtp_port
        video_port = session.b_leg_video_rtp_port if forward_to_callee else session.a_leg_video_rtp_port
        audio_rtcp = session.b_leg_rtcp_port if forward_to_callee else session.a_leg_rtcp_port
        video_rtcp = session.b_leg_video_rtcp_port if forward_to_callee else session.a_leg_video_rtcp_port
        new_sdp = self.sdp_processor.modify_sdp(
            sdp_body,
            self.server_ip,
            audio_port,
            new_video_port=video_port,
            new_audio_rtcp_port=audio_rtcp,
            new_video_rtcp_port=video_rtcp,
        )
        leg = "B-leg" if forward_to_callee else "A-leg"
        print(f"[MediaRelay] INVITE SDP 修改为{leg}端口: 音频={audio_port}", end='')
        if video_port:
            print(f", 视频={video_port}")
        else:
            print()
        return new_sdp, session

    def process_answer_sdp(self, call_id: str, sdp_body: str,
                          callee_addr: Tuple[str, int],
                          response_to_caller: bool = True) -> Tuple[str, bool]:
        """
        处理 200 OK 的 SDP。response_to_caller=True 用 A-leg，False 用 B-leg。
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
            old_b_audio_direction = session.b_leg_audio_direction
            session.b_leg_audio_direction = media_info.get('audio_direction', 'sendrecv')
            print(f"[MediaRelay] B-leg音频信息: {session.b_leg_remote_addr}, 方向: {session.b_leg_audio_direction}")
            if old_b_audio_direction != session.b_leg_audio_direction:
                print(f"[MediaRelay] B-leg音频方向已改变: {old_b_audio_direction} → {session.b_leg_audio_direction}", file=sys.stderr, flush=True)
            
            if media_info.get('video_port'):
                video_ip = media_info.get('video_connection_ip') or media_info.get('connection_ip')
                old_b_leg_video_addr = session.b_leg_video_remote_addr
                session.b_leg_video_remote_addr = (video_ip, media_info['video_port'])
                old_b_video_direction = session.b_leg_video_direction
                session.b_leg_video_direction = media_info.get('video_direction', 'sendrecv')
                print(f"[MediaRelay] B-leg视频信息: {session.b_leg_video_remote_addr}, 方向: {session.b_leg_video_direction}")
                if old_b_leg_video_addr != session.b_leg_video_remote_addr:
                    print(f"[MediaRelay] B-leg视频地址已更新: {old_b_leg_video_addr} → {session.b_leg_video_remote_addr}", file=sys.stderr, flush=True)
                if old_b_video_direction != session.b_leg_video_direction:
                    print(f"[MediaRelay] B-leg视频方向已改变: {old_b_video_direction} → {session.b_leg_video_direction}", file=sys.stderr, flush=True)
                if not session.a_leg_video_rtp_port or not session.b_leg_video_rtp_port:
                    a_v = self.port_manager.allocate_port_pair(call_id)
                    b_v = self.port_manager.allocate_port_pair(call_id)
                    if a_v and b_v:
                        session.a_leg_video_rtp_port, session.a_leg_video_rtcp_port = a_v[0], a_v[1]
                        session.b_leg_video_rtp_port, session.b_leg_video_rtcp_port = b_v[0], b_v[1]
                        print(f"[MediaRelay] 分配视频端口: A-leg={a_v}, B-leg={b_v}", file=sys.stderr, flush=True)
        # 双端口模式：主叫使用 A-leg 端口，被叫使用 B-leg 端口
        # 根据 response_to_caller 选择对应的端口
        if response_to_caller:
            audio_port = session.a_leg_rtp_port
            video_port = session.a_leg_video_rtp_port
            audio_rtcp = session.a_leg_rtcp_port
            video_rtcp = session.a_leg_video_rtcp_port
            leg = "A-leg"
        else:
            audio_port = session.b_leg_rtp_port
            video_port = session.b_leg_video_rtp_port
            audio_rtcp = session.b_leg_rtcp_port
            video_rtcp = session.b_leg_video_rtcp_port
            leg = "B-leg"
        new_sdp = self.sdp_processor.modify_sdp(
            sdp_body,
            self.server_ip,
            audio_port,
            new_video_port=video_port,
            new_audio_rtcp_port=audio_rtcp,
            new_video_rtcp_port=video_rtcp,
        )
        print(f"[MediaRelay] 200 OK SDP 修改为{leg}端口: 音频={audio_port}", end='')
        if video_port:
            print(f", 视频={video_port}")
        else:
            print()
        return new_sdp, True
    
    def start_media_forwarding(self, call_id: str,
                               from_tag: Optional[str] = None,
                               to_tag: Optional[str] = None):
        """
        启动媒体转发（双端口模式）
        
        主叫和被叫使用不同的端口：
        - A-leg 转发器：监听 A-leg 端口，接收主叫的 RTP，转发给被叫
        - B-leg 转发器：监听 B-leg 端口，接收被叫的 RTP，转发给主叫
        
        Args:
            call_id: 呼叫ID
            from_tag: From标签（可选，内置实现不使用，仅为接口兼容性保留）
            to_tag: To标签（可选，内置实现不使用，仅为接口兼容性保留）
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
        
        # re-INVITE 场景：更新已有转发器的目标，如果不存在则创建
        if session.started_at:
            print(f"[MediaRelay] re-INVITE 更新目标: {call_id}")
            fwd_a = self._forwarders.get((call_id, 'a', 'rtp'))
            fwd_b = self._forwarders.get((call_id, 'b', 'rtp'))
            if fwd_a and fwd_b:
                # 转发器存在，检查目标地址是否改变
                old_target_a = fwd_a.target_addr
                old_target_b = fwd_b.target_addr
                reset_audio_stats = (old_target_a != b_leg_target or old_target_b != a_leg_target)
                
                # 更新目标地址
                fwd_a.update_target(b_leg_target, reset_stats=reset_audio_stats)
                fwd_b.update_target(a_leg_target, reset_stats=reset_audio_stats)
                
                fwd_a_rtcp = self._forwarders.get((call_id, 'a', 'rtcp'))
                fwd_b_rtcp = self._forwarders.get((call_id, 'b', 'rtcp'))
                if fwd_a_rtcp:
                    old_rtcp_target = (old_target_a[0], old_target_a[1] + 1)
                    new_rtcp_target = (b_leg_target[0], b_leg_target[1] + 1)
                    fwd_a_rtcp.update_target(new_rtcp_target, reset_stats=(old_rtcp_target != new_rtcp_target))
                if fwd_b_rtcp:
                    old_rtcp_target = (old_target_b[0], old_target_b[1] + 1)
                    new_rtcp_target = (a_leg_target[0], a_leg_target[1] + 1)
                    fwd_b_rtcp.update_target(new_rtcp_target, reset_stats=(old_rtcp_target != new_rtcp_target))
                
                # 如果目标地址改变，发送 NAT 打洞包
                if reset_audio_stats:
                    print(f"[MediaRelay] 音频目标地址改变，发送 NAT 打洞包: {call_id}", file=sys.stderr, flush=True)
                    fwd_a.send_nat_punch(count=20, interval=0.01)
                    fwd_b.send_nat_punch(count=20, interval=0.01)
                # 检查媒体方向是否改变
                audio_direction_changed = False
                video_direction_changed = False
                if session.a_leg_audio_direction == 'inactive' or session.b_leg_audio_direction == 'inactive':
                    print(f"[MediaRelay] 检测到音频方向为 inactive: A-leg={session.a_leg_audio_direction}, B-leg={session.b_leg_audio_direction}", file=sys.stderr, flush=True)
                if session.a_leg_video_direction == 'inactive' or session.b_leg_video_direction == 'inactive':
                    print(f"[MediaRelay] 检测到视频方向为 inactive: A-leg={session.a_leg_video_direction}, B-leg={session.b_leg_video_direction}", file=sys.stderr, flush=True)
                    # 注意：inactive 时通常不需要停止转发器，因为可能只是临时暂停
                
                # 处理视频转发器
                video_forwarders_exist = False
                if session.b_leg_video_rtp_port:
                    a_leg_video_target = session.get_a_leg_video_rtp_target_addr()
                    b_leg_video_target = session.get_b_leg_video_rtp_target_addr()
                    print(f"[MediaRelay] re-INVITE 视频目标地址检查: {call_id}", file=sys.stderr, flush=True)
                    print(f"  A-leg视频目标: {a_leg_video_target}, B-leg视频目标: {b_leg_video_target}", file=sys.stderr, flush=True)
                    print(f"  A-leg视频远程地址: {session.a_leg_video_remote_addr}, 方向: {session.a_leg_video_direction}", file=sys.stderr, flush=True)
                    print(f"  B-leg视频远程地址: {session.b_leg_video_remote_addr}, 方向: {session.b_leg_video_direction}", file=sys.stderr, flush=True)
                    if a_leg_video_target and b_leg_video_target:
                        fwd_video_a = self._forwarders.get((call_id, 'a', 'video-rtp'))
                        fwd_video_b = self._forwarders.get((call_id, 'b', 'video-rtp'))
                        if fwd_video_a and fwd_video_b:
                            # 视频转发器已存在，检查目标地址是否改变
                            old_target_a = fwd_video_a.target_addr
                            old_target_b = fwd_video_b.target_addr
                            
                            print(f"[MediaRelay] 视频转发器当前目标: A-leg={old_target_a}, B-leg={old_target_b}", file=sys.stderr, flush=True)
                            print(f"[MediaRelay] 视频转发器新目标: A-leg→{b_leg_video_target}, B-leg→{a_leg_video_target}", file=sys.stderr, flush=True)
                            
                            # 如果目标地址改变，重置统计（视频切换场景）
                            reset_stats = (old_target_a != b_leg_video_target or old_target_b != a_leg_video_target)
                            
                            if reset_stats:
                                print(f"[MediaRelay] 检测到视频目标地址改变，将重置统计并发送 NAT 打洞包: {call_id}", file=sys.stderr, flush=True)
                            
                            fwd_video_a.update_target(b_leg_video_target, reset_stats=reset_stats)
                            fwd_video_b.update_target(a_leg_video_target, reset_stats=reset_stats)
                            
                            fwd_video_a_rtcp = self._forwarders.get((call_id, 'a', 'video-rtcp'))
                            fwd_video_b_rtcp = self._forwarders.get((call_id, 'b', 'video-rtcp'))
                            if fwd_video_a_rtcp:
                                old_rtcp_target = (old_target_a[0], old_target_a[1] + 1)
                                new_rtcp_target = (b_leg_video_target[0], b_leg_video_target[1] + 1)
                                fwd_video_a_rtcp.update_target(new_rtcp_target, reset_stats=(old_rtcp_target != new_rtcp_target))
                            if fwd_video_b_rtcp:
                                old_rtcp_target = (old_target_b[0], old_target_b[1] + 1)
                                new_rtcp_target = (a_leg_video_target[0], a_leg_video_target[1] + 1)
                                fwd_video_b_rtcp.update_target(new_rtcp_target, reset_stats=(old_rtcp_target != new_rtcp_target))
                            
                            # 如果目标地址改变，发送 NAT 打洞包
                            if reset_stats:
                                print(f"[MediaRelay] 视频目标地址改变，发送 NAT 打洞包: {call_id}", file=sys.stderr, flush=True)
                                fwd_video_a.send_nat_punch(count=20, interval=0.01)
                                fwd_video_b.send_nat_punch(count=20, interval=0.01)
                            
                            video_forwarders_exist = True
                        else:
                            # 视频转发器不存在（re-INVITE 时添加视频），需要创建
                            print(f"[MediaRelay] re-INVITE 检测到视频但转发器不存在，将创建视频转发器: {call_id}", file=sys.stderr, flush=True)
                            video_forwarders_exist = False
                
                # 如果音频和视频转发器都已更新，返回
                # 注意：即使视频端口存在，如果视频转发器不存在，也需要继续创建
                if session.b_leg_video_rtp_port and video_forwarders_exist:
                    # 视频端口存在且转发器已更新，返回
                    return True
                elif not session.b_leg_video_rtp_port:
                    # 没有视频端口，音频转发器已更新，返回
                    return True
                # 否则继续执行下面的创建逻辑（创建视频转发器）
            else:
                # 转发器不存在（可能初始 INVITE 时未成功启动），创建新的转发器
                print(f"[MediaRelay] re-INVITE 转发器不存在，创建新转发器: {call_id}", file=sys.stderr, flush=True)
                # 继续执行下面的创建逻辑
        
        caller = session.caller_number or "A"
        callee = session.callee_number or "B"
        
        a_expected_ip = session.a_leg_signaling_addr[0] if session.a_leg_signaling_addr else (
            session.a_leg_remote_addr[0] if session.a_leg_remote_addr else None)
        b_expected_ip = session.b_leg_signaling_addr[0] if session.b_leg_signaling_addr else (
            session.b_leg_remote_addr[0] if session.b_leg_remote_addr else None)
        
        # 检查音频转发器是否已存在（re-INVITE 场景下可能已存在）
        audio_forwarders_exist = (
            self._forwarders.get((call_id, 'a', 'rtp')) and 
            self._forwarders.get((call_id, 'b', 'rtp'))
        )
        
        if not audio_forwarders_exist:
            print(f"[MediaRelay] 启动双端口媒体转发: {call_id}", file=sys.stderr, flush=True)
            print(f"  主叫({caller}): 信令={session.a_leg_signaling_addr}, "
                  f"SDP={session.a_leg_remote_addr}, 目标={a_leg_target}",
                  file=sys.stderr, flush=True)
            print(f"  被叫({callee}): 信令={session.b_leg_signaling_addr}, "
                  f"SDP={session.b_leg_remote_addr}, 目标={b_leg_target}",
                  file=sys.stderr, flush=True)
            print(f"  A-leg RTP端口: {session.a_leg_rtp_port} (主叫发送到此端口)",
                  file=sys.stderr, flush=True)
            print(f"  B-leg RTP端口: {session.b_leg_rtp_port} (被叫发送到此端口)",
                  file=sys.stderr, flush=True)
            
            # A-leg 转发器：监听 A-leg 端口，接收主叫的 RTP，转发给被叫
            forwarder_a = DualPortMediaForwarder(
                local_port=session.a_leg_rtp_port,
                target_addr=b_leg_target,
                expected_ip=a_expected_ip,
                call_name=f"{caller}→{callee}-A"
            )
            forwarder_a.start()
            
            # B-leg 转发器：监听 B-leg 端口，接收被叫的 RTP，转发给主叫
            forwarder_b = DualPortMediaForwarder(
                local_port=session.b_leg_rtp_port,
                target_addr=a_leg_target,
                expected_ip=b_expected_ip,
                call_name=f"{callee}→{caller}-B"
            )
            forwarder_b.start()
            
            # RTCP 转发器
            forwarder_a_rtcp = DualPortMediaForwarder(
                local_port=session.a_leg_rtcp_port,
                target_addr=(b_leg_target[0], b_leg_target[1] + 1),
                expected_ip=a_expected_ip,
                call_name=f"{caller}→{callee}-A-RTCP"
            )
            forwarder_a_rtcp.start()
            
            forwarder_b_rtcp = DualPortMediaForwarder(
                local_port=session.b_leg_rtcp_port,
                target_addr=(a_leg_target[0], a_leg_target[1] + 1),
                expected_ip=b_expected_ip,
                call_name=f"{callee}→{caller}-B-RTCP"
            )
            forwarder_b_rtcp.start()
            
            print(f"[MediaRelay] 发送NAT打洞包（音频）: {call_id}", file=sys.stderr, flush=True)
            forwarder_a.send_nat_punch(count=20, interval=0.01)
            forwarder_b.send_nat_punch(count=20, interval=0.01)
            
            self._forwarders[(call_id, 'a', 'rtp')] = forwarder_a
            self._forwarders[(call_id, 'b', 'rtp')] = forwarder_b
            self._forwarders[(call_id, 'a', 'rtcp')] = forwarder_a_rtcp
            self._forwarders[(call_id, 'b', 'rtcp')] = forwarder_b_rtcp
        else:
            print(f"[MediaRelay] 音频转发器已存在，跳过创建: {call_id}", file=sys.stderr, flush=True)
        
        # 如果有视频流，启动视频转发器（仅在不存在时创建）
        if (session.b_leg_video_rtp_port and 
            session.a_leg_video_remote_addr and 
            session.b_leg_video_remote_addr):
            
            a_leg_video_target = session.get_a_leg_video_rtp_target_addr()
            b_leg_video_target = session.get_b_leg_video_rtp_target_addr()
            
            if a_leg_video_target and b_leg_video_target:
                # 检查视频转发器是否已存在
                video_forwarders_exist = (
                    self._forwarders.get((call_id, 'a', 'video-rtp')) and 
                    self._forwarders.get((call_id, 'b', 'video-rtp'))
                )
                
                if not video_forwarders_exist:
                    print(f"[MediaRelay] 启动视频转发: {call_id}", file=sys.stderr, flush=True)
                    print(f"  主叫({caller})视频: {a_leg_video_target}", file=sys.stderr, flush=True)
                    print(f"  被叫({callee})视频: {b_leg_video_target}", file=sys.stderr, flush=True)
                    print(f"  A-leg视频RTP端口: {session.a_leg_video_rtp_port}", file=sys.stderr, flush=True)
                    print(f"  B-leg视频RTP端口: {session.b_leg_video_rtp_port}", file=sys.stderr, flush=True)
                    
                    # A-leg 视频转发器
                    forwarder_video_a = DualPortMediaForwarder(
                        local_port=session.a_leg_video_rtp_port,
                        target_addr=b_leg_video_target,
                        expected_ip=a_expected_ip,
                        call_name=f"{caller}→{callee}-VIDEO-A"
                    )
                    forwarder_video_a.start()
                    
                    # B-leg 视频转发器
                    forwarder_video_b = DualPortMediaForwarder(
                        local_port=session.b_leg_video_rtp_port,
                        target_addr=a_leg_video_target,
                        expected_ip=b_expected_ip,
                        call_name=f"{callee}→{caller}-VIDEO-B"
                    )
                    forwarder_video_b.start()
                    
                    # 视频 RTCP 转发器
                    forwarder_video_a_rtcp = DualPortMediaForwarder(
                        local_port=session.a_leg_video_rtcp_port,
                        target_addr=(b_leg_video_target[0], b_leg_video_target[1] + 1),
                        expected_ip=a_expected_ip,
                        call_name=f"{caller}→{callee}-VIDEO-A-RTCP"
                    )
                    forwarder_video_a_rtcp.start()
                    
                    forwarder_video_b_rtcp = DualPortMediaForwarder(
                        local_port=session.b_leg_video_rtcp_port,
                        target_addr=(a_leg_video_target[0], a_leg_video_target[1] + 1),
                        expected_ip=b_expected_ip,
                        call_name=f"{callee}→{caller}-VIDEO-B-RTCP"
                    )
                    forwarder_video_b_rtcp.start()
                    
                    print(f"[MediaRelay] 发送NAT打洞包（视频）: {call_id}", file=sys.stderr, flush=True)
                    forwarder_video_a.send_nat_punch(count=20, interval=0.01)
                    forwarder_video_b.send_nat_punch(count=20, interval=0.01)
                    
                    self._forwarders[(call_id, 'a', 'video-rtp')] = forwarder_video_a
                    self._forwarders[(call_id, 'b', 'video-rtp')] = forwarder_video_b
                    self._forwarders[(call_id, 'a', 'video-rtcp')] = forwarder_video_a_rtcp
                    self._forwarders[(call_id, 'b', 'video-rtcp')] = forwarder_video_b_rtcp
                    
                    print(f"[MediaRelay] 视频转发已启动: {call_id}", file=sys.stderr, flush=True)
                else:
                    print(f"[MediaRelay] 视频转发器已存在，跳过创建: {call_id}", file=sys.stderr, flush=True)
        
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
        for key in [(call_id, 'a', 'rtp'), (call_id, 'b', 'rtp'),
                    (call_id, 'a', 'rtcp'), (call_id, 'b', 'rtcp'),
                    (call_id, 'a', 'video-rtp'), (call_id, 'b', 'video-rtp'),
                    (call_id, 'a', 'video-rtcp'), (call_id, 'b', 'video-rtcp')]:
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
        """获取会话统计信息（含音视频端口及诊断，供 MML 媒体端点可视化）
        
        返回详细的统计信息，区分：
        - 主叫和被叫
        - 音频和视频
        - 上行和下行（RTP 和 RTCP）
        """
        session = self._sessions.get(call_id)
        if not session:
            return None

        # 音频转发器
        fwd_a_audio = self._forwarders.get((call_id, 'a', 'rtp'))
        fwd_b_audio = self._forwarders.get((call_id, 'b', 'rtp'))
        fwd_a_audio_rtcp = self._forwarders.get((call_id, 'a', 'rtcp'))
        fwd_b_audio_rtcp = self._forwarders.get((call_id, 'b', 'rtcp'))
        
        # 视频转发器
        fwd_a_video = self._forwarders.get((call_id, 'a', 'video-rtp'))
        fwd_b_video = self._forwarders.get((call_id, 'b', 'video-rtp'))
        fwd_a_video_rtcp = self._forwarders.get((call_id, 'a', 'video-rtcp'))
        fwd_b_video_rtcp = self._forwarders.get((call_id, 'b', 'video-rtcp'))
        
        # 音频统计：以服务器为中心
        # A-leg: 主叫→服务器（接收）和 服务器→被叫（发送）
        audio_caller_to_server_rtp = fwd_a_audio.packets_received if fwd_a_audio else 0
        audio_caller_to_server_rtcp = fwd_a_audio_rtcp.packets_received if fwd_a_audio_rtcp else 0
        audio_server_to_callee_rtp = fwd_a_audio.packets_sent if fwd_a_audio else 0
        audio_server_to_callee_rtcp = fwd_a_audio_rtcp.packets_sent if fwd_a_audio_rtcp else 0
        # B-leg: 被叫→服务器（接收）和 服务器→主叫（发送）
        audio_callee_to_server_rtp = fwd_b_audio.packets_received if fwd_b_audio else 0
        audio_callee_to_server_rtcp = fwd_b_audio_rtcp.packets_received if fwd_b_audio_rtcp else 0
        audio_server_to_caller_rtp = fwd_b_audio.packets_sent if fwd_b_audio else 0
        audio_server_to_caller_rtcp = fwd_b_audio_rtcp.packets_sent if fwd_b_audio_rtcp else 0
        
        # 视频统计：以服务器为中心
        # A-leg: 主叫→服务器（接收）和 服务器→被叫（发送）
        video_caller_to_server_rtp = fwd_a_video.packets_received if fwd_a_video else 0
        video_caller_to_server_rtcp = fwd_a_video_rtcp.packets_received if fwd_a_video_rtcp else 0
        video_server_to_callee_rtp = fwd_a_video.packets_sent if fwd_a_video else 0
        video_server_to_callee_rtcp = fwd_a_video_rtcp.packets_sent if fwd_a_video_rtcp else 0
        # B-leg: 被叫→服务器（接收）和 服务器→主叫（发送）
        video_callee_to_server_rtp = fwd_b_video.packets_received if fwd_b_video else 0
        video_callee_to_server_rtcp = fwd_b_video_rtcp.packets_received if fwd_b_video_rtcp else 0
        video_server_to_caller_rtp = fwd_b_video.packets_sent if fwd_b_video else 0
        video_server_to_caller_rtcp = fwd_b_video_rtcp.packets_sent if fwd_b_video_rtcp else 0
        
        # 兼容旧格式：主叫→被叫（上行），被叫→主叫（下行）
        audio_uplink_rtp = audio_server_to_callee_rtp
        audio_uplink_rtcp = audio_server_to_callee_rtcp
        audio_downlink_rtp = audio_server_to_caller_rtp
        audio_downlink_rtcp = audio_server_to_caller_rtcp
        
        video_uplink_rtp = video_server_to_callee_rtp
        video_uplink_rtcp = video_server_to_callee_rtcp
        video_downlink_rtp = video_server_to_caller_rtp
        video_downlink_rtcp = video_server_to_caller_rtcp
        
        duration = time.time() - session.started_at if session.started_at else 0
        diagnosis = []
        if not session.started_at:
            diagnosis.append("媒体转发未启动")
        elif fwd_a_audio and fwd_b_audio:
            # 音频诊断
            if audio_uplink_rtp == 0 and audio_downlink_rtp == 0 and duration > 5:
                diagnosis.append("音频长时间无包，可能双不通")
            elif audio_uplink_rtp == 0 and duration > 2:
                diagnosis.append("音频上行（主叫→被叫）未收到")
            elif audio_downlink_rtp == 0 and duration > 2:
                diagnosis.append("音频下行（被叫→主叫）未收到")
            
            # 视频诊断
            if fwd_a_video or fwd_b_video:
                if video_uplink_rtp == 0 and video_downlink_rtp == 0 and duration > 5:
                    diagnosis.append("视频长时间无包，可能双不通")
                elif video_uplink_rtp == 0 and duration > 2:
                    diagnosis.append("视频上行（主叫→被叫）未收到")
                elif video_downlink_rtp == 0 and duration > 2:
                    diagnosis.append("视频下行（被叫→主叫）未收到")
            
            if not diagnosis:
                diagnosis.append("正常转发")
        else:
            diagnosis.append("转发器未创建")
        
        return {
            'call_id': call_id,
            'caller': session.caller_number or 'N/A',
            'callee': session.callee_number or 'N/A',
            # 端口信息
            'a_leg_rtp_port': session.a_leg_rtp_port,
            'a_leg_rtcp_port': session.a_leg_rtcp_port,
            'b_leg_rtp_port': session.b_leg_rtp_port,
            'b_leg_rtcp_port': session.b_leg_rtcp_port,
            'a_leg_video_rtp_port': session.a_leg_video_rtp_port,
            'a_leg_video_rtcp_port': session.a_leg_video_rtcp_port,
            'b_leg_video_rtp_port': session.b_leg_video_rtp_port,
            'b_leg_video_rtcp_port': session.b_leg_video_rtcp_port,
            # 音频统计（兼容旧格式）
            'a_to_b_packets': audio_uplink_rtp,
            'b_to_a_packets': audio_downlink_rtp,
            # 详细统计（以服务器为中心）
            'audio': {
                'uplink': {
                    'rtp': audio_uplink_rtp, 
                    'rtcp': audio_uplink_rtcp,
                    'caller_to_server': {'rtp': audio_caller_to_server_rtp, 'rtcp': audio_caller_to_server_rtcp},
                    'server_to_callee': {'rtp': audio_server_to_callee_rtp, 'rtcp': audio_server_to_callee_rtcp},
                },
                'downlink': {
                    'rtp': audio_downlink_rtp, 
                    'rtcp': audio_downlink_rtcp,
                    'callee_to_server': {'rtp': audio_callee_to_server_rtp, 'rtcp': audio_callee_to_server_rtcp},
                    'server_to_caller': {'rtp': audio_server_to_caller_rtp, 'rtcp': audio_server_to_caller_rtcp},
                },
            },
            'video': {
                'uplink': {
                    'rtp': video_uplink_rtp, 
                    'rtcp': video_uplink_rtcp,
                    'caller_to_server': {'rtp': video_caller_to_server_rtp, 'rtcp': video_caller_to_server_rtcp},
                    'server_to_callee': {'rtp': video_server_to_callee_rtp, 'rtcp': video_server_to_callee_rtcp},
                },
                'downlink': {
                    'rtp': video_downlink_rtp, 
                    'rtcp': video_downlink_rtcp,
                    'callee_to_server': {'rtp': video_callee_to_server_rtp, 'rtcp': video_callee_to_server_rtcp},
                    'server_to_caller': {'rtp': video_server_to_caller_rtp, 'rtcp': video_server_to_caller_rtcp},
                },
            } if (fwd_a_video or fwd_b_video) else None,
            'caller_latched': True if fwd_a_audio and fwd_a_audio.packets_sent > 0 else False,
            'callee_latched': True if fwd_b_audio and fwd_b_audio.packets_sent > 0 else False,
            'duration': duration,
            'duration_sec': round(duration, 1),
            'diagnosis': ' | '.join(diagnosis),
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
        print(f"  模式: 双端口")
        print(f"  主叫({caller}): 信令={session.a_leg_signaling_addr}, SDP={session.a_leg_remote_addr}")
        print(f"  被叫({callee}): 信令={session.b_leg_signaling_addr}, SDP={session.b_leg_remote_addr}")
        print(f"  主叫应发送到: {self.server_ip}:{session.a_leg_rtp_port}")
        print(f"  被叫应发送到: {self.server_ip}:{session.b_leg_rtp_port}")
        
        fwd_a = self._forwarders.get((call_id, 'a', 'rtp'))
        fwd_b = self._forwarders.get((call_id, 'b', 'rtp'))
        if fwd_a and fwd_b:
            elapsed = time.time() - session.started_at if session.started_at else 0
            print(f"  运行: {'是' if (fwd_a.running and fwd_b.running) else '否'}, 已启动 {elapsed:.1f}s")
            print(f"  主叫→被叫: {fwd_a.packets_sent} 包 (A-leg端口 {session.a_leg_rtp_port})")
            print(f"  被叫→主叫: {fwd_b.packets_sent} 包 (B-leg端口 {session.b_leg_rtp_port})")
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
