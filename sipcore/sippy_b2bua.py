# sipcore/sippy_b2bua.py
"""
基于Sippy B2BUA的SIP信令处理实现

Sippy是一个成熟的Python SIP B2BUA库，RFC3261兼容，广泛用于生产环境。

安装:
  pip install sippy

特性:
- RFC3261完全兼容
- 自动处理SIP事务和对话
- 支持RTPProxy集成
- 高性能（5000-10000并发会话）
- 完善的错误处理

参考: https://github.com/sippy/b2bua
"""

import sys
import time
import logging
from typing import Optional, Dict, Tuple, Callable
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
    print("[SippyB2BUA-ERROR] sippy库未安装，请运行: pip install sippy", file=sys.stderr, flush=True)


class SippyB2BUAHandler:
    """
    Sippy B2BUA处理器
    
    处理SIP信令，包括注册、呼叫建立、媒体中继等。
    """
    
    def __init__(self, server_ip: str, server_port: int = 5060,
                 rtpproxy_socket: Optional[str] = None,
                 rtpproxy_tcp: Optional[Tuple[str, int]] = None,
                 on_call_start: Optional[Callable] = None,
                 on_call_end: Optional[Callable] = None):
        """
        初始化Sippy B2BUA处理器
        
        Args:
            server_ip: 服务器IP地址
            server_port: 服务器端口（默认5060）
            rtpproxy_socket: RTPProxy Unix socket路径
            rtpproxy_tcp: RTPProxy TCP地址
            on_call_start: 呼叫开始回调函数
            on_call_end: 呼叫结束回调函数
        """
        if not SIPPY_AVAILABLE:
            raise ImportError("sippy库未安装，请运行: pip install sippy")
        
        self.server_ip = server_ip
        self.server_port = server_port
        self.on_call_start = on_call_start
        self.on_call_end = on_call_end
        
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
        self.b2bua_server = B2buaServer(self.sip_config, self._on_call)
        
        # 会话管理
        self._sessions: Dict[str, Dict] = {}
        self._lock = Lock()
        
        print(f"[SippyB2BUA] 初始化完成: {server_ip}:{server_port}", file=sys.stderr, flush=True)
        if rtpproxy_socket or rtpproxy_tcp:
            print(f"[SippyB2BUA] RTPProxy配置: {self.sip_config.rtp_proxy}", file=sys.stderr, flush=True)
    
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
                print(f"[SippyB2BUA] 呼叫开始: {call_id}, 主叫={call_info.get('caller')}, 被叫={call_info.get('callee')}", 
                      file=sys.stderr, flush=True)
                if self.on_call_start:
                    try:
                        self.on_call_start(call_id, call_info)
                    except Exception as e:
                        print(f"[SippyB2BUA-ERROR] on_call_start回调失败: {e}", file=sys.stderr, flush=True)
            
            elif event == 'end':
                if call_id in self._sessions:
                    self._sessions[call_id]['ended_at'] = time.time()
                    print(f"[SippyB2BUA] 呼叫结束: {call_id}, 持续时间={time.time() - self._sessions[call_id]['started_at']:.2f}秒",
                          file=sys.stderr, flush=True)
                    if self.on_call_end:
                        try:
                            self.on_call_end(call_id, self._sessions[call_id])
                        except Exception as e:
                            print(f"[SippyB2BUA-ERROR] on_call_end回调失败: {e}", file=sys.stderr, flush=True)
                    del self._sessions[call_id]
            
            elif event == 'update':
                if call_id in self._sessions:
                    self._sessions[call_id].update(call_info)
                    print(f"[SippyB2BUA] 呼叫更新: {call_id}", file=sys.stderr, flush=True)
    
    def start(self):
        """启动B2BUA服务器"""
        try:
            self.b2bua_server.start()
            print(f"[SippyB2BUA] 服务器已启动: {self.server_ip}:{self.server_port}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[SippyB2BUA-ERROR] 启动失败: {e}", file=sys.stderr, flush=True)
            raise
    
    def stop(self):
        """停止B2BUA服务器"""
        try:
            self.b2bua_server.stop()
            print(f"[SippyB2BUA] 服务器已停止", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[SippyB2BUA-ERROR] 停止失败: {e}", file=sys.stderr, flush=True)
    
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


class SippyB2BUAServer:
    """
    Sippy B2BUA服务器包装器
    
    提供更高级的接口，集成注册管理、CDR等功能。
    """
    
    def __init__(self, server_ip: str, server_port: int = 5060,
                 rtpproxy_socket: Optional[str] = None,
                 rtpproxy_tcp: Optional[Tuple[str, int]] = None,
                 registrations: Optional[Dict] = None,
                 cdr_callback: Optional[Callable] = None):
        """
        初始化Sippy B2BUA服务器
        
        Args:
            server_ip: 服务器IP地址
            server_port: 服务器端口
            rtpproxy_socket: RTPProxy Unix socket路径
            rtpproxy_tcp: RTPProxy TCP地址
            registrations: 注册信息字典（用于查找用户）
            cdr_callback: CDR回调函数
        """
        self.registrations = registrations or {}
        self.cdr_callback = cdr_callback
        
        # 创建B2BUA处理器
        self.handler = SippyB2BUAHandler(
            server_ip=server_ip,
            server_port=server_port,
            rtpproxy_socket=rtpproxy_socket,
            rtpproxy_tcp=rtpproxy_tcp,
            on_call_start=self._on_call_start,
            on_call_end=self._on_call_end
        )
    
    def _on_call_start(self, call_id: str, call_info: Dict):
        """呼叫开始回调"""
        caller = call_info.get('caller', '')
        callee = call_info.get('callee', '')
        print(f"[SippyB2BUA] 呼叫开始: {call_id}, {caller} -> {callee}", file=sys.stderr, flush=True)
        
        # 调用CDR回调
        if self.cdr_callback:
            try:
                self.cdr_callback('CALL_START', {
                    'call_id': call_id,
                    'caller': caller,
                    'callee': callee,
                    'started_at': time.time()
                })
            except Exception as e:
                print(f"[SippyB2BUA-ERROR] CDR回调失败: {e}", file=sys.stderr, flush=True)
    
    def _on_call_end(self, call_id: str, session_info: Dict):
        """呼叫结束回调"""
        caller = session_info.get('caller', '')
        callee = session_info.get('callee', '')
        duration = (session_info.get('ended_at') or time.time()) - session_info.get('started_at', time.time())
        print(f"[SippyB2BUA] 呼叫结束: {call_id}, 持续时间={duration:.2f}秒", file=sys.stderr, flush=True)
        
        # 调用CDR回调
        if self.cdr_callback:
            try:
                self.cdr_callback('CALL_END', {
                    'call_id': call_id,
                    'caller': caller,
                    'callee': callee,
                    'duration': duration,
                    'ended_at': session_info.get('ended_at')
                })
            except Exception as e:
                print(f"[SippyB2BUA-ERROR] CDR回调失败: {e}", file=sys.stderr, flush=True)
    
    def start(self):
        """启动服务器"""
        self.handler.start()
    
    def stop(self):
        """停止服务器"""
        self.handler.stop()
    
    def get_session(self, call_id: str) -> Optional[Dict]:
        """获取呼叫会话"""
        return self.handler.get_session(call_id)
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return self.handler.get_stats()
