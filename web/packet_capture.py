"""
数据包抓取模块 - 基于tcpdump的实时抓包

使用tcpdump进行实时抓包，通过WebSocket传输到前端显示。
支持过滤、实时显示、保存等功能。
"""

import subprocess
import asyncio
import json
import re
import threading
from typing import Optional, Dict, Set, Callable
from datetime import datetime
import sys


class PacketCapture:
    """
    数据包抓取器
    
    使用tcpdump进行实时抓包，支持过滤和实时传输。
    """
    
    def __init__(self, interface: str = "any", filter_expr: str = ""):
        """
        初始化抓包器
        
        Args:
            interface: 网络接口（默认any，抓取所有接口）
            filter_expr: tcpdump过滤表达式（如 "port 5060"）
        """
        self.interface = interface
        self.filter_expr = filter_expr
        self.process: Optional[subprocess.Popen] = None
        self.is_capturing = False
        self.subscribers: Set[Callable] = set()
        self.lock = threading.Lock()
        self.packet_count = 0
        self.start_time: Optional[datetime] = None
    
    def start(self):
        """启动抓包"""
        if self.is_capturing:
            return False
        
        try:
            # 构建tcpdump命令
            cmd = ["tcpdump", "-i", self.interface, "-n", "-l", "-q"]
            
            # 添加过滤表达式
            if self.filter_expr:
                cmd.extend([self.filter_expr])
            
            # 启动tcpdump进程
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            self.is_capturing = True
            self.start_time = datetime.now()
            self.packet_count = 0
            
            # 启动读取线程
            thread = threading.Thread(target=self._read_packets, daemon=True)
            thread.start()
            
            return True
        except Exception as e:
            print(f"[PacketCapture-ERROR] 启动失败: {e}", file=sys.stderr, flush=True)
            return False
    
    def stop(self):
        """停止抓包"""
        if not self.is_capturing:
            return
        
        self.is_capturing = False
        
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except:
                try:
                    self.process.kill()
                except:
                    pass
            self.process = None
    
    def _read_packets(self):
        """读取数据包（在独立线程中运行）"""
        if not self.process:
            return
        
        try:
            for line in iter(self.process.stdout.readline, ''):
                if not self.is_capturing:
                    break
                
                if line.strip():
                    packet_info = self._parse_packet(line.strip())
                    if packet_info:
                        self.packet_count += 1
                        # 添加type字段标识这是数据包
                        packet_info['type'] = 'packet'
                        if self.packet_count % 10 == 0:  # 每10个包打印一次日志
                            print(f"[PacketCapture-DEBUG] 已解析 {self.packet_count} 个数据包", file=sys.stderr, flush=True)
                        self._notify_subscribers(packet_info)
        except Exception as e:
            print(f"[PacketCapture-ERROR] 读取数据包失败: {e}", file=sys.stderr, flush=True)
        finally:
            self.is_capturing = False
    
    def _parse_packet(self, line: str) -> Optional[Dict]:
        """
        解析tcpdump输出行
        
        tcpdump输出格式示例：
        "12:34:56.789123 IP 192.168.1.100.5060 > 192.168.1.200.5060: UDP, length 123"
        "12:34:56.789123 IP 192.168.1.100 > 192.168.1.200: ICMP echo request, id 12345, seq 1, length 64"
        """
        try:
            # 解析时间戳
            time_match = re.match(r'(\d{2}:\d{2}:\d{2}\.\d+)', line)
            timestamp = time_match.group(1) if time_match else ""
            
            # 解析协议
            protocol_match = re.search(r'\b(IP|ARP|ICMP|TCP|UDP|SIP)\b', line)
            protocol = protocol_match.group(1) if protocol_match else "UNKNOWN"
            
            # 解析源地址和目标地址
            # 格式: IP src > dst 或 IP src.port > dst.port
            addr_match = re.search(r'IP\s+([^\s>]+)\s*>\s*([^\s:]+)', line)
            if addr_match:
                src = addr_match.group(1)
                dst = addr_match.group(2)
            else:
                src = ""
                dst = ""
            
            # 解析端口（如果有）
            src_port = ""
            dst_port = ""
            if "." in src:
                parts = src.rsplit(".", 1)
                if parts[1].isdigit():
                    src_port = parts[1]
                    src = parts[0]
            if "." in dst:
                parts = dst.rsplit(".", 1)
                if parts[1].isdigit():
                    dst_port = parts[1]
                    dst = parts[0]
            
            # 解析长度
            length_match = re.search(r'length\s+(\d+)', line)
            length = length_match.group(1) if length_match else "0"
            
            # 解析标志（TCP）
            flags = ""
            if "TCP" in line:
                flags_match = re.search(r'Flags\s+\[([^\]]+)\]', line)
                if flags_match:
                    flags = flags_match.group(1)
            
            # 解析SIP方法（如果有）
            sip_method = ""
            if "SIP" in line or "5060" in line:
                sip_match = re.search(r'\b(INVITE|ACK|BYE|CANCEL|REGISTER|OPTIONS|MESSAGE|PRACK|UPDATE|REFER|NOTIFY|SUBSCRIBE|200|180|183|401|403|404|480|486|487|488|500|503)\b', line)
                if sip_match:
                    sip_method = sip_match.group(1)
            
            return {
                "timestamp": timestamp,
                "protocol": protocol,
                "src_ip": src,
                "src_port": src_port,
                "dst_ip": dst,
                "dst_port": dst_port,
                "length": length,
                "flags": flags,
                "sip_method": sip_method,
                "raw": line,
                "packet_num": self.packet_count + 1
            }
        except Exception as e:
            print(f"[PacketCapture-ERROR] 解析数据包失败: {e}, line={line[:100]}", file=sys.stderr, flush=True)
            return None
    
    def subscribe(self, callback: Callable):
        """订阅数据包通知"""
        with self.lock:
            self.subscribers.add(callback)
    
    def unsubscribe(self, callback: Callable):
        """取消订阅"""
        with self.lock:
            self.subscribers.discard(callback)
    
    def _notify_subscribers(self, packet_info: Dict):
        """通知所有订阅者"""
        with self.lock:
            subscriber_count = len(self.subscribers)
            if subscriber_count == 0:
                print(f"[PacketCapture-DEBUG] 没有订阅者，跳过通知", file=sys.stderr, flush=True)
                return
            
            print(f"[PacketCapture-DEBUG] 通知 {subscriber_count} 个订阅者", file=sys.stderr, flush=True)
            for callback in list(self.subscribers):  # 使用列表副本避免迭代时修改
                try:
                    callback(packet_info)
                except Exception as e:
                    print(f"[PacketCapture-ERROR] 通知订阅者失败: {e}", file=sys.stderr, flush=True)
                    import traceback
                    traceback.print_exc()
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        duration = 0
        if self.start_time:
            duration = (datetime.now() - self.start_time).total_seconds()
        
        return {
            "is_capturing": self.is_capturing,
            "packet_count": self.packet_count,
            "duration": duration,
            "interface": self.interface,
            "filter": self.filter_expr
        }


# 全局抓包器实例
_capture: Optional[PacketCapture] = None


def get_capture() -> Optional[PacketCapture]:
    """获取全局抓包器实例"""
    return _capture


def create_capture(interface: str = "any", filter_expr: str = "") -> PacketCapture:
    """创建新的抓包器实例"""
    global _capture
    if _capture and _capture.is_capturing:
        _capture.stop()
    _capture = PacketCapture(interface, filter_expr)
    return _capture


def start_capture(interface: str = "any", filter_expr: str = "") -> bool:
    """启动抓包"""
    capture = create_capture(interface, filter_expr)
    return capture.start()


def stop_capture():
    """停止抓包"""
    global _capture
    if _capture:
        _capture.stop()


def get_capture_stats() -> Dict:
    """获取抓包统计信息"""
    if _capture:
        return _capture.get_stats()
    return {
        "is_capturing": False,
        "packet_count": 0,
        "duration": 0,
        "interface": "",
        "filter": ""
    }
