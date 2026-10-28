# ChatAI 35.2.4 → OpenAI 2API

> `ChatAI_ AI Chatbot_35.2.4_Mod_VIP.apk`（`com.chatbot.ai.aichat.openaibot.chat`）逆向 →
> 上游协议还原 → OpenAI 兼容 2API 网关 + demo 页 + 压测台账。
> **仅用于安全研究与协议学习，请勿商用滥用。**

---

> ## ⚠️ 先读这三条，否则会误判这个项目
> 1. **「17 个模型」其实是 1 个后端模型**——3 组固定 prompt × 17 个模型名，每种只有 1 种字节级一致的答案，连错都一起错。
>    详见 [`model_quality_eval.md`](./model_quality_eval.md)。接渠道**不要按模型名差异化定价**。
> 2. **上游没有流式**——带 `stream` 字段直接 400，SSE 由网关本地切块模拟，不是真流。
> 3. **绘图不可用**——`generate_art` 恒 400、`/api/v2/art` 恒 500、`gen-anime-ai` 域已死。

## 📚 文档索引

| 文档 | 给谁看 | 内容 |
|---|---|---|
| [`docs/NEWAPI-INTEGRATION.md`](./docs/NEWAPI-INTEGRATION.md) | **要对接 new-api 的执行会话** | 两条路（零改码 / 原生渠道 type 74）、渠道配置表、Go adaptor 骨架、计费口径、验收清单、故障排查表 |
| [`docs/PROTOCOL.md`](./docs/PROTOCOL.md) | 要复刻协议的人 | 30 行可跑的 JWT 实现、全部端点表、请求/响应/错误结构、硬上限、7 条必须的防护 |
| [`model_quality_eval.md`](./model_quality_eval.md) | 选型/定价的人 | 「17 名字 = 1 后端」的证据链 + 那个后端会什么/不会什么 |
| [`benchmark_results.md`](./benchmark_results.md) | 关心稳定性的人 | 协议边界、R1 17/17、阶梯并发 1→50、上下文边界、绘图判死证据、本机代理约束 |

---

## TL;DR

| 项 | 结论 |
|---|---|
| 模型别名 | 网关额外提供 `chatai-default` / `chatai` / `default` 三个别名（映射到那个唯一后端），接渠道建议只用它 |
| 上游 | `https://chatapi.begamob.com`，主端点 `POST /api/v1/chat` |
| 鉴权 | **客户端自签 JWT-HS256**，HS256 密钥硬编码在 APK（`ax/bx/cx/jc.java`），无账号、无设备绑定、无注册 |
| VIP 校验 | **纯客户端**（SharedPreferences 里的 `key_save_status_premium_data`），服务端不校验 → 自签 JWT 直接拿全部模型 |
| 模型 | **17/17 实测 200**（GPT-4o/4.1/5 全系、Claude 4.5、Gemini 3 Pro、Grok-3、Llama4、DeepSeek） |
| 多模态 | **可读图**：`POST chat-ai-iaa.begamob.com/api/v3/chatCustom`（NestJS，201），content 必须是 `[{type:"text"\|"image_url"}]` |
| 附加能力 | `/api/v1/summarize_text`（摘要+推荐追问）、`summarize_chat`、`topic_chat`、`suggestChatQuestion`、`chatCustom v1/v2` 全实测 200 |
| 绘图 | **不可用**：`/api/v1/generate_art` 恒 400（需无法还原的 AES 组织令牌）、`/api/v2/art` 恒 500、`gen-anime-ai` 域已死 |
| 流式 | **上游没有**（`stream` 字段直接 400；WS `/api/v1/ws/chat` 3 变体全 404）→ 网关侧模拟 SSE |
| 限流 | 123 阶梯 + 90 连发请求，**零 429、零上游 5xx**（受本机代理隧道上限约束，详见 benchmark_results.md §6） |
| 硬上限 | `max_tokens ≤ 16384`（16385 → 400）；上下文 ≈ **127,948 中文字符** |

```bash
python demo_server.py            # http://127.0.0.1:8916
curl http://127.0.0.1:8916/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}]}'
```

浏览器打开 `http://127.0.0.1:8916/` 即 demo 页。

---

## 1. APK 深度分析

