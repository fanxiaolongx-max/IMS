#!/usr/bin/env python3
"""
动态获取公网IP地址工具
支持多个API服务，自动选择可用的服务
"""

import urllib.request
import urllib.error
import json
import sys
import time

# 多个公网IP查询服务（按优先级排序）
IP_SERVICES = [
    {
        'name': 'ipify',
        'url': 'https://api.ipify.org?format=json',
        'parser': lambda r: json.loads(r)['ip']
    },
    {
        'name': 'ifconfig.me',
        'url': 'https://ifconfig.me/ip',
        'parser': lambda r: r.strip()
    },
    {
        'name': 'icanhazip',
        'url': 'https://icanhazip.com',
        'parser': lambda r: r.strip()
    },
    {
        'name': 'ip-api',
        'url': 'http://ip-api.com/json',
        'parser': lambda r: json.loads(r)['query']
    },
    {
        'name': 'httpbin',
        'url': 'https://httpbin.org/ip',
        'parser': lambda r: json.loads(r)['origin'].split(',')[0].strip()
    }
]


def get_public_ip(timeout=5, retries=2):
    """
    获取公网IP地址
    
    Args:
        timeout: 每个请求的超时时间（秒）
        retries: 每个服务失败后的重试次数
    
    Returns:
        str: 公网IP地址，失败返回None
    """
    for service in IP_SERVICES:
        for attempt in range(retries):
            try:
                req = urllib.request.Request(
                    service['url'],
                    headers={'User-Agent': 'Mozilla/5.0'}
                )
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    data = response.read().decode('utf-8')
                    ip = service['parser'](data)
                    
                    # 验证IP格式
                    if validate_ip(ip):
                        print(f"[INFO] 成功从 {service['name']} 获取公网IP: {ip}", file=sys.stderr)
                        return ip
                    else:
                        print(f"[WARN] {service['name']} 返回了无效IP: {ip}", file=sys.stderr)
            except urllib.error.URLError as e:
                if attempt < retries - 1:
                    time.sleep(0.5)  # 短暂等待后重试
                    continue
                print(f"[DEBUG] {service['name']} 失败: {e}", file=sys.stderr)
            except Exception as e:
                print(f"[DEBUG] {service['name']} 解析失败: {e}", file=sys.stderr)
                break
    
    return None


def validate_ip(ip):
    """验证IP地址格式"""
    if not ip:
        return False
    parts = ip.split('.')
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(part) <= 255 for part in parts)
    except ValueError:
        return False


def main():
    """主函数"""
    ip = get_public_ip()
    if ip:
        print(ip)
        return 0
    else:
        print("[ERROR] 无法获取公网IP地址", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
