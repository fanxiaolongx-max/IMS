"""
MML (Man-Machine Language) 管理界面服务器

类似华为网管界面的 MML 命令行管理系统
- 左侧：命令树
- 中间：命令输入/输出
- 右侧：实时日志
"""

import asyncio
import json
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from typing import List, Set, Dict
import os
import sys
import queue
import logging
import re

# WebSocket 支持
try:
    import websockets
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    print("[WARNING] websockets not installed, real-time logs disabled")
    print("Install: pip install websockets")

# SIP 消息跟踪支持
try:
    from sipcore.sip_message_tracker import get_tracker
    SIP_TRACKER_AVAILABLE = True
except ImportError:
    SIP_TRACKER_AVAILABLE = False
    print("[WARNING] sip_message_tracker module not available")

# 导入认证模块
try:
    from web.web_auth import get_auth_manager, AuthManager
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    print("[WARNING] Auth module not available")


# 获取认证管理器
def get_auth():
    """获取认证管理器实例"""
    if AUTH_AVAILABLE:
        return get_auth_manager()
    return None


# 日志订阅器集合（用于实时推送日志）
log_subscribers = set()
# 日志消息队列（用于线程安全的日志传递）
log_queue = queue.Queue(maxsize=1000)


class MMLCommandTree:
    """MML 命令树定义"""
    
    @staticmethod
    def get_command_tree():
        """获取命令树结构"""
        return {
            "系统管理": {
                "icon": "⚙️",
                "commands": {
                    "查询系统状态": "DSP SYSINFO",
                    "查询系统配置": "DSP SYSCFG",
                    "修改日志级别": "SET LOGLEVEL",
                    "查询服务状态": "DSP SRVSTAT",
                    "重启服务": "RST SERVICE CONFIRM=YES"
                }
            },
            "用户管理": {
                "icon": "👤",
                "commands": {
                    "查询所有用户": "DSP USER ALL",
                    "查询指定用户": "DSP USER",
                    "添加用户": "ADD USER",
                    "删除用户": "RMV USER",
                    "修改用户": "MOD USER"
                }
            },
            "注册管理": {
                "icon": "📝",
                "commands": {
                    "查询注册列表": "DSP REG ALL",
                    "查询指定注册": "DSP REG SPECIFIC",
                    "查询注册统计": "DSP REG STAT",
                    "强制注销": "RMV REG SPECIFIC",
                    "清除所有注册": "CLR REG ALL CONFIRM=YES"
                }
            },
            "呼叫管理": {
                "icon": "📞",
                "commands": {
                    "查询活跃呼叫": "DSP CALL ACTIVE",
                    "查询呼叫统计": "DSP CALL STAT",
                    "查询指定呼叫": "DSP CALL",
                    "强制挂断": "RMV CALL",
                    "清除所有呼叫": "CLR CALL"
                }
            },
            "CDR 管理": {
                "icon": "📊",
                "commands": {
                    "查询今日 CDR": "DSP CDR TODAY",
                    "查询指定日期 CDR": "DSP CDR",
                    "查询 CDR 统计": "DSP CDR STAT",
                    "导出 CDR": "EXP CDR",
                    "清理旧 CDR": "CLR CDR"
                }
            },
            "配置管理": {
                "icon": "🔧",
                "commands": {
                    "查询所有配置": "DSP CFG",
                    "查询指定配置": "DSP CFG",
                    "修改日志级别": "SET CFG",
                    "导出配置": "EXP CFG"
                }
            },
            "性能监控": {
                "icon": "📈",
                "commands": {
                    "查询性能指标": "DSP PERF TYPE=ALL",
                    "查询 CPU 使用": "DSP PERF TYPE=CPU",
                    "查询内存使用": "DSP PERF TYPE=MEM",
                    "查询网络流量": "DSP PERF TYPE=NET",
                    "查询消息统计": "DSP PERF TYPE=MSG"
                }
            },
            "日志管理": {
                "icon": "📋",
                "commands": {
                    "查询日志配置": "DSP LOG CFG",
                    "修改日志级别": "SET LOG",
                    "查询最近日志": "DSP LOG RECENT LINES={n}",
                    "搜索日志": "DSP LOG SEARCH KEYWORD={keyword}",
                    "清理日志": "CLR LOG BEFORE={date} CONFIRM=YES"
                }
            },
            "外呼管理": {
                "icon": "📢",
                "commands": {
                    "查询外呼服务状态": "DSP DIALSVC",
                    "启动外呼服务": "STR DIALSVC",
                    "停止外呼服务": "STP DIALSVC",
                    "发起单次外呼": "STR CALL SINGLE",
                    "批量外呼": "STR CALL BATCH",
                    "查询外呼统计": "DSP CALL STAT",
                    "查询外呼配置": "DSP DIALSVC CFG"
                }
            },
            "安全管理": {
                "icon": "🛡️",
                "commands": {
                    "查询黑名单": "DSP BLACKLIST",
                    "添加黑名单": "ADD BLACKLIST IP=x.x.x.x",
                    "删除黑名单": "RMV BLACKLIST IP=x.x.x.x",
                    "查询攻击统计": "DSP ATTACK STAT"
                }
            },
            "帮助信息": {
                "icon": "❓",
                "commands": {
                    "显示所有命令": "HELP ALL",
                    "显示命令帮助": "HELP CMD={command}",
                    "显示参数说明": "HELP PARAM={parameter}",
                    "显示快捷键": "HELP HOTKEY"
                }
            }
        }


