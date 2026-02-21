# -*- coding: utf-8 -*-
"""
H.264 RTP 解析与 fMP4 打包，供媒体流监听后端使用。
从有视频起在后台打包为 init + fragment，前台直接接收并 append 到 MSE 播放。
"""
import base64
import struct
from typing import Optional, Tuple, List, Any


def _u32be(b: bytearray, v: int) -> None:
    b.append((v >> 24) & 0xFF)
    b.append((v >> 16) & 0xFF)
    b.append((v >> 8) & 0xFF)
    b.append(v & 0xFF)


def _write_u32be(arr: bytearray, offset: int, val: int) -> None:
    arr[offset] = (val >> 24) & 0xFF
    arr[offset + 1] = (val >> 16) & 0xFF
    arr[offset + 2] = (val >> 8) & 0xFF
    arr[offset + 3] = val & 0xFF


def _write_box(buf: bytearray, box_type: str, payload: bytes) -> None:
    length = 8 + len(payload)
    _u32be(buf, length)
    buf.extend(box_type.encode('ascii'))
    buf.extend(payload)


def build_avcc(sps: bytes, pps: bytes) -> bytes:
    if not sps or not pps or len(sps) < 4 or len(pps) < 1:
        return b''
    out = bytearray()
    out.append(1)
    out.append(sps[1])
    out.append(sps[2])
    out.append(sps[3])
    out.append(0xFF)
    out.append(0xE1)
    _u32be(out, len(sps))
    out.extend(sps)
    out.append(1)
    _u32be(out, len(pps))
    out.extend(pps)
    return bytes(out)


