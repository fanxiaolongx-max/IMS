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
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass, field


@dataclass
class MediaSession:
    """媒体会话信息"""
    call_id: str
    # 主叫侧 (A-leg) - 端口（必须有，无默认值）
    a_leg_rtp_port: int
    a_leg_rtcp_port: int
    # 被叫侧 (B-leg) - 端口（必须有，无默认值）
    b_leg_rtp_port: int
    b_leg_rtcp_port: int
    
    # 主叫侧 - 其他信息（可选，有默认值）
    a_leg_remote_addr: Optional[Tuple[str, int]] = None  # 从SDP提取的地址
    a_leg_actual_addr: Optional[Tuple[str, int]] = None  # 对称RTP学习到的地址
    a_leg_sdp: Optional[str] = None  # 原始SDP
    a_leg_signaling_addr: Optional[Tuple[str, int]] = None  # 信令来源地址（优先使用）
    
    # 被叫侧 - 其他信息（可选，有默认值）
    b_leg_remote_addr: Optional[Tuple[str, int]] = None
    b_leg_actual_addr: Optional[Tuple[str, int]] = None
    b_leg_sdp: Optional[str] = None
    b_leg_signaling_addr: Optional[Tuple[str, int]] = None  # 信令来源地址（优先使用）
    
    # 状态（可选，有默认值）
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    
    # 统计（可选，有默认值）
    a_to_b_bytes: int = 0
    b_to_a_bytes: int = 0
    a_to_b_packets: int = 0
    b_to_a_packets: int = 0
    
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
        从SDP中提取媒体信息
        
        Returns:
            {
                'connection_ip': str,  # c= 行中的IP
                'audio_port': int,     # m=audio 行中的端口
                'audio_payloads': List[str],  # 支持的payload类型
                'codec_info': Dict[str, str]  # payload -> codec
            }
        """
        if not sdp_body:
            return None
        
        result = {
            'connection_ip': None,
            'audio_port': None,
            'audio_payloads': [],
            'codec_info': {}
        }
        
        lines = sdp_body.split('\r\n') if '\r\n' in sdp_body else sdp_body.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # 解析 c= 行 (连接信息)
            # 格式: c=IN IP4 192.168.1.100
            if line.startswith('c='):
                parts = line[2:].split()
                if len(parts) >= 3 and parts[1] == 'IP4':
                    result['connection_ip'] = parts[2]
            
            # 解析 m=audio 行 (媒体描述)
            # 格式: m=audio 49170 RTP/AVP 0 8 18
            elif line.startswith('m=audio '):
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        result['audio_port'] = int(parts[1])
                        result['audio_payloads'] = parts[3:]
                    except ValueError:
                        pass
            
            # 解析 a=rtpmap 行 (编解码映射)
            # 格式: a=rtpmap:0 PCMU/8000
            elif line.startswith('a=rtpmap:'):
                match = re.match(r'a=rtpmap:(\d+)\s+(.+)', line)
                if match:
                    payload = match.group(1)
                    codec_info = match.group(2)
                    result['codec_info'][payload] = codec_info
        
        return result if result['audio_port'] else None
    
    @staticmethod
    def modify_sdp(sdp_body: str, new_ip: str, new_port: int, force_plain_rtp: bool = False) -> str:
        """
        修改SDP中的IP地址和端口
        
        Args:
            sdp_body: 原始SDP
            new_ip: 新的IP地址
            new_port: 新的RTP端口
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
                    line = f"m=audio {new_port} {proto} {payloads}"
            
            # 跳过 SRTP 加密属性行（仅在强制使用普通RTP时）
            elif force_plain_rtp and (line.startswith('a=crypto:') or line.startswith('a=fingerprint:')):
                continue
            
            new_lines.append(line)
        
        # 确保使用 \r\n 作为行分隔符 (SIP标准)
        return '\r\n'.join(new_lines) + '\r\n'