| 项 | 值 |
|---|---|
| 包名 | `com.chatbot.ai.aichat.openaibot.chat` |
| versionName / Code | `35.2.4` |
| 内部代码版本串 | `ChatAI_v35.2.2_(352201)_05_06_2026-23_50_release`（**包版本升了，代码里版本串没升**） |
| 大小 | 35 MB，4 个 dex，16,803 个类（jadx 全量反编译，268 个无关 SDK 类反编译告警） |
| 加固 | **无壳** |
| 语言/框架 | Kotlin + Hilt + Retrofit2 + OkHttp 4.12 + RxJava2 |
| 混淆 | R8 全量（业务包落在 `ax.bx.cx`），但**字符串常量（密钥/域名/路径）全部可读** |
| 三方 SDK | Firebase、Adjust、穿山甲 Pangle、Unity Ads、Moloco、Vungle、InMobi、Meta Audience、ikame SDK |
| 签名 | `META-INF/BNDLTOOL.RSA`（bundletool 重签过，非原始开发者证书） |

### 1.1 与 `com.begamob.chatgpt_openai` 的关系

同一套白标代码（`com.begamob.chatgpt_openai.*` 业务包原样存在，本包只是换了外层包名 +
`com.chatbot.ai.aichat.openaibot.chat` 的 Application/入口），**协议完全同源**：
同一密钥、同一 `bundleId`、同一上游域名。

### 1.2 VIP 是客户端假把式（关键发现）

```
ax/bx/cx/ma0.java:H(StatusPremiumData)  ->  gson.toJson 后写 SharedPreferences
ax/bx/cx/ma0.java:q()                   ->  读 key_save_status_premium_data，缺省 "非会员"
StatusPremiumData                       ->  { actual_status_iap, is_have_iap, number_close_premium }
```

- 会员状态 = **本地 JSON 反序列化结果**，没有任何服务端校验接口
- 聊天链路上游只认 JWT 里的 `bundleId/os/versionApp`，**完全不查询付费状态**
- → 这就是为什么「Mod VIP」版能做出来，也是为什么一个不存在的用户（`userId:` 空、
  `deviceId:` 随便填）能调用全部模型。**服务端没把付费当权限，只把 bundleId 当身份。**

### 1.3 埋点/广告面（不影响协议，仅记录）

- 穿山甲 `com.bytedance.sdk.openadsdk`（`libpglarmor.so` 是它的加密库，**不是加固壳**）
- Firebase Analytics / Crashlytics / RemoteConfig、Adjust 归因
- `com.pairip.application.Application`（Google Play 保护壳的壳类，说明这包本来是 Play 分发的 split 基础包）

---

## 2. 上游协议还原

### 2.1 端点清单（`OpenAiApi.java` + 各 Retrofit 实例）

| 域名 | 端点 | 用途 | 状态 |
|---|---|---|---|
| `chatapi.begamob.com` | `POST /api/v1/chat` | 主聊天 | ✅ 实测 200 |
| | `POST /api/v1/chat_v4` | GPT-4 通道 | ✅ 实测 200 |
| | `POST /api/v2/chat` | 带图输入 | ✅ 实测 200 |
| | `POST /api/v1/chatCustom`、`/api/v2/chatCustom` | 自定义角色 | ✅ 实测 200 |
| | `POST /api/v1/topic_chat` | 话题聊天 | ✅ 实测 200（`{topicText,topicContent}`） |
| | `POST /api/v1/summarize_chat` | 对话摘要 | ✅ 实测 200 |
| | `POST /api/v1/summarize_text` | 文本摘要 + 推荐追问 | ✅ 实测 200 |
| | `POST /api/v1/suggestChatQuestion` | 推荐提问 | ✅ 实测 200 |
| | `POST /api/v1/summarize_file`、`uploadSummaryText` | 文件摘要 | 已还原未验证 |
| | `GET /api/getTime` | 服务器时间戳（毫秒） | ✅ 实测 200 |
| | `POST /api/v1/gen-anime` | 动漫风绘图 | ❌ 404 |
| | `WS /api/v1/ws/chat` | 流式 | ❌ 404（3 变体） |
| `chat-ai-iaa.begamob.com` | **`POST /api/v3/chatCustom`** | **多模态（文本+图片 URL）** | ✅ 实测 201，能正确读图 |
| `aiapi-art.begamob.com` | `POST /api/v1/generate_art` | AI 绘图 | ❌ 恒 400 `request_invalid` |
| | `POST /api/v2/art` | 绘图 v2 | ❌ 恒 500 |
| `gen-anime-ai.begamob.com` | `OpenAiApi` | 动漫绘图 | ❌ **DNS 不解析，域已下线** |
| `color-phone-2.begamob.com` | `assets/`、`/items/category_background` | 壁纸素材 | 静态资源，固定 Bearer |
| `s2s.begamob.com` | ikame SDK 服务端归因 | 埋点 | 与聊天无关 |

### 2.2 鉴权：客户端自签 JWT（核心）

`ax/bx/cx/jc.java`：

