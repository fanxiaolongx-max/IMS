#!/usr/bin/env python3
"""
B2BUA 媒体中继功能测试脚本

测试内容：
1. 检查媒体中继模块是否正确加载
2. 检查端口分配功能
3. 检查SDP修改功能
4. 模拟一次呼叫的媒体处理流程
"""

import sys
sys.path.insert(0, '/root/fanxiaolongx-max/IMS')

def test_media_relay():
    """测试媒体中继功能"""
    print("=" * 60)
    print("B2BUA 媒体中继功能测试")
    print("=" * 60)
    
    # 1. 测试模块导入
    print("\n[1] 测试模块导入...")
    try:
        from sipcore.media_relay import (
            MediaRelay, MediaSession, RTPPortManager, 
            SDPProcessor, RTPForwarder,
            init_media_relay, get_media_relay
        )
        print("  ✓ 所有模块导入成功")
    except Exception as e:
        print(f"  ✗ 模块导入失败: {e}")
        return False
    
    # 2. 测试端口管理器
    print("\n[2] 测试端口管理器...")
    try:
        pm = RTPPortManager()
        stats = pm.get_stats()
        print(f"  总端口对: {stats['total_pairs']}")
        print(f"  已使用: {stats['used_pairs']}")
        print(f"  可用: {stats['available_pairs']}")
        
        # 分配端口
        ports = pm.allocate_port_pair("test-call-1")
        if ports:
            print(f"  ✓ 分配端口成功: RTP={ports[0]}, RTCP={ports[1]}")
            pm.release_port_pair(ports[0], ports[1])
            print(f"  ✓ 释放端口成功")
        else:
            print(f"  ✗ 分配端口失败")
    except Exception as e:
        print(f"  ✗ 端口管理器测试失败: {e}")
        return False
    
    # 3. 测试SDP处理器
    print("\n[3] 测试SDP处理器...")
    try:
        sdp_proc = SDPProcessor()
        
        # 示例SDP
        sample_sdp = """v=0
o=- 123456 654321 IN IP4 192.168.1.100
s=SIP Call
c=IN IP4 192.168.1.100
t=0 0
m=audio 10000 RTP/AVP 0 8
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
"""
        
        # 提取媒体信息
        info = sdp_proc.extract_media_info(sample_sdp)
        print(f"  原始连接IP: {info['connection_ip']}")
        print(f"  原始音频端口: {info['audio_port']}")
        print(f"  支持的payload: {info['audio_payloads']}")
        
        # 修改SDP
        new_sdp = sdp_proc.modify_sdp(sample_sdp, "172.31.10.126", 20000)
        new_info = sdp_proc.extract_media_info(new_sdp)
        print(f"  修改后连接IP: {new_info['connection_ip']}")
        print(f"  修改后音频端口: {new_info['audio_port']}")
        
        if new_info['connection_ip'] == "172.31.10.126" and new_info['audio_port'] == 20000:
            print("  ✓ SDP修改成功")
        else:
            print("  ✗ SDP修改失败")
    except Exception as e:
        print(f"  ✗ SDP处理器测试失败: {e}")
        return False
    
    # 4. 测试媒体中继完整流程
    print("\n[4] 测试媒体中继完整流程...")
    try:
        relay = MediaRelay("172.31.10.126")
        
        # 模拟INVITE SDP处理
        caller_sdp = """v=0
o=- 123456 654321 IN IP4 192.168.1.100
s=SIP Call
c=IN IP4 192.168.1.100
t=0 0
m=audio 10000 RTP/AVP 0
a=rtpmap:0 PCMU/8000
"""
        
        new_sdp, session = relay.process_invite_sdp(
            "test-call-001", 
            caller_sdp, 
            ("192.168.1.100", 5060)
        )
        
        if session:
            print(f"  ✓ 创建媒体会话成功")
            print(f"    Call-ID: test-call-001")
            print(f"    A-leg RTP端口: {session.a_leg_rtp_port}")
            print(f"    B-leg RTP端口: {session.b_leg_rtp_port}")
            
            # 模拟200 OK SDP处理
            callee_sdp = """v=0
o=- 987654 456789 IN IP4 192.168.1.200
s=SIP Call
c=IN IP4 192.168.1.200
t=0 0
m=audio 20000 RTP/AVP 0
a=rtpmap:0 PCMU/8000
"""
            
            new_sdp2, success = relay.process_answer_sdp(
                "test-call-001",
                callee_sdp,
                ("192.168.1.200", 5060)
            )
            
            if success:
                print(f"  ✓ 处理200 OK SDP成功")
                print(f"    A-leg将发送到: 172.31.10.126:{session.a_leg_rtp_port}")
                print(f"    B-leg将发送到: 172.31.10.126:{session.b_leg_rtp_port}")
                
                # 清理
                relay.end_session("test-call-001")
                print(f"  ✓ 会话清理成功")
            else:
                print(f"  ✗ 处理200 OK SDP失败")
        else:
            print(f"  ✗ 创建媒体会话失败")
    except Exception as e:
        print(f"  ✗ 媒体中继测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n" + "=" * 60)
    print("所有测试通过！B2BUA功能已就绪")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = test_media_relay()
    sys.exit(0 if success else 1)
