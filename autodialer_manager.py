"""
外呼服务管理器
用于在后台运行和管理外呼客户端，可通过 MML 界面控制
"""

import threading
import time
from typing import Optional, Dict, List
from sip_client_standalone import AutoDialerClient


class AutoDialerManager:
    """外呼服务管理器"""
    
    def __init__(self, config_file: str = "sip_client_config.json", server_globals: Optional[Dict] = None):
        """
        初始化外呼管理器
        
        Args:
            config_file: 外呼客户端配置文件路径
            server_globals: 服务器全局变量字典，用于访问 REG_BINDINGS 进行清理
        """
        self.config_file = config_file
        self.server_globals = server_globals or {}
        self.client: Optional[AutoDialerClient] = None
        self.is_running = False
        self.is_registered = False
        self._lock = threading.Lock()
        self.start_time: Optional[float] = None
        self.main_port = 10000  # 主端口（外呼终端端口）
        
    def start(self) -> tuple[bool, str]:
        """
        启动外呼服务
        
        Returns:
            (成功标志, 消息)
        """
        with self._lock:
            if self.is_running:
                return False, "外呼服务已启动"
            
            try:
                # 创建外呼客户端（传入 server_globals，内嵌时用 127.0.0.1 注册以便服务器回送 INVITE）
                self.client = AutoDialerClient(self.config_file, server_globals=self.server_globals)
                
                # 更新主端口配置（从客户端配置读取）
                self.main_port = self.client.config.get("local_port", 10000)
                
                # 注册到 SIP 服务器
                if not self.client.register():
                    self.client = None
                    return False, "注册到 SIP 服务器失败"
                
                self.is_running = True
                self.is_registered = True
                self.start_time = time.time()
                
                return True, "外呼服务启动成功"
                
            except Exception as e:
                self.client = None
                self.is_running = False
                self.is_registered = False
                return False, f"启动外呼服务失败: {str(e)}"
    
    def stop(self) -> tuple[bool, str]:
        """
        停止外呼服务
        
        Returns:
            (成功标志, 消息)
        """
        with self._lock:
            if not self.is_running:
                return False, "外呼服务未启动"
            
            try:
                if self.client:
                    self.client.close()
                    self.client = None
                
                self.is_running = False
                self.is_registered = False
                self.start_time = None
                
                return True, "外呼服务已停止"
                
            except Exception as e:
                return False, f"停止外呼服务失败: {str(e)}"
    
    def dial(self, callee: str, media_file: Optional[str] = None, 
             duration: float = 0.0) -> tuple[bool, str]:
        """
        发起单次外呼（异步，不阻塞）
        
        Args:
            callee: 被叫用户号码
            media_file: 媒体文件路径（None 表示使用默认）
            duration: 播放时长（秒），0表示播放完整文件
        
        Returns:
            (成功标志, 消息)
        """
        with self._lock:
            if not self.is_running or not self.is_registered:
                return False, "外呼服务未启动，请先启动外呼服务"
            
            if not self.client:
                return False, "外呼客户端未初始化"
        
        # 在锁外执行，避免阻塞
        try:
            # 使用 dial_concurrent 避免阻塞和状态冲突
            import threading
            
            def dial_async():
                try:
                    self.client.dial_concurrent(callee, media_file, duration)
                except Exception as e:
                    print(f"[ERROR] [{callee}] 异步外呼失败: {e}")
                    import traceback
                    traceback.print_exc()
            
            # 在后台线程中执行（daemon=True 确保不会阻塞主进程）
            thread = threading.Thread(target=dial_async, daemon=True)
            thread.start()
            
            return True, f"外呼请求已发送到 {callee}（后台执行中）"
        except Exception as e:
            print(f"[ERROR] [{callee}] 外呼异常: {e}")
            import traceback
            traceback.print_exc()
            return False, f"外呼异常: {str(e)}"
    
    def dial_batch(self, callees: List[str], media_file: Optional[str] = None,
                   duration: float = 0.0) -> tuple[bool, str, Dict]:
        """
        批量外呼（并发模式，异步执行，不阻塞）
        
        Args:
            callees: 被叫号码列表
            media_file: 媒体文件路径（None 表示使用默认）
            duration: 播放时长（秒），0表示播放完整文件
        
        Returns:
            (成功标志, 消息, 结果字典) - 立即返回，批量呼叫在后台执行
        """
        with self._lock:
            if not self.is_running or not self.is_registered:
                return False, "外呼服务未启动，请先启动外呼服务", {}
            
            if not self.client:
                return False, "外呼客户端未初始化", {}
            
            if not callees:
                return False, "被叫号码列表为空", {}
        
        # 在锁外执行，避免阻塞
        try:
            import threading
            import concurrent.futures
            
            def dial_batch_async():
                """后台批量外呼函数"""
                results = {}
                try:
                    def dial_single(callee: str) -> tuple:
                        """单个呼叫函数（带异常保护）"""
                        try:
                            success = self.client.dial_concurrent(callee, media_file, duration)
                            return (callee, success)
                        except Exception as e:
                            print(f"[ERROR] [{callee}] 批量外呼异常: {e}")
                            import traceback
                            traceback.print_exc()
                            return (callee, False)
                    
                    # 使用线程池并发执行
                    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(callees), 10)) as executor:
                        # 提交所有呼叫任务
                        futures = {executor.submit(dial_single, callee): callee for callee in callees}
                        
                        # 等待所有呼叫完成（带超时保护）
                        try:
                            for future in concurrent.futures.as_completed(futures, timeout=300.0):  # 最多等待 5 分钟
                                callee = futures[future]
                                try:
                                    result = future.result(timeout=1.0)  # 每个 future 最多等待 1 秒
                                    callee_result, success = result
                                    results[callee_result] = success
                                    print(f"[AutoDialerManager] [{callee_result}] 呼叫完成: {'成功' if success else '失败'}")
                                except concurrent.futures.TimeoutError:
                                    results[callee] = False
                                    print(f"[WARNING] [AutoDialerManager] [{callee}] 呼叫超时")
                                except Exception as e:
                                    results[callee] = False
                                    print(f"[ERROR] [AutoDialerManager] [{callee}] 呼叫异常: {e}")
                                    import traceback
                                    traceback.print_exc()
                        except concurrent.futures.TimeoutError:
                            # 批量呼叫总超时
                            print(f"[WARNING] [AutoDialerManager] 批量外呼超时（部分呼叫可能仍在进行）")
                            # 记录未完成的呼叫
                            for future in futures:
                                if not future.done():
                                    callee = futures[future]
                                    results[callee] = False
                                    print(f"[WARNING] [AutoDialerManager] [{callee}] 呼叫未完成（超时）")
                    
                    success_count = sum(1 for v in results.values() if v)
                    total_count = len(results)
                    print(f"[AutoDialerManager] 批量外呼完成: {success_count}/{total_count} 成功")
                    
                    # 清理残留注册（除主端口外）
                    self._cleanup_residual_registrations()
                    
                except Exception as pool_err:
                    print(f"[ERROR] [AutoDialerManager] 批量外呼线程池异常: {pool_err}")
                    import traceback
                    traceback.print_exc()
            
            # 在后台线程中执行（daemon=True 确保不会阻塞主进程）
            thread = threading.Thread(target=dial_batch_async, daemon=True)
            thread.start()
            
            # 立即返回，不等待批量呼叫完成
            return True, f"批量外呼请求已提交 {len(callees)} 个号码（后台执行中）", {}
            
        except Exception as e:
            print(f"[ERROR] [AutoDialerManager] 批量外呼启动异常: {e}")
            import traceback
            traceback.print_exc()
            return False, f"批量外呼启动异常: {str(e)}", {}
    
    def get_status(self) -> Dict:
        """
        获取外呼服务状态
        
        Returns:
            状态字典
        """
        with self._lock:
            status = {
                "running": self.is_running,
                "registered": self.is_registered,
                "start_time": self.start_time,
                "uptime": None,
                "stats": {}
            }
            
            if self.start_time:
                status["uptime"] = int(time.time() - self.start_time)
            
            if self.client:
                status["stats"] = self.client.stats.copy()
            else:
                status["stats"] = {
                    "total_calls": 0,
                    "successful_calls": 0,
                    "failed_calls": 0
                }
            
            return status
    
    def get_config(self) -> Dict:
        """
        获取外呼配置
        
        Returns:
            配置字典
        """
        with self._lock:
            if self.client:
                return self.client.config.copy()
            else:
                # 尝试加载配置
                try:
                    client = AutoDialerClient(self.config_file)
                    return client.config.copy()
                except:
                    return {}
    
    def update_config(self, updates: Dict) -> tuple[bool, str]:
        """
        更新外呼配置
        
        Args:
            updates: 配置更新字典
        
        Returns:
            (成功标志, 消息)
        """
        with self._lock:
            try:
                if not self.client:
                    return False, "外呼客户端未初始化"
                
                # 更新配置
                self.client.config.update(updates)
                
                # 保存配置
                self.client._save_config(self.client.config, self.config_file)
                
                return True, "配置已更新（重启服务后生效）"
                
            except Exception as e:
                return False, f"更新配置失败: {str(e)}"
    
    def _cleanup_residual_registrations(self):
        """
        清理残留注册信息（除主端口外）
        批量外呼完成后，清理除主端口（10000）之外的所有注册绑定
        """
        try:
            reg_bindings = self.server_globals.get('REG_BINDINGS', {})
            if not reg_bindings:
                return
            
            # 获取配置信息
            if self.client:
                username = self.client.config.get("username", "0000")
                server_ip = self.client.config.get("server_ip", "192.168.100.8")
            else:
                # 从配置文件中读取
                try:
                    import json
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    username = config.get("username", "0000")
                    server_ip = config.get("server_ip", "192.168.100.8")
                except:
                    username = "0000"
                    server_ip = "192.168.100.8"
            
            # 构造 AOR（Address of Record）
            aor = f"sip:{username}@{server_ip}"
            
            if aor not in reg_bindings:
                return
            
            bindings = reg_bindings[aor]
            now = int(time.time())
            
            # 过滤掉已过期的绑定
            valid_bindings = [b for b in bindings if b["expires"] > now]
            
            # 查找需要保留的主端口绑定和非主端口绑定
            main_binding = None
            other_bindings = []
            
            for binding in valid_bindings:
                contact = binding["contact"]
                # 解析端口号（格式：sip:user@ip:port）
                import re
                port_match = re.search(r':(\d+)', contact)
                if port_match:
                    port = int(port_match.group(1))
                    if port == self.main_port:
                        main_binding = binding
                    else:
                        other_bindings.append(binding)
            
            # 如果有非主端口的绑定，清理它们
            if other_bindings:
                print(f"[AutoDialerManager] 发现 {len(other_bindings)} 个残留注册（非主端口），正在清理...")
                
                # 直接清理 REG_BINDINGS（最简单直接的方法）
                if main_binding:
                    # 只保留主端口的绑定
                    reg_bindings[aor] = [main_binding]
                    print(f"[AutoDialerManager] 已清理残留注册，仅保留主端口 {self.main_port} 的注册")
                else:
                    # 如果没有主端口绑定，删除所有非主端口的绑定（保留所有绑定避免误删）
                    reg_bindings[aor] = [b for b in valid_bindings if b not in other_bindings]
                    if reg_bindings[aor]:
                        print(f"[AutoDialerManager] 已清理 {len(other_bindings)} 个非主端口注册，保留 {len(reg_bindings[aor])} 个其他注册")
                    else:
                        print(f"[WARNING] [AutoDialerManager] 未找到主端口 {self.main_port} 的注册，已清理所有非主端口注册")
            
        except Exception as e:
            print(f"[WARNING] [AutoDialerManager] 清理残留注册异常（已忽略）: {e}")
            import traceback
            traceback.print_exc()

