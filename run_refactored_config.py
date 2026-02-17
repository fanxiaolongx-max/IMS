#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重构版本配置文件

用于配置RTPProxy和其他重构相关的设置
"""

import os

# ====== RTPProxy配置 ======

# RTPProxy TCP地址（默认127.0.0.1:7722）
RTPPROXY_TCP_HOST = os.getenv("RTPPROXY_TCP_HOST", "127.0.0.1")
RTPPROXY_TCP_PORT = int(os.getenv("RTPPROXY_TCP_PORT", "7722"))
RTPPROXY_TCP = (RTPPROXY_TCP_HOST, RTPPROXY_TCP_PORT)

# RTPProxy Unix Socket路径（如果使用Unix socket）
RTPPROXY_SOCKET_PATH = os.getenv("RTPPROXY_SOCKET_PATH", None)

# ====== 媒体中继配置 ======

# 是否启用媒体中继（使用RTPProxy）
ENABLE_MEDIA_RELAY = os.getenv("ENABLE_MEDIA_RELAY", "true").lower() == "true"

# 媒体中继模式
# "rtpproxy" - 使用RTPProxy（推荐）
# "custom" - 使用自定义媒体转发（已废弃）
MEDIA_RELAY_MODE = os.getenv("MEDIA_RELAY_MODE", "rtpproxy")

# ====== SIP信令配置 ======

# SIP信令处理模式
# "custom" - 使用自定义SIP处理（当前）
# "sippy" - 使用Sippy B2BUA（未来）
SIP_SIGNALING_MODE = os.getenv("SIP_SIGNALING_MODE", "custom")

# ====== 服务器配置 ======

# 服务器IP（从环境变量读取，如果没有则自动检测）
SERVER_IP = os.getenv("SERVER_IP", None)  # 如果为None，将在run.py中自动检测
SERVER_PORT = int(os.getenv("SERVER_PORT", "5060"))
UDP_BIND_IP = os.getenv("UDP_BIND_IP", "0.0.0.0")

# ====== 日志配置 ======

LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")
LOG_FILE = os.getenv("LOG_FILE", "logs/ims-sip-server.log")

# ====== 功能开关 ======

# 是否启用CDR记录
ENABLE_CDR = os.getenv("ENABLE_CDR", "true").lower() == "true"

# 是否启用用户管理
ENABLE_USER_MANAGEMENT = os.getenv("ENABLE_USER_MANAGEMENT", "true").lower() == "true"

# 是否启用MML管理界面
ENABLE_MML = os.getenv("ENABLE_MML", "true").lower() == "true"
MML_PORT = int(os.getenv("MML_PORT", "8888"))

# 是否启用外呼管理器
ENABLE_AUTODIALER = os.getenv("ENABLE_AUTODIALER", "true").lower() == "true"

# ====== 配置验证 ======

def validate_config():
    """验证配置"""
    errors = []
    
    if ENABLE_MEDIA_RELAY:
        if MEDIA_RELAY_MODE == "rtpproxy":
            if not RTPPROXY_SOCKET_PATH and not RTPPROXY_TCP:
                errors.append("RTPProxy配置缺失：必须指定socket_path或tcp_addr")
    
    if errors:
        raise ValueError("配置错误:\n" + "\n".join(f"  - {e}" for e in errors))
    
    return True

# ====== 配置信息打印 ======

def print_config():
    """打印配置信息"""
    print("=" * 60)
    print("重构版本配置")
    print("=" * 60)
    print(f"媒体中继模式: {MEDIA_RELAY_MODE}")
    if ENABLE_MEDIA_RELAY and MEDIA_RELAY_MODE == "rtpproxy":
        if RTPPROXY_SOCKET_PATH:
            print(f"RTPProxy Socket: {RTPPROXY_SOCKET_PATH}")
        else:
            print(f"RTPProxy TCP: {RTPPROXY_TCP[0]}:{RTPPROXY_TCP[1]}")
    print(f"SIP信令模式: {SIP_SIGNALING_MODE}")
    print(f"服务器地址: {SERVER_IP or '自动检测'}:{SERVER_PORT}")
    print(f"CDR记录: {'启用' if ENABLE_CDR else '禁用'}")
    print(f"用户管理: {'启用' if ENABLE_USER_MANAGEMENT else '禁用'}")
    print(f"MML界面: {'启用' if ENABLE_MML else '禁用'}")
    print("=" * 60)

if __name__ == "__main__":
    print_config()
    try:
        validate_config()
        print("✓ 配置验证通过")
    except ValueError as e:
        print(f"✗ 配置验证失败: {e}")
        exit(1)
