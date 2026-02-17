# sipcore/rtpproxy_client.py
"""
RTPProxy客户端 - 基于成熟的开源RTPProxy实现媒体中继

RTPProxy是一个高性能的RTP代理，广泛用于Kamailio、OpenSIPS等SIP服务器。
本模块提供Python客户端接口，通过Unix socket或TCP socket与rtpproxy通信。

安装rtpproxy:
  Ubuntu/Debian: apt-get install rtpproxy
  或从源码编译: https://github.com/sippy/rtpproxy

配置rtpproxy:
  rtpproxy -l <server_ip> -s udp:127.0.0.1:7722 -F
  或使用Unix socket: rtpproxy -l <server_ip> -s unix:/var/run/rtpproxy.sock -F
"""

import socket
import time
import sys
from typing import Optional, Tuple, Dict


class RTPProxyClient:
    """
    RTPProxy客户端
    
    通过Unix socket或TCP socket与rtpproxy通信，控制RTP媒体流。
    """
    
    def __init__(self, socket_path: Optional[str] = None, 
                 tcp_addr: Optional[Tuple[str, int]] = None,
                 udp_addr: Optional[Tuple[str, int]] = None,
                 timeout: float = 5.0):
        """
        初始化RTPProxy客户端
        
        Args:
            socket_path: Unix socket路径，例如 '/var/run/rtpproxy.sock'
            tcp_addr: TCP地址，例如 ('127.0.0.1', 7722)
            udp_addr: UDP地址，例如 ('127.0.0.1', 7722) - 用于UDP控制socket
            timeout: 连接超时时间（秒）
        
        注意: socket_path、tcp_addr 或 udp_addr 必须指定一个
        """
        self.socket_path = socket_path
        self.tcp_addr = tcp_addr
        self.udp_addr = udp_addr
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self._connect()
    
    def _connect(self):
        """连接到rtpproxy"""
        try:
            if self.socket_path:
                # Unix socket连接
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                self.sock.settimeout(self.timeout)
                self.sock.connect(self.socket_path)
                print(f"[RTPProxy] 已连接到Unix socket: {self.socket_path}", file=sys.stderr, flush=True)
            elif self.udp_addr:
                # UDP连接（用于UDP控制socket）
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.settimeout(self.timeout)
                self.sock.connect(self.udp_addr)
                print(f"[RTPProxy] 已连接到UDP: {self.udp_addr[0]}:{self.udp_addr[1]}", file=sys.stderr, flush=True)
            elif self.tcp_addr:
                # TCP连接
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(self.timeout)
                self.sock.connect(self.tcp_addr)
                print(f"[RTPProxy] 已连接到TCP: {self.tcp_addr[0]}:{self.tcp_addr[1]}", file=sys.stderr, flush=True)
            else:
                raise ValueError("必须指定socket_path、tcp_addr或udp_addr")
        except Exception as e:
            print(f"[RTPProxy-ERROR] 连接失败: {e}", file=sys.stderr, flush=True)
            raise
    
    def _send_command(self, command: str) -> str:
        """
        发送命令到rtpproxy并接收响应
        
        Args:
            command: rtpproxy命令字符串（ng协议格式）
            
        Returns:
            响应字符串
        """
        if not self.sock:
            self._connect()
        
        try:
            # 发送命令（ng协议需要以换行符结尾）
            if isinstance(command, str):
                command = command.encode('utf-8')
            self.sock.sendall(command + b'\n')
            
            # 接收响应（rtpproxy响应以换行符结尾）
            response = b''
            while True:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                if b'\n' in response:
                    # 提取第一行（rtpproxy响应通常是单行）
                    response = response.split(b'\n', 1)[0]
                    break
            
            return response.decode('utf-8', errors='ignore').strip()
        except socket.timeout:
            print(f"[RTPProxy-ERROR] 命令超时: {command[:50]}", file=sys.stderr, flush=True)
            raise
        except Exception as e:
            print(f"[RTPProxy-ERROR] 命令执行失败: {command[:50]}, 错误: {e}", file=sys.stderr, flush=True)
            # 尝试重连
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
            self._connect()
            raise
    
    def create_offer(self, call_id: str, from_tag: str) -> Optional[int]:
        """
        创建RTP会话offer（INVITE阶段）
        
        RTPProxy使用两步协议：
        1. INVITE阶段：发送V命令（只有call-id和from-tag），RTPProxy返回分配的端口
        2. 200 OK阶段：发送V命令（call-id, from-tag, to-tag），RTPProxy完成会话建立
        
        Args:
            call_id: 呼叫ID
            from_tag: From标签
            
        Returns:
            RTPProxy分配的端口号，失败返回None
        """
        # RTPProxy rtpp协议格式（INVITE阶段）:
        # V<call_id> <from_tag>
        # 注意：RTPProxy 3.1.1对命令格式很严格，call_id和tag中不能包含空格
        # 清理call_id和tag，移除可能导致解析错误的字符（空格、换行等）
        clean_call_id = call_id.replace(' ', '_').replace('\n', '').replace('\r', '').replace('\t', '')
        clean_from_tag = from_tag.replace(' ', '_').replace('\n', '').replace('\r', '').replace('\t', '')
        # 确保命令格式正确：V后无空格，call_id和tag之间有空格
        cmd = f"V{clean_call_id} {clean_from_tag}".strip()
        print(f"[RTPProxy-DEBUG] Offer命令: {repr(cmd)}", file=sys.stderr, flush=True)
        try:
            response = self._send_command(cmd)
            print(f"[RTPProxy-DEBUG] Offer响应: {repr(response)}", file=sys.stderr, flush=True)
            # rtpproxy返回格式:
            # - 成功: <port_number> (分配的RTP端口)
            # - 失败: V E<error_code>
            
            # 检查错误响应
            if response.startswith("V E") or response.startswith("U E"):
                print(f"[RTPProxy-ERROR] 创建offer失败: {call_id}, 响应={response}", file=sys.stderr, flush=True)
                return None
            
            # 解析端口号
            parts = response.split()
            if len(parts) >= 1:
                try:
                    port = int(parts[0])
                    print(f"[RTPProxy] 创建offer成功: {call_id}, RTP端口={port}", file=sys.stderr, flush=True)
                    return port
                except ValueError:
                    print(f"[RTPProxy-ERROR] 创建offer失败: {call_id}, 响应格式异常={response}", file=sys.stderr, flush=True)
                    return None
            else:
                print(f"[RTPProxy-ERROR] 创建offer失败: {call_id}, 响应格式异常={response}", file=sys.stderr, flush=True)
                return None
        except Exception as e:
            print(f"[RTPProxy-ERROR] 创建offer异常: {call_id}, 错误={e}", file=sys.stderr, flush=True)
            return None
    
    def create_answer(self, call_id: str, from_tag: str, to_tag: str) -> Optional[int]:
        """
        创建RTP会话answer（200 OK阶段）
        
        Args:
            call_id: 呼叫ID
            from_tag: From标签
            to_tag: To标签
            
        Returns:
            RTPProxy分配的第二个端口号，失败返回None
        """
        # RTPProxy rtpp协议格式（200 OK阶段）:
        # V<call_id> <from_tag> <to_tag>
        # 注意：RTPProxy 3.1.1对命令格式很严格，call_id和tag中不能包含空格
        # 清理call_id和tag，移除可能导致解析错误的字符
        # RTPProxy对特殊字符很敏感，需要清理：空格、换行、制表符、以及可能引起解析错误的特殊字符
        # 注意：保留字母、数字、连字符、下划线，其他特殊字符替换为下划线
        import re
        # 先替换空格和换行符，再清理其他特殊字符
        clean_call_id = re.sub(r'[^\w\-]', '_', call_id.replace(' ', '_').replace('\n', '').replace('\r', '').replace('\t', ''))
        clean_from_tag = re.sub(r'[^\w\-]', '_', from_tag.replace(' ', '_').replace('\n', '').replace('\r', '').replace('\t', ''))
        clean_to_tag = re.sub(r'[^\w\-]', '_', to_tag.replace(' ', '_').replace('\n', '').replace('\r', '').replace('\t', ''))
        # 确保命令格式正确：V后无空格，call_id和tag之间有空格
        cmd = f"V{clean_call_id} {clean_from_tag} {clean_to_tag}".strip()
        print(f"[RTPProxy-DEBUG] Answer命令: {repr(cmd)}", file=sys.stderr, flush=True)
        try:
            response = self._send_command(cmd)
            print(f"[RTPProxy-DEBUG] Answer响应: {repr(response)}", file=sys.stderr, flush=True)
            # rtpproxy返回格式:
            # - 成功: <port_number> (分配的第二个RTP端口)
            # - 失败: V E<error_code>
            
            # 检查错误响应
            if response.startswith("V E") or response.startswith("U E"):
                print(f"[RTPProxy-ERROR] 创建answer失败: {call_id}, 响应={response}", file=sys.stderr, flush=True)
                return None
            
            # 解析端口号
            parts = response.split()
            if len(parts) >= 1:
                try:
                    port = int(parts[0])
                    print(f"[RTPProxy] 创建answer成功: {call_id}, RTP端口={port}", file=sys.stderr, flush=True)
                    return port
                except ValueError:
                    print(f"[RTPProxy-ERROR] 创建answer失败: {call_id}, 响应格式异常={response}", file=sys.stderr, flush=True)
                    return None
            else:
                print(f"[RTPProxy-ERROR] 创建answer失败: {call_id}, 响应格式异常={response}", file=sys.stderr, flush=True)
                return None
        except Exception as e:
            print(f"[RTPProxy-ERROR] 创建answer异常: {call_id}, 错误={e}", file=sys.stderr, flush=True)
            return None
    
    def create_session(self, call_id: str, from_tag: str, to_tag: str,
                      from_addr: Tuple[str, int], to_addr: Tuple[str, int],
                      flags: str = "") -> Optional[str]:
        """
        创建RTP会话（使用rtpp协议，两步协议）
        
        RTPProxy使用两步协议：
        1. INVITE阶段：发送V命令（只有call-id和from-tag），RTPProxy返回分配的端口
        2. 200 OK阶段：发送V命令（call-id, from-tag, to-tag），RTPProxy完成会话建立
        
        本方法用于200 OK阶段，完成会话建立。
        
        注意：如果V命令返回E0错误，可能需要使用U命令格式（带IP地址参数）
        
        Args:
            call_id: 呼叫ID
            from_tag: From标签
            to_tag: To标签
            from_addr: 源地址 (IP, port) - RTPProxy需要此参数
            to_addr: 目标地址 (IP, port) - RTPProxy需要此参数
            flags: 标志字符串（如 'r'=record, 'w'=write等）
            
        Returns:
            会话ID（rtpproxy返回的端口号），失败返回None
        """
        # 先尝试V命令（简单格式）
        port = self.create_answer(call_id, from_tag, to_tag)
        if port:
            return str(port)
        
        # 如果V命令失败，尝试U命令（完整格式，带IP地址）
        print(f"[RTPProxy] V命令失败，尝试U命令格式: {call_id}", file=sys.stderr, flush=True)
        return self._create_session_u_command(call_id, from_tag, to_tag, from_addr, to_addr, flags)
    
    def _create_session_u_command(self, call_id: str, from_tag: str, to_tag: str,
                                  from_addr: Tuple[str, int], to_addr: Tuple[str, int],
                                  flags: str = "") -> Optional[str]:
        """
        使用U命令创建RTP会话（完整格式，带IP地址参数）
        
        U命令格式：U<call_id> <from_tag> <to_tag> <from_ip>:<from_port> <to_ip>:<to_port> <flags>
        
        Args:
            call_id: 呼叫ID
            from_tag: From标签
            to_tag: To标签
            from_addr: 源地址 (IP, port)
            to_addr: 目标地址 (IP, port)
            flags: 标志字符串
            
        Returns:
            会话ID（端口号），失败返回None
        """
        # 清理call-id和tag
        clean_call_id = call_id.replace(' ', '_').replace('\n', '').replace('\r', '').replace('\t', '')
        clean_from_tag = from_tag.replace(' ', '_').replace('\n', '').replace('\r', '').replace('\t', '')
        clean_to_tag = to_tag.replace(' ', '_').replace('\n', '').replace('\r', '').replace('\t', '')
        
        # U命令格式：U<call_id> <from_tag> <to_tag> <from_ip>:<from_port> <to_ip>:<to_port> <flags>
        cmd = f"U{clean_call_id} {clean_from_tag} {clean_to_tag} {from_addr[0]}:{from_addr[1]} {to_addr[0]}:{to_addr[1]} {flags}".strip()
        
        try:
            response = self._send_command(cmd)
            
            # 检查错误响应
            if response.startswith("U E") or response.startswith("V E"):
                print(f"[RTPProxy-ERROR] U命令失败: {call_id}, 响应={response}", file=sys.stderr, flush=True)
                return None
            
            # 解析端口号（U命令返回格式：<port_number>）
            parts = response.split()
            if len(parts) >= 1:
                try:
                    port = int(parts[0])
                    print(f"[RTPProxy] U命令成功: {call_id}, RTP端口={port}", file=sys.stderr, flush=True)
                    return str(port)
                except ValueError:
                    print(f"[RTPProxy-ERROR] U命令响应格式异常: {call_id}, 响应={response}", file=sys.stderr, flush=True)
                    return None
            else:
                print(f"[RTPProxy-ERROR] U命令响应格式异常: {call_id}, 响应={response}", file=sys.stderr, flush=True)
                return None
        except Exception as e:
            print(f"[RTPProxy-ERROR] U命令异常: {call_id}, 错误={e}", file=sys.stderr, flush=True)
            return None
    
    def delete_session(self, call_id: str, from_tag: str, to_tag: str) -> bool:
        """
        删除RTP会话
        
        Args:
            call_id: 呼叫ID
            from_tag: From标签
            to_tag: To标签
            
        Returns:
            是否成功
        """
        # rtpproxy命令格式: D<call_id> <from_tag> <to_tag>
        cmd = f"D{call_id} {from_tag} {to_tag}"
        try:
            response = self._send_command(cmd)
            # rtpproxy返回 "OK" 表示成功
            success = response.upper() == "OK" or response.startswith("OK")
            if success:
                print(f"[RTPProxy] 删除会话成功: {call_id}", file=sys.stderr, flush=True)
            else:
                print(f"[RTPProxy-WARN] 删除会话响应异常: {call_id}, 响应={response}", file=sys.stderr, flush=True)
            return success
        except Exception as e:
            print(f"[RTPProxy-ERROR] 删除会话异常: {call_id}, 错误={e}", file=sys.stderr, flush=True)
            return False
    
    def query_session(self, call_id: str, from_tag: str, to_tag: str) -> Optional[Dict]:
        """
        查询会话信息
        
        Args:
            call_id: 呼叫ID
            from_tag: From标签
            to_tag: To标签
            
        Returns:
            会话信息字典，失败返回None
        """
        # rtpproxy命令格式: Q<call_id> <from_tag> <to_tag>
        cmd = f"Q{call_id} {from_tag} {to_tag}"
        try:
            response = self._send_command(cmd)
            # rtpproxy返回格式: <session_id> <from_ip>:<from_port> <to_ip>:<to_port>
            parts = response.split()
            if len(parts) >= 3:
                return {
                    'session_id': parts[0],
                    'from_addr': parts[1],
                    'to_addr': parts[2]
                }
            return None
        except Exception as e:
            print(f"[RTPProxy-ERROR] 查询会话异常: {call_id}, 错误={e}", file=sys.stderr, flush=True)
            return None
    
    def close(self):
        """关闭连接"""
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
