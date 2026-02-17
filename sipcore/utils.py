# sipcore/utils.py
import random
import string
from datetime import datetime, timezone

def gen_tag(n=8):
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))

def sip_date():
    # RFC 1123 date
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

def _host_port_from_sip_uri(uri: str) -> tuple[str, int]:
    """
    从SIP URI中提取主机和端口

    例如：
    - sip:1002@192.168.1.60:5066;transport=udp -> ("192.168.1.60", 5066)
    - sip:192.168.1.60:5066 -> ("192.168.1.60", 5066)
    - sip:1002@192.168.1.60 -> ("192.168.1.60", 5060)
    """
    u = uri
    if u.startswith("sip:"):
        u = u[4:]
    # 去掉用户@部分
    if "@" in u:
        u = u.split("@", 1)[1]
    # 去掉参数
    if ";" in u:
        u = u.split(";", 1)[0]
    # 提取端口
    if ":" in u:
        host, port = u.rsplit(":", 1)
        try:
            return host, int(port)
        except:
            return host, 5060
    return u, 5060

