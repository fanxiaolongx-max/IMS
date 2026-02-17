"""
STUN Server Implementation (RFC 5389)

STUN (Session Traversal Utilities for NAT) 服务器实现
用于帮助客户端发现其NAT映射和公网地址
"""

import socket
import asyncio
import struct
import hashlib
import hmac
from typing import Tuple, Optional, Dict, Any
import logging


# STUN 消息类型
STUN_METHOD_BINDING = 0x0001
STUN_CLASS_REQUEST = 0x00
STUN_CLASS_INDICATION = 0x01
STUN_CLASS_SUCCESS = 0x02
STUN_CLASS_ERROR = 0x03


# STUN 属性类型
STUN_ATTR_MAPPED_ADDRESS = 0x0001
STUN_ATTR_XOR_MAPPED_ADDRESS = 0x0020
STUN_ATTR_USERNAME = 0x0006
STUN_ATTR_MESSAGE_INTEGRITY = 0x0008
STUN_ATTR_ERROR_CODE = 0x0009
STUN_ATTR_REALM = 0x0014
STUN_ATTR_NONCE = 0x0015
STUN_ATTR_SOFTWARE = 0x8022
STUN_ATTR_FINGERPRINT = 0x8028


# STUN 魔数
STUN_MAGIC_COOKIE = 0x2112A442


class STUNMessage:
    """STUN 消息基类"""

    def __init__(self, msg_type: int, msg_class: int, transaction_id: bytes,
                 attributes: Dict[int, Any] = None):
        self.msg_type = msg_type
        self.msg_class = msg_class
        self.transaction_id = transaction_id
        self.attributes = attributes or {}

    @property
    def message_type(self) -> int:
        """消息类型字 (16 bits)"""
        return (self.msg_type & 0x0FFF) | (self.msg_class << 12)

    def encode(self, include_integrity: bool = False, username: str = None,
               password: str = None, realm: str = None) -> bytes:
        """编码 STUN 消息为字节"""
        # 先编码消息头和属性（不包括 MESSAGE-INTEGRITY）
        data = bytearray()
        # Type (2 bytes)
        data.extend(struct.pack('!H', self.message_type))
        # Length (2 bytes, 占位，后面更新)
        data.extend(b'\x00\x00')
        # Magic Cookie (4 bytes)
        data.extend(struct.pack('!I', STUN_MAGIC_COOKIE))
        # Transaction ID (12 bytes)
        data.extend(self.transaction_id)

        # 编码属性
        attributes_data = bytearray()
        for attr_type, attr_value in self.attributes.items():
            if attr_type == STUN_ATTR_MESSAGE_INTEGRITY:
                continue  # MESSAGE-INTEGRITY 在后面处理
            encoded = self._encode_attribute(attr_type, attr_value)
            attributes_data.extend(encoded)

        # 填充到4字节边界
        padding_len = (4 - (len(attributes_data) % 4)) % 4
        attributes_data.extend(b'\x00' * padding_len)

        # 更新消息长度
        data[2:4] = struct.pack('!H', len(attributes_data))

        # 添加属性
        data.extend(attributes_data)

        # 计算并添加 MESSAGE-INTEGRITY
        if include_integrity and username and password:
            integrity = self._compute_integrity(bytes(data), username, password, realm)
            integrity_attr = self._encode_attribute(STUN_ATTR_MESSAGE_INTEGRITY, integrity)
            data.extend(integrity_attr)
            # 更新消息长度
            data[2:4] = struct.pack('!H', len(attributes_data) + len(integrity_attr))

        return bytes(data)

    def _encode_attribute(self, attr_type: int, value: Any) -> bytes:
        """编码单个属性"""
        if attr_type == STUN_ATTR_MAPPED_ADDRESS:
            # MAPPED-ADDRESS: 1 byte family + 1 byte padding + 2 bytes port + 4/16 bytes IP
            family, port, ip = value
            if ':' in ip:
                family = 0x02  # IPv6
                ip_bytes = socket.inet_pton(socket.AF_INET6, ip)
            else:
                family = 0x01  # IPv4
                ip_bytes = socket.inet_pton(socket.AF_INET, ip)
            data = struct.pack('!BBH', family, 0, port) + ip_bytes
        elif attr_type == STUN_ATTR_XOR_MAPPED_ADDRESS:
            # XOR-MAPPED-ADDRESS: 类似 MAPPED-ADDRESS，但需要 XOR
            family, port, ip = value
            if ':' in ip:
                family = 0x02
                ip_bytes = socket.inet_pton(socket.AF_INET6, ip)
            else:
                family = 0x01
                ip_bytes = socket.inet_pton(socket.AF_INET, ip)
            # XOR port
            port ^= (STUN_MAGIC_COOKIE >> 16) & 0xFFFF
            # XOR IP
            if len(ip_bytes) == 4:  # IPv4
                cookie_bytes = struct.pack('!I', STUN_MAGIC_COOKIE)
                ip_bytes = bytes([ip_bytes[i] ^ cookie_bytes[i] for i in range(4)])
            else:  # IPv6
                cookie_bytes = struct.pack('!I', STUN_MAGIC_COOKIE) + self.transaction_id
                ip_bytes = bytes([ip_bytes[i] ^ cookie_bytes[i] for i in range(16)])
            data = struct.pack('!BBH', family, 0, port) + ip_bytes
        elif attr_type == STUN_ATTR_USERNAME:
            data = value.encode('utf-8')
        elif attr_type == STUN_ATTR_REALM:
            data = value.encode('utf-8')
        elif attr_type == STUN_ATTR_NONCE:
            data = value.encode('utf-8')
        elif attr_type == STUN_ATTR_SOFTWARE:
            data = value.encode('utf-8')
        elif attr_type == STUN_ATTR_ERROR_CODE:
            error_class, number, reason = value
            # Error Code: 20 bits (4 bytes)
            # Bits 0-7: padding + error class high bits
            # Bits 8-15: error class low bits + error number high bits
            # Bits 16-23: error number low bits
            # 实际格式: 0x0000 | (error_class << 8) | number
            error_code = (error_class << 8) | number
            data = struct.pack('!HH', 0, error_code) + reason.encode('utf-8')
        elif attr_type == STUN_ATTR_MESSAGE_INTEGRITY:
            data = value  # 20 bytes HMAC-SHA1
        elif attr_type == STUN_ATTR_FINGERPRINT:
            data = struct.pack('!I', value)
        else:
            data = b''

        # 填充到4字节边界
        padding_len = (4 - (len(data) % 4)) % 4
        data = data + b'\x00' * padding_len

        # 属性头: 类型 (2 bytes) + 长度 (2 bytes)
        header = struct.pack('!HH', attr_type, len(data) - padding_len)

        return header + data

    def _compute_integrity(self, message: bytes, username: str, password: str,
                          realm: str = None) -> bytes:
        """计算 MESSAGE-INTEGRITY (HMAC-SHA1)"""
        # 构造长期密钥
        if realm:
            key = (username + ":" + realm + ":" + password).encode('utf-8')
        else:
            key = password.encode('utf-8')

        # 计算整个消息的 HMAC-SHA1
        hmac_value = hmac.new(key, message, hashlib.sha1).digest()
        return hmac_value


