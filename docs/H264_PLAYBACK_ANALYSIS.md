# H.264 监看播放问题分析（前端 vs 后端）

本文仅做原因分析，不修改代码。用于判断“有画面但卡顿 / 不出图 / 解码报错”等问题的根因更可能在前端还是后端。

---

## 1. 数据流概览

```
终端 RTP (UDP) → media_relay 转发线程 → [stream_channel Queue + history_buffer deque]
                                              ↓
MML WebSocket 新连接 ← get_channel_buffered_packets(history) + stream_channel.get()
                                              ↓
build_stats_from_rtp() → JSON { rtp_payload_b64, rtp_timestamp, codec, ... }
                                              ↓
前端 ws.onmessage → handleRtpPayloadForStream(streamType, payloadB64, codec, payloadType, rtpTimestamp)
                                              ↓
NAL 解析 (单 NAL / FU-A) → SPS/PPS → initVideoDecoderIfReadyForStream → decodeAndDrawH264ForStream
                                              ↓
VideoDecoder.decode(EncodedVideoChunk) → output(frame) → ctx.drawImage(frame) → 画布
```

---

## 2. 后端可能的问题点

### 2.1 【高】RTP 载荷超过 2000 字节即不发给前端

- **位置**：`web/mml_server.py` 里 `build_stats_from_rtp`，约 3291–3293 行。
- **逻辑**：`if rtp_payload and len(rtp_payload) <= 2000` 才设置 `rtp_payload_b64`，否则前端收不到该包。
- **影响**：
  - H.264 **单 NAL 模式**下，一个 IDR 关键帧往往在一个 RTP 包里，常见几 KB 到几十 KB，**几乎全部 > 2000**，会被后端直接丢弃。
  - 前端永远收不到关键帧 → 一直“等待关键帧”，或“已送帧:4 已解码:0”（只收到 P 帧、解码器要求先有关键帧）。
- **结论**：若终端或编码器使用**单 NAL 模式**发关键帧，这是**后端**导致的“不出图/卡在等待关键帧”的主要原因。

### 2.2 【低】历史包是否推送

- **位置**：同上文件，`history_limit = 0` 时不再推送历史；若仍为 2000，则新连接会收到大量历史包。
- **现象**：若日志里仍出现“已发送历史包 xxx 个”，说明当前运行的服务未用 `history_limit=0` 或未重启，重开监看会先快放旧帧再实时（此前已讨论过）。
- **结论**：属于**后端**策略问题，与“H.264 解码/出图”无直接关系，但影响观感。

### 2.3 【低】RTP 时间戳与包顺序

- **实现**：后端从 RTP 头 4–7 字节读 32 位时间戳，随 `rtp_timestamp` 下发；包顺序由 Queue 保证，历史由 deque 按旧→新发送。
- **结论**：时间戳与顺序在后端是正确传递的，**不是**当前播放问题的主因。

---

## 3. 前端可能的问题点

### 3.1 【中】只处理 NAL type 1 和 5，且必须先有关键帧

- **位置**：`decodeAndDrawH264ForStream`：只对 `nalType === 1`（非 IDR slice）和 `nalType === 5`（IDR）调用解码；且 `hasKey` 为 false 时丢弃所有非关键帧。
- **影响**：若因后端 2000 字节限制导致关键帧从未到达，前端会一直不送 P 帧，界面表现为“等待关键帧”或“已送帧:4 已解码:0”。
- **结论**：行为符合 H.264 解码规范，根因仍是**后端未把大关键帧包发下来**。

### 3.2 【低】SPS/PPS 与解码器重建

- **逻辑**：收到 SPS/PPS 若与当前不同则替换并 `initVideoDecoderIfReadyForStream`，会先 `dec.close()` 再建新解码器，避免 re-INVITE 后参数集变化导致的花屏/报错。
- **结论**：实现合理，**不是**主要问题来源。

### 3.3 【低】时间戳与 duration

- **逻辑**：有 `rtp_timestamp` 时用 `rtp_timestamp * 1e6 / 90000` 作为 decode 时间戳；否则用固定 33ms 递进。H.264 解码 chunk 使用 `duration: 33333`（微秒）。
- **结论**：能缓解“长时间动一下”的卡顿；若仍卡顿，更可能是网络/缓冲或关键帧缺失导致解码器无法正常输出，而非单纯时间戳错误。

### 3.4 【低】FU-A 重组与 NAL 类型

- **逻辑**：FU-A 按 S/E 位重组，`realType` 从 FU header 取；重组后的 NAL 首字节为 `(payload[0]&0xE0)|realType`，类型正确。
- **结论**：FU-A 路径正确，**不是**主要问题。

---

## 4. 综合判断表

