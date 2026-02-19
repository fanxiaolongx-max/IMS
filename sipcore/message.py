# sipcore/message.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional

CRLF = "\r\n"

@dataclass
class SIPMessage:
    start_line: str
    headers: Dict[str, List[str]] = field(default_factory=dict)
    body: bytes = b""

    def get(self, name: str) -> Optional[str]:
        vals = self.headers.get(name.lower())
        return vals[0] if vals else None

    def add_header(self, name: str, value: str):
        self.headers.setdefault(name.lower(), []).append(value)

    # def to_bytes(self) -> bytes:
    #     lines = [self.start_line]
    #     for k, vs in self.headers.items():
    #         for v in vs:
    #             lines.append(f"{self._canon(k)}: {v}")
    #     lines.append("")  # empty line before body
    #     head = (CRLF.join(lines)).encode()
    #     return head + (self.body or b"")

    def to_bytes(self) -> bytes:
        lines = [self.start_line]
        for k, vs in self.headers.items():
            for v in vs:
                lines.append(f"{self._canon(k)}: {v}")
        # Header 部分结尾要加两个 CRLF：一个 join 的结尾 + 一个额外空行
        data = CRLF.join(lines) + CRLF * 2
        return data.encode() + (self.body or b"")

    @staticmethod
    def _canon(k: str) -> str:
        """
        规范化SIP头字段名称，使用RFC 3261规定的标准格式
        
        RFC 3261规定的标准头字段名称：
        - Call-ID (不是 Call-Id)
        - CSeq (不是 Cseq)
        - Record-Route (标准格式)
        - 其他字段：每个单词首字母大写，用连字符连接
        """
        # RFC 3261标准头字段名称映射
        standard_headers = {
            "call-id": "Call-ID",
            "cseq": "CSeq",
            "www-authenticate": "WWW-Authenticate",
            "max-forwards": "Max-Forwards",
            "content-type": "Content-Type",
            "content-length": "Content-Length",
            "record-route": "Record-Route",
            "contact": "Contact",
            "user-agent": "User-Agent",
            "allow": "Allow",
            "supported": "Supported",
            "require": "Require",
            "proxy-require": "Proxy-Require",
            "proxy-authorization": "Proxy-Authorization",
            "authorization": "Authorization",
            "from": "From",
            "to": "To",
            "via": "Via",
            "route": "Route",
            "rseq": "RSeq",
            "rack": "RAck",
        }
        
        # 转换为小写查找
        k_lower = k.lower()
        if k_lower in standard_headers:
            return standard_headers[k_lower]
        
        # 对于不在标准列表中的字段，使用标准格式：每个单词首字母大写
        return "-".join(p.capitalize() for p in k.split("-"))
