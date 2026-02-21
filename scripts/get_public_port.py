#!/usr/bin/env python3
"""
检测NAT端口映射的工具
通过STUN服务器检测公网IP和端口映射
"""

import socket
import struct
import sys
import time

# STUN服务器列表
STUN_SERVERS = [
    ("stun.l.google.com", 19302),
    ("stun1.l.google.com", 19302),
    ("stun2.l.google.com", 19302),
    ("stun.stunprotocol.org", 3478),
]


def stun_request(server_host, server_port, local_port=5060):
    """
    发送STUN请求，检测NAT映射的公网IP和端口
    
    Args:
        server_host: STUN服务器地址
        server_port: STUN服务器端口
        local_port: 本地监听端口（用于检测该端口的映射）
    
    Returns:
        tuple: (公网IP, 公网端口) 或 None
    """
    try:
        # 创建UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5)
        
        # 绑定到本地端口（如果可能）
        try:
            sock.bind(("0.0.0.0", local_port))
        except OSError:
            # 端口被占用，尝试绑定到随机端口
            sock.bind(("0.0.0.0", 0))
        
        # STUN绑定请求消息
        # Message Type: Binding Request (0x0001)
        # Message Length: 0
        # Transaction ID: 随机12字节
        transaction_id = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
        message = struct.pack('!HH', 0x0001, 0) + transaction_id
        
        # 发送STUN请求
        sock.sendto(message, (server_host, server_port))
        
        # 接收响应
        response, addr = sock.recvfrom(1024)
        sock.close()
        
        # 解析STUN响应
        if len(response) < 20:
            return None
        
        # 检查消息类型（应该是Binding Response: 0x0101）
        msg_type = struct.unpack('!H', response[0:2])[0]
        if msg_type != 0x0101:
            return None
        
        # 查找MAPPED-ADDRESS属性（0x0001）
        offset = 20
        while offset < len(response) - 4:
            attr_type = struct.unpack('!H', response[offset:offset+2])[0]
            attr_len = struct.unpack('!H', response[offset+2:offset+4])[0]
            
            if attr_type == 0x0001:  # MAPPED-ADDRESS
                # 跳过family字段（1字节）和端口（2字节）
                port = struct.unpack('!H', response[offset+5:offset+7])[0]
                ip_bytes = response[offset+7:offset+7+4]
                ip = '.'.join(str(b) for b in ip_bytes)
                return (ip, port)
            
            offset += 4 + attr_len
        
        return None
        
    except Exception as e:
        print(f"[DEBUG] STUN请求失败 ({server_host}:{server_port}): {e}", file=sys.stderr)
        return None


def detect_nat_mapping(local_port=5060):
    """
    检测NAT端口映射
    
    Args:
        local_port: 本地端口号
    
    Returns:
        tuple: (公网IP, 公网端口) 或 None
    """
    print(f"[INFO] 检测端口 {local_port} 的NAT映射...", file=sys.stderr)
    
    for server_host, server_port in STUN_SERVERS:
        print(f"[INFO] 尝试 STUN 服务器: {server_host}:{server_port}", file=sys.stderr)
        result = stun_request(server_host, server_port, local_port)
        if result:
            public_ip, public_port = result
            print(f"[SUCCESS] 检测到NAT映射: {local_port} -> {public_port} (公网IP: {public_ip})", file=sys.stderr)
            return result
        time.sleep(0.5)
    
    print(f"[WARN] 无法通过STUN检测NAT映射", file=sys.stderr)
    return None


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='检测NAT端口映射')
    parser.add_argument('--port', type=int, default=5060, help='本地端口号（默认: 5060）')
    parser.add_argument('--format', choices=['ip', 'port', 'both'], default='port',
                       help='输出格式: ip=只输出IP, port=只输出端口, both=输出IP:端口')
    
    args = parser.parse_args()
    
    result = detect_nat_mapping(args.port)
    
    if result:
        public_ip, public_port = result
        if args.format == 'ip':
            print(public_ip)
        elif args.format == 'port':
            print(public_port)
        else:  # both
            print(f"{public_ip}:{public_port}")
        return 0
    else:
        print("[ERROR] 无法检测NAT映射", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
