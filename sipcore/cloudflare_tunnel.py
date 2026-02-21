"""
Cloudflare 临时隧道（cloudflared quick tunnel）集成

用于在无公网 IP 环境下将本地端口暴露到公网，便于公网用户注册与访问。
- 支持 TCP（如 SIP 5060）、HTTP（如 MML 8888）
- 注意：Quick Tunnel 不支持 UDP，RTP 媒体需服务器具备公网 UDP 或使用 TURN

依赖：已安装 cloudflared，且可执行在 PATH 中。
"""

import asyncio
import re
import shutil
import subprocess
import sys
import os
import signal
import platform
import tempfile
from typing import Optional, Tuple, List, Dict

# 隧道进程与输出解析
# cloudflared 输出示例（TCP）: "Your quick Tunnel has been created! Visit https://xxx-xxx-xxx.trycloudflare.com" 或含 port
# 也常见: "INF +--------------------------------------------------------------------------------------------+"
#         "INF |  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |"
#         "INF |  https://xxxx.trycloudflare.com                                                           |"
# TCP 时可能还有: "Connection to xxx.trycloudflare.com:port established"
_TRYCF_RE = re.compile(r"https://([a-zA-Z0-9-]+\.trycloudflare\.com)", re.I)
_TRYCF_TCP_RE = re.compile(r"(?:tcp://)?([a-zA-Z0-9-]+\.trycloudflare\.com)(?::(\d+))?", re.I)


def _find_cloudflared() -> Optional[str]:
    return shutil.which("cloudflared")


def find_existing_tunnels() -> List[Dict]:
    """
    查找本地已运行的 cloudflared 隧道进程
    
    Returns:
        隧道信息列表，每个元素包含 {pid, cmd, url, type}
    """
    tunnels = []
    try:
        if platform.system() == "Windows":
            # Windows: 使用 tasklist 和 wmic
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq cloudflared.exe", "/FO", "CSV"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]  # 跳过标题行
                for line in lines:
                    if 'cloudflared' in line.lower():
                        parts = line.split(',')
                        if len(parts) > 1:
                            pid = parts[1].strip('"')
                            # 获取命令行
                            cmd_result = subprocess.run(
                                ["wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine", "/format:list"],
                                capture_output=True,
                                text=True,
                                timeout=5
                            )
                            cmd = ""
                            if cmd_result.returncode == 0:
                                for cmd_line in cmd_result.stdout.split('\n'):
                                    if cmd_line.startswith('CommandLine='):
                                        cmd = cmd_line.split('=', 1)[1]
                                        break
                            if cmd:
                                tunnels.append({"pid": int(pid), "cmd": cmd, "url": "", "type": ""})
        else:
            # Unix-like: 使用 ps
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'cloudflared' in line.lower() and 'grep' not in line.lower():
                        parts = line.split()
                        if len(parts) >= 2:
                            try:
                                pid = int(parts[1])
                                cmd = ' '.join(parts[10:])  # 命令行从第11个字段开始
                                
                                # 解析 URL 和类型
                                url = ""
                                tunnel_type = "unknown"
                                
                                # 检查是否是 quick tunnel (--url)
                                url_match = re.search(r'--url\s+([^\s]+)', cmd)
                                if url_match:
                                    url = url_match.group(1)
                                    if 'tcp://' in url:
                                        tunnel_type = "tcp"
                                    elif 'http://' in url or 'https://' in url:
                                        tunnel_type = "http"
                                elif 'tunnel run' in cmd or '--config' in cmd:
                                    # 长期运行的命名隧道
                                    tunnel_type = "named"
                                    config_match = re.search(r'--config\s+([^\s]+)', cmd)
                                    name_match = re.search(r'tunnel run\s+([^\s]+)', cmd)
                                    if config_match or name_match:
                                        tunnel_name = name_match.group(1) if name_match else "unknown"
                                        url = f"named:{tunnel_name}"
                                
                                tunnels.append({
                                    "pid": pid,
                                    "cmd": cmd,
                                    "url": url,
                                    "type": tunnel_type
                                })
                            except (ValueError, IndexError):
                                continue
    except Exception as e:
        print(f"[CF-TUNNEL] 查询现有隧道失败: {e}", file=sys.stderr, flush=True)
    
    return tunnels


