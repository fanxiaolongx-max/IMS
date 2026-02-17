"""
NAT Helper - 服务器端NAT处理模块

基于业界最佳实践（Kamailio/OpenSIPS方式）实现服务器端NAT处理：
1. fix_contact() - 重写Contact头为源地址:端口
2. fix_nated_sdp() - 修正SDP中的IP/端口
3. nat_keepalive() - NAT保活
4. 检测NAT - 判断客户端是否在NAT后

参考：
- Kamailio nathelper模块: https://kamailio.org/docs/modules/stable/modules/nathelper.html
- OpenSIPS nat_traversal模块: https://opensips.org/docs/modules/2.3.x/nat_traversal.html
"""

import re
import socket
import ipaddress
from typing import Tuple, Optional, Dict, Set
from sipcore.message import SIPMessage


class NATHelper:
    """
    NAT助手类
    
    实现服务器端NAT处理，符合业界最佳实践。
    """
    
    def __init__(self, server_ip: str, local_networks: Optional[list] = None):
        """
        初始化NAT助手
        
        Args:
            server_ip: 服务器公网IP
            local_networks: 本地网络列表（CIDR格式），例如 ['192.168.0.0/16', '10.0.0.0/8']
        """
        self.server_ip = server_ip
        self.local_networks = local_networks or []
        
        # 编译本地网络CIDR
        self._local_networks_set: Set[ipaddress.IPv4Network] = set()
        for net in self.local_networks:
            try:
                self._local_networks_set.add(ipaddress.ip_network(net, strict=False))
            except ValueError:
                pass
    
    def is_local_ip(self, ip: str) -> bool:
        """判断IP是否在本地网络"""
        try:
            ip_addr = ipaddress.ip_address(ip)
            # 检查是否是私网地址
            if ip_addr.is_private:
                return True
            # 检查是否在配置的本地网络中
            for net in self._local_networks_set:
                if ip_addr in net:
                    return True
            return False
        except ValueError:
            return False
    
    def is_behind_nat(self, contact_ip: str, source_addr: Tuple[str, int]) -> bool:
        """
        检测客户端是否在NAT后
        
        判断逻辑：
        1. Contact头中的IP是私网地址，但源地址是公网地址 -> 在NAT后
        2. Contact头中的IP与源地址IP不同 -> 可能在NAT后
        
        Args:
            contact_ip: Contact头中的IP地址
            source_addr: UDP数据包的源地址 (ip, port)
        
        Returns:
            True表示客户端在NAT后
        """
        source_ip = source_addr[0]
        
        # 如果Contact IP是私网地址，但源地址是公网地址，说明在NAT后
        if self.is_local_ip(contact_ip) and not self.is_local_ip(source_ip):
            return True
        
        # 如果Contact IP与源地址IP不同，可能在NAT后
        if contact_ip != source_ip:
            return True
        
        return False
    
    def fix_contact(self, contact_header: str, source_addr: Tuple[str, int]) -> str:
        """
        修正Contact头（类似Kamailio的fix_contact()）
        
        将Contact头中的地址替换为实际的源地址:端口，用于NAT穿透。
        
        Args:
            contact_header: Contact头值，例如 "sip:1001@192.168.1.100:5060"
            source_addr: UDP数据包的源地址 (ip, port)
        
        Returns:
            修正后的Contact头
        """
        source_ip, source_port = source_addr
        
        # 提取用户部分
        user_match = re.search(r'sip:([^@]+)@', contact_header)
        if not user_match:
            return contact_header
        
        user = user_match.group(1)
        
        # 替换IP和端口
        # 处理格式: sip:user@IP:port;params 或 <sip:user@IP:port>;params
        if contact_header.startswith('<'):
            # 格式: <sip:user@IP:port>;params
            new_contact = f"<sip:{user}@{source_ip}:{source_port}>"
            # 保留参数
            params_match = re.search(r'>([^>]*)$', contact_header)
            if params_match:
                new_contact += params_match.group(1)
        else:
            # 格式: sip:user@IP:port;params
            new_contact = f"sip:{user}@{source_ip}:{source_port}"
            # 保留参数
            params_match = re.search(r'[;>]([^;>]*)$', contact_header)
            if params_match:
                new_contact += ";" + params_match.group(1)
        
        return new_contact
    
    def fix_nated_sdp(self, sdp_body: str, source_addr: Tuple[str, int]) -> str:
        """
        修正SDP中的IP地址（类似Kamailio的fix_nated_sdp()）
        
        将SDP中的连接IP替换为实际的源地址IP，用于NAT穿透。
        
        Args:
            sdp_body: SDP内容
            source_addr: UDP数据包的源地址 (ip, port)
        
        Returns:
            修正后的SDP
        """
        source_ip = source_addr[0]
        lines = sdp_body.split('\n')
        new_lines = []
        
        for line in lines:
            # 修正 c=IN IP4 行
            if line.startswith('c=IN IP4 '):
                parts = line.split()
                if len(parts) >= 3:
                    old_ip = parts[2]
                    # 如果原IP是私网地址，替换为源地址IP
                    if self.is_local_ip(old_ip):
                        new_line = f"c=IN IP4 {source_ip}"
                        if len(parts) > 3:
                            new_line += " " + " ".join(parts[3:])
                        new_lines.append(new_line)
                        continue
            
            new_lines.append(line)
        
        return '\n'.join(new_lines)
    
    def add_contact_alias(self, contact_header: str, source_addr: Tuple[str, int]) -> str:
        """
        添加Contact别名（RFC 3261兼容方式）
        
        在Contact头中添加alias参数，而不是直接修改地址。
        这是RFC 3261推荐的NAT处理方式。
        
        Args:
            contact_header: Contact头值
            source_addr: UDP数据包的源地址 (ip, port)
        
        Returns:
            添加了alias的Contact头
        """
        source_ip, source_port = source_addr
        
        # 检查是否已有alias参数
        if ';alias=' in contact_header or ';alias="' in contact_header:
            return contact_header
        
        # 添加alias参数
        alias = f"sip:{source_ip}:{source_port}"
        if contact_header.endswith(';') or contact_header.endswith('>'):
            return contact_header.rstrip(';>') + f';alias="{alias}">'
        else:
            return contact_header + f';alias="{alias}"'
    
    def extract_contact_ip_port(self, contact_header: str) -> Optional[Tuple[str, int]]:
        """
        从Contact头提取IP和端口
        
        Args:
            contact_header: Contact头值
        
        Returns:
            (ip, port) 元组，如果提取失败返回None
        """
        # 匹配格式: sip:user@IP:port 或 <sip:user@IP:port>
        match = re.search(r'@([^:;>]+):(\d+)', contact_header)
        if match:
            ip = match.group(1)
            port = int(match.group(2))
            return (ip, port)
        return None
    
    def process_register_contact(self, msg: SIPMessage, source_addr: Tuple[str, int]) -> bool:
        """
        处理REGISTER请求的Contact头
        
        自动检测NAT并修正Contact头。
        
        Args:
            msg: SIP消息
            source_addr: UDP数据包的源地址
        
        Returns:
            True表示进行了NAT修正
        """
        contacts = msg.headers.get("contact", [])
        if not contacts:
            return False
        
        modified = False
        new_contacts = []
        
        for contact in contacts:
            contact_ip_port = self.extract_contact_ip_port(contact)
            if contact_ip_port:
                contact_ip = contact_ip_port[0]
                if self.is_behind_nat(contact_ip, source_addr):
                    # 修正Contact头
                    fixed_contact = self.fix_contact(contact, source_addr)
                    new_contacts.append(fixed_contact)
                    modified = True
                else:
                    new_contacts.append(contact)
            else:
                new_contacts.append(contact)
        
        if modified:
            msg.headers["contact"] = new_contacts
        
        return modified
    
    def process_invite_sdp(self, msg: SIPMessage, source_addr: Tuple[str, int]) -> bool:
        """
        处理INVITE请求的SDP
        
        自动检测NAT并修正SDP中的IP地址。
        
        Args:
            msg: SIP消息
            source_addr: UDP数据包的源地址
        
        Returns:
            True表示进行了NAT修正
        """
        if not msg.body:
            return False
        
        try:
            sdp_body = msg.body.decode('utf-8', errors='ignore') if isinstance(msg.body, bytes) else msg.body
            
            # 提取SDP中的IP
            connection_match = re.search(r'c=IN IP4 ([^\s\r\n]+)', sdp_body)
            if connection_match:
                sdp_ip = connection_match.group(1)
                if self.is_behind_nat(sdp_ip, source_addr):
                    # 修正SDP
                    fixed_sdp = self.fix_nated_sdp(sdp_body, source_addr)
                    msg.body = fixed_sdp.encode('utf-8') if isinstance(msg.body, bytes) else fixed_sdp
                    # 更新Content-Length
                    if 'content-length' in msg.headers:
                        msg.headers['content-length'] = [str(len(msg.body) if isinstance(msg.body, bytes) else len(msg.body.encode('utf-8')))]
                    return True
        except Exception:
            pass
        
        return False
    
    def process_response_sdp(self, msg: SIPMessage, source_addr: Tuple[str, int]) -> bool:
        """
        处理响应消息的SDP（200 OK等）
        
        自动检测NAT并修正SDP中的IP地址。
        
        Args:
            msg: SIP响应消息
            source_addr: UDP数据包的源地址
        
        Returns:
            True表示进行了NAT修正
        """
        return self.process_invite_sdp(msg, source_addr)


# 全局NAT助手实例
_nat_helper: Optional[NATHelper] = None


def init_nat_helper(server_ip: str, local_networks: Optional[list] = None) -> NATHelper:
    """
    初始化全局NAT助手
    
    Args:
        server_ip: 服务器公网IP
        local_networks: 本地网络列表（CIDR格式）
    """
    global _nat_helper
    _nat_helper = NATHelper(server_ip, local_networks)
    return _nat_helper


def get_nat_helper() -> Optional[NATHelper]:
    """获取全局NAT助手实例"""
    return _nat_helper
