"""
IMS 用户管理模块

管理已开户的用户信息（不同于 SIP 注册状态）
- 用户基本信息
- 用户状态管理
- 用户增删改查
"""

import json
import os
import threading
from datetime import datetime
from typing import Dict, List, Optional


class UserManager:
    """用户管理器"""
    
    def __init__(self, data_file='data/users.json'):
        self.data_file = data_file
        self.users = {}  # {username: user_info}
        self.lock = threading.Lock()
        self._file_mtime = 0  # 文件最后修改时间
        self._load_users()
    
    def _load_users(self):
        """从文件加载用户数据"""
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
            
            if os.path.exists(self.data_file):
                # 检查文件修改时间
                current_mtime = os.path.getmtime(self.data_file)
                # 如果文件被修改（或者首次加载），重新加载
                is_initial_load = (self._file_mtime == 0)
                if current_mtime > self._file_mtime or is_initial_load:
                    old_count = len(self.users)
                    with open(self.data_file, 'r', encoding='utf-8') as f:
                        self.users = json.load(f)
                    new_count = len(self.users)
                    self._file_mtime = current_mtime
                    # 只在初始化时或用户数量变化时打印日志
                    if is_initial_load or old_count != new_count:
                        print(f"[USER] 已加载 {len(self.users)} 个用户")
            else:
                # 创建默认用户
                self._create_default_users()
                if os.path.exists(self.data_file):
                    self._file_mtime = os.path.getmtime(self.data_file)
        except Exception as e:
            print(f"[USER] 加载用户数据失败: {e}")
            self.users = {}
    
    def _save_users(self):
        """保存用户数据到文件"""
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.users, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[USER] 保存用户数据失败: {e}")
    
    def _create_default_users(self):
        """创建默认测试用户"""
        default_users = [
            {
                'username': '1001',
                'password': '1001',
                'display_name': '测试用户1001',
                'phone': '13800001001',
                'email': 'user1001@example.com',
                'status': 'ACTIVE',
                'service_type': 'BASIC',
                'create_time': datetime.now().isoformat(),
            },
            {
                'username': '1002',
                'password': '1002',
                'display_name': '测试用户1002',
                'phone': '13800001002',
                'email': 'user1002@example.com',
                'status': 'ACTIVE',
                'service_type': 'PREMIUM',
                'create_time': datetime.now().isoformat(),
            },
        ]
        
        for user in default_users:
            self.users[user['username']] = user
        
        self._save_users()
        print(f"[USER] 已创建 {len(default_users)} 个默认用户")
    
    def add_user(self, username: str, password: str, display_name: str = '',
                 phone: str = '', email: str = '', service_type: str = 'BASIC') -> Dict:
        """添加新用户"""
        with self.lock:
            if username in self.users:
                return {'success': False, 'message': f'用户 {username} 已存在'}
            
            user = {
                'username': username,
                'password': password,
                'display_name': display_name or f'用户{username}',
                'phone': phone,
                'email': email,
                'status': 'ACTIVE',
                'service_type': service_type,
                'create_time': datetime.now().isoformat(),
                'update_time': datetime.now().isoformat(),
            }
            
            self.users[username] = user
            self._save_users()
            
            return {'success': True, 'message': f'用户 {username} 添加成功', 'user': user}
    
    def delete_user(self, username: str) -> Dict:
        """删除用户"""
        with self.lock:
            if username not in self.users:
                return {'success': False, 'message': f'用户 {username} 不存在'}
            
            del self.users[username]
            self._save_users()
            
            return {'success': True, 'message': f'用户 {username} 删除成功'}
    
    def modify_user(self, username: str, **kwargs) -> Dict:
        """修改用户信息"""
        with self.lock:
            if username not in self.users:
                return {'success': False, 'message': f'用户 {username} 不存在'}
            
            user = self.users[username]
            
            # 允许修改的字段
            allowed_fields = ['password', 'display_name', 'phone', 'email', 'status', 'service_type', 'role']
            
            for field, value in kwargs.items():
                if field in allowed_fields and value is not None:
                    user[field] = value
            
            user['update_time'] = datetime.now().isoformat()
            
            self._save_users()
            
            return {'success': True, 'message': f'用户 {username} 修改成功', 'user': user}
    
    def get_user(self, username: str) -> Optional[Dict]:
        """查询单个用户"""
        with self.lock:
            return self.users.get(username)
    
    def get_all_users(self, status: Optional[str] = None) -> List[Dict]:
        """查询所有用户"""
        with self.lock:
            # 每次调用时检查文件修改时间，如果文件被修改，重新加载
            # 这对于高并发测试场景很重要，因为测试脚本会动态添加用户
            try:
                if os.path.exists(self.data_file):
                    current_mtime = os.path.getmtime(self.data_file)
                    # 如果文件被修改（时间增加），重新加载
                    # 注意：即使时间相同，也可能是文件被修改了（由于文件系统精度），所以每次都检查
                    if current_mtime >= self._file_mtime:
                        old_count = len(self.users)
                        # 读取文件内容并检查是否真的变化了
                        with open(self.data_file, 'r', encoding='utf-8') as f:
                            new_users = json.load(f)
                        # 如果用户数据有变化，更新
                        if new_users != self.users or current_mtime > self._file_mtime:
                            self.users = new_users
                            self._file_mtime = current_mtime
            except Exception as e:
                # 如果重新加载失败，使用现有数据
                pass
            
            users = list(self.users.values())
            
            if status:
                users = [u for u in users if u.get('status') == status]
            
            return users
    
    def get_user_count(self, status: Optional[str] = None) -> int:
        """获取用户数量"""
        users = self.get_all_users(status)
        return len(users)
    
    def authenticate(self, username: str, password: str) -> bool:
        """验证用户凭证"""
        user = self.get_user(username)
        if not user:
            # 如果找不到用户，尝试重新加载文件（可能文件被外部修改）
            # 这样可以支持动态添加用户（如高并发测试场景）
            try:
                self._load_users()
                user = self.get_user(username)
            except:
                pass
        
        if not user:
            return False
        
        return user.get('password') == password and user.get('status') == 'ACTIVE'


# 全局用户管理器实例
_user_manager = None


def init_user_manager(data_file='data/users.json'):
    """
    初始化用户管理器（单例模式）
    
    Args:
        data_file: 用户数据文件路径
    
    Returns:
        UserManager 实例
    
    Note:
        如果实例已存在，直接返回现有实例，不会重复创建
    """
    global _user_manager
    if _user_manager is None:
        _user_manager = UserManager(data_file)
        
        # 只在真正创建实例时输出日志
        try:
            # 尝试获取日志记录器
            from sipcore.logger import get_logger
            log = get_logger()
            log.info("[USER] User management system initialized")
        except:
            # 如果日志系统未初始化，使用 print
            print("[USER] User management system initialized")
    
    return _user_manager


def get_user_manager() -> UserManager:
    """获取用户管理器实例"""
    global _user_manager
    if _user_manager is None:
        _user_manager = UserManager()
    return _user_manager