def decode_stun_message(data: bytes) -> Optional[Tuple[STUNMessage, bytes]]:
    """解码 STUN 消息"""
    if len(data) < 20:
        return None

    # 解析消息头
    msg_type = struct.unpack('!H', data[0:2])[0]
    msg_class = (msg_type >> 12) & 0x0F
    msg_method = msg_type & 0x0FFF

    msg_len = struct.unpack('!H', data[2:4])[0]
    magic_cookie = struct.unpack('!I', data[4:8])[0]

    if magic_cookie != STUN_MAGIC_COOKIE:
        return None

    transaction_id = data[8:20]

    # 解析属性
    attributes = {}
    offset = 20
    end = offset + msg_len

    while offset < end:
        if offset + 4 > end:
            break

        attr_type = struct.unpack('!H', data[offset:offset+2])[0]
        attr_len = struct.unpack('!H', data[offset+2:offset+4])[0]
        offset += 4

        # 读取属性值
        attr_value = data[offset:offset+attr_len]
        offset += attr_len

        # 填充到4字节边界
        padding_len = (4 - (attr_len % 4)) % 4
        offset += padding_len

        # 解码属性值
        if attr_type == STUN_ATTR_MAPPED_ADDRESS:
            if len(attr_value) >= 8:
                family = attr_value[0]
                port = struct.unpack('!H', attr_value[2:4])[0]
                if family == 0x01:  # IPv4
                    ip = socket.inet_ntop(socket.AF_INET, attr_value[4:8])
                elif family == 0x02:  # IPv6
                    ip = socket.inet_ntop(socket.AF_INET6, attr_value[4:20])
                else:
                    continue
                attributes[attr_type] = (family, port, ip)
        elif attr_type == STUN_ATTR_XOR_MAPPED_ADDRESS:
            if len(attr_value) >= 8:
                family = attr_value[0]
                port = struct.unpack('!H', attr_value[2:4])[0]
                # XOR 解码端口
                port ^= (STUN_MAGIC_COOKIE >> 16) & 0xFFFF
                # XOR 解码 IP
                if family == 0x01:  # IPv4
                    ip_bytes = attr_value[4:8]
                    cookie_bytes = struct.pack('!I', STUN_MAGIC_COOKIE)
                    ip_bytes = bytes([ip_bytes[i] ^ cookie_bytes[i] for i in range(4)])
                    ip = socket.inet_ntop(socket.AF_INET, ip_bytes)
                elif family == 0x02:  # IPv6
                    ip_bytes = attr_value[4:20]
                    cookie_bytes = struct.pack('!I', STUN_MAGIC_COOKIE) + transaction_id
                    ip_bytes = bytes([ip_bytes[i] ^ cookie_bytes[i] for i in range(16)])
                    ip = socket.inet_ntop(socket.AF_INET6, ip_bytes)
                else:
                    continue
                attributes[attr_type] = (family, port, ip)
        elif attr_type == STUN_ATTR_USERNAME:
            attributes[attr_type] = attr_value.decode('utf-8')
        elif attr_type == STUN_ATTR_REALM:
            attributes[attr_type] = attr_value.decode('utf-8')
        elif attr_type == STUN_ATTR_NONCE:
            attributes[attr_type] = attr_value.decode('utf-8')
        elif attr_type == STUN_ATTR_MESSAGE_INTEGRITY:
            attributes[attr_type] = attr_value
        elif attr_type == STUN_ATTR_ERROR_CODE:
            if len(attr_value) >= 4:
                error_code = struct.unpack('!H', attr_value[2:4])[0]
                error_class = (error_code >> 8) & 0x07
                error_num = error_code & 0xFF
                reason = attr_value[4:].decode('utf-8')
                attributes[attr_type] = (error_class, error_num, reason)
        elif attr_type == STUN_ATTR_FINGERPRINT:
            if len(attr_value) == 4:
                attributes[attr_type] = struct.unpack('!I', attr_value)[0]
        else:
            attributes[attr_type] = attr_value

    message = STUNMessage(msg_method, msg_class, transaction_id, attributes)
    return message, data[:20+msg_len]