class RTPForwarder:
    """RTP转发器 (单端口)"""
    
    def __init__(self, local_port: int, target_addr: Tuple[str, int], 
                 symmetric_rtp: bool = True, timeout: float = 30.0):
        """
        初始化RTP转发器
        
        Args:
            local_port: 本地监听端口
            target_addr: 目标地址 (ip, port)
            symmetric_rtp: 是否启用对称RTP
            timeout: 对称RTP学习超时时间（秒）
        """
        self.local_port = local_port
        self.target_addr = target_addr
        self.symmetric_rtp = symmetric_rtp
        self.timeout = timeout
        
        self.sock: Optional[socket.socket] = None
        self.running = False
        self.thread: Optional[threading.Thread] = None
        
        # 对称RTP学习的实际地址
        self.actual_target_addr = target_addr
        self._addr_learned = False
        self._relearn_needed = False  # 重新学习标志（用于re-INVITE）
        
        # 对端转发器引用（用于跨转发器对称RTP学习）
        # A-leg转发器的 peer_forwarder 指向 B-leg转发器（反之亦然）
        # 当本转发器收到首包时，把源地址通知给对端转发器作为目标地址
        self.peer_forwarder: Optional['RTPForwarder'] = None
        
        # 统计
        self.packets_received = 0
        self.packets_sent = 0
        self.bytes_received = 0
        self.bytes_sent = 0
        
        # 收包统计（用于调试）
        self._last_log_time = 0
        self._last_packets = 0
        self._last_bytes = 0
        self._src_addr_history: List[Tuple[str, int]] = []  # 记录源地址历史
    
    def start(self):
        """启动转发器"""
        if self.running:
            return
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('0.0.0.0', self.local_port))
        self.sock.settimeout(1.0)  # 1秒超时，便于检查running标志
        
        self.running = True
        self.thread = threading.Thread(target=self._forward_loop, daemon=True)
        self.thread.start()
    
    def stop(self):
        """停止转发器"""
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
    
    def update_target(self, new_addr: Tuple[str, int]):
        """更新目标地址（用于对称RTP学习后）"""
        self.actual_target_addr = new_addr
        self._addr_learned = True
    
    def reset_symmetric_learning(self):
        """重置对称RTP学习状态（用于re-INVITE场景）"""
        self._addr_learned = False
        self._relearn_needed = True
        print(f"[RTP] 重置对称RTP学习状态: 端口 {self.local_port}")
    
    def _learn_symmetric_addr(self) -> bool:
        """学习对称RTP地址"""
        if not self.symmetric_rtp or self._addr_learned:
            return True
        if not self.sock:
            return False

        start_time = time.time()
        try:
            self.sock.setblocking(False)
        except Exception:
            return True

        try:
            while time.time() - start_time < self.timeout:
                if not self.running or not self.sock:
                    return False

                try:
                    data, addr = self.sock.recvfrom(2048)
                    if len(data) >= 12:  # RTP头至少12字节
                        # 学习到这个地址
                        old_addr = self.actual_target_addr
                        self.actual_target_addr = (addr[0], addr[1])
                        self._addr_learned = True
                        print(f"[RTP] 对称RTP学习: {old_addr} -> {addr}")

                        # 转发这个包
                        self._send_packet(data, addr)
                        return True
                except BlockingIOError:
                    time.sleep(0.01)
                    continue
        finally:
            if self.sock:
                try:
                    self.sock.setblocking(True)
                except Exception:
                    pass

        # 超时，使用配置的地址
        print(f"[RTP] 对称RTP超时，使用配置地址: {self.actual_target_addr}")
        return True
    
    def _send_packet(self, data: bytes, from_addr: Tuple[str, int]):
        """发送数据包到目标地址"""
        if not self.sock:
            return
        try:
            self.sock.sendto(data, self.actual_target_addr)
            self.packets_sent += 1
            self.bytes_sent += len(data)
        except Exception as e:
            print(f"[RTP] 发送错误: {e}")
    
    def _log_stats(self):
        """输出收包统计"""
        now = time.time()
        if now - self._last_log_time >= 5:  # 每5秒输出一次
            pkts_diff = self.packets_received - self._last_packets
            bytes_diff = self.bytes_received - self._last_bytes
            if pkts_diff > 0 or self.packets_received > 0:
                learned_status = "已学习" if self._addr_learned else "未学习"
                print(f"[RTP-STATS] 端口 {self.local_port}: "
                      f"收包 {self.packets_received} ({pkts_diff}/5s), "
                      f"发包 {self.packets_sent}, "
                      f"目标 {self.actual_target_addr} ({learned_status}), "
                      f"源地址历史 {self._src_addr_history[-3:] if self._src_addr_history else 'None'}")
            elif self.packets_received == 0 and now - self._last_log_time >= 10:
                # 如果10秒内没有收到包，输出警告
                print(f"[RTP-WARNING] 端口 {self.local_port}: 10秒内未收到任何RTP包，目标 {self.actual_target_addr}")
            self._last_log_time = now
            self._last_packets = self.packets_received
            self._last_bytes = self.bytes_received
    
    def _forward_loop(self):
        """
        转发主循环 - B2BUA模式，支持跨转发器对称RTP学习（Opto-RTP / Latching）
        
        NAT 穿越原理：
        - 信令端口和 RTP 端口经过 NAT 后映射到不同的公网端口
        - 信令: 10.x.x.x:5060 → NAT → 1.2.3.4:3189（服务器知道）
        - RTP:  10.x.x.x:53186 → NAT → 1.2.3.4:XXXXX（服务器不知道！）
        - SDP 中写的是私网端口 53186，但 NAT 后变成了随机端口 XXXXX
        
        解决方案（业界标准：Opto-RTP / Latching）：
        - A-leg 端口收到主叫首包 → 首包源地址就是主叫的真实 NAT 后地址
        - 把这个地址通知给 B-leg 转发器（peer_forwarder），作为"发回给主叫"的目标
        - 同理 B-leg 端口收到被叫首包 → 通知 A-leg 转发器
        
        注意：不是更新自己的目标，而是更新对端转发器的目标（跨转发器学习）
        """
        import sys
        initial_target = self.actual_target_addr
        print(f"[RTP] 转发器启动: 端口 {self.local_port}, 初始目标 {initial_target}, "
              f"对称RTP={self.symmetric_rtp}, peer={self.peer_forwarder.local_port if self.peer_forwarder else 'None'}",
              file=sys.stderr, flush=True)

        while self.running and self.sock:
            try:
                data, addr = self.sock.recvfrom(2048)
                
                # 检查是否是RTP/SRTP包（至少12字节头）
                if len(data) < 12:
                    continue
                
                self.packets_received += 1
                self.bytes_received += len(data)
                
                # 记录源地址（去重保存最近5个）
                if addr not in self._src_addr_history:
                    self._src_addr_history.append(addr)
                    if len(self._src_addr_history) > 5:
                        self._src_addr_history.pop(0)
                    print(f"[RTP-SRC] 端口 {self.local_port}: 新源地址 {addr} (当前目标: {self.actual_target_addr})",
                          file=sys.stderr, flush=True)
                
                # 跨转发器对称RTP学习（Latching）
                # 本端口收到对端的首包 → 通知对端转发器（peer_forwarder）更新目标地址
                # 例如：A-leg端口(20000)收到主叫RTP → 通知B-leg转发器：发往主叫应该用这个源地址
                if self.symmetric_rtp and not self._addr_learned:
                    self._addr_learned = True
                    if self.peer_forwarder:
                        old_peer_target = self.peer_forwarder.actual_target_addr
                        self.peer_forwarder.actual_target_addr = addr
                        print(f"[RTP-LATCH] 端口 {self.local_port}: 对称RTP学习成功（Latching）",
                              file=sys.stderr, flush=True)
                        print(f"  收到首包来自: {addr} (NAT后的真实地址)",
                              file=sys.stderr, flush=True)
                        print(f"  更新对端转发器(端口{self.peer_forwarder.local_port})目标: {old_peer_target} → {addr}",
                              file=sys.stderr, flush=True)
                    else:
                        print(f"[RTP-LATCH] 端口 {self.local_port}: 收到首包来自 {addr}，但无对端转发器",
                              file=sys.stderr, flush=True)
                
                # 转发到目标地址
                self._send_packet(data, addr)
                
                # 定期输出统计
                self._log_stats()
                
            except socket.timeout:
                self._log_stats()
                continue
            except Exception as e:
                if self.running:
                    print(f"[RTP-ERROR] 端口 {self.local_port}: 转发错误: {e}",
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
                                  caller_addr: Tuple[str, int]) -> Tuple[str, Optional[MediaSession]]:
        """
        处理转发给被叫的INVITE SDP
        修改SDP指向服务器的B-leg端口，让被叫发送RTP到B-leg端口
        同时保存A-leg的媒体信息和信令地址
        
        Args:
            call_id: 呼叫ID
            sdp_body: 原始SDP
            caller_addr: 主叫信令地址（NAT后的真实地址）
            
        Returns:
            (修改后的SDP, MediaSession对象)
        """
        # 获取或创建会话
        session = self._sessions.get(call_id)
        if not session:
            session = self.create_session(call_id)
            if not session:
                return sdp_body, None
        
        # 保存A-leg信令地址（优先使用，NAT后的真实地址）
        # 使用信令来源端口+1作为RTP端口估计（标准RTP端口是SDP端口+0）
        session.a_leg_signaling_addr = caller_addr
        print(f"[MediaRelay] A-leg信令地址: {caller_addr} (NAT后真实地址)")
        
        # 提取A-leg原始媒体信息（SDP中声明的地址）
        media_info = self.sdp_processor.extract_media_info(sdp_body)
        if media_info:
            session.a_leg_remote_addr = (media_info['connection_ip'], media_info['audio_port'])
            session.a_leg_sdp = sdp_body
            print(f"[MediaRelay] A-leg媒体信息: {session.a_leg_remote_addr}")
        
        # 修改SDP（指向B-leg端口，给被叫用的）
        new_sdp = self.sdp_processor.modify_sdp(
            sdp_body,
            self.server_ip,
            session.b_leg_rtp_port
        )
        
        print(f"[MediaRelay] INVITE转发给被叫，SDP修改为B-leg端口: {session.b_leg_rtp_port}")
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
            session.b_leg_remote_addr = (media_info['connection_ip'], media_info['audio_port'])
            session.b_leg_sdp = sdp_body
        
        # 修改SDP（指向A-leg端口，给主叫用的）
        new_sdp = self.sdp_processor.modify_sdp(
            sdp_body,
            self.server_ip,
            session.a_leg_rtp_port
        )
        
        print(f"[MediaRelay] 200OK发给主叫，SDP修改为A-leg端口: {session.a_leg_rtp_port}")
        return new_sdp, True
    
    def start_media_forwarding(self, call_id: str):
        """
        启动媒体转发
        在收到200 OK后调用（支持re-INVITE时更新目标地址）
        正常转发模式：主叫的媒体转发给被叫，被叫的媒体转发给主叫
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
        
        # 获取 RTP 目标地址：必须用 SDP 的 RTP 端口（信令 IP + SDP 端口），否则主被叫听不到
        a_leg_target = session.get_a_leg_rtp_target_addr()  # 发往主叫的地址（用于B-leg转发器）
        b_leg_target = session.get_b_leg_rtp_target_addr()  # 发往被叫的地址（用于A-leg转发器）
        
        if not a_leg_target or not b_leg_target:
            print(f"[MediaRelay] 无法启动转发，目标地址不完整: {call_id}", flush=True)
            print(f"  A-leg目标: {a_leg_target}", flush=True)
            print(f"  B-leg目标: {b_leg_target}", flush=True)
            return False
        
        # 验证目标地址正确性（防止环回）
        if a_leg_target == b_leg_target:
            print(f"[MediaRelay-ERROR] 目标地址相同，会导致环回！", flush=True)
            print(f"  A-leg目标: {a_leg_target}", flush=True)
            print(f"  B-leg目标: {b_leg_target}", flush=True)
            return False
        
        # 如果转发已启动，更新目标地址（re-INVITE场景）
        if session.started_at:
            print(f"[MediaRelay] 转发已启动，更新目标地址: {call_id}")
            print(f"  A-leg信令地址: {session.a_leg_signaling_addr}")
            print(f"  A-legSDP地址: {session.a_leg_remote_addr}")
            print(f"  B-leg信令地址: {session.b_leg_signaling_addr}")
            print(f"  B-legSDP地址: {session.b_leg_remote_addr}")
            print(f"  使用A-leg目标: {a_leg_target}")
            print(f"  使用B-leg目标: {b_leg_target}")
            
            # 更新已有转发器的目标地址（正常转发模式）
            forwarder_a_to_b = self._forwarders.get((call_id, 'a', 'rtp'))
            forwarder_b_to_a = self._forwarders.get((call_id, 'b', 'rtp'))
            forwarder_a_rtcp = self._forwarders.get((call_id, 'a', 'rtcp'))
            forwarder_b_rtcp = self._forwarders.get((call_id, 'b', 'rtcp'))
            
            if forwarder_a_to_b:
                forwarder_a_to_b.update_target(b_leg_target)  # 转发给B-leg
                forwarder_a_to_b.reset_symmetric_learning()  # 重新学习真实地址
            if forwarder_b_to_a:
                forwarder_b_to_a.update_target(a_leg_target)  # 转发给A-leg
                forwarder_b_to_a.reset_symmetric_learning()  # 重新学习真实地址
            if forwarder_a_rtcp:
                forwarder_a_rtcp.update_target((b_leg_target[0], b_leg_target[1] + 1))  # 转发给B-leg
            if forwarder_b_rtcp:
                forwarder_b_rtcp.update_target((a_leg_target[0], a_leg_target[1] + 1))  # 转发给A-leg
            
            return True
        
        import sys
        print(f"[MediaRelay] 启动媒体转发: {call_id}", file=sys.stderr, flush=True)
        print(f"  主叫(A): 信令={session.a_leg_signaling_addr}, SDP={session.a_leg_remote_addr}, 初始目标={a_leg_target}", file=sys.stderr, flush=True)
        print(f"  被叫(B): 信令={session.b_leg_signaling_addr}, SDP={session.b_leg_remote_addr}, 初始目标={b_leg_target}", file=sys.stderr, flush=True)
        print(f"  转发: A端口({session.a_leg_rtp_port})→被叫{b_leg_target}, B端口({session.b_leg_rtp_port})→主叫{a_leg_target}", file=sys.stderr, flush=True)
        print(f"  对称RTP学习(Latching): 已启用，收到首包后自动学习NAT后真实地址", file=sys.stderr, flush=True)
        
        # 创建4个转发器（正常转发模式）：
        # A-leg RTP -> B-leg RTP (主叫媒体转发给被叫)
        # B-leg RTP -> A-leg RTP (被叫媒体转发给主叫)
        # A-leg RTCP -> B-leg RTCP
        # B-leg RTCP -> A-leg RTCP
        
        # A-leg RTP 接收器 (端口: session.a_leg_rtp_port)
        # 收到后转发到 B-leg 的实际地址（主叫媒体转发给被叫）
        forwarder_a_to_b = RTPForwarder(
            local_port=session.a_leg_rtp_port,
            target_addr=b_leg_target,
            symmetric_rtp=True
        )
        forwarder_a_to_b.start()
        
        # B-leg RTP 接收器 (端口: session.b_leg_rtp_port)
        # 收到后转发到 A-leg 的实际地址（被叫媒体转发给主叫）
        forwarder_b_to_a = RTPForwarder(
            local_port=session.b_leg_rtp_port,
            target_addr=a_leg_target,
            symmetric_rtp=True
        )
        forwarder_b_to_a.start()
        
        # RTCP转发器（正常转发模式）
        forwarder_a_rtcp = RTPForwarder(
            local_port=session.a_leg_rtcp_port,
            target_addr=(b_leg_target[0], b_leg_target[1] + 1),
            symmetric_rtp=False
        )
        forwarder_a_rtcp.start()
        
        forwarder_b_rtcp = RTPForwarder(
            local_port=session.b_leg_rtcp_port,
            target_addr=(a_leg_target[0], a_leg_target[1] + 1),
            symmetric_rtp=False
        )
        forwarder_b_rtcp.start()
        
        # 设置跨转发器对称RTP学习（peer关联）
        # A-leg端口收到主叫首包 → 更新B-leg转发器的目标（发回给主叫的地址）
        # B-leg端口收到被叫首包 → 更新A-leg转发器的目标（发回给被叫的地址）
        forwarder_a_to_b.peer_forwarder = forwarder_b_to_a  # A收到主叫包→更新B的目标为主叫真实地址
        forwarder_b_to_a.peer_forwarder = forwarder_a_to_b  # B收到被叫包→更新A的目标为被叫真实地址
        
        # 保存转发器
        self._forwarders[(call_id, 'a', 'rtp')] = forwarder_a_to_b
        self._forwarders[(call_id, 'b', 'rtp')] = forwarder_b_to_a
        self._forwarders[(call_id, 'a', 'rtcp')] = forwarder_a_rtcp
        self._forwarders[(call_id, 'b', 'rtcp')] = forwarder_b_rtcp
        
        session.started_at = time.time()
        import sys
        print(f"[MediaRelay] 媒体转发已启动: {call_id}", file=sys.stderr, flush=True)
        print(f"[MediaRelay] 媒体转发已启动: {call_id}", flush=True)
        
        return True
    
    def stop_media_forwarding(self, call_id: str):
        """停止媒体转发"""
        session = self._sessions.get(call_id)
        if not session:
            return
        
        print(f"[MediaRelay] 停止媒体转发: {call_id}")
        
        # 停止所有转发器
        for key in [(call_id, 'a', 'rtp'), (call_id, 'b', 'rtp'),
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
        
        # 释放端口
        self.port_manager.release_port_pair(session.a_leg_rtp_port, session.a_leg_rtcp_port)
        self.port_manager.release_port_pair(session.b_leg_rtp_port, session.b_leg_rtcp_port)
        
        # 清理映射
        with self._lock:
            for port in [session.a_leg_rtp_port, session.a_leg_rtcp_port,
                        session.b_leg_rtp_port, session.b_leg_rtcp_port]:
                self._port_session_map.pop(port, None)
            
            self._sessions.pop(call_id, None)
        
        print(f"[MediaRelay] 会话已清理: {call_id}")
    
    def get_session_stats(self, call_id: str) -> Optional[Dict]:
        """获取会话统计信息"""
        session = self._sessions.get(call_id)
        if not session:
            return None
        
        forwarder_a = self._forwarders.get((call_id, 'a', 'rtp'))
        forwarder_b = self._forwarders.get((call_id, 'b', 'rtp'))
        
        return {
            'call_id': call_id,
            'a_leg_port': session.a_leg_rtp_port,
            'b_leg_port': session.b_leg_rtp_port,
            'a_to_b_packets': forwarder_a.packets_sent if forwarder_a else 0,
            'b_to_a_packets': forwarder_b.packets_sent if forwarder_b else 0,
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
        
        print(f"\n========== 媒体诊断: {call_id} ==========")
        print(f"[服务器配置]")
        print(f"  服务器IP: {self.server_ip}")
        
        print(f"\n[地址信息]")
        print(f"  A-leg(1001):")
        print(f"    信令地址: {session.a_leg_signaling_addr} (NAT后真实地址，优先使用)")
        print(f"    SDP声明:  {session.a_leg_remote_addr} (可能为私网)")
        print(f"  B-leg(1003):")
        print(f"    信令地址: {session.b_leg_signaling_addr} (NAT后真实地址，优先使用)")
        print(f"    SDP声明:  {session.b_leg_remote_addr} (可能为私网)")
        
        print(f"\n[服务器监听端口]")
        print(f"  A-leg RTP端口 {session.a_leg_rtp_port}: {'✓ 监听中' if self._check_port_listening(session.a_leg_rtp_port) else '❌ 未监听'}")
        print(f"  B-leg RTP端口 {session.b_leg_rtp_port}: {'✓ 监听中' if self._check_port_listening(session.b_leg_rtp_port) else '❌ 未监听'}")
        
        print(f"\n[转发器状态]")
        print(f"  会话启动时间: {session.started_at}")
        print(f"  使用目标地址: A-leg={session.get_a_leg_target_addr()}, B-leg={session.get_b_leg_target_addr()}")
        
        # A-leg RTP转发器统计（接收主叫RTP，转发给被叫）
        fa = self._forwarders.get((call_id, 'a', 'rtp'))
        if fa:
            expected_target = session.get_b_leg_rtp_target_addr()  # 应该转发给被叫
            print(f"\n  [A-leg转发器] 端口 {fa.local_port} (接收主叫RTP -> 转发给被叫)")
            print(f"    运行状态: {'运行中' if fa.running else '已停止'}")
            print(f"    配置目标: {fa.actual_target_addr}")
            print(f"    期望目标: {expected_target} (被叫地址)")
            if fa.actual_target_addr != expected_target:
                print(f"    ⚠️ 警告: 配置目标与期望目标不一致！可能导致转发错误")
            print(f"    收包: {fa.packets_received}, 发包: {fa.packets_sent}")
            print(f"    源地址历史: {fa._src_addr_history}")
            if fa.packets_received == 0:
                print(f"    ❌ 问题: A-leg转发器没有收到任何RTP包！")
                print(f"    说明: 主叫没有发送RTP到服务器A-leg端口 {fa.local_port}")
                print(f"    主叫应该发送到: {self.server_ip}:{fa.local_port}")
                print(f"    检查: 主叫是否按照200 OK中的SDP发送RTP？")
        else:
            print(f"\n  [A-leg转发器] 未创建")
        
        # B-leg RTP转发器统计（接收被叫RTP，转发给主叫）
        fb = self._forwarders.get((call_id, 'b', 'rtp'))
        if fb:
            expected_target = session.get_a_leg_rtp_target_addr()  # 应该转发给主叫
            print(f"\n  [B-leg转发器] 端口 {fb.local_port} (接收被叫RTP -> 转发给主叫)")
            print(f"    运行状态: {'运行中' if fb.running else '已停止'}")
            print(f"    配置目标: {fb.actual_target_addr}")
            print(f"    期望目标: {expected_target} (主叫地址)")
            if fb.actual_target_addr != expected_target:
                print(f"    ⚠️ 警告: 配置目标与期望目标不一致！可能导致环回或转发错误")
                print(f"    问题: B-leg转发器应该转发给主叫，但配置目标是 {fb.actual_target_addr}")
                print(f"    这会导致被叫的RTP被转发回被叫自己，造成环回！")
            print(f"    收包: {fb.packets_received}, 发包: {fb.packets_sent}")
            print(f"    源地址历史: {fb._src_addr_history}")
            if fb.packets_received > 0 and fb.packets_sent == 0:
                print(f"    ❌ 问题: B-leg转发器收到包但没有发送！")
                print(f"    检查: 目标地址 {fb.actual_target_addr} 是否正确？")
            elif fb.packets_received == 0:
                print(f"    ❌ 问题: B-leg转发器没有收到任何RTP包！")
                print(f"    说明: 被叫没有发送RTP到服务器B-leg端口 {fb.local_port}")
                print(f"    被叫应该发送到: {self.server_ip}:{fb.local_port}")
        else:
            print(f"\n  [B-leg转发器] 未创建")
        
        print(f"\n[预期媒体流]")
        print(f"  1001应发送到: {self.server_ip}:{session.a_leg_rtp_port}")
        print(f"  1003应发送到: {self.server_ip}:{session.b_leg_rtp_port}")
        
        print(f"\n[诊断结论]")
        if fa and fb and fa.running and fb.running:
            if fa.packets_received == 0 and fb.packets_received == 0:
                print(f"  ❌ 双向都没有收到媒体包")
                print(f"     → 检查1001和1003是否把RTP发到上述服务器端口")
                print(f"     → 可能SDP中的IP/端口修改未生效")
                print(f"     → 可能终端有NAT，没有发送到服务器")
            elif fa.packets_received == 0:
                print(f"  ❌ A-leg(1001→服务器)没有媒体包")
                print(f"     → 1001没有把RTP发到 {self.server_ip}:{session.a_leg_rtp_port}")
            elif fb.packets_received == 0:
                print(f"  ❌ B-leg(1003→服务器)没有媒体包")
                print(f"     → 1003没有把RTP发到 {self.server_ip}:{session.b_leg_rtp_port}")
            else:
                print(f"  ✓ 双向都有媒体包")
                if fa.packets_sent == 0:
                    print(f"  ❌ A-leg转发器没有发包到1003")
                if fb.packets_sent == 0:
                    print(f"  ❌ B-leg转发器没有发包到1001")
        else:
            print(f"  ❌ 转发器未启动或已停止")
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
