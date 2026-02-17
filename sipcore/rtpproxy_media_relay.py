# sipcore/rtpproxy_media_relay.py
"""
基于RTPProxy的媒体中继实现

使用成熟的开源RTPProxy替代自定义RTP转发代码，提供更稳定可靠的媒体中继功能。

RTPProxy特性：
- 高性能RTP代理，广泛用于生产环境
- 自动处理NAT穿透和对称RTP
- 支持ICE、SRTP等高级特性
- 低延迟、低丢包率

使用方法：
1. 安装rtpproxy: apt-get install rtpproxy
2. 启动rtpproxy: rtpproxy -l <server_ip> -s udp:127.0.0.1:7722 -F
3. 在代码中使用RTPProxyMediaRelay替代MediaRelay
"""

import re
import sys
import time
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field

from sipcore.rtpproxy_client import RTPProxyClient
from sipcore.media_relay import MediaSession, SDPProcessor, RTPPortManager


class RTPProxyMediaRelay:
    """
    基于RTPProxy的媒体中继管理器
    
    实现与MediaRelay相同的接口，但使用RTPProxy作为底层RTP代理引擎。
    """
    
    def __init__(self, server_ip: str,
                 rtpproxy_socket: Optional[str] = None,
                 rtpproxy_tcp: Optional[Tuple[str, int]] = None,
                 rtpproxy_udp: Optional[Tuple[str, int]] = None):
        """
        初始化RTPProxy媒体中继
        
        Args:
            server_ip: 服务器IP地址（用于SDP中声明）
            rtpproxy_socket: rtpproxy Unix socket路径，例如 '/var/run/rtpproxy.sock'
            rtpproxy_tcp: rtpproxy TCP地址，例如 ('127.0.0.1', 7722)
            rtpproxy_udp: rtpproxy UDP地址，例如 ('127.0.0.1', 7722) - 用于UDP控制socket
        """
        self.server_ip = server_ip
        self.sdp_processor = SDPProcessor()
        self.port_manager = RTPPortManager()
        
        # 初始化RTPProxy客户端
        try:
            self.rtpproxy = RTPProxyClient(
                socket_path=rtpproxy_socket,
                tcp_addr=rtpproxy_tcp,
                udp_addr=rtpproxy_udp
            )
            print(f"[RTPProxyMediaRelay] RTPProxy客户端初始化成功", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[RTPProxyMediaRelay-ERROR] RTPProxy客户端初始化失败: {e}", file=sys.stderr, flush=True)
            print(f"[RTPProxyMediaRelay-ERROR] 请确保rtpproxy已启动:", file=sys.stderr, flush=True)
            if rtpproxy_socket:
                print(f"[RTPProxyMediaRelay-ERROR]   rtpproxy -l {server_ip} -s unix:{rtpproxy_socket} -F", file=sys.stderr, flush=True)
            elif rtpproxy_udp:
                print(f"[RTPProxyMediaRelay-ERROR]   rtpproxy -l {server_ip} -s udp:{rtpproxy_udp[0]}:{rtpproxy_udp[1]} -F", file=sys.stderr, flush=True)
            elif rtpproxy_tcp:
                print(f"[RTPProxyMediaRelay-ERROR]   rtpproxy -l {server_ip} -s tcp:{rtpproxy_tcp[0]}:{rtpproxy_tcp[1]} -F", file=sys.stderr, flush=True)
            raise
        
        # 会话管理: call_id -> MediaSession
        self._sessions: Dict[str, MediaSession] = {}
        
        # RTPProxy会话映射: call_id -> {'from_tag': session_id, 'to_tag': session_id}
        self._rtpproxy_sessions: Dict[str, Dict[str, str]] = {}
        
        print(f"[RTPProxyMediaRelay] 初始化完成，服务器IP: {server_ip}", file=sys.stderr, flush=True)
    
    def create_session(self, call_id: str) -> Optional[MediaSession]:
        """
        创建新的媒体会话（分配端口）
        
        注意: RTPProxy会自动分配端口，这里只是为了兼容性保留端口分配逻辑
        """
        # 分配端口（用于SDP修改）
        a_ports = self.port_manager.allocate_port_pair(call_id)
        if not a_ports:
            print(f"[RTPProxyMediaRelay] 端口分配失败 (A-leg): {call_id}", file=sys.stderr, flush=True)
            return None
        
        b_ports = self.port_manager.allocate_port_pair(call_id)
        if not b_ports:
            self.port_manager.release_port_pair(a_ports[0], a_ports[1])
            print(f"[RTPProxyMediaRelay] 端口分配失败 (B-leg): {call_id}", file=sys.stderr, flush=True)
            return None
        
        session = MediaSession(
            call_id=call_id,
            a_leg_rtp_port=a_ports[0],
            a_leg_rtcp_port=a_ports[1],
            b_leg_rtp_port=b_ports[0],
            b_leg_rtcp_port=b_ports[1]
        )
        
        self._sessions[call_id] = session
        self._rtpproxy_sessions[call_id] = {}
        
        print(f"[RTPProxyMediaRelay] 创建会话: {call_id}", file=sys.stderr, flush=True)
        return session
    
    def process_invite_to_callee(self, call_id: str, sdp_body: str,
                                  caller_addr: Tuple[str, int],
                                  caller_number: Optional[str] = None,
                                  callee_number: Optional[str] = None,
                                  from_tag: Optional[str] = None) -> Tuple[str, Optional[MediaSession]]:
        """
        处理转发给被叫的INVITE SDP
        
        修改SDP指向服务器的B-leg端口，让被叫发送RTP到B-leg端口
        
        RTPProxy两步协议：
        1. INVITE阶段：发送offer命令（V<call_id> <from_tag>）
        2. 200 OK阶段：发送answer命令（V<call_id> <from_tag> <to_tag>）
        
        Args:
            call_id: 呼叫ID
            sdp_body: SDP内容
            caller_addr: 主叫信令地址
            caller_number: 主叫号码（可选）
            callee_number: 被叫号码（可选）
            from_tag: From标签（用于RTPProxy offer命令，可选）
        """
        session = self._sessions.get(call_id)
        if not session:
            session = self.create_session(call_id)
            if not session:
                return sdp_body, None
        
        if caller_number:
            session.caller_number = caller_number
        if callee_number:
            session.callee_number = callee_number
        
        session.a_leg_signaling_addr = caller_addr
        print(f"[RTPProxyMediaRelay] A-leg信令地址: {caller_addr}", file=sys.stderr, flush=True)
        
        # 提取A-leg媒体信息
        media_info = self.sdp_processor.extract_media_info(sdp_body)
        if media_info:
            # 保存音频信息
            audio_ip = media_info.get('audio_connection_ip') or media_info.get('connection_ip')
            session.a_leg_remote_addr = (audio_ip, media_info['audio_port'])
            session.a_leg_sdp = sdp_body
            print(f"[RTPProxyMediaRelay] A-leg音频信息: {session.a_leg_remote_addr}", file=sys.stderr, flush=True)
            
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
                        
                        print(f"[RTPProxyMediaRelay] 检测到视频流，分配视频端口:", file=sys.stderr, flush=True)
                        print(f"  A-leg视频: RTP={a_video_ports[0]}, RTCP={a_video_ports[1]}", file=sys.stderr, flush=True)
                        print(f"  B-leg视频: RTP={b_video_ports[0]}, RTCP={b_video_ports[1]}", file=sys.stderr, flush=True)
                    else:
                        print(f"[RTPProxyMediaRelay-WARNING] 视频端口分配失败，将只处理音频: {call_id}", file=sys.stderr, flush=True)
                
                # 保存视频信息
                video_ip = media_info.get('video_connection_ip') or media_info.get('connection_ip')
                session.a_leg_video_remote_addr = (video_ip, media_info['video_port'])
                print(f"[RTPProxyMediaRelay] A-leg视频信息: {session.a_leg_video_remote_addr}", file=sys.stderr, flush=True)
        
        # RTPProxy两步协议：INVITE阶段发送offer命令
        if from_tag:
            # 检查是否已经发送过offer
            if call_id not in self._rtpproxy_sessions:
                print(f"[RTPProxyMediaRelay] INVITE阶段：发送RTPProxy offer命令: {call_id}, from_tag={from_tag}", file=sys.stderr, flush=True)
                offer_port = self.rtpproxy.create_offer(call_id, from_tag)
                if offer_port:
                    print(f"[RTPProxyMediaRelay] RTPProxy offer成功，端口: {offer_port}", file=sys.stderr, flush=True)
                    # 保存offer端口和from_tag
                    self._rtpproxy_sessions[call_id] = {
                        'offer_port': offer_port,
                        'from_tag': from_tag
                    }
                else:
                    print(f"[RTPProxyMediaRelay] RTPProxy offer失败: {call_id}", file=sys.stderr, flush=True)
            else:
                print(f"[RTPProxyMediaRelay] RTPProxy offer已发送: {call_id}", file=sys.stderr, flush=True)
        else:
            print(f"[RTPProxyMediaRelay] 警告: INVITE阶段未提供from_tag，无法发送RTPProxy offer: {call_id}", file=sys.stderr, flush=True)
        
        # 修改SDP指向B-leg端口
        new_sdp = self.sdp_processor.modify_sdp(
            sdp_body,
            self.server_ip,
            session.b_leg_rtp_port,
            new_video_port=session.b_leg_video_rtp_port  # 传递视频端口（如果有）
        )
        
        print(f"[RTPProxyMediaRelay] INVITE转发给被叫，SDP修改为B-leg端口: 音频={session.b_leg_rtp_port}", end='', file=sys.stderr, flush=True)
        if session.b_leg_video_rtp_port:
            print(f", 视频={session.b_leg_video_rtp_port}", file=sys.stderr, flush=True)
        else:
            print(file=sys.stderr, flush=True)
        return new_sdp, session
    
    def process_answer_sdp(self, call_id: str, sdp_body: str,
                          callee_addr: Tuple[str, int]) -> Tuple[str, bool]:
        """
        处理200 OK的SDP（被叫侧）
        
        修改SDP指向服务器的B-leg端口（与INVITE相同）
        """
        session = self._sessions.get(call_id)
        if not session:
            print(f"[RTPProxyMediaRelay] 会话不存在: {call_id}", file=sys.stderr, flush=True)
            return sdp_body, False
        
        session.b_leg_signaling_addr = callee_addr
        print(f"[RTPProxyMediaRelay] B-leg信令地址: {callee_addr}", file=sys.stderr, flush=True)
        
        # 提取被叫媒体信息
        media_info = self.sdp_processor.extract_media_info(sdp_body)
        if media_info:
            # 保存音频信息
            audio_ip = media_info.get('audio_connection_ip') or media_info.get('connection_ip')
            session.b_leg_remote_addr = (audio_ip, media_info['audio_port'])
            session.b_leg_sdp = sdp_body
            print(f"[RTPProxyMediaRelay] B-leg音频信息: {session.b_leg_remote_addr}", file=sys.stderr, flush=True)
            
            # 检测并处理视频流
            if media_info.get('video_port'):
                video_ip = media_info.get('video_connection_ip') or media_info.get('connection_ip')
                session.b_leg_video_remote_addr = (video_ip, media_info['video_port'])
                print(f"[RTPProxyMediaRelay] B-leg视频信息: {session.b_leg_video_remote_addr}", file=sys.stderr, flush=True)
        
        # 修改SDP指向B-leg端口
        new_sdp = self.sdp_processor.modify_sdp(
            sdp_body,
            self.server_ip,
            session.b_leg_rtp_port,
            new_video_port=session.b_leg_video_rtp_port  # 传递视频端口（如果有）
        )
        
        print(f"[RTPProxyMediaRelay] 200OK发给主叫，SDP修改为B-leg端口: {session.b_leg_rtp_port}", file=sys.stderr, flush=True)
        return new_sdp, True
    
    def _extract_tags_from_sdp(self, sdp_body: str) -> Tuple[Optional[str], Optional[str]]:
        """
        从SDP中提取From和To标签（用于rtpproxy会话标识）
        
        注意: SDP本身不包含标签，需要从SIP消息头中获取
        这里提供一个占位实现，实际使用时需要传入标签
        """
        # SDP中通常不包含标签信息，需要从SIP消息头获取
        # 这里返回None，实际标签应该在start_media_forwarding时传入
        return None, None
    
    def start_media_forwarding(self, call_id: str, 
                               from_tag: Optional[str] = None,
                               to_tag: Optional[str] = None) -> bool:
        """
        启动媒体转发（通过RTPProxy）
        
        RTPProxy的NAT处理机制：
        1. 对称RTP（Symmetric RTP）：RTPProxy会自动从第一个收到的RTP包中学习真实的源地址
        2. 自动NAT穿透：使用信令地址（NAT后的公网IP）作为初始目标，RTPProxy会学习实际的媒体源地址
        3. 双向转发：RTPProxy自动处理双向RTP转发，无需手动配置
        
        注意: 
        - 传递给RTPProxy的地址应该使用信令地址（NAT后的公网IP）+ SDP中的RTP端口
        - RTPProxy会通过对称RTP自动学习真实的RTP源地址，即使客户端在NAT后也能正常工作
        
        Args:
            call_id: 呼叫ID
            from_tag: From标签（从SIP消息头获取，可选）
            to_tag: To标签（从SIP消息头获取，可选）
        """
        session = self._sessions.get(call_id)
        if not session:
            print(f"[RTPProxyMediaRelay] 无法启动转发，会话不存在: {call_id}", file=sys.stderr, flush=True)
            return False
        
        if not session.a_leg_remote_addr or not session.b_leg_remote_addr:
            print(f"[RTPProxyMediaRelay] 无法启动转发，媒体地址不完整: {call_id}", file=sys.stderr, flush=True)
            return False
        
        # 获取目标地址（用于rtpproxy会话创建）
        # 重要：使用信令地址（NAT后的公网IP）+ SDP中的RTP端口
        # RTPProxy会通过对称RTP自动学习真实的RTP源地址
        a_leg_target = session.get_a_leg_rtp_target_addr()
        b_leg_target = session.get_b_leg_rtp_target_addr()
        
        if not a_leg_target or not b_leg_target:
            print(f"[RTPProxyMediaRelay] 无法启动转发，目标地址不完整: {call_id}", file=sys.stderr, flush=True)
            return False
        
        # 使用默认标签（如果未提供）
        if not from_tag:
            from_tag = f"tag-{call_id[:8]}"
        if not to_tag:
            to_tag = f"tag-{call_id[8:16]}" if len(call_id) > 8 else f"tag-{call_id}"
        
        # 创建RTPProxy会话
        # RTPProxy的NAT处理流程：
        # 1. 我们传递信令地址（NAT后的公网IP）+ SDP中的RTP端口作为初始目标
        # 2. RTPProxy创建会话，分配媒体端口
        # 3. 当第一个RTP包到达时，RTPProxy通过对称RTP学习真实的源地址
        # 4. RTPProxy自动更新目标地址，实现NAT穿透
        # 5. 双向RTP转发自动建立
        
        # 标志说明：
        # '' - 默认模式，启用对称RTP和NAT穿透
        # 'r' - 录制模式
        # 'w' - 写入模式
        # 's' - 对称RTP模式（默认启用）
        flags = "s"  # 显式启用对称RTP模式（虽然默认已启用）
        
        print(f"[RTPProxyMediaRelay] 创建RTPProxy会话（NAT处理）: {call_id}", file=sys.stderr, flush=True)
        print(f"  A-leg目标: {a_leg_target} (信令IP={session.a_leg_signaling_addr[0] if session.a_leg_signaling_addr else 'N/A'}, SDP端口={session.a_leg_remote_addr[1] if session.a_leg_remote_addr else 'N/A'})", file=sys.stderr, flush=True)
        print(f"  B-leg目标: {b_leg_target} (信令IP={session.b_leg_signaling_addr[0] if session.b_leg_signaling_addr else 'N/A'}, SDP端口={session.b_leg_remote_addr[1] if session.b_leg_remote_addr else 'N/A'})", file=sys.stderr, flush=True)
        print(f"  对称RTP: 启用（RTPProxy将自动学习真实的RTP源地址）", file=sys.stderr, flush=True)
        
        # RTPProxy两步协议：
        # 1. INVITE阶段：应该已经发送过offer（在process_invite_to_callee中）
        # 2. 200 OK阶段：发送answer完成会话建立
        # 检查是否已经发送过offer
        if call_id not in self._rtpproxy_sessions:
            # 如果INVITE阶段没有发送offer，这里尝试发送（可能from_tag在INVITE时不可用）
            print(f"[RTPProxyMediaRelay] 警告: 200 OK阶段发现offer未发送，尝试发送offer: {call_id}", file=sys.stderr, flush=True)
            offer_port = self.rtpproxy.create_offer(call_id, from_tag)
            if offer_port:
                print(f"[RTPProxyMediaRelay] RTPProxy offer成功，端口: {offer_port}", file=sys.stderr, flush=True)
                self._rtpproxy_sessions[call_id] = {'offer_port': offer_port, 'from_tag': from_tag}
            else:
                print(f"[RTPProxyMediaRelay] RTPProxy offer失败，无法继续answer: {call_id}", file=sys.stderr, flush=True)
                return False
        
        # 发送answer命令（200 OK阶段）
        print(f"[RTPProxyMediaRelay] 200 OK阶段：发送RTPProxy answer命令: {call_id}, from_tag={from_tag}, to_tag={to_tag}", file=sys.stderr, flush=True)
        session_id = self.rtpproxy.create_answer(call_id, from_tag, to_tag)
        
        if session_id:
            # 更新会话信息
            if call_id in self._rtpproxy_sessions:
                self._rtpproxy_sessions[call_id].update({
                    'answer_port': session_id,
                    'from_tag_str': from_tag,
                    'to_tag_str': to_tag
                })
            else:
                self._rtpproxy_sessions[call_id] = {
                    'answer_port': session_id,
                    'from_tag_str': from_tag,
                    'to_tag_str': to_tag
                }
            session.started_at = time.time()
            print(f"[RTPProxyMediaRelay] 媒体转发已启动: {call_id}, answer_port={session_id}", file=sys.stderr, flush=True)
            print(f"[RTPProxyMediaRelay]  主叫目标: {a_leg_target}, 被叫目标: {b_leg_target}", file=sys.stderr, flush=True)
            return True
        else:
            print(f"[RTPProxyMediaRelay] 媒体转发启动失败: {call_id}", file=sys.stderr, flush=True)
            # 输出详细错误信息以便调试
            print(f"[RTPProxyMediaRelay]  可能原因: RTPProxy协议格式错误或需要先发送offer命令", file=sys.stderr, flush=True)
            return False
    
    def end_session(self, call_id: str,
                    from_tag: Optional[str] = None,
                    to_tag: Optional[str] = None) -> bool:
        """
        结束媒体会话
        
        Args:
            call_id: 呼叫ID
            from_tag: From标签（可选）
            to_tag: To标签（可选）
        """
        session = self._sessions.get(call_id)
        if not session:
            return False
        
        # 获取保存的标签
        rtpproxy_info = self._rtpproxy_sessions.get(call_id, {})
        if not from_tag:
            from_tag = rtpproxy_info.get('from_tag_str') or f"tag-{call_id[:8]}"
        if not to_tag:
            to_tag = rtpproxy_info.get('to_tag_str') or (f"tag-{call_id[8:16]}" if len(call_id) > 8 else f"tag-{call_id}")
        
        # 删除RTPProxy会话
        success = self.rtpproxy.delete_session(call_id, from_tag, to_tag)
        
        # 释放音频端口
        if session.a_leg_rtp_port:
            self.port_manager.release_port_pair(session.a_leg_rtp_port, session.a_leg_rtcp_port)
        if session.b_leg_rtp_port:
            self.port_manager.release_port_pair(session.b_leg_rtp_port, session.b_leg_rtcp_port)
        
        # 释放视频端口（如果有）
        if session.a_leg_video_rtp_port and session.a_leg_video_rtcp_port:
            self.port_manager.release_port_pair(session.a_leg_video_rtp_port, session.a_leg_video_rtcp_port)
        if session.b_leg_video_rtp_port and session.b_leg_video_rtcp_port:
            self.port_manager.release_port_pair(session.b_leg_video_rtp_port, session.b_leg_video_rtcp_port)
        
        # 清理会话
        if call_id in self._sessions:
            del self._sessions[call_id]
        if call_id in self._rtpproxy_sessions:
            del self._rtpproxy_sessions[call_id]
        
        session.ended_at = time.time()
        print(f"[RTPProxyMediaRelay] 会话已结束（包含视频端口）: {call_id}", file=sys.stderr, flush=True)
        return success
    
    def get_session_stats(self, call_id: str) -> Optional[Dict]:
        """获取会话统计信息"""
        session = self._sessions.get(call_id)
        if not session:
            return None
        
        rtpproxy_info = self._rtpproxy_sessions.get(call_id, {})
        
        return {
            'call_id': call_id,
            'caller': session.caller_number,
            'callee': session.callee_number,
            'a_leg_rtp_port': session.a_leg_rtp_port,
            'b_leg_rtp_port': session.b_leg_rtp_port,
            'rtpproxy_session_id': rtpproxy_info.get('from_tag'),
            'started_at': session.started_at,
            'ended_at': session.ended_at
        }
    
    def print_media_diagnosis(self, call_id: str):
        """打印媒体诊断信息"""
        stats = self.get_session_stats(call_id)
        if stats:
            print(f"\n[RTPProxyMediaRelay] 媒体诊断: {call_id}", file=sys.stderr, flush=True)
            print(f"  主叫: {stats['caller']}, 被叫: {stats['callee']}", file=sys.stderr, flush=True)
            print(f"  A-leg端口: {stats['a_leg_rtp_port']}, B-leg端口: {stats['b_leg_rtp_port']}", file=sys.stderr, flush=True)
            print(f"  RTPProxy会话ID: {stats['rtpproxy_session_id']}", file=sys.stderr, flush=True)
        else:
            print(f"[RTPProxyMediaRelay] 会话不存在: {call_id}", file=sys.stderr, flush=True)
    
    # 注意: _sessions属性已在__init__中定义，这里不需要重复定义


# 全局媒体中继实例
_media_relay: Optional[RTPProxyMediaRelay] = None


def init_media_relay(server_ip: str,
                     rtpproxy_socket: Optional[str] = None,
                     rtpproxy_tcp: Optional[Tuple[str, int]] = None,
                     rtpproxy_udp: Optional[Tuple[str, int]] = None) -> RTPProxyMediaRelay:
    """
    初始化全局RTPProxy媒体中继
    
    Args:
        server_ip: 服务器IP地址
        rtpproxy_socket: rtpproxy Unix socket路径
        rtpproxy_tcp: rtpproxy TCP地址
        rtpproxy_udp: rtpproxy UDP地址（用于UDP控制socket）
    """
    global _media_relay
    _media_relay = RTPProxyMediaRelay(
        server_ip=server_ip,
        rtpproxy_socket=rtpproxy_socket,
        rtpproxy_tcp=rtpproxy_tcp,
        rtpproxy_udp=rtpproxy_udp
    )
    return _media_relay


def get_media_relay() -> Optional[RTPProxyMediaRelay]:
    """获取全局媒体中继实例"""
    return _media_relay
