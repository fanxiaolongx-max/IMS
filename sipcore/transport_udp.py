# sipcore/transport_udp.py
import asyncio
from typing import Callable
from .logger import get_logger

log = get_logger()

class UDPServer:
    def __init__(self, local=("0.0.0.0", 5060), handler: Callable[[bytes, tuple, asyncio.DatagramTransport], None]=None):
        self.local = local
        self.handler = handler
        self.transport: asyncio.DatagramTransport | None = None

    async def start(self):
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(
            lambda: _UDPProtocol(self.handler, self),
            local_addr=self.local
        )

class _UDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, handler, server_ref=None):
        self.handler = handler
        self.transport = None
        self.server_ref = server_ref  # 引用UDPServer实例

    def connection_made(self, transport):
        self.transport = transport
        sock = transport.get_extra_info("sockname")
        log.info(f"UDP server listening on {sock}")
        # 通知UDPServer保存transport引用
        if self.server_ref:
            self.server_ref.transport = transport

    def datagram_received(self, data, addr):
        if self.handler:
            self.handler(data, addr, self.transport)

    def error_received(self, exc):
        # UDP 发送错误（目标不可达等）
        # errno 65: No route to host (macOS/BSD)
        # errno 113: No route to host (Linux)  
        # errno 101: Network is unreachable
        if hasattr(exc, 'errno') and exc.errno in (65, 113, 101):
            # 目标主机不可达是常见的网络状况（客户端下线、断网等）
            # 使用 WARNING 而不是 ERROR，因为这不是服务器错误
            log.warning(f"UDP: Target unreachable - {exc}")
        else:
            # 其他 UDP 错误
            log.error(f"UDP server error: {exc}")
