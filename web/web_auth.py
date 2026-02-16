"""
Web 认证模块
提供会话管理和登录验证功能

注意：Web 认证现在使用 SIP 用户管理系统 (UserManager)
需要在 data/users.json 中存在对应用户才能登录
"""

import hashlib
import secrets
import time
from typing import Dict, Optional

# 会话管理
class SessionManager:
    """会话管理器"""
    
    def __init__(self, session_timeout: int = 3600):
        """
        初始化会话管理器
        
        Args:
            session_timeout: 会话超时时间（秒），默认1小时
        """
        self.sessions: Dict[str, dict] = {}
        self.session_timeout = session_timeout
    
    def create_session(self, username: str) -> str:
        """创建新会话"""
        session_id = secrets.token_urlsafe(32)
        self.sessions[session_id] = {
            'username': username,
            'created_at': time.time(),
            'last_accessed': time.time()
        }
        return session_id
    
    def validate_session(self, session_id: str) -> bool:
        """验证会话是否有效"""
        if not session_id or session_id not in self.sessions:
            return False
        
        session = self.sessions[session_id]
        now = time.time()
        
        # 检查是否超时
        if now - session['last_accessed'] > self.session_timeout:
            del self.sessions[session_id]
            return False
        
        # 更新最后访问时间
        session['last_accessed'] = now
        return True
    
    def get_session_user(self, session_id: str) -> Optional[str]:
        """获取会话关联的用户名"""
        if not self.validate_session(session_id):
            return None
        return self.sessions.get(session_id, {}).get('username')
    
    def destroy_session(self, session_id: str):
        """销毁会话"""
        if session_id in self.sessions:
            del self.sessions[session_id]
    
    def cleanup_expired(self):
        """清理过期会话"""
        now = time.time()
        expired = [
            sid for sid, session in self.sessions.items()
            if now - session['last_accessed'] > self.session_timeout
        ]
        for sid in expired:
            del self.sessions[sid]


class AuthManager:
    """认证管理器
    
    使用 SIP 用户管理系统 (UserManager) 进行认证
    只有具有以下角色的用户可以登录 Web 管理界面：
    - ADMIN: 管理员，拥有所有权限
    - OPERATOR: 操作员，拥有大部分管理权限
    """
    
    def __init__(self):
        self.session_manager = SessionManager()
        self._init_default_admin()
    
    def _init_default_admin(self):
        """初始化默认管理员（如果 users.json 中没有管理员）"""
        try:
            from sipcore.user_manager import get_user_manager
            user_mgr = get_user_manager()
            
            # 检查是否已存在 admin 用户
            admin_user = user_mgr.get_user('admin')
            if not admin_user:
                # 创建默认管理员用户
                user_mgr.add_user(
                    username='admin',
                    password='admin',
                    display_name='系统管理员',
                    phone='',
                    email='',
                    service_type='BASIC'
                )
                # 重新加载以获取新用户
                admin_user = user_mgr.get_user('admin')
            
            # 确保 admin 用户有 role 字段
            if admin_user and 'role' not in admin_user:
                user_mgr.modify_user('admin', role='ADMIN')
                
        except Exception as e:
            print(f"[AUTH] 初始化默认管理员失败: {e}")
    
    def _hash_password(self, password: str) -> str:
        """对密码进行 SHA256 哈希"""
        return hashlib.sha256(password.encode('utf-8')).hexdigest()
    
    def _get_user_manager(self):
        """获取用户管理器"""
        try:
            from sipcore.user_manager import get_user_manager
            return get_user_manager()
        except:
            return None
    
    def _can_login_web(self, user: dict) -> bool:
        """检查用户是否可以登录 Web 管理界面"""
        if not user:
            return False
        # 检查用户状态
        if user.get('status') != 'ACTIVE':
            return False
        # 检查角色（ADMIN 或 OPERATOR 可以登录）
        role = user.get('role', 'USER')
        return role in ('ADMIN', 'OPERATOR')
    
    def authenticate(self, username: str, password: str) -> bool:
        """验证用户名和密码"""
        user_mgr = self._get_user_manager()
        if not user_mgr:
            return False
        
        user = user_mgr.get_user(username)
        if not user:
            return False
        
        # 检查是否有 Web 登录权限
        if not self._can_login_web(user):
            return False
        
        # 验证密码（使用 SIP 用户的明文密码）
        return user.get('password') == password
    
    def login(self, username: str, password: str) -> Optional[str]:
        """
        登录并创建会话
        
        Returns:
            成功返回 session_id，失败返回 None
        """
        if self.authenticate(username, password):
            return self.session_manager.create_session(username)
        return None
    
    def logout(self, session_id: str):
        """登出"""
        self.session_manager.destroy_session(session_id)
    
    def check_auth(self, session_id: str) -> bool:
        """检查是否已认证"""
        return self.session_manager.validate_session(session_id)
    
    def get_current_user(self, session_id: str) -> Optional[str]:
        """获取当前登录用户"""
        return self.session_manager.get_session_user(session_id)
    
    def change_password(self, username: str, old_password: str, new_password: str) -> tuple:
        """
        修改密码
        
        Returns:
            (success: bool, message: str)
        """
        user_mgr = self._get_user_manager()
        if not user_mgr:
            return False, "用户管理系统不可用"
        
        user = user_mgr.get_user(username)
        if not user:
            return False, "用户不存在"
        
        # 验证原密码
        if user.get('password') != old_password:
            return False, "原密码错误"
        
        if len(new_password) < 6:
            return False, "新密码长度不能少于6位"
        
        # 使用 UserManager 修改密码（会持久化到文件）
        result = user_mgr.modify_user(username, password=new_password)
        if result['success']:
            return True, "密码修改成功"
        else:
            return False, result.get('message', '密码修改失败')


# 全局认证管理器实例
_auth_manager: Optional[AuthManager] = None


def get_auth_manager() -> AuthManager:
    """获取全局认证管理器实例"""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager()
    return _auth_manager
