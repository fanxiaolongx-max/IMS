# sipcore/sdp_parser.py
"""
SDP (Session Description Protocol) 解析工具
RFC 4566 - SDP: Session Description Protocol

主要功能：
1. 解析 SDP 消息体
2. 提取媒体类型（audio/video）
3. 提取编解码信息（PCMU, PCMA, H264等）
"""

from typing import Dict, List, Set, Optional


def parse_sdp(sdp_body: bytes) -> Dict[str, any]:
    """
    解析 SDP 消息体
    
    Args:
        sdp_body: SDP 消息体（bytes）
        
    Returns:
        解析结果字典:
        {
            'media_types': ['audio', 'video'],  # 媒体类型列表
            'codecs': ['PCMU', 'PCMA', 'H264'], # 编解码列表
            'call_type': 'AUDIO+VIDEO',         # 呼叫类型
            'codec_str': 'PCMU, PCMA, H264'     # 编解码字符串
        }
    """
    if not sdp_body:
        return {
            'media_types': [],
            'codecs': [],
            'call_type': '',
            'codec_str': ''
        }
    
    try:
        # 解码 SDP
        sdp_text = sdp_body.decode('utf-8', errors='ignore')
        
        # 解析媒体类型和编解码
        media_types = set()  # 使用 set 避免重复
        codecs = []  # 保持顺序，可能有重复（audio 和 video 可能用不同编解码）
        codec_map = {}  # payload type -> codec name
        
        lines = sdp_text.split('\n')
        current_media = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # m=<media> <port> <proto> <fmt> ...
            # 例如: m=audio 49170 RTP/AVP 0 8 97
            if line.startswith('m='):
                parts = line[2:].split()
                if len(parts) >= 4:
                    media_type = parts[0]  # audio, video, etc.
                    media_types.add(media_type)
                    current_media = media_type
            
            # a=rtpmap:<payload type> <encoding name>/<clock rate>[/<encoding params>]
            # 例如: a=rtpmap:0 PCMU/8000
            #      a=rtpmap:8 PCMA/8000
            #      a=rtpmap:96 H264/90000
            elif line.startswith('a=rtpmap:'):
                rtpmap = line[9:]  # 去掉 "a=rtpmap:"
                parts = rtpmap.split()
                if len(parts) >= 2:
                    payload_type = parts[0]
                    codec_info = parts[1]  # 例如: PCMU/8000
                    codec_name = codec_info.split('/')[0]  # 提取编解码名称
                    codec_map[payload_type] = codec_name
                    
                    # 添加到编解码列表（按出现顺序，带媒体类型标记）
                    if current_media and codec_name not in [c['name'] for c in codecs if c.get('media') == current_media]:
                        codecs.append({
                            'name': codec_name,
                            'media': current_media,
                            'payload': payload_type
                        })
        
        # 静态 payload 类型（RFC 3551）
        # 即使没有 rtpmap，也能识别常见编解码
        STATIC_PAYLOAD_TYPES = {
            '0': 'PCMU',      # G.711 μ-law
            '3': 'GSM',       # GSM
            '4': 'G723',      # G.723
            '5': 'DVI4',      # DVI4 8kHz
            '6': 'DVI4',      # DVI4 16kHz
            '7': 'LPC',       # LPC
            '8': 'PCMA',      # G.711 A-law
            '9': 'G722',      # G.722
            '10': 'L16',      # L16 stereo
            '11': 'L16',      # L16 mono
            '12': 'QCELP',    # QCELP
            '13': 'CN',       # Comfort Noise
            '14': 'MPA',      # MPEG Audio
            '15': 'G728',     # G.728
            '16': 'DVI4',     # DVI4 11kHz
            '17': 'DVI4',     # DVI4 22kHz
            '18': 'G729',     # G.729
        }
        
        # 如果没有找到编解码但有媒体类型，尝试从 m= 行提取 payload types
        if not codecs and media_types:
            for line in lines:
                if line.startswith('m='):
                    parts = line[2:].split()
                    if len(parts) >= 4:
                        media_type = parts[0]
                        payload_types = parts[3:]  # 第4个及之后的都是 payload type
                        for pt in payload_types:
                            if pt in STATIC_PAYLOAD_TYPES:
                                codec_name = STATIC_PAYLOAD_TYPES[pt]
                                if codec_name not in [c['name'] for c in codecs if c.get('media') == media_type]:
                                    codecs.append({
                                        'name': codec_name,
                                        'media': media_type,
                                        'payload': pt
                                    })
        
        # 生成呼叫类型
        call_type = _generate_call_type(media_types)
        
        # 生成编解码字符串（去重）
        codec_names = []
        seen = set()
        for codec in codecs:
            name = codec['name']
            if name not in seen:
                codec_names.append(name)
                seen.add(name)
        codec_str = ', '.join(codec_names) if codec_names else ''
        
        return {
            'media_types': sorted(list(media_types)),
            'codecs': codec_names,
            'call_type': call_type,
            'codec_str': codec_str
        }
        
    except Exception as e:
        # 解析失败，返回空结果
        return {
            'media_types': [],
            'codecs': [],
            'call_type': '',
            'codec_str': ''
        }


