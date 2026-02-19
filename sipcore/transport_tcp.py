"""
SIP over TCP 传输层

用于通过 TCP 接收/发送 SIP 消息，便于与 Cloudflare Tunnel 等只支持 TCP 的出口配合。
与 UDP 共用同一套 on_datagram 风格的处理逻辑；addr 为对端 (host, port)，transport 为该连接的发送封装。
"""

import asyncio
from typing import Callable, Optional, Tuple

from .logger import get_logger

log = get_logger()


def _content_length_from_headers(head_raw: bytes) -> int:
    """从 SIP 头部分解析 Content-Length，未找到则返回 0。"""
    for line in head_raw.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            try:
                return int(line.split(b":", 1)[1].strip())
            except (ValueError, IndexError):
                return 0
    return 0


class _TCPTransport:
    """对单条 TCP 连接的发送封装，兼容 UDP transport 的 sendto(data, addr) 接口。"""

    def __init__(self, transport: asyncio.Transport, peer: Tuple[str, int]):
        self._transport = transport
        self._peer = peer

    def sendto(self, data: bytes, addr: Tuple[str, int]):
        self._transport.write(data)

    def get_extra_info(self, name: str, default=None):
        if name == "peername":
            return self._peer
        return self._transport.get_extra_info(name, default)


class _SIPTCPProtocol(asyncio.Protocol):
    """按 SIP 消息边界（Content-Length）从 TCP 流中拆包并交给 handler。"""

    def __init__(self, handler: Callable, server_ref):
        self.handler = handler
        self.server_ref = server_ref
        self._buffer = b""
        self._transport: Optional[asyncio.Transport] = None
        self._peer: Optional[Tuple[str, int]] = None

    def connection_made(self, transport: asyncio.BaseTransport):
        self._transport = transport
        self._peer = transport.get_extra_info("peername")
        log.info(f"[SIP/TCP] 连接建立: {self._peer}")

    def data_received(self, data: bytes):
        self._buffer += data
        while True:
            msg_bytes, rest = self._read_one_message(self._buffer)
            if msg_bytes is None:
                break
            self._buffer = rest
            if self.handler and self._peer:
                tcp_transport = _TCPTransport(self._transport, self._peer)  # type: ignore
                try:
                    self.handler(msg_bytes, self._peer, tcp_transport)
                except Exception as e:
                    log.error(f"[SIP/TCP] handler error: {e}")

    def _read_one_message(self, buf: bytes) -> Tuple[Optional[bytes], bytes]:
        """从 buf 中读出一条完整 SIP 消息，返回 (message_bytes, remaining_buffer)。"""
        pos = buf.find(b"\r\n\r\n")
        if pos == -1:
            return None, buf
        head = buf[:pos]
        body_start = pos + 4
        cl = _content_length_from_headers(head)
        if cl < 0:
            return None, buf
        total = body_start + cl
        if len(buf) < total:
            return None, buf
        return buf[:total], buf[total:]

    def connection_lost(self, exc):
        log.info(f"[SIP/TCP] 连接关闭: {self._peer}, exc={exc}")


class TCPServer:
    """SIP over TCP 服务端，监听指定地址并派发到与 UDP 相同的 handler。"""

    def __init__(self, local: Tuple[str, int] = ("0.0.0.0", 5060), handler: Callable = None):
        self.local = local
        self.handler = handler
        self._server: Optional[asyncio.Server] = None

    async def start(self):
        self._server = await asyncio.get_event_loop().create_server(
            lambda: _SIPTCPProtocol(self.handler, self),
            self.local[0],
            self.local[1],
        )
        log.info(f"[SIP/TCP] 监听 {self.local[0]}:{self.local[1]}")

    def close(self):
        if self._server:
            self._server.close()

    async def wait_closed(self):
        if self._server:
            await self._server.wait_closed()
