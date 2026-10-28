# 上游协议规格（ChatAI 35.2.4 → begamob）

> 这份文档是「不用看 APK 也能复刻」的最小规格。所有数字都是 2026-10-29 实测。
> 实现参考：`demo_server.py`（Python，~400 行）；Go 骨架见 [`NEWAPI-INTEGRATION.md`](./NEWAPI-INTEGRATION.md) §3.4。

---

## 1. 身份与鉴权

上游是 begamob 白标 SaaS，**没有账号体系**：客户端自己签一个 JWT 当身份。

| 项 | 值 |
|---|---|
| 算法 | HS256 |
| 密钥（硬编码在 APK `ax/bx/cx/jc.java`） | `stteam-ikameglobal-chatapiopenai`（32 字节） |
| claims | `iat`、`exp`（**秒级 epoch**）、`bundleId`、`os`、`versionApp` |
| bundleId | `com.chatbot.ai.aichat.openaibot.chat` |
| os / versionApp | `Android` / `35.2.2`（35.2.4 的包里也是这个串，没升） |

**必带请求头**

```
Authorization: Bearer <JWT>
user-header: bundleId:com.chatbot.ai.aichat.openaibot.chat/versionApp:35.2.2/OS:Android/osVersion:33/userId:/deviceId:<任意串>
User-Agent: VersionApp:35.2.2/AppId:com.chatbot.ai.aichat.openaibot.chat/Build:352201/VersionSDK:33/OS:Android/UserAgent:okhttp/4.12.0userId:/deviceId:<同一任意串>
Content-Type: application/json
```

- `userId` 可以为空，`deviceId` 任意 → **无设备绑定、无设备额度**
- 服务端不查付费状态（VIP 校验纯客户端 SharedPreferences）→ 不买会员也能用全部模型

### 最小可运行实现（Python）

```python
import base64, hashlib, hmac, json, time, requests

SECRET = b'stteam-ikameglobal-chatapiopenai'
BUNDLE = 'com.chatbot.ai.aichat.openaibot.chat'
VER    = '35.2.2'

def b64u(b): return base64.urlsafe_b64encode(b).rstrip(b'=').decode()

def jwt(ttl=3600):
    now = int(time.time())                       # ★ 秒级，毫秒 → 401
    h = b64u(json.dumps({'alg': 'HS256', 'typ': 'JWT'}, separators=(',', ':')).encode())
    p = b64u(json.dumps({'iat': now, 'exp': now + ttl, 'bundleId': BUNDLE,
                         'os': 'Android', 'versionApp': VER},
                        separators=(',', ':')).encode())
    sig = b64u(hmac.new(SECRET, f'{h}.{p}'.encode(), hashlib.sha256).digest())
    return f'{h}.{p}.{sig}'

def headers():
    did = 'any-device-id'
    return {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + jwt(),
        'user-header': f'bundleId:{BUNDLE}/versionApp:{VER}/OS:Android/osVersion:33/userId:/deviceId:{did}',
        'User-Agent': (f'VersionApp:{VER}/AppId:{BUNDLE}/Build:352201/VersionSDK:33/OS:Android'
                       f'/UserAgent:okhttp/4.12.0userId:/deviceId:{did}'),
    }

r = requests.post('https://chatapi.begamob.com/api/v1/chat',
                  json={'model': 'chatai-default', 'messages': [{'role': 'user', 'content': 'hi'}],
                        'max_tokens': 64, 'temperature': 0.7},
                  headers=headers(), timeout=120)
print(r.status_code, r.json()['choices'][0]['message']['content'])
```

---

## 2. 端点清单

| 域名 | 端点 | 说明 | 状态 |
|---|---|---|---|
| `chatapi.begamob.com` | `POST /api/v1/chat` | 主聊天 | ✅ 200 |
| | `POST /api/v1/chat_v4` | 同上（历史通道） | ✅ 200 |
| | `POST /api/v2/chat` | 同上（历史通道） | ✅ 200 |
| | `POST /api/v1/chatCustom` | 同上（自定义角色） | ✅ 200 |
| | `POST /api/v2/chatCustom` | 同上 | ✅ 200 |
| | `POST /api/v1/summarize_chat` | 对话摘要（同聊天结构） | ✅ 200 |
| | `POST /api/v1/summarize_text` | 文本摘要 | ✅ 200（专用结构，见 §4.3） |
| | `POST /api/v1/topic_chat` | 话题生成 | ✅ 200（`{topicText,topicContent}`） |
| | `POST /api/v1/suggestChatQuestion` | 推荐追问 | ✅ 200（`{statusCode,data:{data:[]}}`） |
| | `POST /api/v1/summarize_file` | 文件摘要 | 已还原未验 |
| | `GET /api/getTime` | 服务器毫秒时间戳 | ✅ 200 |
| | `POST /api/v3/chatCustom` | — | ❌ 404（不在这个域） |
| | `WS /api/v1/ws/chat` | 流式 | ❌ 404（3 变体全 404） |
| | `POST /api/v1/gen-anime` | 绘图 | ❌ 404 |
| `chat-ai-iaa.begamob.com` | **`POST /api/v3/chatCustom`** | **多模态（文本+图片 URL）** | ✅ 201 |
| `aiapi-art.begamob.com` | `POST /api/v1/generate_art` | 绘图 | ❌ 恒 400 |
| | `POST /api/v2/art` | 绘图 v2 | ❌ 恒 500 |
| `gen-anime-ai.begamob.com` | — | 动漫绘图 | ❌ DNS 不解析 |
| `color-phone-2.begamob.com` | `assets/` 等 | 壁纸静态资源 | 与聊天无关 |