class MMLCommandExecutor:
    """MML 命令执行器"""
    
    def __init__(self, server_globals=None):
        self.server_globals = server_globals or {}
        self.command_handlers = {
            "DSP": self._handle_display,
            "ADD": self._handle_add,
            "RMV": self._handle_remove,
            "MOD": self._handle_modify,
            "SET": self._handle_set,
            "CLR": self._handle_clear,
            "RST": self._handle_reset,
            "STR": self._handle_start,
            "STP": self._handle_stop,
            "EXP": self._handle_export,
            "SAVE": self._handle_save,
            "HELP": self._handle_help,
        }
    
    def execute(self, command_line):
        """执行 MML 命令"""
        try:
            # 解析命令
            parts = command_line.strip().split()
            if not parts:
                return self._error_response("空命令")
            
            verb = parts[0].upper()
            
            if verb not in self.command_handlers:
                return self._error_response(f"未知命令: {verb}")
            
            # 执行命令
            handler = self.command_handlers[verb]
            result = handler(parts)
            
            return result
            
        except Exception as e:
            return self._error_response(f"命令执行错误: {str(e)}")
    
    def _parse_params(self, parts):
        """解析命令参数"""
        params = {}
        for part in parts:
            if '=' in part:
                key, value = part.split('=', 1)
                params[key.upper()] = value
        return params
    
    def _handle_display(self, parts):
        """处理 DSP (Display) 命令"""
        if len(parts) < 2:
            return self._error_response("DSP 命令需要指定对象")
        
        obj = parts[1].upper()
        
        # 特殊处理：DSP CALL STAT -> DSP CALL SUBTYPE=STAT
        if len(parts) > 2 and parts[2].upper() in ['STAT', 'ACTIVE']:
            parts = parts[:2] + [f"SUBTYPE={parts[2].upper()}"] + parts[3:]
        
        # 特殊处理：DSP REG STAT -> DSP REG SUBTYPE=STAT
        if len(parts) > 2 and obj == 'REG' and parts[2].upper() == 'STAT':
            parts = parts[:2] + [f"SUBTYPE=STAT"] + parts[3:]
        
        # 特殊处理：DSP CDR STAT -> DSP CDR SUBTYPE=STAT
        # 特殊处理：DSP CDR TODAY -> DSP CDR DATE=TODAY
        if obj == 'CDR' and len(parts) > 2:
            if parts[2].upper() == 'STAT':
                parts = parts[:2] + [f"SUBTYPE=STAT"] + parts[3:]
            elif parts[2].upper() == 'TODAY':
                parts = parts[:2] + [f"DATE=TODAY"] + parts[3:]
        
        # 特殊处理：DSP PERF ALL/CPU/MEM/NET/MSG -> DSP PERF TYPE=xxx
        if obj == 'PERF' and len(parts) > 2:
            perf_type = parts[2].upper()
            if perf_type in ['ALL', 'CPU', 'MEM', 'NET', 'MSG']:
                parts = parts[:2] + [f"TYPE={perf_type}"] + parts[3:]
        
        params = self._parse_params(parts[2:])
        
        # 获取服务器全局状态
        if not self.server_globals:
            return self._error_response("服务器状态不可用")
        
        if obj == "SYSINFO":
            return self._display_sysinfo(self.server_globals)
        elif obj == "SYSCFG":
            return self._display_syscfg(self.server_globals)
        elif obj == "USER":
            # 区分：DSP USER = 查询已开户用户，DSP REG = 查询已注册用户
            return self._display_users(params)
        elif obj == "REG":
            return self._display_registrations(self.server_globals, params)
        elif obj == "CALL":
            return self._display_calls(self.server_globals, params)
        elif obj == "CDR":
            return self._display_cdr(params)
        elif obj == "CFG":
            return self._display_config(self.server_globals, params)
        elif obj == "PERF":
            return self._display_performance(self.server_globals, params)
        elif obj == "LOG":
            return self._display_logs(params)
        elif obj == "SRVSTAT":
            return self._display_service_status(self.server_globals)
        elif obj == "DIALSVC":
            # 特殊处理：DSP DIALSVC CFG -> DSP DIALSVC SUBTYPE=CFG
            if len(parts) > 2 and parts[2].upper() == 'CFG':
                parts = parts[:2] + [f"SUBTYPE=CFG"] + parts[3:]
            params = self._parse_params(parts[2:])
            return self._display_dialsvc(params)
        elif obj == "BLACKLIST":
            return self._display_blacklist(params)
        elif obj == "ATTACK":
            return self._display_attack_stat(params)
        else:
            return self._error_response(f"未知对象: {obj}")
    
    def _display_sysinfo(self, srv):
        """显示系统信息"""
        import platform
        from datetime import datetime
        
        output = [
            "=" * 60,
            "系统信息",
            "=" * 60,
            f"服务器名称    : IMS SIP Server",
            f"版本          : 2.0.0",
            f"操作系统      : {platform.system()} {platform.release()}",
            f"Python 版本   : {platform.python_version()}",
            f"服务器 IP     : {srv.get('SERVER_IP', 'N/A')}",
            f"服务器端口    : {srv.get('SERVER_PORT', 'N/A')}",
        ]
        
        # 尝试获取系统信息（需要 psutil）
        try:
            import psutil
            uptime = time.time() - psutil.boot_time()
            output.append(f"系统运行时间  : {int(uptime/3600)}小时{int((uptime%3600)/60)}分钟")
            output.append(f"CPU 核心数    : {psutil.cpu_count()}")
            output.append(f"总内存        : {psutil.virtual_memory().total / (1024**3):.2f} GB")
        except ImportError:
            import os
            output.append(f"CPU 核心数    : {os.cpu_count() or 'N/A'}")
            output.append(f"总内存        : N/A (需要安装 psutil)")
        
        # B2BUA 媒体中继状态
        output.append("")
        output.append("-" * 60)
        output.append("B2BUA 媒体中继状态")
        output.append("-" * 60)
        
        from sipcore.media_relay import get_media_relay
        media_relay = get_media_relay()
        if media_relay:
            stats = media_relay.get_all_stats()
            output.append(f"模式          : B2BUA (媒体中继已启用)")
            output.append(f"总端口对      : {stats['port_stats']['total_pairs']}")
            output.append(f"已使用端口对  : {stats['port_stats']['used_pairs']}")
            output.append(f"可用端口对    : {stats['port_stats']['available_pairs']}")
            output.append(f"活跃会话数    : {stats['active_sessions']}")
            if stats['active_sessions'] > 0:
                output.append("")
                output.append("活跃会话详情:")
                for call_id, session_stats in stats['sessions'].items():
                    if session_stats:
                        output.append(f"  {call_id}:")
                        output.append(f"    A-leg端口: {session_stats['a_leg_port']}")
                        output.append(f"    B-leg端口: {session_stats['b_leg_port']}")
                        output.append(f"    A→B包数  : {session_stats['a_to_b_packets']}")
                        output.append(f"    B→A包数  : {session_stats['b_to_a_packets']}")
        else:
            output.append(f"模式          : Proxy (媒体中继未启用)")
        
        output.append("=" * 60)
        
        return self._success_response("\n".join(output))
    
    def _display_syscfg(self, srv):
        """显示系统配置"""
        output = [
            "=" * 60,
            "系统配置",
            "=" * 60,
            f"SERVER_IP              : {srv.get('SERVER_IP', 'N/A')}",
            f"SERVER_PORT            : {srv.get('SERVER_PORT', 'N/A')}",
            f"MAX_FORWARDS           : {srv.get('MAX_FORWARDS', 'N/A')}",
            f"REGISTRATION_EXPIRES   : {srv.get('REGISTRATION_EXPIRES', 'N/A')}",
            f"FORCE_LOCAL_ADDR       : {srv.get('FORCE_LOCAL_ADDR', 'N/A')}",
            "=" * 60,
        ]
        
        return self._success_response("\n".join(output))
    
    def _display_users(self, params):
        """显示已开户用户信息（不是注册用户）"""
        from sipcore.user_manager import get_user_manager
        
        user_mgr = get_user_manager()
        username = params.get('USERNAME', '').upper()
        status = params.get('STATUS', '').upper()
        
        if username:
            # 查询单个用户
            user = user_mgr.get_user(username)
            if not user:
                return self._error_response(f"用户 {username} 不存在")
            
            output = [
                "=" * 60,
                "用户详细信息",
                "=" * 60,
                f"用户名        : {user.get('username', 'N/A')}",
                f"显示名称      : {user.get('display_name', 'N/A')}",
                f"电话号码      : {user.get('phone', 'N/A')}",
                f"邮箱          : {user.get('email', 'N/A')}",
                f"状态          : {user.get('status', 'N/A')}",
                f"服务类型      : {user.get('service_type', 'N/A')}",
                f"创建时间      : {user.get('create_time', 'N/A')}",
                f"更新时间      : {user.get('update_time', 'N/A')}",
                "=" * 60,
            ]
        else:
            # 查询所有用户
            filter_status = status if status in ['ACTIVE', 'INACTIVE', 'SUSPENDED'] else None
            users = user_mgr.get_all_users(status=filter_status)
            
            output = [
                "=" * 100,
                "已开户用户列表",
                "=" * 100,
                f"{'用户名':<15} {'显示名称':<20} {'电话':<15} {'邮箱':<25} {'状态':<10} {'服务类型':<10}",
                "-" * 100,
            ]
            
            for user in users:
                username = user.get('username', 'N/A')
                display_name = user.get('display_name', 'N/A')
                phone = user.get('phone', 'N/A')
                email = user.get('email', 'N/A')
                status = user.get('status', 'N/A')
                service_type = user.get('service_type', 'N/A')
                
                output.append(f"{username:<15} {display_name:<20} {phone:<15} {email:<25} {status:<10} {service_type:<10}")
            
            output.append("-" * 100)
            output.append(f"总计: {len(users)} 个用户")
            output.append("=" * 100)
        
        return self._success_response("\n".join(output))
    
    def _display_registrations(self, srv, params):
        """显示注册信息"""
        subtype = params.get('SUBTYPE', 'ALL').upper()
        uri = params.get('URI', '').strip()
        registrations = srv.get('REGISTRATIONS', {})
        
        if subtype == 'STAT':
            # 注册统计
            total_users = len(registrations)
            total_bindings = sum(len(v) for v in registrations.values())
            
            output = [
                "=" * 60,
                "注册统计",
                "=" * 60,
                f"注册用户数     : {total_users}",
                f"注册绑定数     : {total_bindings}",
                f"平均绑定数     : {total_bindings/total_users if total_users > 0 else 0:.2f}",
                "=" * 60,
            ]
        elif uri:
            # 查询指定用户的注册
            # 标准化 URI：如果只输入号码，转换为 sip:xxx@domain 格式
            if '@' not in uri and not uri.startswith('sip:'):
                # 尝试匹配包含该号码的任意 AOR
                matched_aors = [aor for aor in registrations.keys() if uri in aor]
            else:
                # 精确匹配
                matched_aors = [aor for aor in registrations.keys() if aor == uri or aor == f"sip:{uri}"]
            
            if not matched_aors:
                return self._error_response(f"未找到 URI '{uri}' 的注册信息")
            
            output = [
                "=" * 80,
                f"注册详情 - {uri}",
                "=" * 80,
            ]
            
            count = 0
            for aor in matched_aors:
                bindings = registrations.get(aor, [])
                output.append(f"\nAOR: {aor}")
                output.append("-" * 80)
                output.append(f"{'Contact':<50} {'Expires':<10} {'剩余时间':<10}")
                output.append("-" * 80)
                
                for binding in bindings:
                    count += 1
                    contact = binding.get('contact', 'N/A')
                    expires = binding.get('expires', 0)
                    import time
                    remaining = max(0, expires - int(time.time()))
                    remaining_str = f"{remaining}s" if remaining > 0 else "已过期"
                    output.append(f"{contact:<50} {expires:<10} {remaining_str:<10}")
            
            output.append("=" * 80)
            output.append(f"总计: {count} 条注册记录")
            output.append("=" * 80)
        else:
            # 注册列表
            output = [
                "=" * 80,
                "注册列表",
                "=" * 80,
                f"{'AOR':<40} {'Contact':<30} {'Expires':<10}",
                "-" * 80,
            ]
            
            count = 0
            for aor, bindings in registrations.items():
                for binding in bindings:
                    count += 1
                    contact = binding.get('contact', 'N/A')
                    expires = binding.get('expires', 0)
                    output.append(f"{aor:<40} {contact:<30} {expires:<10}")
            
            output.append("-" * 80)
            output.append(f"总计: {count} 条注册记录")
            output.append("=" * 80)
        
        return self._success_response("\n".join(output))
    
    def _display_calls(self, srv, params):
        """显示呼叫信息"""
        subtype = params.get('SUBTYPE', 'ACTIVE').upper()
        call_id_filter = params.get('CALLID', '').strip()
        dialogs = srv.get('DIALOGS', {})
        pending = srv.get('PENDING_REQUESTS', {})
        branches = srv.get('INVITE_BRANCHES', {})
        
        # 查询指定呼叫
        if call_id_filter:
            # 智能匹配：支持完整 Call-ID 或部分匹配
            matched_calls = []
            for call_id, dialog in dialogs.items():
                if call_id_filter.lower() in call_id.lower():
                    matched_calls.append((call_id, dialog))
            
            if not matched_calls:
                return self._error_response(f"未找到匹配的呼叫: {call_id_filter}")
            
            if len(matched_calls) > 1:
                # 找到多个匹配，要求用户提供更精确的 Call-ID
                output = [
                    "=" * 100,
                    f"找到 {len(matched_calls)} 个匹配的呼叫，请提供更精确的 Call-ID：",
                    "=" * 100,
                    f"{'Call-ID':<50} {'状态':<10}",
                    "-" * 100,
                ]
                for call_id, dialog in matched_calls:
                    output.append(f"{call_id:<50} {'ACTIVE':<10}")
                output.append("=" * 100)
                return self._error_response("\n".join(output))
            
            # 找到唯一匹配的呼叫，显示详细信息
            call_id, dialog = matched_calls[0]
            caller_addr, callee_addr = dialog
            
            # 从 CDR 获取更多信息（如果有）
            try:
                from sipcore.cdr import get_cdr
                cdr = get_cdr()
                session = cdr.get_session(call_id) if cdr else None
            except:
                session = None
            
            output = [
                "=" * 100,
                "呼叫详情",
                "=" * 100,
                f"Call-ID          : {call_id}",
                f"状态             : ACTIVE",
                "",
                "【Dialog 信息】",
                f"  Caller 地址    : {caller_addr[0]}:{caller_addr[1]}",
                f"  Callee 地址    : {callee_addr[0]}:{callee_addr[1]}",
            ]
            
            if session:
                output.extend([
                    "",
                    "【CDR 信息】",
                    f"  Caller URI     : {session.get('caller_uri', 'N/A')}",
                    f"  Callee URI     : {session.get('callee_uri', 'N/A')}",
                    f"  呼叫状态       : {session.get('call_state', 'N/A')}",
                    f"  呼叫类型       : {session.get('call_type', 'N/A')}",
                    f"  编解码         : {session.get('codec', 'N/A')}",
                    f"  开始时间       : {session.get('start_time', 'N/A')}",
                    f"  建立时长       : {session.get('setup_time', 'N/A')}",
                ])
                if 'answer_time' in session:
                    output.append(f"  接听时间       : {session.get('answer_time', 'N/A')}")
            
            output.append("=" * 100)
            return self._success_response("\n".join(output))
        
        # 呼叫统计
        if subtype == 'STAT':
            output = [
                "=" * 60,
                "呼叫统计",
                "=" * 60,
                f"活跃呼叫数     : {len(dialogs)}",
                f"待处理请求数   : {len(pending)}",
                f"INVITE分支数   : {len(branches)}",
                "=" * 60,
            ]
        else:
            # 活跃呼叫列表
            output = [
                "=" * 100,
                "活跃呼叫列表",
                "=" * 100,
                f"{'Call-ID':<40} {'Caller':<25} {'Callee':<25} {'状态':<10}",
                "-" * 100,
            ]
            
            count = 0
            for call_id, dialog in dialogs.items():
                count += 1
                caller_addr, callee_addr = dialog
                # 简化显示
                call_id_short = call_id[:36] + "..." if len(call_id) > 36 else call_id
                caller_str = f"{caller_addr[0]}:{caller_addr[1]}"
                callee_str = f"{callee_addr[0]}:{callee_addr[1]}"
                output.append(f"{call_id_short:<40} {caller_str:<25} {callee_str:<25} {'ACTIVE':<10}")
            
            output.append("-" * 100)
            output.append(f"总计: {count} 个活跃呼叫")
            output.append("=" * 100)
        
        return self._success_response("\n".join(output))
    
    def _display_service_status(self, srv):
        """显示服务状态"""
        import os
        
        registrations = srv.get('REGISTRATIONS', {})
        dialogs = srv.get('DIALOGS', {})
        pending = srv.get('PENDING_REQUESTS', {})
        
        output = [
            "=" * 60,
            "服务状态",
            "=" * 60,
            f"进程 ID        : {os.getpid()}",
        ]
        
        # 尝试获取进程信息（需要 psutil）
        try:
            import psutil
            process = psutil.Process()
            output.append(f"CPU 使用率     : {process.cpu_percent()}%")
            output.append(f"内存使用       : {process.memory_info().rss / (1024**2):.2f} MB")
            output.append(f"线程数         : {process.num_threads()}")
        except ImportError:
            output.append(f"CPU 使用率     : N/A (需要安装 psutil)")
            output.append(f"内存使用       : N/A (需要安装 psutil)")
            output.append(f"线程数         : N/A (需要安装 psutil)")
        
        output.extend([
            f"活跃注册数     : {sum(len(v) for v in registrations.values())}",
            f"活跃呼叫数     : {len(dialogs)}",
            f"待处理请求     : {len(pending)}",
            "=" * 60,
        ])
        
        return self._success_response("\n".join(output))
    
    def _display_dialsvc(self, params):
        """显示外呼服务状态和配置"""
        subtype = params.get('SUBTYPE', '').upper()
        
        # 获取外呼管理器
        dialer_mgr = self.server_globals.get('AUTO_DIALER_MANAGER')
        if not dialer_mgr:
            return self._error_response("外呼管理器未初始化")
        
        if subtype == 'CFG':
            # 显示配置
            config = dialer_mgr.get_config()
            output = [
                "=" * 80,
                "外呼服务配置",
                "=" * 80,
                "",
                f"服务器 IP      : {config.get('server_ip', 'N/A')}",
                f"服务器端口     : {config.get('server_port', 'N/A')}",
                f"用户名         : {config.get('username', 'N/A')}",
                f"本地 IP        : {config.get('local_ip', 'N/A')}",
                f"本地端口       : {config.get('local_port', 'N/A')}",
                f"媒体目录       : {config.get('media_dir', 'N/A')}",
                f"默认媒体文件   : {config.get('media_file', 'N/A')}",
                "",
                "=" * 80,
            ]
        else:
            # 显示状态
            status = dialer_mgr.get_status()
            stats = status.get('stats', {})
            uptime = status.get('uptime', 0)
            
            # 格式化运行时间
            if uptime:
                hours = uptime // 3600
                minutes = (uptime % 3600) // 60
                seconds = uptime % 60
                uptime_str = f"{hours}小时{minutes}分钟{seconds}秒"
            else:
                uptime_str = "N/A"
            
            output = [
                "=" * 80,
                "外呼服务状态",
                "=" * 80,
                "",
                f"运行状态       : {'运行中' if status.get('running') else '已停止'}",
                f"注册状态       : {'已注册' if status.get('registered') else '未注册'}",
                f"启动时间       : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(status.get('start_time'))) if status.get('start_time') else 'N/A'}",
                f"运行时长       : {uptime_str}",
                "",
                "【统计信息】",
                "-" * 80,
                f"总呼叫数       : {stats.get('total_calls', 0)}",
                f"成功呼叫数     : {stats.get('successful_calls', 0)}",
                f"失败呼叫数     : {stats.get('failed_calls', 0)}",
                "",
                "=" * 80,
            ]
        
        return self._success_response("\n".join(output))
    
    def _start_dialsvc(self):
        """启动外呼服务"""
        # 获取外呼管理器
        dialer_mgr = self.server_globals.get('AUTO_DIALER_MANAGER')
        if not dialer_mgr:
            return self._error_response("外呼管理器未初始化")
        
        success, message = dialer_mgr.start()
        
        if success:
            return self._success_response(message)
        else:
            return self._error_response(message)
    
    def _stop_dialsvc(self):
        """停止外呼服务"""
        # 获取外呼管理器
        dialer_mgr = self.server_globals.get('AUTO_DIALER_MANAGER')
        if not dialer_mgr:
            return self._error_response("外呼管理器未初始化")
        
        success, message = dialer_mgr.stop()
        
        if success:
            return self._success_response(message)
        else:
            return self._error_response(message)
    
    def _start_call(self, params):
        """发起外呼（单次或批量）"""
        # 获取外呼管理器
        dialer_mgr = self.server_globals.get('AUTO_DIALER_MANAGER')
        if not dialer_mgr:
            return self._error_response("外呼管理器未初始化")
        
        # 检查是单次还是批量（通过 SUBTYPE 参数判断）
        subtype = params.get('SUBTYPE', '').upper()
        numbers = params.get('NUMBERS', '')
        
        if subtype == 'BATCH' or numbers:
            # 批量呼叫
            if not numbers:
                return self._error_response("批量外呼需要指定 NUMBERS 参数（用逗号分隔或范围，如 1006,1007 或 1000-1005）")
            
            # 解析号码列表（支持逗号分隔和范围）
            callees = self._parse_number_list(numbers)
            if not callees:
                return self._error_response("被叫号码列表为空")
            
            media_file = params.get('MEDIA_FILE', None)
            duration = float(params.get('DURATION', 0))
            
            success, message, results = dialer_mgr.dial_batch(callees, media_file, duration)
            
            if success:
                # 格式化结果（批量外呼现在是异步执行，立即返回）
                output = [
                    "=" * 80,
                    "批量外呼请求",
                    "=" * 80,
                    "",
                    message,
                    "",
                    "提示:",
                    "  批量外呼已在后台执行，不会阻塞 MML 界面",
                    "  可以通过 'DSP CALL STAT' 查看外呼统计信息",
                    "",
                    "=" * 80,
                ]
                
                return self._success_response("\n".join(output))
            else:
                return self._error_response(message)
        else:
            # 单次呼叫
            callee = params.get('CALLEE', '')
            if not callee:
                return self._error_response("单次外呼需要指定 CALLEE 参数")
            
            media_file = params.get('MEDIA_FILE', None)
            duration = float(params.get('DURATION', 0))
            
            success, message = dialer_mgr.dial(callee, media_file, duration)
            
            if success:
                return self._success_response(message)
            else:
                return self._error_response(message)
    
    def _display_cdr(self, params):
        """显示 CDR"""
        import os
        import csv
        from datetime import datetime
        
        subtype = params.get('SUBTYPE', '').upper()
        date = params.get('DATE', datetime.now().strftime('%Y-%m-%d'))
        if date == 'TODAY':
            date = datetime.now().strftime('%Y-%m-%d')
        
        record_type = params.get('TYPE', '').upper()  # CALL, REGISTER, MESSAGE 等
        limit = int(params.get('LIMIT', 50))
        
        cdr_file = f"CDR/{date}/cdr_{date}.csv"
        
        if not os.path.exists(cdr_file):
            return self._error_response(f"CDR 文件不存在: {cdr_file}")
        
        try:
            # 读取 CDR 数据
            records = []
            with open(cdr_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # 类型过滤
                    if record_type and row.get('record_type', '') != record_type:
                        continue
                    records.append(row)
            
            # 统计模式
            if subtype == 'STAT':
                return self._display_cdr_stat(records, date)
            
            # 列表模式
            output = [
                "=" * 150,
                f"CDR 记录 - {date}" + (f" (类型: {record_type})" if record_type else ""),
                "=" * 150,
            ]
            
            if not records:
                output.append("无记录")
                output.append("=" * 150)
                return self._success_response("\n".join(output))
            
            # 表格表头
            header = (
                f"{'序号':<6} {'类型':<12} {'状态':<12} {'时间':<10} "
                f"{'主叫':<18} {'被叫':<18} {'时长':<8} {'结果':<15}"
            )
            output.append(header)
            output.append("-" * 150)
            
            # 显示记录（限制数量）
            for idx, record in enumerate(records[:limit], 1):
                rec_type = record.get('record_type', 'N/A')
                call_state = record.get('call_state', 'N/A')
                start_time = record.get('start_time', 'N/A')
                caller = record.get('caller_uri', 'N/A')
                callee = record.get('callee_uri', 'N/A')
                duration = record.get('duration', '0')
                
                # 截取 URI 显示（去掉 sip: 前缀和域名）
                caller_display = self._format_uri(caller)
                callee_display = self._format_uri(callee)
                
                # 格式化时长
                duration_str = f"{duration}s" if duration and duration != 'N/A' else '-'
                
                # 结果/状态
                if rec_type == 'CALL':
                    if call_state == 'ANSWERED':
                        result = f"已接听 ({record.get('status_code', 'N/A')})"
                    elif call_state == 'FAILED':
                        result = f"失败 ({record.get('status_code', 'N/A')})"
                    elif call_state == 'CANCELLED':
                        result = "已取消"
                    else:
                        result = call_state
                elif rec_type == 'REGISTER':
                    result = f"{record.get('status_code', 'N/A')} {record.get('status_text', '')}"
                else:
                    result = call_state
                
                line = (
                    f"{idx:<6} {rec_type:<12} {call_state:<12} {start_time:<10} "
                    f"{caller_display:<18} {callee_display:<18} {duration_str:<8} {result:<15}"
                )
                output.append(line)
            
            output.append("-" * 150)
            
            # 统计信息
            total = len(records)
            if total > limit:
                output.append(f"显示: {limit}/{total} 条记录 (使用 LIMIT 参数查看更多)")
            else:
                output.append(f"总计: {total} 条记录")
            
            output.append("=" * 150)
            return self._success_response("\n".join(output))
            
        except Exception as e:
            import traceback
            return self._error_response(f"读取 CDR 失败: {str(e)}\n{traceback.format_exc()}")
    
    def _display_cdr_stat(self, records, date):
        """显示 CDR 统计信息"""
        output = [
            "=" * 80,
            f"CDR 统计 - {date}",
            "=" * 80,
        ]
        
        if not records:
            output.append("无记录")
            output.append("=" * 80)
            return self._success_response("\n".join(output))
        
        # 按类型统计
        type_stats = {}
        state_stats = {}
        total_duration = 0
        answered_calls = 0
        
        for record in records:
            rec_type = record.get('record_type', 'UNKNOWN')
            call_state = record.get('call_state', 'UNKNOWN')
            
            # 类型统计
            type_stats[rec_type] = type_stats.get(rec_type, 0) + 1
            
            # 状态统计
            state_stats[call_state] = state_stats.get(call_state, 0) + 1
            
            # 时长统计（只统计呼叫）
            if rec_type == 'CALL' and call_state == 'ANSWERED':
                try:
                    duration = int(record.get('duration', 0) or 0)
                    total_duration += duration
                    answered_calls += 1
                except:
                    pass
        
        # 输出统计
        output.append("\n【记录类型统计】")
        output.append("-" * 80)
        for rec_type, count in sorted(type_stats.items()):
            percentage = count / len(records) * 100
            output.append(f"  {rec_type:<20} : {count:>6} 条 ({percentage:>5.1f}%)")
        
        output.append("\n【呼叫状态统计】")
        output.append("-" * 80)
        for state, count in sorted(state_stats.items()):
            percentage = count / len(records) * 100
            output.append(f"  {state:<20} : {count:>6} 条 ({percentage:>5.1f}%)")
        
        # 呼叫时长统计
        if answered_calls > 0:
            avg_duration = total_duration / answered_calls
            output.append("\n【呼叫时长统计】")
            output.append("-" * 80)
            output.append(f"  接通呼叫数          : {answered_calls} 次")
            output.append(f"  总通话时长          : {total_duration} 秒 ({total_duration//60} 分钟)")
            output.append(f"  平均通话时长        : {avg_duration:.1f} 秒")
        
        output.append("\n【总体统计】")
        output.append("-" * 80)
        output.append(f"  总记录数            : {len(records)}")
        output.append("=" * 80)
        
        return self._success_response("\n".join(output))
    
    def _parse_number_list(self, numbers_str: str) -> List[str]:
        """
        解析号码列表，支持逗号分隔和范围
        
        示例:
            "1006,1007" -> ["1006", "1007"]
            "1000-1005" -> ["1000", "1001", "1002", "1003", "1004", "1005"]
            "1000,1001,1005-1008" -> ["1000", "1001", "1005", "1006", "1007", "1008"]
        """
        callees = []
        
        # 按逗号分割
        parts = [p.strip() for p in numbers_str.split(',') if p.strip()]
        
        for part in parts:
            # 检查是否是范围格式（如 1000-1005）
            if '-' in part:
                try:
                    range_parts = part.split('-', 1)
                    if len(range_parts) == 2:
                        start = int(range_parts[0].strip())
                        end = int(range_parts[1].strip())
                        
                        # 确保范围有效
                        if start > end:
                            start, end = end, start
                        
                        # 限制范围大小（防止过大范围导致性能问题）
                        if end - start > 1000:
                            continue  # 跳过过大的范围
                        
                        # 生成范围内的所有号码
                        for num in range(start, end + 1):
                            callees.append(str(num))
                    else:
                        # 无效的范围格式，作为单个号码处理
                        callees.append(part)
                except ValueError:
                    # 无法解析为数字范围，作为单个号码处理
                    callees.append(part)
            else:
                # 单个号码
                callees.append(part)
        
        # 去重并保持顺序
        seen = set()
        unique_callees = []
        for callee in callees:
            if callee not in seen:
                seen.add(callee)
                unique_callees.append(callee)
        
        return unique_callees
    
    def _format_uri(self, uri):
        """格式化 URI 显示（提取号码部分）"""
        if not uri or uri == 'N/A':
            return 'N/A'
        
        # 去掉 sip: 前缀
        if uri.startswith('sip:'):
            uri = uri[4:]
        
        # 提取 @ 之前的部分
        if '@' in uri:
            uri = uri.split('@')[0]
        
        return uri[:18]  # 限制长度
    
    def _get_config_registry(self):
        """
        获取配置注册表
        包含所有配置项的元数据：名称、当前值、说明、类型、是否可修改
        """
        import logging
        
        # 从 run.py 获取配置（通过 server_globals）
        srv = self.server_globals or {}
        
        registry = {
            # ===== SIP 核心配置（不可修改，影响核心服务） =====
            "SIP.SERVER_IP": {
                "value": srv.get("SERVER_IP", "N/A"),
                "description": "SIP 服务器 IP 地址",
                "type": "string",
                "editable": False,
                "category": "SIP 核心",
                "note": "修改需重启服务"
            },
            "SIP.SERVER_PORT": {
                "value": srv.get("SERVER_PORT", "N/A"),
                "description": "SIP 服务器端口",
                "type": "int",
                "editable": False,
                "category": "SIP 核心",
                "note": "修改需重启服务"
            },
            "SIP.SERVER_URI": {
                "value": srv.get("SERVER_URI", "N/A"),
                "description": "SIP 服务器 URI（用于 Record-Route）",
                "type": "string",
                "editable": False,
                "category": "SIP 核心",
                "note": "自动生成，不可修改"
            },
            "SIP.ALLOW": {
                "value": "INVITE, ACK, CANCEL, BYE, OPTIONS, REGISTER, ...",
                "description": "SIP 允许的方法列表",
                "type": "string",
                "editable": False,
                "category": "SIP 核心",
                "note": "固定值，不可修改"
            },
            "SIP.FORCE_LOCAL_ADDR": {
                "value": srv.get("FORCE_LOCAL_ADDR", False),
                "description": "强制使用本地地址（单机测试模式）",
                "type": "bool",
                "editable": False,
                "category": "SIP 核心",
                "note": "修改需重启服务"
            },
            
            # ===== 日志配置（可修改，不影响核心服务） =====
            "LOG.LEVEL": {
                "value": logging.getLevelName(logging.getLogger("ims-sip-server").level),
                "description": "日志级别",
                "type": "select",
                "options": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                "editable": True,
                "category": "日志",
                "note": "可通过 MML 动态修改"
            },
            "LOG.FILE": {
                "value": "logs/{date}/ims-sip-server.log",
                "description": "日志文件路径（按日期分文件夹）",
                "type": "string",
                "editable": False,
                "category": "日志",
                "note": "固定路径，不可修改"
            },
            "LOG.MAX_ENTRIES": {
                "value": "1000",
                "description": "MML 页面最大日志条数",
                "type": "int",
                "editable": False,
                "category": "日志",
                "note": "前端固定值"
            },
            
            # ===== CDR 配置（不可修改） =====
            "CDR.BASE_DIR": {
                "value": "CDR",
                "description": "CDR 数据存储目录",
                "type": "string",
                "editable": False,
                "category": "CDR",
                "note": "固定目录，不可修改"
            },
            "CDR.FILE_FORMAT": {
                "value": "CDR/{date}/cdr_{date}.csv",
                "description": "CDR 文件格式（按日期分文件夹）",
                "type": "string",
                "editable": False,
                "category": "CDR",
                "note": "固定格式，不可修改"
            },
            
            # ===== 用户管理配置（不可修改） =====
            "USER.DATA_FILE": {
                "value": "data/users.json",
                "description": "用户数据存储文件",
                "type": "string",
                "editable": False,
                "category": "用户管理",
                "note": "固定文件，不可修改"
            },
            
            # ===== MML 配置（可修改，不影响核心服务） =====
            "MML.HTTP_PORT": {
                "value": "8888",
                "description": "MML HTTP 服务端口",
                "type": "int",
                "editable": False,
                "category": "MML",
                "note": "修改需重启服务"
            },
            "MML.WEBSOCKET_PORT": {
                "value": "自动（HTTP端口+1）",
                "description": "MML WebSocket 端口（日志推送，自动设置为 HTTP 端口 + 1）",
                "type": "str",
                "editable": False,
                "category": "MML",
                "note": "自动配置，无需手动设置"
            },
            "MML.MAX_HISTORY": {
                "value": "100",
                "description": "MML 命令历史最大条数",
                "type": "int",
                "editable": False,
                "category": "MML",
                "note": "前端固定值"
            },
            
            # ===== 会话统计（只读） =====
            "SESSION.ACTIVE_CALLS": {
                "value": str(len(srv.get("DIALOGS", {}))),
                "description": "当前活跃呼叫数",
                "type": "int",
                "editable": False,
                "category": "会话统计",
                "note": "实时统计，只读"
            },
            "SESSION.REGISTRATIONS": {
                "value": str(len(srv.get("REGISTRATIONS", {}))),
                "description": "当前注册 AOR 数",
                "type": "int",
                "editable": False,
                "category": "会话统计",
                "note": "实时统计，只读"
            },
            "SESSION.PENDING_REQUESTS": {
                "value": str(len(srv.get("PENDING_REQUESTS", {}))),
                "description": "待处理请求数",
                "type": "int",
                "editable": False,
                "category": "会话统计",
                "note": "实时统计，只读"
            },
        }
        
        return registry
    
    def _display_config(self, srv, params):
        """显示配置"""
        registry = self._get_config_registry()
        
        # 支持按分类查询或查询所有
        category_filter = params.get('CATEGORY', '').upper()
        key_filter = params.get('KEY', '').upper()
        
        output = [
            "=" * 120,
            "系统配置一览",
            "=" * 120,
            "",
            "说明：本配置表包含系统所有配置项的元数据",
            "  • [可修改]：可通过 MML 命令动态修改",
            "  • [只读]：  不可修改，或需重启服务",
            "",
            "=" * 120,
        ]
        
        # 按分类组织输出
        categories = {}
        for key, meta in registry.items():
            cat = meta["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append((key, meta))
        
        # 输出每个分类
        for cat in sorted(categories.keys()):
            # 如果指定了分类过滤，跳过不匹配的分类
            if category_filter and category_filter not in cat.upper():
                continue
            
            output.append("")
            output.append(f"【{cat}】")
            output.append("-" * 120)
            
            for key, meta in categories[cat]:
                # 如果指定了键名过滤，跳过不匹配的
                if key_filter and key_filter not in key.upper():
                    continue
                
                editable_tag = "[可修改]" if meta["editable"] else "[只读]"
                output.append(f"\n  配置项: {key}")
                output.append(f"  当前值: {meta['value']}")
                output.append(f"  说明  : {meta['description']}")
                output.append(f"  类型  : {meta['type']}")
                output.append(f"  状态  : {editable_tag}")
                if meta.get('options'):
                    output.append(f"  可选值: {', '.join(meta['options'])}")
                if meta.get('note'):
                    output.append(f"  备注  : {meta['note']}")
        
        output.extend([
            "",
            "=" * 120,
            f"总配置项数: {len(registry)} 个",
            f"可修改项数: {sum(1 for m in registry.values() if m['editable'])} 个",
            "=" * 120,
        ])
        
        return self._success_response("\n".join(output))
    
    def _display_performance(self, srv, params):
        """显示性能指标"""
        perf_type = params.get('TYPE', 'ALL').upper()
        
        # 尝试导入 psutil
        try:
            import psutil
        except ImportError:
            return self._error_response(
                "性能监控功能不可用\n\n"
                "需要安装 psutil 库:\n"
                "  pip install psutil\n\n"
                "或者:\n"
                "  pip3 install psutil"
            )
        
        output = []
        
        # 显示所有性能指标
        if perf_type == 'ALL':
            output.extend(self._get_cpu_info())
            output.append("")
            output.extend(self._get_memory_info())
            output.append("")
            output.extend(self._get_network_info())
            output.append("")
            output.extend(self._get_message_stats(srv))
        
        # 显示 CPU 性能
        elif perf_type == 'CPU':
            output.extend(self._get_cpu_info())
        
        # 显示内存性能
        elif perf_type == 'MEM':
            output.extend(self._get_memory_info())
        
        # 显示网络流量
        elif perf_type == 'NET':
            output.extend(self._get_network_info())
        
        # 显示消息统计
        elif perf_type == 'MSG':
            output.extend(self._get_message_stats(srv))
        
        else:
            return self._error_response(f"不支持的性能监控类型: {perf_type}")
        
        return self._success_response("\n".join(output))
    
    def _get_cpu_info(self):
        """获取 CPU 性能信息"""
        import psutil
        import os
        
        cpu_percent = psutil.cpu_percent(interval=0.5)
        cpu_count = psutil.cpu_count()
        cpu_count_logical = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq()
        
        # CPU 每核心使用率
        per_cpu = psutil.cpu_percent(interval=0.5, percpu=True)
        
        output = [
            "=" * 80,
            "【CPU 性能指标】",
            "=" * 80,
            "",
            "【基本信息】",
            f"  物理核心数          : {cpu_count} 核",
            f"  逻辑核心数          : {cpu_count_logical} 核",
        ]
        
        if cpu_freq:
            output.extend([
                f"  当前频率            : {cpu_freq.current:.2f} MHz",
                f"  最小频率            : {cpu_freq.min:.2f} MHz",
                f"  最大频率            : {cpu_freq.max:.2f} MHz",
            ])
        
        output.extend([
            "",
            "【CPU 使用率】",
            f"  总体使用率          : {cpu_percent:.1f}%",
        ])
        
        # 显示每个核心的使用率
        if per_cpu:
            output.append("")
            output.append("【各核心使用率】")
            for i, percent in enumerate(per_cpu):
                bar_length = int(percent / 2)  # 50% = 25个字符
                bar = '█' * bar_length + '░' * (50 - bar_length)
                output.append(f"  CPU {i:2d}  [{bar}] {percent:5.1f}%")
        
        # 进程信息
        try:
            process = psutil.Process(os.getpid())
            output.extend([
                "",
                "【当前进程 (SIP服务器)】",
                f"  进程 ID             : {process.pid}",
                f"  CPU 使用率          : {process.cpu_percent():.1f}%",
                f"  线程数              : {process.num_threads()}",
                f"  运行时间            : {self._format_uptime(process.create_time())}",
            ])
        except:
            pass
        
        output.append("=" * 80)
        return output
    
    def _get_memory_info(self):
        """获取内存性能信息"""
        import psutil
        import os
        
        # 虚拟内存（物理内存）
        vm = psutil.virtual_memory()
        # 交换分区
        swap = psutil.swap_memory()
        
        output = [
            "=" * 80,
            "【内存性能指标】",
            "=" * 80,
            "",
            "【物理内存】",
            f"  总容量              : {self._format_bytes(vm.total)}",
            f"  已使用              : {self._format_bytes(vm.used)} ({vm.percent:.1f}%)",
            f"  可用                : {self._format_bytes(vm.available)}",
            f"  空闲                : {self._format_bytes(vm.free)}",
        ]
        
        # 内存使用进度条
        bar_length = int(vm.percent / 2)
        bar = '█' * bar_length + '░' * (50 - bar_length)
        output.append(f"  [{bar}] {vm.percent:.1f}%")
        
        output.extend([
            "",
            "【交换分区】",
            f"  总容量              : {self._format_bytes(swap.total)}",
            f"  已使用              : {self._format_bytes(swap.used)} ({swap.percent:.1f}%)",
            f"  空闲                : {self._format_bytes(swap.free)}",
        ])
        
        # 进程内存使用
        try:
            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()
            mem_percent = process.memory_percent()
            
            output.extend([
                "",
                "【当前进程 (SIP服务器)】",
                f"  物理内存            : {self._format_bytes(mem_info.rss)} ({mem_percent:.2f}%)",
                f"  虚拟内存            : {self._format_bytes(mem_info.vms)}",
            ])
        except:
            pass
        
        output.append("=" * 80)
        return output
    
    def _get_network_info(self):
        """获取网络流量信息"""
        import psutil
        
        # 网络 IO 统计
        net_io = psutil.net_io_counters()
        
        # 网络连接数
        try:
            connections = psutil.net_connections(kind='inet')
            conn_count = len(connections)
            
            # 按状态统计
            conn_stats = {}
            for conn in connections:
                status = conn.status
                conn_stats[status] = conn_stats.get(status, 0) + 1
        except:
            conn_count = 0
            conn_stats = {}
        
        output = [
            "=" * 80,
            "【网络性能指标】",
            "=" * 80,
            "",
            "【流量统计】",
            f"  发送字节数          : {self._format_bytes(net_io.bytes_sent)}",
            f"  接收字节数          : {self._format_bytes(net_io.bytes_recv)}",
            f"  发送数据包          : {net_io.packets_sent:,}",
            f"  接收数据包          : {net_io.packets_recv:,}",
            f"  发送错误            : {net_io.errout:,}",
            f"  接收错误            : {net_io.errin:,}",
            f"  发送丢包            : {net_io.dropout:,}",
            f"  接收丢包            : {net_io.dropin:,}",
            "",
            "【连接统计】",
            f"  总连接数            : {conn_count}",
        ]
        
        # 按状态显示连接数
        if conn_stats:
            output.append("")
            output.append("【连接状态分布】")
            for status, count in sorted(conn_stats.items()):
                output.append(f"  {status:<20}: {count:>6}")
        
        output.append("=" * 80)
        return output
    
    def _get_message_stats(self, srv):
        """获取消息统计信息"""
        dialogs = srv.get('DIALOGS', {})
        registrations = srv.get('REGISTRATIONS', {})
        pending = srv.get('PENDING_REQUESTS', {})
        branches = srv.get('INVITE_BRANCHES', {})
        
        # 统计注册数量
        total_bindings = sum(len(bindings) for bindings in registrations.values())
        
        output = [
            "=" * 80,
            "【SIP 消息统计】",
            "=" * 80,
            "",
            "【会话状态】",
            f"  活跃呼叫数          : {len(dialogs)}",
            f"  注册 AOR 数         : {len(registrations)}",
            f"  注册绑定数          : {total_bindings}",
            f"  待处理请求          : {len(pending)}",
            f"  INVITE 分支数       : {len(branches)}",
        ]
        
        # 从 CDR 获取消息统计（如果有）
        try:
            from sipcore.cdr import get_cdr
            cdr = get_cdr()
            if cdr and hasattr(cdr, 'active_sessions'):
                active_sessions = cdr.active_sessions
                output.extend([
                    "",
                    "【CDR 会话】",
                    f"  活跃 CDR 会话       : {len(active_sessions)}",
                ])
        except:
            pass
        
        output.append("=" * 80)
        return output
    
    def _format_bytes(self, bytes_val):
        """格式化字节数为易读格式"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_val < 1024.0:
                return f"{bytes_val:.2f} {unit}"
            bytes_val /= 1024.0
        return f"{bytes_val:.2f} PB"
    
    def _format_uptime(self, create_time):
        """格式化运行时间"""
        import time
        uptime_seconds = int(time.time() - create_time)
        days = uptime_seconds // 86400
        hours = (uptime_seconds % 86400) // 3600
        minutes = (uptime_seconds % 3600) // 60
        seconds = uptime_seconds % 60
        
        if days > 0:
            return f"{days}天 {hours}小时 {minutes}分钟"
        elif hours > 0:
            return f"{hours}小时 {minutes}分钟 {seconds}秒"
        elif minutes > 0:
            return f"{minutes}分钟 {seconds}秒"
        else:
            return f"{seconds}秒"
    
    def _display_logs(self, params):
        """显示日志"""
        import os
        from datetime import datetime
        
        lines = int(params.get('LINES', 20))
        date = params.get('DATE', datetime.now().strftime('%Y-%m-%d'))
        
        # 日志文件路径（按日期分文件夹）
        log_file = f"logs/{date}/ims-sip-server.log"
        
        # 如果指定日期的日志不存在，尝试读取旧版本的日志文件
        if not os.path.exists(log_file):
            log_file = "logs/ims-sip-server.log"
        
        if not os.path.exists(log_file):
            return self._error_response(f"日志文件不存在: {log_file}")
        
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                log_lines = f.readlines()
                recent = log_lines[-lines:]
                
                output = [
                    "=" * 120,
                    f"日志文件: {log_file}",
                    f"最近 {len(recent)} 条日志",
                    "",
                    "日志格式说明：",
                    "  时间戳(含毫秒)      级别        文件名:函数名:行号                    消息内容",
                    "  YYYY-MM-DD HH:MM:SS.mmm [LEVEL   ] [filename.py:function:line]  message",
                    "=" * 120,
                ]
                output.extend([line.rstrip() for line in recent])
                output.append("=" * 120)
                
                return self._success_response("\n".join(output))
        except Exception as e:
            return self._error_response(f"读取日志失败: {str(e)}")
    
    def _handle_set(self, parts):
        """处理 SET 命令"""
        if len(parts) < 2:
            return self._error_response("SET 命令需要指定对象")
        
        obj = parts[1].upper()
        params = self._parse_params(parts[2:])
        
        if obj == "CFG":
            return self._set_config(params)
        elif obj == "LOG" or obj == "LOGLEVEL":
            return self._set_log_level(params)
        else:
            return self._error_response(f"不支持的 SET 对象: {obj}")
    
    def _set_config(self, params):
        """
        设置配置
        目前只支持修改日志级别（不影响 SIP 核心服务）
        """
        key = params.get('KEY', 'LOG.LEVEL').upper()
        value = params.get('VALUE', '').upper()
        
        # 获取配置注册表
        registry = self._get_config_registry()
        
        # 检查配置项是否存在
        if key not in registry:
            return self._error_response(f"配置项不存在: {key}")
        
        # 检查配置项是否可修改
        if not registry[key]["editable"]:
            return self._error_response(
                f"配置项 {key} 不可修改\n"
                f"原因: {registry[key].get('note', '需要重启服务或修改代码')}"
            )
        
        # 目前只支持修改日志级别
        if key == "LOG.LEVEL":
            if not value:
                return self._error_response("需要指定 VALUE 参数")
            
            # 检查值是否有效
            valid_levels = registry[key].get("options", [])
            if value not in valid_levels:
                return self._error_response(
                    f"无效的日志级别: {value}\n"
                    f"有效值: {', '.join(valid_levels)}"
                )
            
            # 调用日志级别修改方法
            return self._set_log_level({"LEVEL": value})
        
        return self._error_response(f"配置项 {key} 暂不支持通过 MML 修改")
    
    def _set_log_level(self, params):
        """设置日志级别"""
        level = params.get('LEVEL', params.get('LOGLEVEL'))
        
        if not level:
            return self._error_response("需要指定 LEVEL")
        
        try:
            from config.config_manager import apply_config_change
            success, message = apply_config_change("LOG_LEVEL", level)
            
            if success:
                return self._success_response(f"日志级别已更新: {level}")
            else:
                return self._error_response(f"更新失败: {message}")
        except Exception as e:
            return self._error_response(f"设置日志级别失败: {str(e)}")
    
    def _handle_add(self, parts):
        """处理 ADD 命令"""
        if len(parts) < 2:
            return self._error_response("ADD 命令格式错误，需要指定对象")
        
        obj = parts[1].upper()
        params = self._parse_params(parts[2:])
        
        if obj == "USR" or obj == "USER":
            return self._add_user(params)
        elif obj == "BLACKLIST":
            return self._add_blacklist(params)
        else:
            return self._error_response(f"不支持的对象类型: {obj}")
    
    def _handle_remove(self, parts):
        """处理 RMV 命令"""
        if len(parts) < 2:
            return self._error_response("RMV 命令格式错误，需要指定对象")
        
        obj = parts[1].upper()
        params = self._parse_params(parts[2:])
        
        if obj == "USR" or obj == "USER":
            return self._remove_user(params)
        elif obj == "BLACKLIST":
            return self._remove_blacklist(params)
        elif obj == "REG":
            return self._remove_registration(params)
        elif obj == "CALL":
            return self._remove_call(params)
        else:
            return self._error_response(f"不支持的对象类型: {obj}")
    
    def _handle_modify(self, parts):
        """处理 MOD 命令"""
        if len(parts) < 2:
            return self._error_response("MOD 命令格式错误，需要指定对象")
        
        obj = parts[1].upper()
        params = self._parse_params(parts[2:])
        
        if obj == "USR" or obj == "USER":
            return self._modify_user(params)
        else:
            return self._error_response(f"不支持的对象类型: {obj}")
    
    def _add_user(self, params):
        """添加用户"""
        from sipcore.user_manager import get_user_manager
        
        username = params.get('USERNAME', '')
        password = params.get('PASSWORD', '')
        
        if not username:
            return self._error_response("缺少必需参数: USERNAME")
        if not password:
            return self._error_response("缺少必需参数: PASSWORD")
        
        user_mgr = get_user_manager()
        result = user_mgr.add_user(
            username=username,
            password=password,
            display_name=params.get('NAME', ''),
            phone=params.get('PHONE', ''),
            email=params.get('EMAIL', ''),
            service_type=params.get('SERVICE', 'BASIC')
        )
        
        if result['success']:
            user = result['user']
            output = [
                "=" * 60,
                "用户添加成功",
                "=" * 60,
                f"用户名        : {user.get('username')}",
                f"显示名称      : {user.get('display_name')}",
                f"电话号码      : {user.get('phone')}",
                f"邮箱          : {user.get('email')}",
                f"服务类型      : {user.get('service_type')}",
                f"状态          : {user.get('status')}",
                "=" * 60,
            ]
            return self._success_response("\n".join(output))
        else:
            return self._error_response(result['message'])
    
    def _remove_user(self, params):
        """删除用户"""
        from sipcore.user_manager import get_user_manager
        
        username = params.get('USERNAME', '')
        
        if not username:
            return self._error_response("缺少必需参数: USERNAME")
        
        user_mgr = get_user_manager()
        result = user_mgr.delete_user(username)
        
        if result['success']:
            return self._success_response(f"用户 {username} 删除成功")
        else:
            return self._error_response(result['message'])
    
    def _remove_registration(self, params):
        """强制注销指定用户"""
        uri = params.get('URI', '').strip()
        confirm = params.get('CONFIRM', '').upper()
        
        if not uri:
            return self._error_response("缺少必需参数: URI")
        
        if confirm != 'YES':
            return self._error_response("需要确认参数: CONFIRM=YES")
        
        registrations = self.server_globals.get('REGISTRATIONS', {})
        
        # 查找匹配的 AOR
        if '@' not in uri and not uri.startswith('sip:'):
            # 尝试匹配包含该号码的任意 AOR
            matched_aors = [aor for aor in registrations.keys() if uri in aor]
        else:
            # 精确匹配
            matched_aors = [aor for aor in registrations.keys() if aor == uri or aor == f"sip:{uri}"]
        
        if not matched_aors:
            return self._error_response(f"未找到 URI '{uri}' 的注册信息")
        
        # 删除所有匹配的注册
        removed_count = 0
        for aor in matched_aors:
            if aor in registrations:
                bindings_count = len(registrations[aor])
                del registrations[aor]
                removed_count += bindings_count
        
        return self._success_response(f"已强制注销 {len(matched_aors)} 个 AOR，共 {removed_count} 条注册记录")
    
    def _clear_registrations(self, params):
        """清除所有注册"""
        confirm = params.get('CONFIRM', '').upper()
        
        if confirm != 'YES':
            return self._error_response("需要确认参数: CONFIRM=YES")
        
        registrations = self.server_globals.get('REGISTRATIONS', {})
        
        # 统计注册数量
        total_aors = len(registrations)
        total_bindings = sum(len(bindings) for bindings in registrations.values())
        
        # 清空所有注册
        registrations.clear()
        
        return self._success_response(f"已清除所有注册：{total_aors} 个 AOR，共 {total_bindings} 条注册记录")
    
    def _remove_call(self, params):
        """强制挂断单个呼叫"""
        call_id_filter = params.get('CALLID', '').strip()
        confirm = params.get('CONFIRM', '').upper()
        
        if not call_id_filter:
            return self._error_response("需要指定 CALLID 参数")
        
        if confirm != 'YES':
            return self._error_response("需要确认参数: CONFIRM=YES")
        
        dialogs = self.server_globals.get('DIALOGS', {})
        
        # 智能匹配 Call-ID
        matched_calls = []
        for call_id in list(dialogs.keys()):
            if call_id_filter.lower() in call_id.lower():
                matched_calls.append(call_id)
        
        if not matched_calls:
            return self._error_response(f"未找到匹配的呼叫: {call_id_filter}")
        
        if len(matched_calls) > 1:
            # 找到多个匹配，要求用户提供更精确的 Call-ID
            output = [
                "=" * 100,
                f"找到 {len(matched_calls)} 个匹配的呼叫，请提供更精确的 Call-ID：",
                "=" * 100,
            ]
            for call_id in matched_calls:
                output.append(f"  {call_id}")
            output.append("=" * 100)
            return self._error_response("\n".join(output))
        
        # 找到唯一匹配的呼叫，执行强制挂断
        call_id = matched_calls[0]
        dialog = dialogs.get(call_id)
        
        # 从 DIALOGS 中移除（不发送 BYE，只是清理服务器状态）
        del dialogs[call_id]
        
        # 同时清理 CDR 会话（标记为强制终止）
        try:
            from sipcore.cdr import get_cdr
            cdr = get_cdr()
            if cdr:
                session = cdr.get_session(call_id)
                if session:
                    cdr.record_call_end(
                        call_id=call_id,
                        termination_reason="FORCED_TERMINATION_BY_MML"
                    )
        except Exception as e:
            # CDR 操作失败不影响主功能
            pass
        
        output = [
            "=" * 100,
            "强制挂断成功",
            "=" * 100,
            f"Call-ID          : {call_id}",
            f"操作             : 已从服务器 DIALOGS 中移除",
            f"备注             : 此操作不会发送 BYE 消息，仅清理服务器状态",
            "=" * 100,
        ]
        
        return self._success_response("\n".join(output))
    
    def _clear_calls(self, params):
        """清除所有呼叫"""
        confirm = params.get('CONFIRM', '').upper()
        
        if confirm != 'YES':
            return self._error_response("需要确认参数: CONFIRM=YES")
        
        dialogs = self.server_globals.get('DIALOGS', {})
        pending = self.server_globals.get('PENDING_REQUESTS', {})
        branches = self.server_globals.get('INVITE_BRANCHES', {})
        
        # 统计呼叫数量
        total_dialogs = len(dialogs)
        total_pending = len(pending)
        total_branches = len(branches)
        
        # 收集所有 Call-ID（用于 CDR 清理）
        all_call_ids = list(dialogs.keys())
        
        # 清空所有呼叫相关的数据结构
        dialogs.clear()
        pending.clear()
        branches.clear()
        
        # 清理所有活跃会话的 CDR（标记为强制终止）
        terminated_sessions = 0
        try:
            from sipcore.cdr import get_cdr
            cdr = get_cdr()
            if cdr:
                for call_id in all_call_ids:
                    session = cdr.get_session(call_id)
                    if session and session.get('call_state') not in ['ENDED', 'FAILED', 'CANCELLED']:
                        cdr.record_call_end(
                            call_id=call_id,
                            termination_reason="FORCED_TERMINATION_BY_MML_CLR_ALL"
                        )
                        terminated_sessions += 1
        except Exception as e:
            # CDR 操作失败不影响主功能
            pass
        
        output = [
            "=" * 100,
            "清除所有呼叫成功",
            "=" * 100,
            f"已清除 DIALOGS        : {total_dialogs} 个活跃呼叫",
            f"已清除 PENDING        : {total_pending} 个待处理请求",
            f"已清除 INVITE_BRANCHES: {total_branches} 个 INVITE 分支",
        ]
        
        if terminated_sessions > 0:
            output.append(f"已终止 CDR 会话       : {terminated_sessions} 个")
        
        output.extend([
            "",
            "备注: 此操作不会发送 BYE 消息，仅清理服务器状态",
            "=" * 100,
        ])
        
        return self._success_response("\n".join(output))
    
    def _export_cdr(self, params):
        """导出 CDR"""
        import os
        import shutil
        from datetime import datetime
        
        date = params.get('DATE', datetime.now().strftime('%Y-%m-%d'))
        if date == 'TODAY':
            date = datetime.now().strftime('%Y-%m-%d')
        
        record_type = params.get('TYPE', '').upper()
        format_type = params.get('FORMAT', 'CSV').upper()
        
        if format_type != 'CSV':
            return self._error_response("目前只支持 CSV 格式导出")
        
        cdr_file = f"CDR/{date}/cdr_{date}.csv"
        
        if not os.path.exists(cdr_file):
            return self._error_response(f"CDR 文件不存在: {cdr_file}")
        
        try:
            # 创建导出目录
            export_dir = "CDR/exports"
            os.makedirs(export_dir, exist_ok=True)
            
            # 导出文件名
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            export_filename = f"cdr_export_{date}_{timestamp}.csv"
            if record_type:
                export_filename = f"cdr_export_{date}_{record_type}_{timestamp}.csv"
            
            export_path = os.path.join(export_dir, export_filename)
            
            # 如果有类型过滤，需要过滤后导出
            if record_type:
                import csv
                with open(cdr_file, 'r', encoding='utf-8') as fin:
                    reader = csv.DictReader(fin)
                    fieldnames = reader.fieldnames
                    
                    with open(export_path, 'w', encoding='utf-8', newline='') as fout:
                        writer = csv.DictWriter(fout, fieldnames=fieldnames)
                        writer.writeheader()
                        
                        count = 0
                        for row in reader:
                            if row.get('record_type', '') == record_type:
                                writer.writerow(row)
                                count += 1
                
                return self._success_response(
                    f"CDR 导出成功\n"
                    f"文件路径: {export_path}\n"
                    f"记录数量: {count} 条 (类型: {record_type})"
                )
            else:
                # 直接复制整个文件
                shutil.copy2(cdr_file, export_path)
                
                # 统计行数
                with open(export_path, 'r', encoding='utf-8') as f:
                    line_count = sum(1 for _ in f) - 1  # 减去表头
                
                return self._success_response(
                    f"CDR 导出成功\n"
                    f"文件路径: {export_path}\n"
                    f"记录数量: {line_count} 条"
                )
        
        except Exception as e:
            import traceback
            return self._error_response(f"导出 CDR 失败: {str(e)}\n{traceback.format_exc()}")
    
    def _clear_cdr(self, params):
        """清理旧 CDR"""
        import os
        import shutil
        from datetime import datetime, timedelta
        
        before_date = params.get('BEFORE', '').strip()
        confirm = params.get('CONFIRM', '').upper()
        
        if not before_date:
            return self._error_response("缺少必需参数: BEFORE (格式: YYYY-MM-DD)")
        
        if confirm != 'YES':
            return self._error_response("需要确认参数: CONFIRM=YES")
        
        try:
            # 解析日期
            cutoff_date = datetime.strptime(before_date, '%Y-%m-%d')
        except ValueError:
            return self._error_response("日期格式错误，应为: YYYY-MM-DD")
        
        # 安全检查：不允许清理最近 7 天的数据
        min_date = datetime.now() - timedelta(days=7)
        if cutoff_date > min_date:
            return self._error_response(f"安全限制：不允许清理 {min_date.strftime('%Y-%m-%d')} 之后的数据")
        
        cdr_base_dir = "CDR"
        if not os.path.exists(cdr_base_dir):
            return self._error_response("CDR 目录不存在")
        
        try:
            deleted_dirs = []
            deleted_files = 0
            
            # 遍历 CDR 目录
            for dirname in os.listdir(cdr_base_dir):
                dir_path = os.path.join(cdr_base_dir, dirname)
                
                # 跳过非目录和 exports 目录
                if not os.path.isdir(dir_path) or dirname == 'exports':
                    continue
                
                # 尝试解析目录名为日期
                try:
                    dir_date = datetime.strptime(dirname, '%Y-%m-%d')
                    
                    # 如果早于截止日期，删除
                    if dir_date < cutoff_date:
                        # 统计文件数
                        file_count = len([f for f in os.listdir(dir_path) if os.path.isfile(os.path.join(dir_path, f))])
                        deleted_files += file_count
                        
                        # 删除目录
                        shutil.rmtree(dir_path)
                        deleted_dirs.append(dirname)
                except ValueError:
                    # 目录名不是日期格式，跳过
                    continue
            
            if deleted_dirs:
                return self._success_response(
                    f"已清理 CDR 数据\n"
                    f"删除目录数: {len(deleted_dirs)} 个\n"
                    f"删除文件数: {deleted_files} 个\n"
                    f"删除日期: {', '.join(sorted(deleted_dirs)[:10])}" + 
                    (f" ..." if len(deleted_dirs) > 10 else "")
                )
            else:
                return self._success_response(f"没有找到 {before_date} 之前的 CDR 数据")
        
        except Exception as e:
            import traceback
            return self._error_response(f"清理 CDR 失败: {str(e)}\n{traceback.format_exc()}")
    
    def _export_config(self, params):
        """导出配置到文件"""
        import os
        import json
        from datetime import datetime
        
        try:
            # 获取配置注册表
            registry = self._get_config_registry()
            
            # 创建导出目录
            export_dir = "config/exports"
            os.makedirs(export_dir, exist_ok=True)
            
            # 生成导出文件名（带时间戳）
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            export_file = os.path.join(export_dir, f"config_export_{timestamp}.json")
            
            # 准备导出数据
            export_data = {
                "export_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "export_by": "MML Interface",
                "config_version": "1.0",
                "categories": {}
            }
            
            # 按分类组织配置
            for key, meta in registry.items():
                cat = meta["category"]
                if cat not in export_data["categories"]:
                    export_data["categories"][cat] = []
                
                export_data["categories"][cat].append({
                    "key": key,
                    "value": str(meta["value"]),
                    "description": meta["description"],
                    "type": meta["type"],
                    "editable": meta["editable"],
                    "note": meta.get("note", "")
                })
            
            # 写入文件
            with open(export_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            # 统计信息
            total_count = len(registry)
            editable_count = sum(1 for m in registry.values() if m["editable"])
            
            output = [
                "=" * 80,
                "配置导出成功",
                "=" * 80,
                f"导出文件        : {export_file}",
                f"导出时间        : {export_data['export_time']}",
                f"总配置项数      : {total_count} 个",
                f"可修改配置项    : {editable_count} 个",
                f"配置分类数      : {len(export_data['categories'])} 类",
                "",
                "【导出文件格式】",
                "  • JSON 格式",
                "  • 包含所有配置项的完整元数据",
                "  • 按分类组织",
                "  • 可用于备份或文档生成",
                "=" * 80,
            ]
            
            return self._success_response("\n".join(output))
            
        except Exception as e:
            import traceback
            return self._error_response(f"导出配置失败: {str(e)}\n{traceback.format_exc()}")
    
    def _modify_user(self, params):
        """修改用户信息"""
        from sipcore.user_manager import get_user_manager
        
        username = params.get('USERNAME', '')
        
        if not username:
            return self._error_response("缺少必需参数: USERNAME")
        
        # 收集要修改的字段
        updates = {}
        if 'PASSWORD' in params:
            updates['password'] = params['PASSWORD']
        if 'NAME' in params:
            updates['display_name'] = params['NAME']
        if 'PHONE' in params:
            updates['phone'] = params['PHONE']
        if 'EMAIL' in params:
            updates['email'] = params['EMAIL']
        if 'SERVICE' in params:
            updates['service_type'] = params['SERVICE']
        if 'STATUS' in params:
            updates['status'] = params['STATUS']
        
        if not updates:
            return self._error_response("没有指定要修改的字段")
        
        user_mgr = get_user_manager()
        result = user_mgr.modify_user(username, **updates)
        
        if result['success']:
            user = result['user']
            output = [
                "=" * 60,
                "用户修改成功",
                "=" * 60,
                f"用户名        : {user.get('username')}",
                f"显示名称      : {user.get('display_name')}",
                f"电话号码      : {user.get('phone')}",
                f"邮箱          : {user.get('email')}",
                f"服务类型      : {user.get('service_type')}",
                f"状态          : {user.get('status')}",
                f"更新时间      : {user.get('update_time')}",
                "=" * 60,
            ]
            return self._success_response("\n".join(output))
        else:
            return self._error_response(result['message'])
    
    def _handle_clear(self, parts):
        """处理 CLR 命令"""
        if len(parts) < 2:
            return self._error_response("CLR 命令格式错误，需要指定对象")
        
        obj = parts[1].upper()
        params = self._parse_params(parts[2:])
        
        if obj == "REG":
            return self._clear_registrations(params)
        elif obj == "CALL":
            return self._clear_calls(params)
        elif obj == "CDR":
            return self._clear_cdr(params)
        else:
            return self._error_response(f"不支持的对象类型: {obj}")
    
    def _handle_reset(self, parts):
        """处理 RST 命令"""
        return self._error_response("RST 命令暂未实现")
    
    def _display_blacklist(self, params):
        """查询 IP 黑名单"""
        try:
            # 从 run.py 导入黑名单
            import sys
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from run import IP_BLACKLIST, ATTEMPT_COUNTER, SECURITY_CONFIG
            
            output = [
                "=" * 80,
                "IP 黑名单列表",
                "=" * 80,
            ]
            
            if IP_BLACKLIST:
                output.append(f"{'序号':<6} {'IP 地址':<20} {'类型':<15}")
                output.append("-" * 80)
                for idx, ip in enumerate(sorted(IP_BLACKLIST), 1):
                    output.append(f"{idx:<6} {ip:<20} {'手动/自动':<15}")
            else:
                output.append("黑名单为空")
            
            output.append("-" * 80)
            output.append(f"总计: {len(IP_BLACKLIST)} 个黑名单 IP")
            output.append("=" * 80)
            
            # 显示攻击统计
            output.append("")
            output.append("=" * 80)
            "攻击尝试统计（最近）",
            "=" * 80,
            
            if ATTEMPT_COUNTER:
                output.append(f"{'IP 地址':<20} {'失败次数':<12} {'剩余时间(秒)':<15}")
                output.append("-" * 80)
                import time
                now = time.time()
                for ip, (count, first_time) in sorted(ATTEMPT_COUNTER.items(), key=lambda x: -x[1][0])[:20]:
                    remaining = max(0, SECURITY_CONFIG["RATE_LIMIT_WINDOW"] - (now - first_time))
                    output.append(f"{ip:<20} {count:<12} {int(remaining):<15}")
            else:
                output.append("暂无攻击尝试记录")
            
            output.append("=" * 80)
            
            return self._success_response("\n".join(output))
        except Exception as e:
            import traceback
            return self._error_response(f"查询黑名单失败: {str(e)}\n{traceback.format_exc()}")
    
    def _display_attack_stat(self, params):
        """查询攻击统计"""
        return self._display_blacklist(params)  # 复用黑名单显示
    
    def _add_blacklist(self, params):
        """添加 IP 到黑名单"""
        ip = params.get('IP', '')
        if not ip:
            return self._error_response("需要指定 IP 参数，例如: ADD BLACKLIST IP=1.2.3.4")
        
        # 验证 IP 格式
        import re
        if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip):
            return self._error_response(f"无效的 IP 地址格式: {ip}")
        
        try:
            import sys
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from run import IP_BLACKLIST, _save_ip_blacklist
            
            if ip in IP_BLACKLIST:
                return self._error_response(f"IP {ip} 已在黑名单中")
            
            IP_BLACKLIST.add(ip)
            _save_ip_blacklist()
            
            output = [
                "=" * 60,
                "添加黑名单成功，已立即生效",
                "=" * 60,
                f"IP 地址        : {ip}",
                f"当前黑名单数量 : {len(IP_BLACKLIST)}",
                "=" * 60,
            ]
            return self._success_response("\n".join(output))
        except Exception as e:
            return self._error_response(f"添加黑名单失败: {str(e)}")
    
    def _remove_blacklist(self, params):
        """从黑名单移除 IP"""
        ip = params.get('IP', '')
        if not ip:
            return self._error_response("需要指定 IP 参数，例如: RMV BLACKLIST IP=1.2.3.4")
        
        try:
            import sys
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from run import IP_BLACKLIST, _save_ip_blacklist
            
            if ip not in IP_BLACKLIST:
                return self._error_response(f"IP {ip} 不在黑名单中")
            
            IP_BLACKLIST.discard(ip)
            _save_ip_blacklist()
            
            output = [
                "=" * 60,
                "删除黑名单成功，已立即生效",
                "=" * 60,
                f"IP 地址        : {ip}",
                f"当前黑名单数量 : {len(IP_BLACKLIST)}",
                "=" * 60,
            ]
            return self._success_response("\n".join(output))
        except Exception as e:
            return self._error_response(f"删除黑名单失败: {str(e)}")
    
    def _handle_start(self, parts):
        """处理 STR (Start) 命令"""
        if len(parts) < 2:
            return self._error_response("STR 命令需要指定对象")
        
        obj = parts[1].upper()
        
        # 特殊处理：STR CALL SINGLE -> STR CALL SUBTYPE=SINGLE
        # 特殊处理：STR CALL BATCH -> STR CALL SUBTYPE=BATCH
        if obj == "CALL" and len(parts) > 2:
            subtype = parts[2].upper()
            if subtype in ['SINGLE', 'BATCH']:
                parts = parts[:2] + [f"SUBTYPE={subtype}"] + parts[3:]
        
        params = self._parse_params(parts[2:])
        
        if obj == "DIALSVC":
            return self._start_dialsvc()
        elif obj == "CALL":
            return self._start_call(params)
        else:
            return self._error_response(f"不支持的对象类型: {obj}")
    
    def _handle_stop(self, parts):
        """处理 STP (Stop) 命令"""
        if len(parts) < 2:
            return self._error_response("STP 命令需要指定对象")
        
        obj = parts[1].upper()
        params = self._parse_params(parts[2:])
        
        if obj == "DIALSVC":
            return self._stop_dialsvc()
        else:
            return self._error_response(f"不支持的对象类型: {obj}")
    
    def _handle_export(self, parts):
        """处理 EXP 命令"""
        if len(parts) < 2:
            return self._error_response("EXP 命令格式错误，需要指定对象")
        
        obj = parts[1].upper()
        params = self._parse_params(parts[2:])
        
        if obj == "CDR":
            return self._export_cdr(params)
        elif obj == "CFG":
            return self._export_config(params)
        else:
            return self._error_response(f"不支持的对象类型: {obj}")
    
    def _handle_save(self, parts):
        """处理 SAVE 命令"""
        try:
            from config.config_manager import save_config, load_config
            config = load_config("config/config.json")
            save_config("config/config.json", config)
            return self._success_response("配置已保存")
        except Exception as e:
            return self._error_response(f"保存配置失败: {str(e)}")
    
    def _handle_help(self, parts):
        """处理 HELP 命令"""
        tree = MMLCommandTree.get_command_tree()
        
        output = [
            "=" * 80,
            "MML 命令帮助",
            "=" * 80,
            "",
            "命令格式:",
            "  VERB OBJECT [PARAM1=VALUE1] [PARAM2=VALUE2] ...",
            "",
            "支持的命令动词:",
            "  DSP  - 显示/查询",
            "  ADD  - 添加",
            "  RMV  - 删除",
            "  MOD  - 修改",
            "  SET  - 设置",
            "  CLR  - 清除",
            "  RST  - 重置",
            "  STR  - 启动",
            "  STP  - 停止",
            "  EXP  - 导出",
            "  SAVE - 保存",
            "",
            "示例:",
            "  DSP SYSINFO                    - 显示系统信息",
            "  DSP REG ALL                    - 显示所有注册",
            "  SET LOG LEVEL=DEBUG            - 设置日志级别为 DEBUG",
            "  DSP CDR DATE=TODAY TYPE=CALL   - 显示今日呼叫 CDR",
            "",
            "=" * 80,
        ]
        
        return self._success_response("\n".join(output))
    
    def _success_response(self, message):
        """成功响应"""
        return {
            "retcode": 0,
            "retmsg": "Success",
            "output": message,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    
    def _error_response(self, message):
        """错误响应"""
        return {
            "retcode": 1,
            "retmsg": message,
            "output": f"ERROR: {message}",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    
class MMLHTTPHandler(BaseHTTPRequestHandler):
    """MML HTTP 请求处理器"""
    
    executor = None  # 将在 init_mml_interface 中设置
    
    def log_message(self, format, *args):
        """禁用默认日志"""
        pass
    
    def _get_session_id(self):
        """从 cookie 中获取 session_id"""
        cookie_header = self.headers.get('Cookie', '')
        if not cookie_header:
            return None
        
        for cookie in cookie_header.split(';'):
            cookie = cookie.strip()
            if cookie.startswith('session_id='):
                return cookie[11:]  # len('session_id=') = 11
        return None
    
    def _set_session_cookie(self, session_id, max_age=3600):
        """设置 session cookie"""
        self.send_header('Set-Cookie', f'session_id={session_id}; HttpOnly; SameSite=Strict; Max-Age={max_age}; Path=/')
    
    def _clear_session_cookie(self):
        """清除 session cookie"""
        self.send_header('Set-Cookie', 'session_id=; HttpOnly; SameSite=Strict; Max-Age=0; Path=/')
    
    def _check_auth(self):
        """检查用户是否已认证"""
        if not AUTH_AVAILABLE:
            return True  # 认证模块不可用时不限制访问
        
        auth = get_auth()
        if auth is None:
            return True
        
        session_id = self._get_session_id()
        return auth.check_auth(session_id)
    
    def _require_auth(self):
        """要求认证，未认证时返回 401"""
        if not self._check_auth():
            self.send_response(302)
            self.send_header('Location', '/login.html')
            self.end_headers()
            return False
        return True
    
    def _send_json_response(self, data, status_code=200):
        """发送 JSON 响应"""
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        response = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.wfile.write(response)
    
    def do_GET(self):
        """处理 GET 请求"""
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == '/' or parsed_path.path == '/index.html':
            if self._require_auth():
                self._serve_index()
        elif parsed_path.path == '/login.html':
            self._serve_login()
        elif parsed_path.path == '/api/command_tree':
            if self._require_auth():
                self._serve_command_tree()
        elif parsed_path.path == '/api/check_auth':
            self._check_auth_status()
        elif parsed_path.path == '/api/logout':
            self._handle_logout()
        elif parsed_path.path == '/api/sip-messages':
            if self._require_auth():
                self._handle_sip_messages_api()
        elif parsed_path.path == '/api/media-endpoints':
            if self._require_auth():
                self._handle_media_endpoints_api()
        else:
            self.send_error(404)
    
    def do_POST(self):
        """处理 POST 请求"""
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == '/api/login':
            self._handle_login()
        elif parsed_path.path == '/api/execute':
            if self._require_auth():
                self._execute_command()
        else:
            self.send_error(404)
    
    def _serve_login(self):
        """提供登录页面"""
        html_file = os.path.join(os.path.dirname(__file__), 'login.html')
        
        try:
            with open(html_file, 'rb') as f:
                content = f.read()
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404, "Login page not found")
    
    def _handle_login(self):
        """处理登录请求"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            username = data.get('username', '').strip()
            password = data.get('password', '')
            
            if not username or not password:
                self._send_json_response({
                    'success': False,
                    'message': '用户名和密码不能为空'
                }, 400)
                return
            
            if not AUTH_AVAILABLE:
                # 认证模块不可用，允许任意登录（仅用于开发）
                self._send_json_response({
                    'success': True,
                    'message': '登录成功（无认证）'
                })
                return
            
            auth = get_auth()
            session_id = auth.login(username, password)
            
            if session_id:
                self.send_response(200)
                self._set_session_cookie(session_id)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                response = json.dumps({
                    'success': True,
                    'message': '登录成功'
                }, ensure_ascii=False).encode('utf-8')
                self.wfile.write(response)
            else:
                self._send_json_response({
                    'success': False,
                    'message': '用户名或密码错误'
                }, 401)
                
        except Exception as e:
            self._send_json_response({
                'success': False,
                'message': f'登录失败: {str(e)}'
            }, 500)
    
    def _handle_logout(self):
        """处理登出请求"""
        if AUTH_AVAILABLE:
            auth = get_auth()
            session_id = self._get_session_id()
            if session_id:
                auth.logout(session_id)
        
        self.send_response(302)
        self._clear_session_cookie()
        self.send_header('Location', '/login.html')
        self.end_headers()
    
    def _check_auth_status(self):
        """检查认证状态"""
        is_authenticated = self._check_auth()
        username = None
        
        if is_authenticated and AUTH_AVAILABLE:
            auth = get_auth()
            session_id = self._get_session_id()
            username = auth.get_current_user(session_id)
        
        self._send_json_response({
            'authenticated': is_authenticated,
            'username': username
        })
    
    def _serve_index(self):
        """提供主页面"""
        html_file = os.path.join(os.path.dirname(__file__), 'mml_interface.html')
        
        try:
            with open(html_file, 'rb') as f:
                content = f.read()
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404, "Interface file not found")
    
    def _serve_command_tree(self):
        """提供命令树"""
        tree = MMLCommandTree.get_command_tree()
        
        self.send_response(200)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        response = json.dumps(tree, ensure_ascii=False).encode('utf-8')
        self.wfile.write(response)
    
    def _execute_command(self):
        """执行命令"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            command = data.get('command', '').strip()
            
            if not command:
                result = {
                    "retcode": 1,
                    "retmsg": "空命令",
                    "output": "ERROR: 命令不能为空"
                }
            else:
                result = self.executor.execute(command)
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            response = json.dumps(result, ensure_ascii=False).encode('utf-8')
            self.wfile.write(response)
            
        except Exception as e:
            self.send_error(500, str(e))
    
    def _handle_media_endpoints_api(self):
        """媒体端点可视化 API：返回当前媒体转发器各会话的音视频 RTP/RTCP 端口及上下行包数、自动诊断"""
        try:
            # MMLHTTPHandler 通过 executor 获取 server_globals（BaseHTTPRequestHandler 无 server_globals 属性）
            server_globals = getattr(self.executor, 'server_globals', None) or {}
            media_relay = server_globals.get('MEDIA_RELAY')
            if not media_relay:
                try:
                    from sipcore.rtpproxy_media_relay import get_media_relay
                    media_relay = get_media_relay()
                except ImportError:
                    pass
                if not media_relay:
                    try:
                        from sipcore.media_relay import get_media_relay
                        media_relay = get_media_relay()
                    except ImportError:
                        pass
            if not media_relay:
                self._send_json_response({
                    'success': True,
                    'relay_type': 'none',
                    'server_ip': server_globals.get('SERVER_IP', 'N/A'),
                    'port_stats': {},
                    'sessions': [],
                    'diagnosis_summary': '媒体中继未启用',
                })
                return
            relay_type = 'rtpproxy' if 'rtpproxy' in type(media_relay).__name__.lower() else 'custom'
            server_ip = getattr(media_relay, 'server_ip', server_globals.get('SERVER_IP', 'N/A'))
            if hasattr(media_relay, 'get_all_stats'):
                all_stats = media_relay.get_all_stats()
                port_stats = all_stats.get('port_stats', {})
                sessions_raw = all_stats.get('sessions', {})
            else:
                port_stats = {}
                sessions_raw = {}
            sessions = []
            for call_id, st in sessions_raw.items():
                if not st:
                    continue
                # 统一格式：主被叫、音视频 RTP/RTCP、上下行包数、诊断
                # 音频端口信息
                audio_a = {
                    'rtp_port': st.get('a_leg_rtp_port'),
                    'rtcp_port': st.get('a_leg_rtcp_port'),
                }
                audio_b = {
                    'rtp_port': st.get('b_leg_rtp_port'),
                    'rtcp_port': st.get('b_leg_rtcp_port'),
                }
                # 视频端口信息
                video_a = {
                    'rtp_port': st.get('a_leg_video_rtp_port'),
                    'rtcp_port': st.get('a_leg_video_rtcp_port'),
                } if st.get('a_leg_video_rtp_port') else None
                video_b = {
                    'rtp_port': st.get('b_leg_video_rtp_port'),
                    'rtcp_port': st.get('b_leg_video_rtcp_port'),
                } if st.get('b_leg_video_rtp_port') else None
                # 详细统计信息（新格式）
                audio_stats = st.get('audio', {})
                video_stats = st.get('video')
                # 兼容旧格式
                uplink = st.get('a_to_b_packets', audio_stats.get('uplink', {}).get('rtp', 0))
                downlink = st.get('b_to_a_packets', audio_stats.get('downlink', {}).get('rtp', 0))
                sessions.append({
                    'call_id': call_id,
                    'caller': st.get('caller', 'N/A'),
                    'callee': st.get('callee', 'N/A'),
                    'audio': {
                        'a_leg': audio_a,
                        'b_leg': audio_b,
                        'stats': audio_stats,  # 包含 uplink/downlink 的 rtp/rtcp 统计
                    },
                    'video': {
                        'a_leg': video_a,
                        'b_leg': video_b,
                        'stats': video_stats,  # 包含 uplink/downlink 的 rtp/rtcp 统计
                    } if (video_a or video_b) else None,
                    'uplink_packets': uplink,  # 兼容旧格式
                    'downlink_packets': downlink,  # 兼容旧格式
                    'duration_sec': st.get('duration_sec') or (st.get('duration') if st.get('duration') is not None else None),
                    'diagnosis': st.get('diagnosis', ''),
                    'audio_drops': st.get('audio_drops'),  # { uplink, downlink } 发送缓冲满丢包
                    'video_drops': st.get('video_drops'),
                })
            # 整体诊断摘要
            active = len(sessions)
            if active == 0:
                diagnosis_summary = '当前无媒体会话'
            else:
                problems = [s['diagnosis'] for s in sessions if s.get('diagnosis') and '未' in s['diagnosis']]
                diagnosis_summary = f'活跃会话 {active} 个；' + ('存在异常: ' + '; '.join(problems[:3]) if problems else '暂无异常')
            self._send_json_response({
                'success': True,
                'relay_type': relay_type,
                'server_ip': server_ip,
                'port_stats': port_stats,
                'sessions': sessions,
                'diagnosis_summary': diagnosis_summary,
            })
        except Exception as e:
            import traceback
            traceback.print_exc(file=sys.stderr)
            self._send_json_response({
                'success': False,
                'message': str(e),
                'sessions': [],
                'diagnosis_summary': '获取媒体端点失败',
            }, 500)
    
    def _handle_sip_messages_api(self):
        """处理SIP消息跟踪API"""
        if not SIP_TRACKER_AVAILABLE:
            result = {
                "success": False,
                "message": "SIP message tracker not available"
            }
            self._send_json_response(result, 503)
            return
        
        try:
            parsed_path = urlparse(self.path)
            query_params = parse_qs(parsed_path.query)
            action = query_params.get('action', [''])[0]
            
            tracker = get_tracker()
            if not tracker:
                result = {
                    "success": False,
                    "message": "SIP tracker not initialized"
                }
                self._send_json_response(result, 503)
                return
            
            if action == 'list':
                # 获取消息列表（支持分页和过滤）
                limit = int(query_params.get('limit', ['1000'])[0])
                offset = int(query_params.get('offset', ['0'])[0])
                
                # 解析过滤条件
                filters = {}
                for key in ['method', 'direction', 'from_user', 'to_user', 'call_id', 'src_ip', 'dst_ip', 'registered_user', 'callee']:
                    if key in query_params:
                        filters[key] = query_params[key][0]
                
                records, total = tracker.get_records(limit=limit, offset=offset, filters=filters if filters else None)
                result = {
                    "success": True,
                    "records": records,
                    "total": total,
                    "limit": limit,
                    "offset": offset
                }
            elif action == 'get':
                # 根据ID获取单条消息
                msg_id = int(query_params.get('id', ['0'])[0])
                record = tracker.get_message_by_id(msg_id)
                if record:
                    result = {
                        "success": True,
                        "record": record
                    }
                else:
                    result = {
                        "success": False,
                        "message": "Message not found"
                    }
            elif action == 'stats':
                # 获取统计信息
                stats = tracker.get_stats()
                result = {
                    "success": True,
                    "stats": stats
                }
            elif action == 'clear':
                # 清空所有记录
                tracker.clear()
                result = {
                    "success": True,
                    "message": "All records cleared"
                }
            else:
                result = {
                    "success": False,
                    "message": f"Unknown action: {action}"
                }
            
            self._send_json_response(result)
            
        except Exception as e:
            print(f"[MML-ERROR] SIP消息API处理异常: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc()
            result = {
                "success": False,
                "message": f"SIP消息操作失败: {str(e)}"
            }
            self._send_json_response(result, 500)


def init_mml_interface(port=8888, server_globals=None):
    """初始化 MML 管理界面
    
    Args:
        port: HTTP 端口
        server_globals: 服务器全局变量字典，包含 REGISTRATIONS, DIALOGS 等
    """
    # 创建执行器并传递服务器状态
    MMLHTTPHandler.executor = MMLCommandExecutor(server_globals)
    
    # HTTP 服务器监听在指定端口，WebSocket 服务器监听在端口+1
    # 注意：Cloudflare 隧道只转发 HTTP 流量到 8888，WebSocket 服务器运行在 8889
    # WebSocket 无法通过 Cloudflare 隧道访问，只能在本机访问
    # TODO: 使用支持 WebSocket 升级的 HTTP 服务器（如 aiohttp）来同时处理 HTTP 和 WebSocket
    http_port = port
    ws_port = port + 1 if WEBSOCKET_AVAILABLE else None
    
    def run_server():
        try:
            server = HTTPServer(('0.0.0.0', http_port), MMLHTTPHandler)
            print(f"[MML] MML 管理界面已启动: http://0.0.0.0:{http_port}", flush=True)
            # 验证服务器已就绪
            import socket
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_sock.settimeout(1)
            result = test_sock.connect_ex(('127.0.0.1', http_port))
            test_sock.close()
            if result == 0:
                print(f"[MML] MML 服务已就绪，端口 {http_port} 可访问", flush=True)
            else:
                print(f"[MML] 警告: 端口 {http_port} 可能未就绪", flush=True)
            server.serve_forever()
        except Exception as e:
            print(f"[MML] ERROR: {e}", flush=True)
    
    # 在独立线程中运行 HTTP 服务器
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    
    # 启动 WebSocket 日志推送服务器（如果可用）
    # 隧道模式：WebSocket 服务器监听在 HTTP 端口（8888），Cloudflare 隧道会将 WebSocket 流量转发到这里
    # 正常模式：WebSocket 服务器监听在 HTTP 端口+1（8889）
    if WEBSOCKET_AVAILABLE:
        start_websocket_server(ws_port)
        
        # 添加日志处理器，将日志推送到队列
        class WebSocketLogHandler(logging.Handler):
            """将日志推送到队列，由 WebSocket 服务器消费"""
            def emit(self, record):
                try:
                    log_message = self.format(record)
                    # 移除 ANSI 颜色代码（如 [32m, [0m 等）
                    log_message = re.sub(r'\x1b\[[0-9;]*m', '', log_message)
                    # 放入队列，如果队列满了就丢弃旧消息
                    try:
                        log_queue.put_nowait(log_message)
                    except queue.Full:
                        # 队列满了，丢弃最老的消息
                        try:
                            log_queue.get_nowait()
                            log_queue.put_nowait(log_message)
                        except:
                            pass
                except:
                    pass
        
        # 添加到根日志器
        ws_handler = WebSocketLogHandler()
        ws_handler.setLevel(logging.DEBUG)
        
        # 使用增强的日志格式（业界最佳实践）
        # 导入 EnhancedFormatter
        try:
            from sipcore.logger import EnhancedFormatter
            log_format = '%(asctime)s [%(levelname)-8s] [%(filename)s:%(funcName)s:%(lineno)d] %(message)s'
            date_format = '%Y-%m-%d %H:%M:%S'
            ws_handler.setFormatter(EnhancedFormatter(log_format, date_format))
        except ImportError:
            # 降级到标准格式
            ws_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)-8s] %(message)s', '%Y-%m-%d %H:%M:%S'))
        
        logging.getLogger().addHandler(ws_handler)


# WebSocket 日志推送（可选）
if WEBSOCKET_AVAILABLE:
    # SIP消息跟踪订阅者
    sip_message_subscribers: Set = set()
    sip_message_callbacks: Dict = {}  # websocket -> callback映射
    # SIP消息队列（用于线程安全的异步发送）
    sip_message_queue: queue.Queue = queue.Queue(maxsize=1000)
    
    # 媒体流监听订阅者: call_id -> {stream_type -> [websocket1, websocket2, ...]}
    # stream_type: 'audio-a', 'audio-b', 'video-a', 'video-b'
    media_stream_subscribers: Dict[str, Dict[str, Set]] = {}
    # 注意：media_stream_callbacks 已废弃，现在使用独立媒体流通道，前台只读取通道，不注册监听器
    media_stream_callbacks: Dict = {}  # (call_id, stream_type) -> callback (已废弃，保留仅为兼容)
    media_stream_lock = threading.Lock()
    
    async def log_push_handler(websocket, path=None):
        """WebSocket 处理器（支持多路径）"""
        # 兼容不同版本的websockets库
        # websockets 16.0+: 通过websocket.request.path获取路径
        # websockets <16.0: 路径作为参数传入
        if path is None:
            try:
                # 尝试新版本API
                path = websocket.request.path
            except AttributeError:
                # 旧版本API，尝试从websocket对象获取
                try:
                    path = getattr(websocket, 'path', '/ws/logs')
                except:
                    # 如果都获取不到，使用默认路径
                    path = '/ws/logs'
        
        print(f"[MML-DEBUG] WebSocket连接请求: path={path}, remote={websocket.remote_address}", file=sys.stderr, flush=True)
        
        # 提取基础路径（去掉查询参数）
        base_path = path.split('?')[0] if path else '/ws/logs'
        
        if base_path == '/ws/logs':
            log_subscribers.add(websocket)
            print(f"[MML-DEBUG] WebSocket连接建立: /ws/logs, 订阅者数量: {len(log_subscribers)}", file=sys.stderr, flush=True)
            try:
                # 发送欢迎消息
                await websocket.send("[INFO] WebSocket日志连接已建立")
                # 保持连接
                await websocket.wait_closed()
                print(f"[MML-DEBUG] WebSocket连接已关闭: /ws/logs", file=sys.stderr, flush=True)
            except websockets.exceptions.ConnectionClosed:
                print(f"[MML-DEBUG] WebSocket连接正常关闭: /ws/logs", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[MML-ERROR] WebSocket日志处理异常: {e}", file=sys.stderr, flush=True)
                import traceback
                traceback.print_exc()
            finally:
                log_subscribers.discard(websocket)
                print(f"[MML-DEBUG] 已移除日志订阅者，剩余: {len(log_subscribers)}", file=sys.stderr, flush=True)
        elif base_path == '/ws/sip-messages':
            # SIP消息跟踪WebSocket
            sip_message_subscribers.add(websocket)
            callback_ref = None
            
            print(f"[MML-DEBUG] WebSocket连接建立: /ws/sip-messages, 订阅者数量: {len(sip_message_subscribers)}", file=sys.stderr, flush=True)
            
            try:
                # 发送欢迎消息（使用type字段标识，前端会过滤掉）
                welcome_msg = {"type": "connected", "message": "SIP消息跟踪WebSocket连接已建立"}
                await websocket.send(json.dumps(welcome_msg, ensure_ascii=False))
                print(f"[MML-DEBUG] 已发送欢迎消息", file=sys.stderr, flush=True)
                
                # 订阅SIP消息通知
                if SIP_TRACKER_AVAILABLE:
                    tracker = get_tracker()
                    if tracker:
                        print(f"[MML-DEBUG] 找到tracker实例，订阅SIP消息通知", file=sys.stderr, flush=True)
                        def sip_message_callback(message_record):
                            # 线程安全的回调：将消息放入队列
                            # 消息记录在独立线程中，没有事件循环，所以使用队列机制
                            try:
                                # 将消息和websocket引用放入队列
                                sip_message_queue.put_nowait((websocket, message_record))
                            except queue.Full:
                                # 队列满了，丢弃最老的消息
                                try:
                                    sip_message_queue.get_nowait()
                                    sip_message_queue.put_nowait((websocket, message_record))
                                except:
                                    pass
                            except Exception as e:
                                print(f"[MML-ERROR] 回调执行失败: {e}", file=sys.stderr, flush=True)
                        
                        callback_ref = sip_message_callback
                        sip_message_callbacks[websocket] = callback_ref
                        tracker.subscribe(callback_ref)
                        print(f"[MML-DEBUG] 已订阅SIP消息通知，订阅者数量: {len(tracker._subscribers)}", file=sys.stderr, flush=True)
                    else:
                        print(f"[MML-DEBUG] tracker实例不存在，可能未初始化", file=sys.stderr, flush=True)
                        await websocket.send(json.dumps({"type": "warning", "message": "SIP tracker未初始化"}, ensure_ascii=False))
                else:
                    print(f"[MML-DEBUG] SIP tracker功能不可用", file=sys.stderr, flush=True)
                    await websocket.send(json.dumps({"type": "error", "message": "SIP tracker功能不可用"}, ensure_ascii=False))
                
                # 保持连接
                await websocket.wait_closed()
                print(f"[MML-DEBUG] WebSocket连接已关闭: /ws/sip-messages", file=sys.stderr, flush=True)
            except websockets.exceptions.ConnectionClosed:
                print(f"[MML-DEBUG] WebSocket连接正常关闭: /ws/sip-messages", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[MML-ERROR] WebSocket处理异常: {e}", file=sys.stderr, flush=True)
                import traceback
                traceback.print_exc()
            finally:
                sip_message_subscribers.discard(websocket)
                # 取消订阅
                if SIP_TRACKER_AVAILABLE and callback_ref:
                    tracker = get_tracker()
                    if tracker:
                        tracker.unsubscribe(callback_ref)
                        print(f"[MML-DEBUG] 已取消订阅，订阅者数量: {len(tracker._subscribers)}", file=sys.stderr, flush=True)
                if websocket in sip_message_callbacks:
                    del sip_message_callbacks[websocket]
                print(f"[MML-DEBUG] 已移除SIP消息订阅者，剩余: {len(sip_message_subscribers)}", file=sys.stderr, flush=True)
        elif base_path == '/ws/media-stream':
            # 媒体流监听WebSocket
            # 从查询参数获取 call_id 和 stream_type
            try:
                # 从websocket对象获取URI（兼容不同websockets版本）
                uri_str = None
                try:
                    # websockets 16.0+: websocket.request.uri
                    if hasattr(websocket, 'request') and hasattr(websocket.request, 'uri'):
                        uri_str = websocket.request.uri
                except:
                    pass
                
                if not uri_str:
                    # 尝试从path中解析（如果path包含查询参数）
                    if '?' in path:
                        uri_str = path
                    else:
                        # 如果都没有，尝试从websocket对象获取
                        try:
                            uri_str = getattr(websocket, 'path', path)
                        except:
                            uri_str = path
                
                # 如果uri_str不包含查询参数，尝试从websocket对象获取
                if not uri_str or '?' not in uri_str:
                    try:
                        if hasattr(websocket, 'request') and hasattr(websocket.request, 'query_string'):
                            query_string = websocket.request.query_string
                            if query_string:
                                uri_str = (uri_str or '/ws/media-stream') + '?' + query_string.decode('utf-8')
                    except:
                        pass
                
                parsed_path = urlparse(uri_str if uri_str else '/')
                print(f"[MML-DEBUG] 解析URI: {uri_str}, parsed_path.query={parsed_path.query}", file=sys.stderr, flush=True)
                
                query_params = parse_qs(parsed_path.query)
                call_id = query_params.get('call_id', [''])[0]
                stream_type = query_params.get('stream_type', [''])[0]  # 'audio-a', 'audio-b', 'video-a', 'video-b'
                
                print(f"[MML-DEBUG] 媒体流监听参数: call_id={call_id}, stream_type={stream_type}", file=sys.stderr, flush=True)
                
                if not call_id or not stream_type:
                    error_msg = json.dumps({"type": "error", "message": f"缺少参数: call_id={call_id}, stream_type={stream_type}"}, ensure_ascii=False)
                    print(f"[MML-ERROR] {error_msg}", file=sys.stderr, flush=True)
                    await websocket.send(error_msg)
                    await websocket.close()
                    return
                
                print(f"[MML-DEBUG] 媒体流监听连接: call_id={call_id}, stream_type={stream_type}", file=sys.stderr, flush=True)
                
                # 注册订阅者
                with media_stream_lock:
                    if call_id not in media_stream_subscribers:
                        media_stream_subscribers[call_id] = {}
                    if stream_type not in media_stream_subscribers[call_id]:
                        media_stream_subscribers[call_id][stream_type] = set()
                    media_stream_subscribers[call_id][stream_type].add(websocket)
                
                # 获取媒体转发器并添加监听回调
                try:
                    from sipcore.media_relay import get_media_relay
                    media_relay = get_media_relay()
                    if media_relay:
                        # 根据stream_type找到对应的转发器
                        forwarder_key = None
                        if stream_type == 'audio-a':
                            forwarder_key = (call_id, 'a', 'rtp')
                        elif stream_type == 'audio-b':
                            forwarder_key = (call_id, 'b', 'rtp')
                        elif stream_type == 'video-a':
                            forwarder_key = (call_id, 'a', 'video-rtp')
                        elif stream_type == 'video-b':
                            forwarder_key = (call_id, 'b', 'video-rtp')
                        
                        if forwarder_key:
                            forwarder = media_relay._forwarders.get(forwarder_key)
                            print(f"[MML-DEBUG] 查找转发器: forwarder_key={forwarder_key}, 找到={forwarder is not None}", file=sys.stderr, flush=True)
                            if not forwarder:
                                # 列出所有转发器用于调试
                                all_forwarders = list(media_relay._forwarders.keys()) if hasattr(media_relay, '_forwarders') else []
                                matching_forwarders = [f for f in all_forwarders if f[0] == call_id]
                                print(f"[MML-DEBUG] 该call_id的所有转发器: {matching_forwarders}", file=sys.stderr, flush=True)
                                print(f"[MML-DEBUG] 所有转发器数量: {len(all_forwarders)}", file=sys.stderr, flush=True)
                            if forwarder:
                                # 获取会话的SDP信息以确定编解码
                                session = media_relay._sessions.get(call_id) if hasattr(media_relay, '_sessions') else None
                                codec_map = {}  # payload_type -> codec_name
                                if session:
                                    # 根据stream_type选择对应的SDP
                                    sdp_body = None
                                    if stream_type in ('audio-a', 'video-a') and session.a_leg_sdp:
                                        sdp_body = session.a_leg_sdp
                                    elif stream_type in ('audio-b', 'video-b') and session.b_leg_sdp:
                                        sdp_body = session.b_leg_sdp
                                    
                                    if sdp_body:
                                        from sipcore.media_relay import SDPProcessor
                                        media_info = SDPProcessor.extract_media_info(sdp_body)
                                        if media_info:
                                            # 按媒体类型取 codec，避免音频 pt 96 被视频 H265 覆盖
                                            if stream_type.startswith('audio') and media_info.get('audio_codec_info'):
                                                codec_map = media_info['audio_codec_info']
                                            elif stream_type.startswith('video') and media_info.get('video_codec_info'):
                                                codec_map = media_info['video_codec_info']
                                            elif media_info.get('codec_info'):
                                                codec_map = media_info['codec_info']
                                
                                # 同步回调函数（在转发器线程中执行）
                                # 从独立媒体流通道读取（后台自动复制，前台只读取，互不干扰，切换流畅）
                                stream_channel = media_relay.get_media_stream_channel(call_id, stream_type)
                                if not stream_channel:
                                    error_msg = f"媒体流通道不存在: {call_id}/{stream_type}"
                                    print(f"[MML-ERROR] {error_msg}", file=sys.stderr, flush=True)
                                    await websocket.send(json.dumps({"type": "error", "message": error_msg}, ensure_ascii=False))
                                    return
                                
                                print(f"[MML-DEBUG] 从独立媒体流通道读取: call_id={call_id}, stream_type={stream_type}", file=sys.stderr, flush=True)
                                
                                # 辅助函数：构建统计信息
                                static_payloads = {
                                    0: 'PCMU', 1: '1016', 2: 'G721', 3: 'GSM', 4: 'G723', 5: 'DVI4', 6: 'DVI4',
                                    7: 'LPC', 8: 'PCMA', 9: 'G722', 10: 'L16', 11: 'L16', 12: 'QCELP', 13: 'CN',
                                    14: 'MPA', 15: 'G728', 16: 'DVI4', 17: 'DVI4', 18: 'G729', 96: 'H264'
                                }
                                def build_stats_from_rtp(rtp_data, source_addr, local_port, timestamp):
                                    payload_type = (rtp_data[1] & 0x7F) if len(rtp_data) >= 12 else None
                                    rtp_payload = rtp_data[12:] if len(rtp_data) >= 12 else None
                                    payload_type_str = str(payload_type) if payload_type is not None else ''
                                    if payload_type_str in codec_map:
                                        codec_name = (codec_map[payload_type_str].split('/')[0]
                                            if '/' in codec_map[payload_type_str] else codec_map[payload_type_str])
                                    else:
                                        codec_name = static_payloads.get(payload_type, 'UNKNOWN') if payload_type is not None else 'UNKNOWN'
                                    rtp_ts = (int(rtp_data[4]) << 24 | int(rtp_data[5]) << 16 | int(rtp_data[6]) << 8 | int(rtp_data[7])) if len(rtp_data) >= 8 else None
                                    s = {
                                        "type": "rtp_packet", "call_id": call_id, "stream_type": stream_type,
                                        "packet_size": len(rtp_data), "payload_size": len(rtp_payload) if rtp_payload else 0,
                                        "payload_type": payload_type, "codec": codec_name,
                                        "source_addr": f"{source_addr[0]}:{source_addr[1]}",
                                        "local_port": local_port, "timestamp": timestamp,
                                        "rtp_timestamp": rtp_ts,
                                        "packets_received": forwarder.packets_received,
                                        "packets_sent": forwarder.packets_sent,
                                        "packets_dropped_send": getattr(forwarder, 'packets_dropped_send', 0),
                                        "total_bytes": forwarder.total_bytes, "rtp_payload_b64": None,
                                    }
                                    if rtp_payload and len(rtp_payload) <= 2000:
                                        import base64
                                        s["rtp_payload_b64"] = base64.b64encode(rtp_payload).decode('utf-8')
                                    return s
                                
                                # 不再向新连接推送历史缓冲，避免关闭后重开时“疯狂快速播放旧帧”；仅推送实时包，前端等下一个关键帧即可出图
                                # history_limit = 0 表示不发送历史，新连接只收实时
                                history_limit = 0
                                buffered = media_relay.get_channel_buffered_packets(call_id, stream_type, limit=history_limit)
                                if buffered:
                                    batch_size = 40
                                    for i in range(0, len(buffered), batch_size):
                                        chunk = buffered[i:i + batch_size]
                                        for rtp_data, source_addr, local_port, ts in chunk:
                                            try:
                                                st = build_stats_from_rtp(rtp_data, source_addr, local_port, ts)
                                                await websocket.send(json.dumps(st, ensure_ascii=False))
                                            except Exception:
                                                break
                                        if i + batch_size < len(buffered):
                                            await asyncio.sleep(0.02)
                                    print(f"[MML-DEBUG] 已发送历史包 {len(buffered)} 个: {call_id}/{stream_type}", file=sys.stderr, flush=True)
                                
                                # 发送欢迎消息
                                try:
                                    connected_msg = json.dumps({"type": "connected", "message": f"媒体流监听已启动: {call_id}/{stream_type}"}, ensure_ascii=False)
                                    await websocket.send(connected_msg)
                                    print(f"[MML-DEBUG] 已发送欢迎消息: call_id={call_id}, stream_type={stream_type}", file=sys.stderr, flush=True)
                                except websockets.exceptions.ConnectionClosed as e:
                                    print(f"[MML-DEBUG] WebSocket连接在发送欢迎消息前已关闭: call_id={call_id}, stream_type={stream_type}, code={e.code}, reason={e.reason}", file=sys.stderr, flush=True)
                                    return
                                except Exception as e:
                                    print(f"[MML-ERROR] 发送欢迎消息失败: call_id={call_id}, stream_type={stream_type}, error={e}", file=sys.stderr, flush=True)
                                    import traceback
                                    traceback.print_exc(file=sys.stderr)
                                    return
                                
                                # 持续从通道读取实时包（用 run_in_executor 避免阻塞事件循环，否则四路只有一路能跑）
                                loop = asyncio.get_event_loop()
                                def get_one():
                                    return stream_channel.get(timeout=1.0)
                                try:
                                    while True:
                                        try:
                                            rtp_data, source_addr, local_port, ts = await loop.run_in_executor(None, get_one)
                                            st = build_stats_from_rtp(rtp_data, source_addr, local_port, ts)
                                            await websocket.send(json.dumps(st, ensure_ascii=False))
                                        except queue.Empty:
                                            await websocket.send(json.dumps({"type": "heartbeat", "timestamp": time.time()}, ensure_ascii=False))
                                except websockets.exceptions.ConnectionClosed:
                                    print(f"[MML-DEBUG] WebSocket连接已关闭（正常）: call_id={call_id}, stream_type={stream_type}", file=sys.stderr, flush=True)
                                    pass
                            else:
                                # 转发器不存在，列出所有可用的转发器用于调试
                                available_forwarders = list(media_relay._forwarders.keys())[:20] if hasattr(media_relay, '_forwarders') else []
                                available_sessions = list(media_relay._sessions.keys())[:10] if hasattr(media_relay, '_sessions') else []
                                error_msg = f"转发器不存在: {forwarder_key}\n可用转发器: {available_forwarders}\n可用会话: {available_sessions}"
                                print(f"[MML-ERROR] {error_msg}", file=sys.stderr, flush=True)
                                try:
                                    await websocket.send(json.dumps({"type": "error", "message": error_msg}, ensure_ascii=False))
                                    # 等待一下让消息发送完成，然后保持连接让前端显示错误
                                    await asyncio.sleep(0.5)
                                except Exception as send_error:
                                    print(f"[MML-ERROR] 发送错误消息失败: {send_error}", file=sys.stderr, flush=True)
                                # 不立即关闭连接，让前端显示错误消息后再关闭
                                return
                        else:
                            error_msg = f"无效的stream_type: {stream_type}，支持的类型: audio-a, audio-b, video-a, video-b"
                            print(f"[MML-ERROR] {error_msg}", file=sys.stderr, flush=True)
                            try:
                                await websocket.send(json.dumps({"type": "error", "message": error_msg}, ensure_ascii=False))
                                await asyncio.sleep(0.5)
                            except Exception as send_error:
                                print(f"[MML-ERROR] 发送错误消息失败: {send_error}", file=sys.stderr, flush=True)
                            return
                    else:
                        error_msg = "媒体转发器未初始化"
                        print(f"[MML-ERROR] {error_msg}", file=sys.stderr, flush=True)
                        try:
                            await websocket.send(json.dumps({"type": "error", "message": error_msg}, ensure_ascii=False))
                            await asyncio.sleep(0.5)
                        except Exception as send_error:
                            print(f"[MML-ERROR] 发送错误消息失败: {send_error}", file=sys.stderr, flush=True)
                        return
                except Exception as e:
                    import traceback
                    error_msg = f"处理媒体流监听请求时发生异常: {str(e)}"
                    print(f"[MML-ERROR] {error_msg}", file=sys.stderr, flush=True)
                    traceback.print_exc(file=sys.stderr)
                    try:
                        await websocket.send(json.dumps({"type": "error", "message": error_msg}, ensure_ascii=False))
                        await asyncio.sleep(0.5)
                    except Exception as send_error:
                        print(f"[MML-ERROR] 发送错误消息失败: {send_error}", file=sys.stderr, flush=True)
                    return
                
                print(f"[MML-DEBUG] 媒体流监听连接已关闭: call_id={call_id}, stream_type={stream_type}", file=sys.stderr, flush=True)
            except Exception as e:
                import traceback
                traceback.print_exc(file=sys.stderr)
                print(f"[MML-ERROR] 媒体流监听处理异常: {e}", file=sys.stderr, flush=True)
            finally:
                # 清理订阅者和回调
                call_id_local = call_id if 'call_id' in locals() else None
                stream_type_local = stream_type if 'stream_type' in locals() else None
                
                if call_id_local and stream_type_local:
                    with media_stream_lock:
                        if call_id_local in media_stream_subscribers:
                            if stream_type_local in media_stream_subscribers[call_id_local]:
                                media_stream_subscribers[call_id_local][stream_type_local].discard(websocket)
                                if not media_stream_subscribers[call_id_local][stream_type_local]:
                                    del media_stream_subscribers[call_id_local][stream_type_local]
                            if not media_stream_subscribers[call_id_local]:
                                del media_stream_subscribers[call_id_local]
                    
                    # 注意：不再需要移除回调，因为现在使用独立媒体流通道，前台只读取通道，不注册监听器
        else:
            # 未知路径，关闭连接
            await websocket.close()
    
    async def _send_sip_message(websocket, message_record):
        """发送SIP消息到WebSocket"""
        try:
            if websocket in sip_message_subscribers:
                message_json = json.dumps(message_record, ensure_ascii=False)
                await websocket.send(message_json)
                # 对于 ACK FWD，总是打印日志（便于调试最后一条消息丢失问题）
                method = message_record.get('method') or message_record.get('status_code') or ''
                direction = message_record.get('direction', '')
                if method == 'ACK' and direction == 'FWD':
                    print(f"[MML-DEBUG] 发送ACK FWD到WebSocket: ID={message_record.get('id')}, Call-ID={message_record.get('call_id', '')[:20]}", file=sys.stderr, flush=True)
                # 减少日志输出频率（每100个消息打印一次）
                elif message_record.get('id', 0) % 100 == 0:
                    print(f"[MML-DEBUG] 发送SIP消息到WebSocket: {len(message_json)} bytes", file=sys.stderr, flush=True)
        except (websockets.exceptions.ConnectionClosed, websockets.exceptions.ConnectionClosedError, websockets.exceptions.ConnectionClosedOK):
            # WebSocket连接已关闭，这是正常的
            pass
        except Exception as e:
            print(f"[MML-ERROR] 发送SIP消息失败: {e}", file=sys.stderr, flush=True)
    
    async def broadcast_logs():
        """从队列中读取日志并广播给所有客户端"""
        while True:
            try:
                # 非阻塞地检查队列
                await asyncio.sleep(0.1)
                
                # 批量获取所有待发送的日志
                messages = []
                while not log_queue.empty() and len(messages) < 100:
                    try:
                        messages.append(log_queue.get_nowait())
                    except queue.Empty:
                        break
                
                # 广播给所有订阅者
                if messages and log_subscribers:
                    for ws in list(log_subscribers):
                        try:
                            for msg in messages:
                                await ws.send(msg)
                        except:
                            # 连接已断开，移除订阅者
                            log_subscribers.discard(ws)
            except Exception as e:
                print(f"[MML] 日志广播错误: {e}")
                await asyncio.sleep(1)
    
    async def broadcast_sip_messages():
        """从队列中读取SIP消息并发送给对应的WebSocket客户端"""
        while True:
            try:
                # 非阻塞地检查队列
                await asyncio.sleep(0.01)  # 更短的延迟，保证实时性
                
                # 批量获取消息（最多100个）
                messages_to_send = []
                while not sip_message_queue.empty() and len(messages_to_send) < 100:
                    try:
                        messages_to_send.append(sip_message_queue.get_nowait())
                    except queue.Empty:
                        break
                
                # 发送消息给对应的WebSocket
                for ws, message_record in messages_to_send:
                    try:
                        # 检查WebSocket是否还在订阅列表中
                        if ws in sip_message_subscribers:
                            await _send_sip_message(ws, message_record)
                        else:
                            # WebSocket已断开，跳过
                            pass
                    except (websockets.exceptions.ConnectionClosed, websockets.exceptions.ConnectionClosedError, websockets.exceptions.ConnectionClosedOK):
                        # 连接已关闭，移除订阅者
                        sip_message_subscribers.discard(ws)
                        if ws in sip_message_callbacks:
                            callback_ref = sip_message_callbacks[ws]
                            if SIP_TRACKER_AVAILABLE:
                                tracker = get_tracker()
                                if tracker:
                                    tracker.unsubscribe(callback_ref)
                            del sip_message_callbacks[ws]
                    except Exception as e:
                        print(f"[MML-ERROR] 发送SIP消息失败: {e}", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[MML-ERROR] SIP消息广播错误: {e}", file=sys.stderr, flush=True)
                await asyncio.sleep(0.1)
    
    def start_websocket_server(port=8889):
        """启动 WebSocket 服务器"""
        async def handler(websocket, path=None):
            """WebSocket处理器（兼容不同版本的websockets库）
            
            websockets 12.0: handler(websocket, path)
            websockets 16.0+: handler(websocket) 且 path = websocket.request.path
            """
            try:
                await log_push_handler(websocket, path)
            except Exception as e:
                print(f"[MML-ERROR] WebSocket handler异常: {e}", file=sys.stderr, flush=True)
                import traceback
                traceback.print_exc()
                try:
                    await websocket.close(code=1011, reason=str(e))
                except:
                    pass
        
        async def main():
            # websockets.serve 在不同版本中handler签名不同
            # 旧版本(12.0): handler(websocket, path) - path作为参数
            # 新版本(16.0+): handler(websocket) - path通过websocket.request.path获取
            # 使用兼容的方式：handler总是接收path参数，如果为None则从websocket.request获取
            async with websockets.serve(handler, "0.0.0.0", port):
                print(f"[MML] WebSocket 服务已启动: ws://0.0.0.0:{port}")
                print(f"[MML]   - 日志推送: ws://0.0.0.0:{port}/ws/logs")
                if SIP_TRACKER_AVAILABLE:
                    print(f"[MML]   - SIP消息跟踪: ws://0.0.0.0:{port}/ws/sip-messages")
                # 启动日志广播任务
                asyncio.create_task(broadcast_logs())
                # 启动SIP消息广播任务
                asyncio.create_task(broadcast_sip_messages())
                await asyncio.Future()  # 永久运行
        
        def run():
            asyncio.run(main())
        
        thread = threading.Thread(target=run, daemon=True)
        thread.start()


if __name__ == "__main__":
    # 测试
    init_mml_interface(8888)
    
    if WEBSOCKET_AVAILABLE:
        start_websocket_server(8889)
    
    print("Press Ctrl+C to stop")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")