def _generate_call_type(media_types: Set[str]) -> str:
    """
    根据媒体类型生成呼叫类型
    
    Args:
        media_types: 媒体类型集合
        
    Returns:
        呼叫类型字符串（AUDIO/VIDEO/AUDIO+VIDEO）
    """
    if not media_types:
        return ''
    
    has_audio = 'audio' in media_types
    has_video = 'video' in media_types
    
    if has_audio and has_video:
        return 'AUDIO+VIDEO'
    elif has_video:
        return 'VIDEO'
    elif has_audio:
        return 'AUDIO'
    else:
        # 其他媒体类型（如 application, text 等）
        return '+'.join(sorted([m.upper() for m in media_types]))


def extract_sdp_info(sdp_body: bytes) -> tuple[str, str]:
    """
    从 SDP 中提取呼叫类型和编解码信息（简化接口）
    
    Args:
        sdp_body: SDP 消息体（bytes）
        
    Returns:
        (call_type, codec_str) 元组
        例如: ('AUDIO', 'PCMU, PCMA') 或 ('AUDIO+VIDEO', 'PCMU, H264')
    """
    result = parse_sdp(sdp_body)
    return result['call_type'], result['codec_str']


def modify_sdp_ip_only(sdp_body: str, new_ip: str) -> str:
    """
    仅修改 SDP 中的 IP 地址（c= 行），端口保持不变。
    用于 passthrough 模式下将 NAT 后地址写入 SDP，让主被叫直接互通。
    
    Args:
        sdp_body: 原始 SDP
        new_ip: 新的 IP 地址（通常是信令地址，NAT 后的公网 IP）
    
    Returns:
        修改后的 SDP
    """
    if not sdp_body:
        return sdp_body
    
    lines = sdp_body.split('\r\n') if '\r\n' in sdp_body else sdp_body.split('\n')
    new_lines = []
    
    for line in lines:
        line_stripped = line.rstrip()
        if not line_stripped:
            new_lines.append(line)
            continue
        
        # 修改 c= 行（只改 IP 地址，保持其他部分不变）
        if line_stripped.startswith('c='):
            parts = line_stripped[2:].split()
            if len(parts) >= 3 and parts[1] == 'IP4':
                line_stripped = f"c=IN IP4 {new_ip}"
        
        new_lines.append(line_stripped)
    
    # 确保使用 \r\n 作为行分隔符 (SIP标准)
    return '\r\n'.join(new_lines) + ('\r\n' if not sdp_body.endswith('\r\n') else '')


# 测试代码（可选）
if __name__ == "__main__":
    # 测试用例 1：纯音频 SDP
    sdp_audio = b"""v=0
o=- 123456 654321 IN IP4 192.168.1.100
s=SIP Call
c=IN IP4 192.168.1.100
t=0 0
m=audio 49170 RTP/AVP 0 8 18
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=rtpmap:18 G729/8000
"""
    
    # 测试用例 2：音视频 SDP
    sdp_video = b"""v=0
o=- 123456 654321 IN IP4 192.168.1.100
s=SIP Call
c=IN IP4 192.168.1.100
t=0 0
m=audio 49170 RTP/AVP 0 8
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
m=video 51372 RTP/AVP 96
a=rtpmap:96 H264/90000
"""
    
    print("测试 1：纯音频")
    result1 = parse_sdp(sdp_audio)
    print(f"  媒体类型: {result1['media_types']}")
    print(f"  编解码: {result1['codecs']}")
    print(f"  呼叫类型: {result1['call_type']}")
    print(f"  编解码字符串: {result1['codec_str']}")
    
    print("\n测试 2：音视频")
    result2 = parse_sdp(sdp_video)
    print(f"  媒体类型: {result2['media_types']}")
    print(f"  编解码: {result2['codecs']}")
    print(f"  呼叫类型: {result2['call_type']}")
    print(f"  编解码字符串: {result2['codec_str']}")
    
    print("\n简化接口测试：")
    call_type, codec_str = extract_sdp_info(sdp_audio)
    print(f"  音频呼叫: {call_type}, 编解码: {codec_str}")
    
    call_type, codec_str = extract_sdp_info(sdp_video)
    print(f"  视频呼叫: {call_type}, 编解码: {codec_str}")

