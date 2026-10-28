# 压测台账 · ChatAI 35.2.4 2API

被测目标：本机 `demo_server.py`（:8916）→ 上游 `chatapi.begamob.com`（文本）/ `chat-ai-iaa.begamob.com`（多模态）
被测环境：Windows 10 Pro，Python 3.14，出口为本地代理 `127.0.0.1:10808`（**非直连**，见 §6）
执行时间：2026-10-29（R1 功能 + 极限 + 浏览器；第二轮补多模态与绘图探针）

---

## 1. 协议/边界探测（`tools/probe_upstream.py`，直打上游）

| 项 | 结果 | 判定 |
|---|---|---|
| `GET /api/getTime` | 200 `{"token":"1793221468279"}`（毫秒时间戳） | 已验证 |
| JWT `exp` = **秒级** epoch | 200 | 已验证 |
| JWT `exp` = **毫秒级** epoch（APK 里 `jc.java` 就是毫秒） | 401 `auth_invalid` | 已验证 |
| 无 Authorization / 伪造签名 | 401 `auth_invalid` | 已验证 |
| 请求体带 `stream` 字段 | 400 Spring 默认错误体（Jackson 未知属性） | 已验证 |
| `messages` 缺失 | 400 Spring 默认错误体 | 已验证 |
| `messages: []`（空数组） | **200** 返回默认回答 | 已验证 |
| 无效模型名 `nonexistent-xyz` | **200**，兜底默认模型 | 已验证 |
| `max_tokens` 上限 | 16384 → 200；**16385 → 400 `request_invalid`** | 已验证（二分法） |
| 上下文上限（中文字符） | 127,948 → 200；**127,977 → 400 `request_invalid`** | 已验证（二分法） |
| `/api/v1/chat_v4`、`/api/v2/chat` | 200 | 已验证 |
| `/api/v1/chatCustom`、`/api/v2/chatCustom` | **200** | 已验证 |
| `/api/v1/summarize_text` | **200** `{requestId,summaryText,summaryContent,suggestList,code}` | 已验证 |
| `/api/v1/summarize_chat`、`/api/v1/topic_chat` | **200**（topic 返回 `{topicText,topicContent}`） | 已验证 |
| `/api/v1/suggestChatQuestion` | **200** `{statusCode,message,data:{data:[…]}}` | 已验证 |
| `/api/v3/chatCustom` on chatapi | 404（不在该域） | 已验证 |
| `/api/v3/chatCustom` on **chat-ai-iaa** | **201** `{success,status_code,request_id,data:{choices}}`（NestJS 服务） | 已验证 |
| v3 纯字符串 content | 400 `messages.0.nested property content must be either object or array` | 已验证 |
| v3 content parts `[{type:text},{type:image_url:{url}}]` | **201**，能正确读图 | 已验证 |
| v3 `image_url` 传字符串 | 400 `must be either object or array` | 已验证 |
| v3 data URL 的图片 | 500 `unsupported image` | 已验证 |
| v3 图片 URL 下载失败（wikimedia 被拒） | 500 code 15500 `Error while downloading file` | 已验证 |
| `GET /api/v1/ws/chat` WS 握手（chatapi / chat-ai-iaa / `/ws/chat`） | 全部 **404** | 已验证 |
| `POST aiapi-art /api/v1/generate_art` | 恒 **400 `request_invalid`**（见 §5） | 已验证 |
| `POST aiapi-art /api/v2/art` | 恒 **500 Internal Server Error** | 已验证 |
| `POST /api/v1/gen-anime` on chatapi | 404；`gen-anime-ai.begamob.com` **DNS 不解析** | 已验证 |

**模型矩阵：17/17 全部 200**
```
gpt-4o  gpt-4o-mini  gpt-4.1  gpt-4.1-mini  gpt-5  gpt-5-mini  gpt-o3-mini  gpt-3.5-turbo
claude-4.5-opus  claude-4.5-sonnet  claude-3.7-sonnet
gemini-3-pro  gemini-2.5-flash
deepseek  grok-3  llama4  llama-3.1
```
> `ModelGpt` 枚举里的 `generate_art` / `ghibli` / `nano-banana-pro` 打到 `/api/v1/chat` 一律 200
> 但只返回普通文本（上游兜底），不产图 → 未列入网关模型表。