def check_port_available(port: int) -> Tuple[bool, Optional[str]]:
    """
    检查端口是否可用
    
    Returns:
        (是否可用, 占用进程信息)
    """
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        
        if result == 0:
            # 端口被占用，尝试查找占用进程
            try:
                if platform.system() == "Windows":
                    result = subprocess.run(
                        ["netstat", "-ano"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        for line in result.stdout.split('\n'):
                            if f':{port}' in line and 'LISTENING' in line:
                                parts = line.split()
                                if len(parts) > 0:
                                    pid = parts[-1]
                                    return False, f"PID {pid}"
                else:
                    # Unix-like
                    result = subprocess.run(
                        ["lsof", "-ti", f":{port}"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        pid = result.stdout.strip().split('\n')[0]
                        return False, f"PID {pid}"
            except:
                pass
            return False, "未知进程"
        return True, None
    except Exception as e:
        return True, None  # 检查失败，假设可用


def cleanup_conflicting_tunnels(target_urls: List[str], keep_named: bool = True) -> int:
    """
    清理冲突的 cloudflared 隧道进程
    
    Args:
        target_urls: 目标 URL 列表（如 ["tcp://127.0.0.1:5060", "http://127.0.0.1:8888"]）
        keep_named: 是否保留命名隧道（通过 --config 运行的长期隧道）
    
    Returns:
        清理的进程数量
    """
    existing = find_existing_tunnels()
    cleaned = 0
    
    for tunnel in existing:
        pid = tunnel["pid"]
        cmd = tunnel["cmd"]
        url = tunnel["url"]
        tunnel_type = tunnel["type"]
        
        # 跳过命名隧道（如果设置了保留）
        if keep_named and tunnel_type == "named":
            print(f"[CF-TUNNEL] 保留命名隧道: PID {pid} ({url})", file=sys.stderr, flush=True)
            continue
        
        # 检查是否与目标 URL 冲突
        should_clean = False
        if tunnel_type in ("tcp", "http") and url:
            # 检查是否指向相同的本地端口
            for target_url in target_urls:
                if url == target_url:
                    should_clean = True
                    print(f"[CF-TUNNEL] 发现冲突隧道: PID {pid}, URL={url}, 目标={target_url}", file=sys.stderr, flush=True)
                    break
        
        # 如果是 quick tunnel 且没有明确匹配，也清理（避免多个 quick tunnel 冲突）
        # 注意：只清理指向相同端口的隧道，不要清理指向其他端口的隧道
        if not should_clean and tunnel_type in ("tcp", "http") and '--url' in cmd:
            # 检查是否指向相同的本地端口
            for target_url in target_urls:
                target_port_match = re.search(r':(\d+)$', target_url)
                if target_port_match:
                    target_port = target_port_match.group(1)
                    # 精确匹配端口，避免误杀其他端口的隧道
                    if f":{target_port}" in url or f"://127.0.0.1:{target_port}" in url or f"://localhost:{target_port}" in url:
                        should_clean = True
                        print(f"[CF-TUNNEL] 发现端口冲突隧道: PID {pid}, URL={url}, 目标端口={target_port}", file=sys.stderr, flush=True)
                        break
        
        if should_clean:
            try:
                print(f"[CF-TUNNEL] 正在终止冲突隧道进程: PID {pid}", file=sys.stderr, flush=True)
                os.kill(pid, signal.SIGTERM)
                # 等待进程退出
                import time
                for _ in range(10):  # 最多等待 1 秒
                    try:
                        os.kill(pid, 0)  # 检查进程是否还存在
                        time.sleep(0.1)
                    except ProcessLookupError:
                        break
                else:
                    # 如果还没退出，强制杀死
                    try:
                        os.kill(pid, signal.SIGKILL)
                        print(f"[CF-TUNNEL] 强制终止进程: PID {pid}", file=sys.stderr, flush=True)
                    except ProcessLookupError:
                        pass
                cleaned += 1
                print(f"[CF-TUNNEL] 已清理冲突隧道: PID {pid}", file=sys.stderr, flush=True)
            except ProcessLookupError:
                # 进程已经不存在
                pass
            except PermissionError:
                print(f"[CF-TUNNEL] 权限不足，无法终止进程: PID {pid}", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[CF-TUNNEL] 终止进程失败: PID {pid}, 错误: {e}", file=sys.stderr, flush=True)
    
    return cleaned


def _devnull_config_path() -> str:
    """返回用于忽略配置文件的路径（Unix: /dev/null，Windows: NUL）"""
    return getattr(os, "devnull", "/dev/null")


def _create_isolated_config_dir() -> Optional[str]:
    """
    创建仅用于 Quick Tunnel 的临时配置目录，写入最小合法 config，
    避免 cloudflared 读取本机 ~/.cloudflared，且避免 "config was empty" 报错。
    调用方需在隧道进程存活期间保留该目录（不删除）。
    """
    try:
        tmp = tempfile.mkdtemp(prefix="cloudflared_quick_")
        cfg_path = os.path.join(tmp, "config.yml")
        with open(cfg_path, "w") as f:
            f.write("# Quick tunnel only - no named tunnel\n")
        return cfg_path
    except Exception as e:
        print(f"[CF-TUNNEL] 创建临时配置目录失败: {e}", file=sys.stderr, flush=True)
        return None


async def start_tunnel(
    url: str,
    timeout: float = 15.0,
    ignore_config: bool = False,
) -> Tuple[Optional[str], Optional[int], Optional[subprocess.Popen]]:
    """
    启动一条 cloudflared quick tunnel，指向本地 url（如 tcp://localhost:5060 或 http://localhost:8888）。

    Args:
        url: 本地服务地址，如 http://127.0.0.1:8888
        timeout: 超时秒数
        ignore_config: 为 True 时完全忽略本机 ~/.cloudflared，使用临时 config 目录强制 Quick Tunnel

    Returns:
        (host, port, process): 解析到的公网 host、port（TCP 时可能非 443）、及子进程；
        port 为 None 时表示 HTTP(S) 使用默认 443；
        解析失败或未安装 cloudflared 时 host 为 None。
    """
    exe = _find_cloudflared()
    if not exe:
        return None, None, None

    # 需要忽略本机配置时：使用临时目录内的小 config，避免读 ~/.cloudflared 且避免 "empty" 报错
    config_yaml = os.path.expanduser("~/.cloudflared/config.yaml")
    config_yml = os.path.expanduser("~/.cloudflared/config.yml")
    has_config = os.path.exists(config_yaml) or os.path.exists(config_yml)
    use_isolated_config = ignore_config or has_config

    env = os.environ.copy()
    if use_isolated_config:
        if ignore_config or has_config:
            print(f"[CF-TUNNEL] 使用临时配置目录，忽略本机 ~/.cloudflared", file=sys.stderr, flush=True)
        isolated_cfg = _create_isolated_config_dir()
        if isolated_cfg:
            cmd = [exe, "tunnel", "--config", isolated_cfg, "--url", url]
            # 让 cloudflared 仅从该目录读配置，不读 ~/.cloudflared
            env["CLOUDFLARED_CONFIG_DIR"] = os.path.dirname(isolated_cfg)
        else:
            cmd = [exe, "tunnel", "--config", _devnull_config_path(), "--url", url]
    else:
        cmd = [exe, "tunnel", "--url", url]

    # 使用 unbuffered 模式，并允许实时查看输出
    # 但为了解析 URL，我们需要捕获输出
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=0,  # 无缓冲
        env=env,
    )
    # 记录进程启动信息用于调试
    print(f"[CF-TUNNEL] 启动 cloudflared 进程 PID {proc.pid}，URL: {url}", file=sys.stderr, flush=True)
    
    host, port = None, None
    output_lines = []  # 保存所有输出用于调试
    try:
        for _ in range(500):  # 避免死循环
            line = proc.stdout.readline() if proc.stdout else ""
            if not line and proc.poll() is not None:
                break
            line = (line or "").strip()
            if not line:
                await asyncio.sleep(0.1)
                continue
            
            # 保存所有输出
            output_lines.append(line)
            
            # 打印所有输出用于调试（HTTP 隧道时）
            if "http://" in url:
                # HTTP 隧道：打印所有输出以便诊断
                print(f"[CF-TUNNEL] cloudflared 输出: {line}", file=sys.stderr, flush=True)
            else:
                # TCP 隧道：只打印关键输出
                if "trycloudflare.com" in line.lower() or "error" in line.lower() or "failed" in line.lower() or "connection" in line.lower():
                    print(f"[CF-TUNNEL] cloudflared 输出: {line}", file=sys.stderr, flush=True)
            # HTTP(S) URL
            m = _TRYCF_RE.search(line)
            if m:
                host = m.group(1)
                port = 443 if "https" in line.lower() else None
                print(f"[CF-TUNNEL] 解析到 HTTP 隧道: {host}", file=sys.stderr, flush=True)
                break
            # 可能带端口的 TCP 行
            m = _TRYCF_TCP_RE.search(line)
            if m:
                host = m.group(1)
                port = int(m.group(2)) if m.group(2) else None
                if host:
                    print(f"[CF-TUNNEL] 解析到 TCP 隧道: {host}:{port}", file=sys.stderr, flush=True)
                    break
        # 等待隧道就绪 - 对于 HTTP 隧道，需要等待连接完全建立
        # cloudflared 输出 "Registered tunnel connection" 后还需要时间建立到本地服务的连接
        if "http://" in url:
            # HTTP 隧道：等待更长时间，并检查是否有连接错误
            await asyncio.sleep(2.0)  # 先等待基本连接
            # 检查是否有错误输出
            has_error = any("error" in line.lower() or "failed" in line.lower() for line in output_lines[-20:])
            if has_error:
                print(f"[CF-TUNNEL] 警告: 检测到错误输出，隧道可能未正确连接", file=sys.stderr, flush=True)
            await asyncio.sleep(3.0)  # 再等待建立到本地服务的连接
        else:
            await asyncio.sleep(2.0)
        
        # 验证本地服务是否可访问
        if "http://" in url:
            import socket
            try:
                test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                test_sock.settimeout(2)
                test_url = url.replace("http://", "").replace("https://", "")
                if ":" in test_url:
                    test_host, test_port = test_url.split(":")
                    test_port = int(test_port)
                else:
                    test_host = test_url
                    test_port = 80 if "http://" in url else 443
                result = test_sock.connect_ex((test_host, test_port))
                test_sock.close()
                if result == 0:
                    print(f"[CF-TUNNEL] 验证: 本地服务 {url} 可访问", file=sys.stderr, flush=True)
                else:
                    print(f"[CF-TUNNEL] 警告: 本地服务 {url} 可能不可访问 (connect result: {result})", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[CF-TUNNEL] 验证本地服务时出错: {e}", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[CF-TUNNEL] 启动隧道时异常: {e}", file=sys.stderr, flush=True)
        if proc.poll() is None:
            proc.terminate()
        return None, None, None
    if not host:
        print(f"[CF-TUNNEL] 警告: 未能解析到隧道 URL，进程状态: {proc.poll()}", file=sys.stderr, flush=True)
        print(f"[CF-TUNNEL] 最后 10 行输出:", file=sys.stderr, flush=True)
        for line in output_lines[-10:]:
            print(f"[CF-TUNNEL]   {line}", file=sys.stderr, flush=True)
        if proc.poll() is None:
            proc.terminate()
        return None, None, None
    print(f"[CF-TUNNEL] 隧道启动成功: {host}:{port or 'default'}", file=sys.stderr, flush=True)
    if "http://" in url:
        print(f"[CF-TUNNEL] 提示: HTTP 隧道已启动，但连接建立可能需要额外时间", file=sys.stderr, flush=True)
        print(f"[CF-TUNNEL] 提示: 如果立即访问返回 404，请等待 10-20 秒后重试", file=sys.stderr, flush=True)
        print(f"[CF-TUNNEL] 提示: 确保本地服务 http://127.0.0.1:8888 正常运行", file=sys.stderr, flush=True)
    return host, port, proc


async def start_sip_tunnel(
    sip_port: int = 5060,
    http_port: Optional[int] = 8888,
    timeout: float = 15.0,
    auto_cleanup: bool = True,
) -> Tuple[Optional[str], Optional[int], Optional[str], Optional[int], List[subprocess.Popen]]:
    """
    启动 SIP(TCP) 与可选的 HTTP 两条 quick tunnel。

    Args:
        sip_port: SIP 端口
        http_port: HTTP 端口（可选）
        timeout: 超时时间（秒）
        auto_cleanup: 是否自动清理冲突的隧道

    Returns:
        (sip_host, sip_port, http_host, http_port, processes)
        - sip_host/sip_port: 公网 SIP 地址（客户端用此注册）
        - http_host/http_port: 公网 MML 地址（可选）
        - processes: 需在退出时 terminate 的进程列表
    """
    # 查询并显示现有隧道
    existing = find_existing_tunnels()
    if existing:
        print(f"[CF-TUNNEL] 发现 {len(existing)} 个现有隧道进程:", file=sys.stderr, flush=True)
        for t in existing:
            print(f"  - PID {t['pid']}: {t['type']} {t['url']}", file=sys.stderr, flush=True)
    
    # 检查端口占用情况
    sip_available, sip_info = check_port_available(sip_port)
    if not sip_available:
        print(f"[CF-TUNNEL] 警告: SIP 端口 {sip_port} 已被占用 ({sip_info})", file=sys.stderr, flush=True)
    
    if http_port is not None:
        http_available, http_info = check_port_available(http_port)
        if not http_available:
            print(f"[CF-TUNNEL] 警告: HTTP 端口 {http_port} 已被占用 ({http_info})", file=sys.stderr, flush=True)
    
    # 自动清理冲突的隧道
    if auto_cleanup:
        target_urls = [f"tcp://127.0.0.1:{sip_port}"]
        if http_port is not None:
            target_urls.append(f"http://127.0.0.1:{http_port}")
        
        cleaned = cleanup_conflicting_tunnels(target_urls, keep_named=True)
        if cleaned > 0:
            print(f"[CF-TUNNEL] 已清理 {cleaned} 个冲突隧道，等待 2 秒后启动新隧道...", file=sys.stderr, flush=True)
            await asyncio.sleep(2.0)  # 等待进程完全退出
    
    procs: List[subprocess.Popen] = []
    sip_host, sip_port_pub = None, None
    http_host, http_port_pub = None, None

    # SIP over TCP
    print(f"[CF-TUNNEL] 正在启动 SIP 隧道: tcp://127.0.0.1:{sip_port}", file=sys.stderr, flush=True)
    h, p, proc = await start_tunnel(f"tcp://127.0.0.1:{sip_port}", timeout=timeout)
    if proc:
        procs.append(proc)
    if h:
        sip_host, sip_port_pub = h, p or 443
        print(f"[CF-TUNNEL] SIP 隧道已启动: {sip_host}:{sip_port_pub}", file=sys.stderr, flush=True)
    else:
        print(f"[CF-TUNNEL] 警告: SIP 隧道启动失败", file=sys.stderr, flush=True)

    # HTTP MML（可选）
    if http_port is not None:
        print(f"[CF-TUNNEL] 正在启动 HTTP 隧道: http://127.0.0.1:{http_port}", file=sys.stderr, flush=True)
        h2, p2, proc2 = await start_tunnel(f"http://127.0.0.1:{http_port}", timeout=timeout)
        if proc2:
            procs.append(proc2)
        if h2:
            http_host, http_port_pub = h2, p2 or 443
            print(f"[CF-TUNNEL] HTTP 隧道已启动: https://{http_host}", file=sys.stderr, flush=True)
        else:
            print(f"[CF-TUNNEL] 错误: HTTP 隧道启动失败，公网 MML 将无法访问", file=sys.stderr, flush=True)
            print(f"[CF-TUNNEL] 请检查: 1) cloudflared 是否已安装 2) 端口 {http_port} 是否被占用 3) 是否有其他冲突的隧道", file=sys.stderr, flush=True)

    return sip_host, sip_port_pub, http_host, http_port_pub, procs
