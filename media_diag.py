#!/usr/bin/env python3
"""
媒体转发实时诊断脚本
在服务器运行期间执行，检查媒体转发状态
"""

import sys
import time
import socket

# 添加项目路径
sys.path.insert(0, '/root/fanxiaolongx-max/IMS')

from sipcore.media_relay import get_media_relay, MediaRelay

def check_udp_port(port: int, timeout: float = 0.5) -> dict:
    """检查 UDP 端口状态"""
    result = {
        'port': port,
        'can_bind': False,  # True 表示端口空闲（没人监听）
        'error': None
    }
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.bind(('0.0.0.0', port))
        sock.close()
        result['can_bind'] = True  # 绑定成功 = 端口空闲
    except OSError as e:
        result['can_bind'] = False  # 绑定失败 = 端口被占用（有人在监听）
        result['error'] = str(e)
    return result

def main():
    print("=" * 60)
    print("媒体转发实时诊断")
    print("=" * 60)
    
    media_relay = get_media_relay()
    if not media_relay:
        print("❌ 媒体中继未初始化")
        return
    
    print(f"\n服务器IP: {media_relay.server_ip}")
    print(f"活动会话数: {len(media_relay._sessions)}")
    
    # 检查所有会话
    for call_id, session in media_relay._sessions.items():
        print(f"\n{'='*60}")
        print(f"呼叫ID: {call_id}")
        print(f"{'='*60}")
        
        caller = session.caller_number or "A-leg"
        callee = session.callee_number or "B-leg"
        
        print(f"\n[会话信息]")
        print(f"  主叫(A-leg): {caller}")
        print(f"  被叫(B-leg): {callee}")
        print(f"  会话启动时间: {session.started_at}")
        if session.started_at:
            elapsed = time.time() - session.started_at
            print(f"  运行时长: {elapsed:.1f}秒")
        
        print(f"\n[端口配置]")
        print(f"  A-leg RTP端口:  {session.a_leg_rtp_port}")
        print(f"  A-leg RTCP端口: {session.a_leg_rtcp_port}")
        print(f"  B-leg RTP端口:  {session.b_leg_rtp_port}")
        print(f"  B-leg RTCP端口: {session.b_leg_rtcp_port}")
        
        print(f"\n[端口监听状态]")
        for port in [session.a_leg_rtp_port, session.a_leg_rtcp_port, 
                     session.b_leg_rtp_port, session.b_leg_rtcp_port]:
            status = check_udp_port(port)
            if status['can_bind']:
                print(f"  端口 {port}: ❌ 空闲（未监听）")
            else:
                print(f"  端口 {port}: ✓ 被占用（监听中）")
        
        print(f"\n[地址信息]")
        print(f"  A-leg信令地址: {session.a_leg_signaling_addr}")
        print(f"  A-leg SDP地址:  {session.a_leg_remote_addr}")
        print(f"  B-leg信令地址: {session.b_leg_signaling_addr}")
        print(f"  B-leg SDP地址:  {session.b_leg_remote_addr}")
        
        print(f"\n[转发器统计]")
        
        # A-leg RTP 转发器
        fa = media_relay._forwarders.get((call_id, 'a', 'rtp'))
        if fa:
            print(f"\n  [A-leg RTP转发器] 端口 {fa.local_port}")
            print(f"    运行状态: {'运行中' if fa.running else '已停止'}")
            print(f"    当前目标: {fa.actual_target_addr}")
            print(f"    收包数量: {fa.packets_received}")
            print(f"    发包数量: {fa.packets_sent}")
            print(f"    收字节数: {fa.bytes_received}")
            print(f"    发字节数: {fa.bytes_sent}")
            print(f"    源地址历史: {fa._src_addr_history}")
            print(f"    是否已学习: {fa._addr_learned}")
            print(f"    对称RTP: {fa.symmetric_rtp}")
            if fa.peer_forwarder:
                print(f"    对端转发器端口: {fa.peer_forwarder.local_port}")
            else:
                print(f"    对端转发器: 无")
        else:
            print(f"\n  [A-leg RTP转发器] 未创建")
        
        # B-leg RTP 转发器
        fb = media_relay._forwarders.get((call_id, 'b', 'rtp'))
        if fb:
            print(f"\n  [B-leg RTP转发器] 端口 {fb.local_port}")
            print(f"    运行状态: {'运行中' if fb.running else '已停止'}")
            print(f"    当前目标: {fb.actual_target_addr}")
            print(f"    收包数量: {fb.packets_received}")
            print(f"    发包数量: {fb.packets_sent}")
            print(f"    收字节数: {fb.bytes_received}")
            print(f"    发字节数: {fb.bytes_sent}")
            print(f"    源地址历史: {fb._src_addr_history}")
            print(f"    是否已学习: {fb._addr_learned}")
            print(f"    对称RTP: {fb.symmetric_rtp}")
            if fb.peer_forwarder:
                print(f"    对端转发器端口: {fb.peer_forwarder.local_port}")
            else:
                print(f"    对端转发器: 无")
        else:
            print(f"\n  [B-leg RTP转发器] 未创建")
        
        print(f"\n[诊断分析]")
        if fa and fb:
            # 分析媒体流向
            print(f"  预期媒体流:")
            print(f"    {caller} 应发到服务器端口 {session.a_leg_rtp_port}")
            print(f"    {callee} 应发到服务器端口 {session.b_leg_rtp_port}")
            
            if fa.packets_received == 0 and fb.packets_received > 0:
                print(f"\n  ⚠️ 单向媒体问题:")
                print(f"    - {callee} → 服务器 → {caller} : 正常 (B-leg收包{fb.packets_received})")
                print(f"    - {caller} → 服务器 : 无包 (A-leg收包{fa.packets_received})")
                print(f"\n  可能原因:")
                print(f"    1. {caller} 没有把RTP发到服务器端口 {session.a_leg_rtp_port}")
                print(f"    2. {caller} 直接发给了 {callee} 的地址")
                print(f"    3. SDP修改未生效，{caller} 仍按原始SDP发送")
            elif fa.packets_received > 0 and fb.packets_received == 0:
                print(f"\n  ⚠️ 单向媒体问题:")
                print(f"    - {caller} → 服务器 → {callee} : 正常")
                print(f"    - {callee} → 服务器 : 无包")
            elif fa.packets_received == 0 and fb.packets_received == 0:
                print(f"\n  ❌ 双向无媒体")
            else:
                print(f"\n  ✓ 双向媒体正常")
                print(f"    - {caller} → 服务器: {fa.packets_received} 包")
                print(f"    - {callee} → 服务器: {fb.packets_received} 包")
                
            # 检查转发目标
            if fa.actual_target_addr:
                print(f"\n  A-leg转发目标: {fa.actual_target_addr} (应转发给{callee})")
            if fb.actual_target_addr:
                print(f"  B-leg转发目标: {fb.actual_target_addr} (应转发给{caller})")

if __name__ == "__main__":
    main()
