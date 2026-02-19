#!/usr/bin/env python3
"""
清理冲突的 Cloudflare Tunnel 进程

用法:
    python scripts/cleanup_cf_tunnels.py [--all] [--keep-named]
    
选项:
    --all: 清理所有 quick tunnel（包括非冲突的）
    --keep-named: 保留命名隧道（默认保留）
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sipcore.cloudflare_tunnel import find_existing_tunnels, cleanup_conflicting_tunnels

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='清理冲突的 Cloudflare Tunnel 进程')
    parser.add_argument('--all', action='store_true', help='清理所有 quick tunnel')
    parser.add_argument('--keep-named', action='store_true', default=True, help='保留命名隧道（默认）')
    parser.add_argument('--target-urls', nargs='+', help='目标 URL 列表（如 tcp://127.0.0.1:5060 http://127.0.0.1:8888）')
    
    args = parser.parse_args()
    
    # 查询现有隧道
    existing = find_existing_tunnels()
    
    if not existing:
        print("未发现运行中的 cloudflared 隧道进程")
        return 0
    
    print(f"发现 {len(existing)} 个 cloudflared 隧道进程:")
    for t in existing:
        print(f"  - PID {t['pid']}: {t['type']} {t['url']}")
        print(f"    命令: {t['cmd'][:100]}...")
    
    if args.all:
        # 清理所有 quick tunnel
        target_urls = []
        for t in existing:
            if t['type'] in ('tcp', 'http') and t['url']:
                target_urls.append(t['url'])
        
        if target_urls:
            cleaned = cleanup_conflicting_tunnels(target_urls, keep_named=args.keep_named)
            print(f"\n已清理 {cleaned} 个隧道进程")
        else:
            print("\n没有需要清理的 quick tunnel")
    elif args.target_urls:
        # 清理指定的目标 URL
        cleaned = cleanup_conflicting_tunnels(args.target_urls, keep_named=args.keep_named)
        print(f"\n已清理 {cleaned} 个冲突隧道进程")
    else:
        # 默认：清理指向 5060 和 8888 的隧道
        target_urls = ["tcp://127.0.0.1:5060", "http://127.0.0.1:8888"]
        cleaned = cleanup_conflicting_tunnels(target_urls, keep_named=args.keep_named)
        print(f"\n已清理 {cleaned} 个冲突隧道进程")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