```java
byte[] bytes = "stteam-ikameglobal-chatapiopenai".getBytes();      // 32 字节 HS256 密钥
SecretKey k = Keys.hmacShaKeyFor(bytes);
Date exp = new Date(new Date().getTime() + 900000);                // ★ 毫秒（服务端会 401）
Map claims = { iat: now_ms, exp: exp_ms,
               bundleId: "com.chatbot.ai.aichat.openaibot.chat",
               os: "Android", versionApp: "35.2.2" };
Jwts.builder().header().add({alg:HS256, typ:JWT}).and().claims(claims).signWith(k, HS256).compact();
```

`ax/bx/cx/a83.java`（拦截器）把它塞进 `Authorization: Bearer <jwt>`，并把结果缓存进
`term_token` —— 也就是说**签名逻辑 6 行就能复刻**：

```python
import base64, hashlib, hmac, json, time
b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b'=').decode()
now = int(time.time())                       # ★ 秒级！APK 用毫秒会被 401
h = b64(json.dumps({"alg":"HS256","typ":"JWT"}, separators=(',',':')).encode())
p = b64(json.dumps({"iat":now,"exp":now+3600,
                    "bundleId":"com.chatbot.ai.aichat.openaibot.chat",
                    "os":"Android","versionApp":"35.2.2"}, separators=(',',':')).encode())
jwt = f"{h}.{p}." + b64(hmac.new(b"stteam-ikameglobal-chatapiopenai", f"{h}.{p}".encode(), hashlib.sha256).digest())
```

> **最大的坑**：APK 里 `exp = new Date().getTime() + 900000` 是**毫秒**，
> 但上游 JWT 校验只认**秒级** epoch —— 毫秒 → `401 auth_invalid`，秒级 → 200。
> 说明 APK 自己那条链路其实是靠 `term_token` 缓存 + 服务端宽容兜住了，直连复刻必须改秒。

### 2.3 必带 Header（`OpenAiUtils.java`）

```
Authorization: Bearer <JWT>
user-header: bundleId:com.chatbot.ai.aichat.openaibot.chat/versionApp:35.2.2/OS:Android/osVersion:33/userId:/deviceId:<任意>
User-Agent: VersionApp:35.2.2/AppId:com.chatbot.ai.aichat.openaibot.chat/Build:352201/VersionSDK:33/OS:Android/UserAgent:okhttp/4.12.0userId:/deviceId:<同一任意值>
Content-Type: application/json
```

- `userId` 可空、`deviceId` 任意 → **无设备指纹、无设备额度**
- `osVersion` / `VersionSDK` 填真实 SDK int（33）即可，不校验

### 2.4 请求/响应

请求（`Completion35Request`，标准 OpenAI 字段）：`model / messages[{role,content}] / max_tokens / temperature / top_p / n / stop / presence_penalty / frequency_penalty`

> 上游 Jackson 配了 `FAIL_ON_UNKNOWN_PROPERTIES`：**多塞任何一个未知字段（如 `stream`）直接 400**。
> 网关必须白名单透传。

响应（非标准，无 `id`/`usage`）：

```json
{"type":"com.ikame.model.ResponseResultDto.ChatCompletionDto",
 "choices":[{"index":0,"message":{"role":"assistant","content":"..."},"finish_reason":"stop"}]}
```

错误体两种：
- 参数/未知字段：`400 {"timestamp":…,"path":"…","status":400,"error":"Bad Request","requestId":"…"}`
- 业务校验：`400 {"error":{"code":"400","message":"request_invalid"}}`
- 鉴权：`401 {"error":{"code":"401","message":"auth_invalid"}}`

### 2.5 模型矩阵与硬上限（二分法实测）

17 个模型全 200：
```
gpt-4o  gpt-4o-mini  gpt-4.1  gpt-4.1-mini  gpt-5  gpt-5-mini  gpt-o3-mini  gpt-3.5-turbo
claude-4.5-opus  claude-4.5-sonnet  claude-3.7-sonnet  gemini-3-pro  gemini-2.5-flash
deepseek  grok-3  llama4  llama-3.1
```
- `max_tokens`：**16384 过 / 16385 → 400**
- 上下文：**127,948 中文字符过 / 127,977 → 400**（≈128K 阈值，与 OpenChat 同源）
- 无效模型名 → **200 兜底**（上游静默降级到默认模型）→ **网关必须自己白名单**
- `messages: []` → 200 空回答（不报错）

### 2.6 多模态读图：另一台机器（第二轮新发现）

`ax/bx/cx/l50.java` 把 `ChatV3CustomApi` 指到 `https://chat-ai-iaa.begamob.com/`，
它和 chatapi 不是同一套服务（NestJS，返回体带 `success/status_code/request_id`）：