---

## 2. R1 功能压测（`stress_test.py`）→ **18/18 PASS**

```
[PASS] health                             chatai-3524-2api models=17
[PASS] models list                        20 项（17 上游名 + chatai-default/chatai/default 别名）
[PASS] 别名 chatai-default                  OK  (1451 ms)
[PASS] baseline gpt-4o-mini               OK  (3715 ms)
[PASS] 多轮中文对话                        京。  (1891 ms)
[PASS] 强模型 claude-4.5-opus              OK  (1904 ms)
[PASS] 强模型 gemini-3-pro                 OK  (1893 ms)
[PASS] 强模型 gpt-5                       OK  (1895 ms)
[PASS] SSE 流式（网关模拟）                  chunks=9 ttft=2090ms total=2159ms
[PASS] 未知模型拦截                         400 unknown model
[PASS] 缺 model                           400 model is required
[PASS] 空 messages                        400 messages is required
[PASS] 超长上下文拦截                       400 context too long: 130000 > 127000
[PASS] max_tokens 超限自动钳制               99999 -> 16384
[PASS] 多模态读图 (v3)                      这是一张Python编程语言的标志。  (2631 ms)
[PASS] 摘要 /v1/summarize                  建议 3 条  (1868 ms)
[PASS] 并发 x6                            6/6 200, p50=1065ms wall=1172ms
[PASS] 出网代理并发上限探针 x10                200x10, 连接层失败 0, 上游 429/503 0
```
原始数据：`r1_results.json`

---

## 3. 极限压测（`stress_extreme.py`）

### 3.1 阶梯并发（每级 N 个短 prompt，`max_tokens=64`）

| 并发 | 200 | 429 | 5xx | p50 | p95 | wall | RPS |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 0 | 0 | 3463 | 3463 | 3464 | 0.29 |
| 2 | 0\* | 0 | 2\* | 4158 | 4158 | 4299 | 0.47 |
| 4 | 4 | 0 | 0 | 4442 | 4606 | 4617 | 0.87 |
| 6 | 6 | 0 | 0 | 2261 | 2463 | 2465 | 2.43 |
| 10 | 10 | 0 | 0 | 1719 | 3136 | 3145 | 3.18 |
| 20 | 20 | 0 | 0 | 3507 | 5718 | 5749 | 3.48 |
| 30 | 30 | 0 | 0 | 4525 | 7835 | 8115 | 3.70 |
| 50 | 50 | 0 | 0 | 7349 | 13081 | 13580 | 3.68 |

\* 第 2 级那一次是本机代理瞬时 SSLEOF（**复测 4 轮 × 2 = 8/8 全 200**），见 §6。
其余全部 200，**零 429、零上游 5xx**。吞吐在 6 并发后饱和于 **≈3.2–3.7 RPS**
= `上游隧道池 6 ÷ 单请求 ~1.7s`，属**本地出口约束**。

### 3.2 持续连发（3 轮 × 30，无间隔，客户端 6 路）

| 轮次 | 200 | 429 | 5xx | p50 | wall | RPS |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 30/30 | 0 | 0 | 1332 | 7660 | 3.92 |
| 2 | 30/30 | 0 | 0 | 1308 | 7421 | 4.04 |
| 3 | 30/30 | 0 | 0 | 1370 | 7216 | 4.16 |

### 3.3 上下文边界（走网关）

| 中文字符 | 结果 |
|---:|---|
| 50,000 | 200（3.6 s） |
| 100,000 | 200（4.5 s） |
| 126,000 | 200（3.9 s） |
| 127,900 | 400（**6 ms**，网关本地拦截，非上游） |
| 128,000 | 400（15 ms，本地拦截） |

> 上游真实边界由直连探针测得：**127,948 过 / 127,977 拒**。网关 `CTX_CHAR_CAP=127000` 留 1K 余量。

### 3.4 全模型矩阵（走网关，17 个）

17 个模型全部 200，耗时 **1003–1427 ms**。

原始数据：`extreme_results.json`

---