class STUNServer:
    """STUN 服务器"""

    def __init__(self, host: str = "0.0.0.0", port: int = 3478,
                 username: str = "123", password: str = "123",
                 realm: str = "ims.stun.server"):
        """
        初始化 STUN 服务器

        Args:
            host: 监听地址
            port: 监听端口 (默认 3478)
            username: STUN 认证用户名
            password: STUN 认证密码
            realm: STUN 认证域
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.realm = realm
        self.logger = logging.getLogger("STUN")

        # UDP socket
        self.socket: Optional[socket.socket] = None
        self.running = False
        self.transport: Optional[asyncio.DatagramTransport] = None
        self.protocol: Optional[asyncio.DatagramProtocol] = None

    async def start(self):
        """启动 STUN 服务器"""
        loop = asyncio.get_event_loop()

        # 创建 UDP socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.host, self.port))

        # 创建传输和协议
        self.transport, self.protocol = await loop.create_datagram_endpoint(
            lambda: STUNServerProtocol(self),
            sock=self.socket
        )

        self.running = True
        self.logger.info(f"[STUN] Server started on {self.host}:{self.port}")
        self.logger.info(f"[STUN] Authentication: username={self.username}, password={self.password}")

    async def stop(self):
        """停止 STUN 服务器"""
        if self.transport:
            self.transport.close()
            self.transport = None

        if self.socket:
            self.socket.close()
            self.socket = None

        self.running = False
        self.logger.info("[STUN] Server stopped")

    def handle_binding_request(self, msg: STUNMessage, addr: Tuple[str, int]):
        """处理绑定请求"""
        try:
            # 检查是否需要认证
            require_auth = STUN_ATTR_USERNAME in msg.attributes
            username = msg.attributes.get(STUN_ATTR_USERNAME)

            if require_auth:
                # 验证认证信息
                integrity = msg.attributes.get(STUN_ATTR_MESSAGE_INTEGRITY)
                if not integrity:
                    # 缺少 MESSAGE-INTEGRITY，返回 401
                    self.send_error_response(msg, addr, 401, "Unauthorized")
                    return

                if username != self.username:
                    # 用户名错误
                    self.send_error_response(msg, addr, 401, "Unauthorized")
                    return

                # 验证 MESSAGE-INTEGRITY
                # 需要重新编码消息计算完整性
                encoded = msg.encode(include_integrity=False, username=username,
                                   password=self.password, realm=self.realm)
                computed_integrity = msg._compute_integrity(
                    encoded + bytes([0, 0, 0, 0]),  # 长度字段补零
                    username, self.password, self.realm
                )

                if computed_integrity != integrity:
                    self.send_error_response(msg, addr, 401, "Unauthorized")
                    return

            # 构造响应
            response = STUNMessage(
                msg_type=STUN_METHOD_BINDING,
                msg_class=STUN_CLASS_SUCCESS,
                transaction_id=msg.transaction_id
            )

            # 添加 XOR-MAPPED-ADDRESS 属性
            client_ip, client_port = addr
            response.attributes[STUN_ATTR_XOR_MAPPED_ADDRESS] = (
                0x01,  # IPv4
                client_port,
                client_ip
            )

            # 添加 SOFTWARE 属性
            response.attributes[STUN_ATTR_SOFTWARE] = "IMS-STUN-SERVER/1.0"

            # 如果有认证，添加 MESSAGE-INTEGRITY
            if require_auth:
                response.attributes[STUN_ATTR_REALM] = self.realm
                encoded = response.encode(include_integrity=False, username=username,
                                          password=self.password, realm=self.realm)
                # 计算完整性 (注意：编码时长度字段需要补零)
                integrity = response._compute_integrity(
                    encoded + bytes([0, 0, 0, 0]),
                    username, self.password, self.realm
                )
                response.attributes[STUN_ATTR_MESSAGE_INTEGRITY] = integrity
                # 重新编码（这次包含正确的完整性值）
                response_data = response.encode(include_integrity=True, username=username,
                                              password=self.password, realm=self.realm)
            else:
                response_data = response.encode()

            # 发送响应
            if self.transport:
                self.transport.sendto(response_data, addr)
                self.logger.info(f"[STUN] Binding response sent to {addr}: "
                              f"MAPPED-ADDRESS={client_ip}:{client_port}")

        except Exception as e:
            self.logger.error(f"[STUN] Error handling binding request: {e}")

    def send_error_response(self, msg: STUNMessage, addr: Tuple[str, int],
                           code: int, reason: str):
        """发送错误响应"""
        try:
            error_class = code // 100
            error_num = code % 100

            response = STUNMessage(
                msg_type=STUN_METHOD_BINDING,
                msg_class=STUN_CLASS_ERROR,
                transaction_id=msg.transaction_id
            )

            # 添加 ERROR-CODE 属性
            response.attributes[STUN_ATTR_ERROR_CODE] = (error_class, error_num, reason)

            # 添加 SOFTWARE 属性
            response.attributes[STUN_ATTR_SOFTWARE] = "IMS-STUN-SERVER/1.0"

            response_data = response.encode()

            if self.transport:
                self.transport.sendto(response_data, addr)
                self.logger.warning(f"[STUN] Error response sent to {addr}: {code} {reason}")

        except Exception as e:
            self.logger.error(f"[STUN] Error sending error response: {e}")


class STUNServerProtocol(asyncio.DatagramProtocol):
    """STUN 服务器协议处理器"""

    def __init__(self, server: STUNServer):
        self.server = server
        self.logger = logging.getLogger("STUN")

    def connection_made(self, transport):
        """连接建立"""
        self.transport = transport

    def datagram_received(self, data, addr):
        """收到数据报"""
        try:
            # 尝试解析 STUN 消息
            result = decode_stun_message(data)
            if not result:
                self.logger.debug(f"[STUN] Invalid STUN message from {addr}")
                return

            msg, _ = result
            self.logger.debug(f"[STUN] Received message: type={msg.msg_type:04x}, "
                            f"class={msg.msg_class}, addr={addr}")

            # 处理绑定请求
            if msg.msg_type == STUN_METHOD_BINDING and msg.msg_class == STUN_CLASS_REQUEST:
                self.server.handle_binding_request(msg, addr)
            else:
                self.logger.debug(f"[STUN] Unsupported message type: {msg.msg_type:04x}")

        except Exception as e:
            self.logger.error(f"[STUN] Error processing datagram: {e}")


def init_stun_server(host: str = "0.0.0.0", port: int = 3478,
                     username: str = "123", password: str = "123",
                     realm: str = "ims.stun.server") -> STUNServer:
    """初始化 STUN 服务器"""
    return STUNServer(host=host, port=port, username=username,
                     password=password, realm=realm)