```http
POST https://chat-ai-iaa.begamob.com/api/v3/chatCustom
（同一套 JWT + user-header + UA）

{"model":"gpt-4o-mini","conversationId":"c1","max_token":256,
 "messages":[{"role":"user","content":[
    {"type":"text","text":"这张图里是什么？"},
    {"type":"image_url","image_url":{"url":"https://…/python.png"}}]}]}
```

→ **201** `{"success":true,"status_code":201,"request_id":"…","data":{"choices":[{"index":0,"message":{"role":"assistant","content":"这是一种编程语言Python的标志。"}}]}}`

坑位：

- `content` **必须**是对象/数组，纯字符串 → `400 messages.0.nested property content must be either object or array`
- `image_url` **必须**是对象 `{url:...}`，字符串 → 400
- `type` 只允许 `text` / `image_url`
- `data:` 开头的 data URL → 500 `unsupported image`
- 服务端会**自己去下载图片 URL**：wikimedia 被拒（`Error while downloading file. Upstream status code: 400`，错误码 15500），`picsum` / `raw.githubusercontent.com` 正常
- 成功码是 **201 不是 200**，响应体多一层 `data`

### 2.7 绘图链路：为什么判死（`tools/probe_art.py`）

`ax/bx/cx/pj.java`（art 域拦截器）本该给 `OpenAI-Organization` 塞一个 AES 解出来的组织令牌：

```java
byte[] ct = Base64.decode("Sc7P6bs4PC4Mid7Tx4ZRDNk1o9sGkyahSNTXT3HdRDY=", 0);   // 32 B
byte[] key = "4203810110384606017206701107750526203160832801170748406508524".getBytes(); // 61 B !
cipher.init(DECRYPT_MODE, new SecretKeySpec(key, "AES"));   // → InvalidKeyException
```

密钥是 **61 字节**，AES 只接受 16/24/32 → `cipher.init` 直接抛异常被 `catch{}` 吞掉，
线上实际发出去的是 `timestamp`（`/api/getTime` 的毫秒值）。实验结果：

| 探针 | 结果 |
|---|---|
| `/api/v1/generate_art` 各种字段组合（6 个 model_id × 2 个 style_id × 加 cfg/steps/seed/negative/high_res） | 恒 400 `request_invalid` |
| 带未知字段 `width/height/size/n/type` | 400 Spring `Unknown property`（说明 DTO 只认自己那几个字段） |
| **不带 Authorization** | **800** `request_invalid`（换了个错误码 → 鉴权其实过了，卡在语义校验） |
| `/api/v2/art` `{prompt,model}`（18 个 model 名） | 恒 500 Internal Server Error |
| style 列表端点 `GET /list?folder=style` | 404（客户端依赖的 style 源已下线） |

用该数字串的 `[:32] / [-32:] / md5 / sha256[:32] / sha1[:16]` 等 8 种派生密钥解那段密文**全部不可读**，
组织令牌无法静态还原 → **绘图能力上游已废，本轮判定不可用**（不是没试够）。

---

## 3. demo 交付

| 文件 | 说明 |
|---|---|
| `demo_server.py` | :8916。`/v1/chat/completions`（非流式 + 网关侧 SSE 模拟 + **图片 URL 自动路由 v3 多模态**）、`/v1/summarize`、`/v1/models`、`/health`、`/stats`、`/api/getTime`、`/` demo 页。含 6 条 keep-alive 隧道池、未知模型白名单、`max_tokens` 钳制、上下文截断保护、连接层异常单次重试 |
| `demo.html` | 中文聊天页：17 模型分组下拉、流式打字机、**图片 URL 输入（多模态）**、**摘要模式**、健康/统计面板 |
| `stress_test.py` | R1 功能压测 18 用例 |
| `stress_extreme.py` | 极限压测：阶梯并发 1→50、3×30 持续连发、上下文边界、全模型矩阵 |
| `tools/probe_upstream.py` | 直打上游的独立协议探针（不经过网关） |
| `tools/probe_art.py` | 绘图链路探针 + AES 密钥派生尝试 |
| `tools/e2e_demo.py` | Playwright 真实浏览器验收（文本/流式/读图/摘要 + 控制台错误检测 + 6 张截图） |
| `benchmark_results.md` | 压测台账（含环境约束与绘图判死证据） |
| `r1_results.json` / `extreme_results.json` | 原始结果 |

---

## 4. 压测结论摘要