## 4. 真实浏览器验收（`tools/e2e_demo.py`，Playwright + Chromium）→ **PASS**

```
[1] 页面加载 OK · 健康: 网关正常 · 17 模型 · 模型选项: 17
[2] 非流式回复 OK · len=78 · 1474 ms · 上游 1472 ms
[3] 流式回复 OK · len=9 · 1271 ms · SSE 模拟
[4] 多模态读图 OK · 这是一种编程语言Python的标志。
[5] 摘要模式 OK · 人工智能是计算机科学的一个分支…
[6] 统计面板刷新 OK · 请求=297 上游成功=270 P50=1582 ms
[7] 控制台错误 0 条, 请求失败 0 条
```
截图：`shot_1_idle.png` / `shot_2_nonstream.png` / `shot_3_stream.png` / `shot_4_stats.png` /
`shot_5_vision.png` / `shot_6_summarize.png`

---

## 5. 绘图链路（第二轮深挖）→ **未打通，判定不可用**

| 探针 | 结果 |
|---|---|
| `POST aiapi-art /api/v1/generate_art` `{prompt,model_id,style_id}` | 400 `request_invalid`（ErrorDTO） |
| 加 `aspect_ratio` / `cfg` / `steps` / `seed` / `negative_prompt` / `high_res_results` | 仍 400 `request_invalid` |
| 加未知字段 `width`/`height`/`size`/`n`/`type` | 400 Spring `Unknown property`（证明 DTO 只认自己的字段） |
| 6 个 `model_id`（27/28/29/30/31/34）、`style_id` 0/1 | 全 400 `request_invalid` |
| **不带 Authorization** | **800** `request_invalid`（另一套错误码 → 鉴权是过了的，卡在语义校验） |
| `POST aiapi-art /api/v2/art` `{prompt,model}` | **500 Internal Server Error**（18 个 model 名全 500） |
| `GET /list?folder=style`（style 列表端点） | 404（客户端代码里的 style 源已下线） |

**根因（静态确认）**：art 域拦截器 `ax/bx/cx/pj.java` 本来要把 `OpenAI-Organization` 设为
AES/ECB 解出来的组织令牌，但硬编码密钥
`4203810110384606017206701107750526203160832801170748406508524` 是 **61 字节**（AES 只接受 16/24/32），
`cipher.init` 抛 `InvalidKeyException` 被 `catch` 吞掉 → 实际发出去的是 `timestamp`。
密文 `Sc7P6bs4PC4Mid7Tx4ZRDNk1o9sGkyahSNTXT3HdRDY=`（32 B）用该数字串的
`[:32]/[-32:]/md5/sha256[:32]/sha1[:16]` 等 8 种派生密钥解密**全部不可读** → 正确令牌无法静态还原。

**结论**：`/api/v1/generate_art` 的语义校验需要那个无法复现的组织令牌；
`/api/v2/art` 服务端自身 500。→ **绘图能力在本轮不可用（不是我们没试够，是链路上游已废）。**

---

## 6. 环境约束（重要，非上游问题）

本机**没有直连出网**（`trust_env=False` 直连 100% ConnectionError），全部流量走本地代理
`127.0.0.1:10808`。该代理的**并发隧道上限 ≈ 6–7 条**：

```
代理 x2/x3/x5/x6 -> 全 200
代理 x8/x10/x16 -> 100% SSLError（SSLEOF during handshake）
对照 api.github.com x8/x10 -> 同样 100% SSLError
```

→ **≥8 并发失败与 begamob 无关**，是本机代理的隧道数上限。
网关因此固定 6 条 keep-alive 会话（`UPSTREAM_POOL` 可调）做连接池，超出即排队：
既不撑爆代理也不漏隧道。首版用 thread-local session 会累积泄漏，把 6–7 条额度吃满，
表现为「并发全 502」——已修复。

偶发的**单次** SSLEOF 仍会出现（本机代理抖动），网关对连接层异常重试 1 次；
R1 探针用例 `出网代理并发上限探针` 就是用来区分「连接层失败」与「上游 429/503」的。

要在真实服务器上复测上游限流，需**直连出口**；届时把 `UPSTREAM_POOL` 调大即可。
