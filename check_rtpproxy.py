#!/usr/bin/env python3
"""
RTPProxy诊断脚本 - 检查RTPProxy是否正常运行并测试协议
"""
import socket
import sys

def test_rtpproxy_udp(host='127.0.0.1', port=7722):
    """测试UDP socket连接"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2)
        sock.connect((host, port))
        
        # 测试V命令（创建会话）
        # RTPProxy协议格式: V<call-id> <from-tag> <to-tag>
        cmd = f"V test-call-id-123 tag-from tag-to\n"
        print(f"[测试] 发送命令: {cmd.strip()}")
        sock.sendall(cmd.encode())
        
        response = sock.recv(1024).decode('utf-8', errors='ignore').strip()
        print(f"[测试] RTPProxy响应: {response}")
        
        if response:
            print(f"[成功] RTPProxy正在运行并响应命令")
            return True
        else:
            print(f"[失败] RTPProxy未响应")
            return False
            
    except ConnectionRefusedError:
        print(f"[错误] 无法连接到RTPProxy ({host}:{port})")
        print(f"[提示] 请启动RTPProxy: rtpproxy -l <server_ip> -s udp:{host}:{port} -F")
        return False
    except socket.timeout:
        print(f"[错误] RTPProxy响应超时")
        return False
    except Exception as e:
        print(f"[错误] 测试失败: {e}")
        return False
    finally:
        try:
            sock.close()
        except:
            pass

def test_rtpproxy_unix(socket_path='/var/run/rtpproxy.sock'):
    """测试Unix socket连接"""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.settimeout(2)
        sock.connect(socket_path)
        
        cmd = f"V test-call-id-123 tag-from tag-to\n"
        print(f"[测试] 发送命令: {cmd.strip()}")
        sock.sendall(cmd.encode())
        
        response = sock.recv(1024).decode('utf-8', errors='ignore').strip()
        print(f"[测试] RTPProxy响应: {response}")
        
        if response:
            print(f"[成功] RTPProxy正在运行并响应命令")
            return True
        else:
            print(f"[失败] RTPProxy未响应")
            return False
            
    except FileNotFoundError:
        print(f"[错误] Unix socket不存在: {socket_path}")
        print(f"[提示] 请启动RTPProxy: rtpproxy -l <server_ip> -s unix:{socket_path} -F")
        return False
    except Exception as e:
        print(f"[错误] 测试失败: {e}")
        return False
    finally:
        try:
            sock.close()
        except:
            pass

if __name__ == '__main__':
    print("=" * 60)
    print("RTPProxy诊断工具")
    print("=" * 60)
    
    # 测试UDP socket
    print("\n[1] 测试UDP socket (127.0.0.1:7722)...")
    udp_ok = test_rtpproxy_udp()
    
    # 测试Unix socket
    print("\n[2] 测试Unix socket (/var/run/rtpproxy.sock)...")
    unix_ok = test_rtpproxy_unix()
    
    print("\n" + "=" * 60)
    if udp_ok or unix_ok:
        print("[结果] RTPProxy运行正常 ✓")
        sys.exit(0)
    else:
        print("[结果] RTPProxy未运行或配置不正确 ✗")
        print("\n[解决方案]")
        print("1. 安装RTPProxy: apt-get install rtpproxy")
        print("2. 启动RTPProxy:")
        print("   UDP模式: rtpproxy -l <server_ip> -s udp:127.0.0.1:7722 -F")
        print("   Unix模式: rtpproxy -l <server_ip> -s unix:/var/run/rtpproxy.sock -F")
        sys.exit(1)