| 现象 | 更可能位置 | 简要原因 |
|------|------------|----------|
| 一直“等待关键帧”、或“已送帧:N 已解码:0” | **后端** | 关键帧 RTP 载荷 > 2000 被丢弃，前端从未收到 IDR |
| 有图但“很长时间动一下” | 后端 + 前端 | 后端丢大包导致关键帧少；前端已用 RTP 时间戳，若仍卡可再查解码器缓冲/刷新策略 |
| 关闭监看再打开先快放旧帧再实时 | **后端** | 新连接仍推送历史缓冲（未设 history_limit=0 或未重启） |
| re-INVITE 后花屏/解码器报错 | 前端 | 已通过 SPS/PPS 变化重建解码器缓解；若仍出现需看是否在同一流内混用多组 SPS/PPS |
| 两路监看串画面 | 前端 | 已用 monitoringCallId/currentMonitorCallId 做隔离 |

---

## 5. 建议的优先排查/修复顺序（供后续改代码时参考）

1. **后端**：放宽或取消“仅当 `len(rtp_payload) <= 2000` 才带 `rtp_payload_b64`”的限制（例如提高到 64KB 或按 codec 区分），确保关键帧大包能下发。
2. **后端**：确认 `history_limit = 0` 已生效且服务已重启，避免重开监看时快放历史。
3. **前端**：在无 RTP 时间戳时保持当前递进策略；若后续需要“仅实时、不播历史”，可配合后端不推历史或前端忽略早于连接建立时刻的 RTP 时间戳（可选）。

---

## 6. 控制台 `AbortError: Aborted due to close()` 分析（H.264 有、H.265 没有）

### 6.1 报错来源

- **控制台位置**：约 `(index):5138`，对应代码是 `initVideoDecoderIfReadyForStream` 里的一行：  
  `if (dec) { try { dec.close().catch(function() {}); } catch (e) {} ... }`
- **表面**：是在“关闭旧解码器”时触发的。
- **实际**：`AbortError: Aborted due to close()` 来自 **`VideoDecoder.decode()` 返回的 Promise 被拒绝**，不是来自 `dec.close()` 的 Promise。
- **WebCodecs 行为**：调用 `dec.close()` 时，解码器会中止所有尚未完成的 `decode()`；这些已提交但未完成的 `decode()` 的 Promise 会被 reject，reason 为 `AbortError: Aborted due to close()`。当前代码只对 **`dec.close()`** 做了 `.catch(function() {})`，没有对 **`dec.decode()`** 的返回值做 `.catch()`，所以一旦在 close 之前有过 decode 调用，close 时就会产生“未捕获的 Promise 拒绝”，控制台就会打出这条 AbortError。

### 6.2 为何 H.264 容易出、H.265 不出

- **H.264**：  
  - 每次收到 **SPS（b0===7）** 或 **PPS（b0===8）** 都会调 `initVideoDecoderIfReadyForStream(st)`；若当前已有解码器且 SPS/PPS 有更新，就会先 `dec.close()` 再建新解码器。  
  - 同一路流里，**SPS/PPS 和 slice（type 1/5）会交错到达**：可能先收到若干 slice 并调用了 `decode()`，随后才收到 SPS 或 PPS，此时再 `init...` → `close()`，之前已提交的 `decode()` 会被中止，其 Promise 未被捕获 → 控制台报错。  
  - 因此 H.264 路径下“先 decode 后 close”的机会多，AbortError 更容易出现。
- **H.265**：  
  - 创建/重建解码器的入口是 `initHevcDecoderForStream`，一般在收到 **VPS/SPS/PPS（type 32/33/34）** 或首帧 **IDR（type 19/20）** 时调用。  
  - 常见顺序是：先一串参数集（VPS→SPS→PPS），再 IDR，再 P 帧；参数集阶段通常还**没有**调用过 `decode()`，因此第一次 `close()`（若有）时没有“未完成的 decode”，不会产生未捕获的 AbortError。  
  - 之后即便有 close（例如 in-band 参数集更新），发生频率也低于 H.264 的“每个 SPS/PPS 都可能 close”，所以控制台很少看到同款报错。

### 6.3 小结

| 项目 | 说明 |
|------|------|
| 报错本质 | `decode()` 的 Promise 在 `close()` 时被 reject，未用 `.catch()` 吞掉 |
| 触发位置 | 5138 行执行 `dec.close()` 时，之前已提交的 `decode()` 被中止 |
| H.264 多、H.265 少 | H.264 在每条 SPS/PPS 都可能 close，且与 slice 交错，易出现“先 decode 后 close”；H.265 多在参数集阶段 close，尚未 decode |

**后续若改代码**：在每次 `dec.decode(...)` 调用处对返回值加 `.catch(function() {})`（或统一封装一个 safeDecode），即可避免该未捕获的 AbortError，无需改动 close 逻辑本身。

---

## 7. 小结

- **“H.264 播放有问题”**（不出图、卡在关键帧、已送帧多已解码为 0）在多数情况下是**后端**因 **2000 字节上限丢弃了整包关键帧** 导致。
- 前端逻辑（NAL 解析、SPS/PPS、解码器创建/重建、时间戳、FU-A）整体合理；在关键帧能完整到达的前提下，现有前端足以正常出图与实时播放。