def build_mp4_init(sps: bytes, pps: bytes) -> bytes:
    """构建 fMP4 init segment（ftyp + moov），与前端 JS 结构一致。"""
    if not sps or not pps or len(sps) < 7 or len(pps) < 4:
        return b''
    avcc = build_avcc(sps, pps)
    if not avcc:
        return b''
    # avcC box
    avcc_box = bytearray()
    _u32be(avcc_box, 8 + len(avcc))
    avcc_box.extend(b'avcC')
    avcc_box.extend(avcc)
    # avc1 sample entry (86 bytes fixed + avcC box)
    avc1_payload = bytearray(86)
    avc1_payload[78:86] = b'\x00\x48\x00\x00\x00\x48\x00\x00\x00\x00\x00\x00'
    avc1_payload.extend(avcc_box)
    # stsd
    stsd_payload = bytearray(8)
    struct.pack_into('>I', stsd_payload, 4, 1)
    stsd_payload.extend(avc1_payload)
    stsd_box = bytearray()
    _write_box(stsd_box, 'stsd', bytes(stsd_payload))
    # stts, stsc, stsz, stco (empty)
    stts = bytearray(12)
    stsc = bytearray(12)
    stsz = bytearray(16)
    stco = bytearray(8)
    stbl = bytearray()
    _write_box(stbl, 'stsd', stsd_payload)
    _write_box(stbl, 'stts', bytes(stts))
    _write_box(stbl, 'stsc', bytes(stsc))
    _write_box(stbl, 'stsz', bytes(stsz))
    _write_box(stbl, 'stco', bytes(stco))
    # dinf (dref)
    dref_payload = bytes([0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0x0c,
                          0x75, 0x72, 0x6c, 0x20, 0, 0, 0, 1])
    dref_box = bytearray()
    _write_box(dref_box, 'dref', dref_payload)
    dinf = bytearray()
    _write_box(dinf, 'dinf', bytes(dref_box))
    # minf: vmhd + dinf + stbl
    vmhd = bytes([0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    minf = bytearray()
    _write_box(minf, 'vmhd', vmhd)
    minf.extend(dinf)
    minf.extend(struct.pack('>I', 8 + len(stbl)))
    minf.extend(b'stbl')
    minf.extend(stbl)
    # mdia: mdhd + hdlr + minf
    mdhd = bytearray(32)
    struct.pack_into('>IIII', mdhd, 4, 0, 0, 90000, 0)
    mdhd[20:22] = b'\x55\xc4'
    hdlr_payload = bytes([0, 0, 0, 0, 0, 0, 0, 0, 0x76, 0x69, 0x64, 0x65,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          0x56, 0x69, 0x64, 0x65, 0x6f, 0x48, 0x61, 0x6e, 0x64, 0x6c, 0x65, 0x72, 0x00])
    mdia = bytearray()
    _write_box(mdia, 'mdhd', bytes(mdhd))
    _write_box(mdia, 'hdlr', hdlr_payload)
    _write_box(mdia, 'minf', bytes(minf))
    # trak: tkhd + mdia
    tkhd = bytearray(92)
    tkhd[6] = 0x03
    struct.pack_into('>III', tkhd, 12, 1, 0, 1)
    struct.pack_into('>III', tkhd, 48, 0x00010000, 0, 0)
    struct.pack_into('>III', tkhd, 64, 0x00010000, 0, 0)
    struct.pack_into('>I', tkhd, 72, 0x0140)
    struct.pack_into('>I', tkhd, 76, 0x00e0)
    trak = bytearray()
    _write_box(trak, 'tkhd', bytes(tkhd))
    _write_box(trak, 'mdia', bytes(mdia))
    # mvex (trex)
    trex = bytes([0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0,
                  0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    mvex = bytearray()
    _write_box(mvex, 'trex', trex)
    # mvhd
    mvhd = bytearray(108)
    struct.pack_into('>IIII', mvhd, 4, 0, 0, 90000, 0)
    struct.pack_into('>II', mvhd, 16, 0x10000, 0x100)
    struct.pack_into('>I', mvhd, 32, 2)
    struct.pack_into('>IIII', mvhd, 52, 0x00010000, 0, 0, 0)
    struct.pack_into('>IIII', mvhd, 68, 0x00010000, 0, 0, 0)
    moov = bytearray()
    _write_box(moov, 'mvhd', bytes(mvhd))
    _write_box(moov, 'mvex', bytes(mvex))
    _write_box(moov, 'trak', bytes(trak))
    # ftyp
    ftyp_payload = b'isom\x00\x00\x00\x01isomiso5mp41'
    ftyp = bytearray()
    _write_box(ftyp, 'ftyp', ftyp_payload)
    out = bytearray()
    out.extend(ftyp)
    _u32be(out, 8 + len(moov))
    out.extend(b'moov')
    out.extend(moov)
    return bytes(out)


def build_mp4_fragment(nal_bytes: bytes, dts: int, is_keyframe: bool) -> bytes:
    """单个 NAL 打包为 moof + mdat fragment。mdat=8+4+n(长度前缀+NAL)；trun sample_size=4+n。"""
    n = len(nal_bytes)
    sample_size = 4 + n  # AVCC: 4-byte length + NAL
    mdat_len = 8 + sample_size
    mdat = bytearray()
    _u32be(mdat, mdat_len)
    mdat.extend(b'mdat')
    _u32be(mdat, n)
    mdat.extend(nal_bytes)
    sample_duration = 3000
    trun = bytearray(8 + 4 + 4 + 4 + 4 + 4 + 4)
    _write_u32be(trun, 0, len(trun))
    trun[4:8] = b'trun'
    trun[8:12] = b'\x00\x00\x0f\x01'
    _write_u32be(trun, 12, 1)
    _write_u32be(trun, 16, 0)
    _write_u32be(trun, 20, 0x02000000 if is_keyframe else 0)
    _write_u32be(trun, 24, sample_duration)
    _write_u32be(trun, 28, sample_size)
    tfhd = bytearray(8 + 16)
    _write_u32be(tfhd, 0, 8 + 16)
    tfhd[4:8] = b'tfhd'
    tfhd[8:12] = b'\x00\x00\x00\x2e'
    _write_u32be(tfhd, 12, 1)
    _write_u32be(tfhd, 16, 1)
    tfdt = bytearray(8 + 8)
    _write_u32be(tfdt, 0, 8 + 8)
    tfdt[4:8] = b'tfdt'
    tfdt[8:12] = b'\x00\x00\x00\x01'
    _write_u32be(tfdt, 12, int(dts) & 0xFFFFFFFF)
    traf = bytearray()
    _write_box(traf, 'tfhd', bytes(tfhd))
    _write_box(traf, 'tfdt', bytes(tfdt))
    _write_box(traf, 'trun', bytes(trun))
    mfhd = bytearray(12)
    _write_u32be(mfhd, 0, 12)
    mfhd[4:8] = b'mfhd'
    _write_u32be(mfhd, 8, 0)
    mfhd_len = len(mfhd)
    tfhd_box_len = 8 + len(tfhd)
    tfdt_box_len = 8 + len(tfdt)
    traf_len = 8 + len(traf)
    moof_len = 8 + (8 + mfhd_len) + traf_len
    data_offset = moof_len
    # moof: [8 moof][12 mfhd][4 traf_len][4 traf][traf...]; trun starts at 8+12+8 + tfhd_box + tfdt_box
    trun_start_in_moof = 8 + (8 + mfhd_len) + 8 + tfhd_box_len + tfdt_box_len
    patch_off = trun_start_in_moof + 8 + 4 + 4  # trun box header 8, version+flags 4, sample_count 4
    moof = bytearray()
    _u32be(moof, moof_len)
    moof.extend(b'moof')
    moof.extend(mfhd)
    moof.extend(struct.pack('>I', traf_len))
    moof.extend(b'traf')
    moof.extend(traf)
    if patch_off + 4 <= len(moof):
        struct.pack_into('>I', moof, patch_off, data_offset)
    return bytes(moof) + bytes(mdat)


class H264StreamProcessor:
    """按流维护 SPS/PPS/FU-A 重组，并产出 (sps, pps, nal, is_keyframe) 事件。"""
    def __init__(self) -> None:
        self.sps: Optional[bytes] = None
        self.pps: Optional[bytes] = None
        self.fua_buffer: Optional[Tuple[int, List[bytes]]] = None  # (nal_header, chunks)
        self.dts: int = 0

    def feed(self, rtp_payload: bytes) -> List[Tuple[Optional[bytes], Optional[bytes], Optional[bytes], bool]]:
        """
        喂入一个 RTP 载荷（H.264），返回本包产生的列表：
        [(sps, pps, nal, is_keyframe), ...]
        其中 sps/pps 仅在本次更新时非 None；nal 为可解码的一帧（类型 1 或 5）；is_keyframe 为是否为 IDR。
        """
        out: List[Tuple[Optional[bytes], Optional[bytes], Optional[bytes], bool]] = []
        if len(rtp_payload) < 2:
            return out
        b0 = rtp_payload[0] & 0x1F
        if 1 <= b0 <= 23:
            self.fua_buffer = None
            if b0 == 7:
                if not self.sps or len(rtp_payload) > len(self.sps):
                    self.sps = bytes(rtp_payload)
                out.append((self.sps, None, None, False))
            elif b0 == 8:
                if not self.pps or len(rtp_payload) > len(self.pps):
                    self.pps = bytes(rtp_payload)
                out.append((None, self.pps, None, False))
            elif b0 in (1, 5):
                out.append((None, None, bytes(rtp_payload), b0 == 5))
        elif b0 in (28, 29) and len(rtp_payload) >= 3:
            fu_header = rtp_payload[1]
            real_type = fu_header & 0x1F
            start = (fu_header & 0x80) != 0
            end = (fu_header & 0x40) != 0
            nal_header = (rtp_payload[0] & 0xE0) | real_type
            fragment = rtp_payload[2:]
            if start:
                self.fua_buffer = (nal_header, [fragment])
            elif self.fua_buffer and self.fua_buffer[0] == nal_header:
                self.fua_buffer[1].append(fragment)
            if end and self.fua_buffer and self.fua_buffer[0] == nal_header:
                full = bytes([self.fua_buffer[0]]) + b''.join(self.fua_buffer[1])
                self.fua_buffer = None
                if real_type == 7:
                    if not self.sps or len(full) > len(self.sps):
                        self.sps = full
                    out.append((self.sps, None, None, False))
                elif real_type == 8:
                    if not self.pps or len(full) > len(self.pps):
                        self.pps = full
                    out.append((None, self.pps, None, False))
                elif real_type in (1, 5):
                    out.append((None, None, full, real_type == 5))
        return out

    def next_dts(self, delta: int = 3000) -> int:
        d = self.dts
        self.dts += delta
        return d