- R1 功能：**18/18 PASS**（含错误路径 4 项、多模态读图、摘要、别名、并发、钳制、上下文拦截）
- 极限：阶梯 1/2/4/6/10/20/30/50 并发 → **123/123 全 200，零 429 零上游 5xx**
  （第 2 级曾有一次本机代理瞬时 SSLEOF，复测 4×2=8/8 全 200）；
  3×30 持续连发 **90/90 全 200，零 429**
- 吞吐饱和于 **≈3.2–3.7 RPS**（= 6 条隧道 ÷ 单请求 ~1.7s，**本机代理约束，非上游限流**）
- 浏览器：页面加载 / 非流式 / 流式 / 读图 / 摘要 / 统计刷新全绿，**0 控制台错误 0 请求失败**

完整数据与「为什么并发 8 以上全失败」的环境解释见 `benchmark_results.md`。

---

## 5. 与 35.2.8（`com.begamob.chatgpt_openai`）的差异

| 维度 | 35.2.4（本包） | 35.2.8（前次） |
|---|---|---|
| 包名 | `com.chatbot.ai.aichat.openaibot.chat` | `com.begamob.chatgpt_openai` |
| 密钥 / bundleId / 上游 | **完全相同** | 同 |
| 模型枚举 | 20 个（含 grok-3 / llama-3.1 / llama4 / gpt-3.5-turbo / gpt-o3-mini / nano-banana-pro / ghibli） | 15 个 |
| 版本串硬编码 | `35.2.2` / `Build 352201` | `35.2.8` / `Build 352804` |
| WS 流式 | 404（3 变体） | 404（7 变体） |
| 多模态读图 | ✅ `/api/v3/chatCustom`（chat-ai-iaa）201 可读图 | 未探 |
| 摘要/话题/推荐追问 | ✅ 全 200 | 已还原未验证 |
| 绘图 | ❌ 400/500，域已废 | ❌ 未打通 |
| 上下文上限 | 127,948 字符 | 127,900 字符（同阈值） |

→ **一句话：同一个上游、同一把密钥、更旧的壳，模型表多 2 个文本模型（grok-3 / llama4）。**

---

## 6. 踩坑记录

1. **`exp` 毫秒 vs 秒**：APK 代码用毫秒，上游只认秒。照抄 APK 必 401。
2. **`stream` 字段会让上游 400**：不是"忽略"，是 Jackson 未知属性直接拒。网关必须剥字段。
3. **无效模型名上游兜底 200**：不做白名单会出现「请求 gpt-9 也返回正常回答」的假象。
4. **`max_tokens` > 16384 直接 400 `request_invalid`**，不是截断。
5. **WS 流式早被上游关掉**：别浪费时间在 WS 握手上，SSE 只能网关模拟。
6. **thread-local requests.Session 会漏隧道**：`ThreadingHTTPServer` 每个连接一个新线程，
   thread-local session 永不释放，压测几十个请求后就把本机代理 6–7 条隧道额度吃满，
   表现为「并发全 502」。改成固定大小连接池（`queue.Queue` + borrow/return）即解决。
7. **本机无直连**：`trust_env=False` 全部 ConnectionError，所有流量必须走 `127.0.0.1:10808`。
8. **v3 的 `content` 不能是字符串**：必须是 `[{type:"text"|"image_url"}]`，否则 400；
   成功码是 201、响应体多包一层 `data`；`image_url` 必须是 `{url:...}` 对象。
9. **v3 会自己下载图片**：图床被墙/被拒会返回 500 code 15500，不是你的请求有问题。
10. **art 域的 AES 是死代码**：61 字节密钥必然抛 `InvalidKeyException`，`OpenAI-Organization`
    实际等于 `timestamp`；组织令牌无法静态还原 → 绘图这条路走不通，别在 `generate_art` 上继续试字段组合。

---

## 7. 目录

```
├── docs/
│   ├── NEWAPI-INTEGRATION.md # new-api 对接指南（两条路 + Go 骨架）
│   └── PROTOCOL.md           # 上游协议规格（可独立复刻）
├── model_quality_eval.md     # 17 名字 = 1 后端的评测证据
├── demo_server.py            # 网关（:8916）
├── demo.html                 # demo 页
├── stress_test.py            # R1 功能压测（17 用例）
├── stress_extreme.py         # 极限压测
├── benchmark_results.md      # 压测台账
├── r1_results.json
├── extreme_results.json
├── shot_1_idle.png … shot_6_summarize.png
└── tools/
    ├── probe_upstream.py     # 上游协议探针
    ├── probe_art.py          # 绘图链路探针 + AES 派生尝试
    └── e2e_demo.py           # Playwright 浏览器验收
```

## License

研究用途，不提供任何担保。