---

## 3. 文本聊天

### 3.1 请求

```json
{
  "model": "chatai-default",
  "messages": [{"role": "user", "content": "hi"}],
  "max_tokens": 1024,
  "temperature": 0.7
}
```

- 字段白名单：`model,messages,max_tokens,temperature,top_p,n,stop,presence_penalty,frequency_penalty`
- **未知字段（如 `stream`）→ 400**：上游 Jackson 开了 `FAIL_ON_UNKNOWN_PROPERTIES`
- `messages: []` → **200**（返回兜底回答，不报错）
- 未知 `model` → **200**（静默兜底到唯一那个默认模型）

### 3.2 响应

```json
{"type":"com.ikame.model.ResponseResultDto.ChatCompletionDto",
 "choices":[{"index":0,
             "message":{"role":"assistant","content":"..."},
             "finish_reason":"stop"}]}
```

**没有 `id` / `created` / `usage`** —— 要的话自己补（usage 只能按字符估算）。

### 3.3 错误

| 场景 | HTTP | 体 |
|---|---|---|
| 鉴权失败 | 401 | `{"error":{"code":"401","message":"auth_invalid"}}` |
| 业务校验（max_tokens 越界、上下文越界、role 非法） | 400 | `{"error":{"code":"400","message":"request_invalid"}}` |
| 参数结构错 / 未知字段 / 缺 model | 400 | `{"timestamp":…,"path":"…","status":400,"error":"Bad Request","requestId":"…"}` |

### 3.4 硬上限（二分法实测）

| 项 | 值 |
|---|---|
| `max_tokens` | **16384 通过 / 16385 → 400** |
| 上下文 | **127,948 中文字符通过 / 127,977 → 400**（建议实现侧 127,000 截断） |

---

## 4. 多模态（图片输入）

### 4.1 换域名 + 换 body 形状

```http
POST https://chat-ai-iaa.begamob.com/api/v3/chatCustom
（鉴权头与文本链路完全一致）

{"model":"gpt-4o-mini",
 "conversationId":"c1",
 "max_token":256,
 "messages":[{"role":"user","content":[
    {"type":"text","text":"这张图里是什么？"},
    {"type":"image_url","image_url":{"url":"https://…/python.png"}}]}]}
```

### 4.2 响应（成功码 **201**，多一层 `data`）

```json
{"success":true,"status_code":201,"request_id":"…","message":"ok",
 "data":{"choices":[{"index":0,"message":{"role":"assistant","content":"…"},"finish_reason":"stop"}]}}
```

### 4.3 坑

| 现象 | 原因 |
|---|---|
| `400 messages.0.nested property content must be either object or array` | `content` 传了字符串，必须 parts 数组 |
| `400 … image_url must be either object or array` | `image_url` 传了字符串，必须 `{"url":...}` |
| `400 … type must be one of: text, image_url` | part 的 `type` 只能是这两个 |
| `500 … unsupported image` | `data:` base64 不支持 |
| `500 code 15500 Error while downloading file` | 服务端**自己去下载图片 URL**，图床被拒/被墙（wikimedia 被拒，`picsum.photos` / `raw.githubusercontent.com` 可用） |

---

## 5. 摘要端点结构

```http
POST https://chatapi.begamob.com/api/v1/summarize_text
{"model":"gpt-4o-mini","messages":[{"role":"user","content":"<待摘要长文>"}],"max_tokens":1024}
```

```json
{"requestId":"…","summaryText":"…","summaryContent":"","code":200,
 "suggestList":["追问1","追问2","追问3"]}
```

---

## 6. 实现侧必须做的防护（否则线上必踩）

1. **`max_tokens` 钳制到 16384**，超了不是截断而是 400
2. **上下文按字符数截断**（>127,000 直接本地拒，别打上游）
3. **模型名白名单**：上游对未知模型返回 200 兜底，不做白名单会出现「用户请求 gpt-9 也正常回答」的假象
4. **请求体白名单**：不要透传 OpenAI 原体（`stream`/`tools`/`response_format` 等都会 400）
5. **`usage` 自估**：中文 1 字≈1 token，ASCII 4 字符≈1 token
6. **流式自己模拟**：上游无流式能力
7. **连接池**：如果你的出口是代理，注意并发隧道上限（本机实测 ≈6–7 条，x8 起 100% SSLEOF，与上游无关）

---

## 7. 一条命令自检

```bash
python tools/probe_upstream.py      # 打全部端点 + 模型矩阵 + 边界二分
python tools/probe_art.py           # 绘图链路（预期全失败，见文档）
```
