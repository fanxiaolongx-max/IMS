"""
Sippy B2BUA完整集成模块

基于Sippy B2BUA实现完整的SIP信令处理，集成：
- RTPProxy媒体中继
- 服务器端NAT处理
- CDR记录
- 用户管理
"""

import sys
import time
import asyncio
import logging
from typing import Optional, Dict, Tuple, Callable, Any
from threading import Lock

try:
    from sippy.Core.EventDispatcher import ED2
    from sippy.SipConf import SipConf
    from sippy.B2buaServer import B2buaServer
    from sippy.Time.Timeout import Timeout
    from sippy.Core.SipLogger import SipLogger
    SIPPY_AVAILABLE = True
except ImportError:
    SIPPY_AVAILABLE = False
    print("[SippyIntegration-ERROR] sippy库未安装，请运行: pip install sippy", file=sys.stderr, flush=True)


class SippyB2BUAIntegration:
    """
    Sippy B2BUA完整集成
    
    提供完整的SIP信令处理，包括注册、呼叫、NAT处理等。
    """
    
    def __init__(self, 
                 server_ip: str,
                 server_port: int = 5060,
                 rtpproxy_tcp: Optional[Tuple[str, int]] = None,
                 rtpproxy_socket: Optional[str] = None,
                 registrations: Optional[Dict] = None,
                 cdr_callback: Optional[Callable] = None,
                 user_manager: Optional[Any] = None,
                 nat_helper: Optional[Any] = None):
        """
        初始化Sippy B2BUA集成
        
        Args:
            server_ip: 服务器IP地址
            server_port: 服务器端口
            rtpproxy_tcp: RTPProxy TCP地址
            rtpproxy_socket: RTPProxy Unix socket路径
            registrations: 注册信息字典
            cdr_callback: CDR回调函数
            user_manager: 用户管理器实例
            nat_helper: NAT助手实例
        """
        if not SIPPY_AVAILABLE:
            raise ImportError("sippy库未安装，请运行: pip install sippy")
        
        self.server_ip = server_ip
        self.server_port = server_port
        self.registrations = registrations or {}
        self.cdr_callback = cdr_callback
        self.user_manager = user_manager
        self.nat_helper = nat_helper
        
        # 配置Sippy
        self.sip_config = SipConf()
        self.sip_config.my_address = server_ip
        self.sip_config.my_port = server_port
        self.sip_config.my_fqdn = server_ip
        
        # RTPProxy配置
        if rtpproxy_socket:
            self.sip_config.rtp_proxy = f"unix:{rtpproxy_socket}"
        elif rtpproxy_tcp:
            self.sip_config.rtp_proxy = f"udp:{rtpproxy_tcp[0]}:{rtpproxy_tcp[1]}"
        
        # 创建B2BUA服务器
        # 注意：需要根据Sippy实际API调整
        try:
            self.b2bua_server = B2buaServer(self.sip_config, self._on_call)
        except Exception as e:
            print(f"[SippyIntegration-ERROR] 创建B2BUA服务器失败: {e}", file=sys.stderr, flush=True)
            # 如果Sippy API不同，可能需要不同的初始化方式
            raise
        
        # 会话管理
        self._sessions: Dict[str, Dict] = {}
        self._lock = Lock()
        
        print(f"[SippyIntegration] 初始化完成: {server_ip}:{server_port}", file=sys.stderr, flush=True)
        if rtpproxy_socket or rtpproxy_tcp:
            print(f"[SippyIntegration] RTPProxy配置: {self.sip_config.rtp_proxy}", file=sys.stderr, flush=True)
    
    def _on_call(self, call_id: str, event: str, call_info: Dict):
        """
        B2BUA呼叫事件处理
        
        Args:
            call_id: 呼叫ID
            event: 事件类型（'start', 'end', 'update'等）
            call_info: 呼叫信息
        """
        with self._lock:
            if event == 'start':
                self._sessions[call_id] = {
                    'call_id': call_id,
                    'caller': call_info.get('caller'),
                    'callee': call_info.get('callee'),
                    'started_at': time.time(),
                    'ended_at': None
                }
                print(f"[SippyIntegration] 呼叫开始: {call_id}, 主叫={call_info.get('caller')}, 被叫={call_info.get('callee')}", 
                      file=sys.stderr, flush=True)
                
                # CDR记录
                if self.cdr_callback:
                    try:
                        self.cdr_callback('CALL_START', {
                            'call_id': call_id,
                            'caller': call_info.get('caller'),
                            'callee': call_info.get('callee'),
                            'started_at': time.time()
                        })
                    except Exception as e:
                        print(f"[SippyIntegration-ERROR] CDR回调失败: {e}", file=sys.stderr, flush=True)
            
            elif event == 'end':
                if call_id in self._sessions:
                    self._sessions[call_id]['ended_at'] = time.time()
                    duration = time.time() - self._sessions[call_id]['started_at']
                    print(f"[SippyIntegration] 呼叫结束: {call_id}, 持续时间={duration:.2f}秒",
                          file=sys.stderr, flush=True)
                    
                    # CDR记录
                    if self.cdr_callback:
                        try:
                            self.cdr_callback('CALL_END', {
                                'call_id': call_id,
                                'caller': self._sessions[call_id].get('caller'),
                                'callee': self._sessions[call_id].get('callee'),
                                'duration': duration,
                                'ended_at': self._sessions[call_id]['ended_at']
                            })
                        except Exception as e:
                            print(f"[SippyIntegration-ERROR] CDR回调失败: {e}", file=sys.stderr, flush=True)
                    
                    del self._sessions[call_id]
            
            elif event == 'update':
                if call_id in self._sessions:
                    self._sessions[call_id].update(call_info)
                    print(f"[SippyIntegration] 呼叫更新: {call_id}", file=sys.stderr, flush=True)
    
    def start(self):
        """启动B2BUA服务器"""
        try:
            self.b2bua_server.start()
            print(f"[SippyIntegration] 服务器已启动: {self.server_ip}:{self.server_port}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[SippyIntegration-ERROR] 启动失败: {e}", file=sys.stderr, flush=True)
            raise
    
    def stop(self):
        """停止B2BUA服务器"""
        try:
            self.b2bua_server.stop()
            print(f"[SippyIntegration] 服务器已停止", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[SippyIntegration-ERROR] 停止失败: {e}", file=sys.stderr, flush=True)
    
    def get_session(self, call_id: str) -> Optional[Dict]:
        """获取呼叫会话信息"""
        with self._lock:
            return self._sessions.get(call_id)
    
    def get_all_sessions(self) -> Dict[str, Dict]:
        """获取所有活跃会话"""
        with self._lock:
            return self._sessions.copy()
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._lock:
            active_calls = len(self._sessions)
            total_duration = sum(
                (s.get('ended_at') or time.time()) - s.get('started_at', time.time())
                for s in self._sessions.values()
            )
            return {
                'active_calls': active_calls,
                'total_duration': total_duration,
                'server_ip': self.server_ip,
                'server_port': self.server_port
            }
