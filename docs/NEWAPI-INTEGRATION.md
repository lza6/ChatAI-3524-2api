# ChatAI 35.2.4 → new-api-Max 渠道对接指南

> **仓库**：https://github.com/lza6/ChatAI-3524-2api
> **上游**：`https://chatapi.begamob.com`（文本）/ `https://chat-ai-iaa.begamob.com`（多模态）
> **本文档自包含**，执行会话不需要读过 APK，也不需要懂 JWT 之外的密码学。
> 协议细节见 [`PROTOCOL.md`](./PROTOCOL.md)，模型真实能力见 [`../model_quality_eval.md`](../model_quality_eval.md)。

---

## 0. 动手之前必须知道的三件事（会影响你的技术选型）

### 0.1 「17 个模型」其实是 **1 个后端模型**

实测证据（`model_quality_eval.md` 第 2 节）：3 组固定 prompt × 17 个模型名 → 每种只有 **1 种字节级一致的答案**；
连错都一起错（`9.11 vs 9.9` 全答 `9.11`，`2^100 mod 1000` 全答 `24`）。

**所以：**

- ❌ 不要按 `gpt-5` / `claude-4.5-opus` 的倍率计费 → 那是虚假宣传
- ✅ 建议对外只暴露**一个**中性模型名（本仓库 demo 已提供别名 `chatai-default`）
- ✅ 真要保留多个名字，就当成 alias，价格全部对齐同一倍率

### 0.2 上游**没有流式**

带 `stream` 字段直接 400（Jackson 未知属性），WS `/api/v1/ws/chat` 全 404。
流式只能由网关/适配器**本地切块模拟**——第一次字延迟约等于整段生成时间（≈1–2s），不是真流。

### 0.3 绘图**不可用**

`aiapi-art /api/v1/generate_art` 恒 400、`/api/v2/art` 恒 500、`gen-anime-ai.begamob.com` DNS 已死。
别把 token 浪费在绘图排期上（证据见 `benchmark_results.md` 第 5 节）。

---

## 1. 两条路，先选一条

| | **方案 A：零改码**（OpenAI 类型渠道） | **方案 B：原生渠道 type 74** |
|---|---|---|
| 工作量 | 30 分钟，改后台配置 | 半天，改 6 个 Go 文件 + 前端 1 处 |
| 是否需要跑 demo | **需要**（demo 进程常驻） | 不需要，直连上游 |
| 依赖链 | new-api → 本地 demo(:8916) → 上游 | new-api → 上游 |
| 多模态读图 | 支持（demo 内自动路由 v3） | 需自己实现路由 |
| 摘要端点 | 支持（demo 的 `/v1/summarize`，但 new-api 渠道不暴露非标端点） | 需自己加 relay 模式 |
| 维护成本 | 多一个进程要守护 | 单进程 |
| 适合 | **先验证价值、快速上线** | 长期生产、要接进渠道面板 |

> **推荐路径**：先 A 跑通验证业务价值 → 稳定后按 B 固化为原生渠道。两条路的协议参数完全一致，A 的 demo 就是 B 的参考实现。

---

## 2. 方案 A：零改码（推荐先做）

### 2.1 在能出网的机器上起 demo 网关

```powershell
cd D:\apk-analysis\chatai3524      # 或者你克隆下来的仓库目录
$env:HOST = "0.0.0.0"              # 同机对接可省略；docker/局域网对接必须
$env:PORT = "8916"
$env:UPSTREAM_POOL = "6"           # 上游并发连接池，见 2.6
Start-Process -WindowStyle Hidden python -ArgumentList "demo_server.py"
```

验证（必须三步全绿再往下走）：

```powershell
curl http://127.0.0.1:8916/health
# {"status":"ok","service":"chatai-3524-2api","vision":true,"summarize":true,"models":17,...}

curl http://127.0.0.1:8916/v1/models
# 20 个 id：17 个上游模型名 + chatai-default / chatai / default

curl http://127.0.0.1:8916/v1/chat/completions -H "Content-Type: application/json" `
  -d '{\"model\":\"chatai-default\",\"messages\":[{\"role\":\"user\",\"content\":\"只回一个字：好\"}]}'
# 200 + choices[0].message.content
```

> ⚠️ Windows 的 `curl` 在 Git Bash 里发中文会变 GBK 导致 demo 报 `bad json`——用 PowerShell 的 `curl.exe`
> 或直接用 `python -c` 发请求，别怀疑 demo。

### 2.2 new-api 后台加渠道

管理后台 → 渠道 → 添加渠道：

| 配置项 | 值 | 说明 |
|---|---|---|
| 类型 | **OpenAI** | demo 是标准 OpenAI 兼容面，无需新类型 |
| 名称 | `chatai-3524` | 随意 |
| Base URL | `http://127.0.0.1:8916` | **不带 `/v1`**；docker 里跑 new-api 用 `http://host.docker.internal:8916` 或宿主局域网 IP |
| 密钥 | `sk-chatai` | demo **不校验** Authorization，随便填非空值（避免 new-api 因空 key 报错） |
| 模型 | `chatai-default` | 见 2.3 |
| 分组 | 按你的业务 | |

### 2.3 模型映射策略（重要）

**保守方案（推荐）**：只上 `chatai-default` 一个模型。
`chatai-default` 在 demo 内部映射到上游 `gpt-4o-mini`（就是那个唯一后端）。

**如果业务非要名字好看**，new-api 侧做「模型重定向」把外部名指到 `chatai-default`：

| 用户看到的模型名 | 重定向到 |
|---|---|
| `gpt-4o-mini` | `chatai-default` |
| `claude-4.5-sonnet` | `chatai-default` |
| `gemini-3-pro` | `chatai-default` |

> 但请同步在用户可见文案里写清「多模型为标签，底层同一模型」，否则等于承诺了做不到的能力。

### 2.4 计费配置

- 倍率：按你实际成本给**单一倍率**（不要给 `gpt-5`/`claude-opus` 那种高档倍率）
- demo 返回的 `usage` 是**字符估算**（中文 1 字≈1 token，ASCII 4 字符≈1 token），不是上游真值（上游不给）
  → 计费宽松一点没关系，但**不要拿它做精确对账**

### 2.5 验证清单（照着打勾）

| # | 验证 | 命令/操作 | 期望 |
|---|---|---|---|
| 1 | 非流式 | 后台「渠道测试」或 `curl <new-api>/v1/chat/completions` 走 `chatai-default` | 200，有正文 |
| 2 | 流式 | 同一请求加 `"stream":true` | 有 SSE 分帧（网关模拟），最后 `[DONE]` |
| 3 | 读图 | `messages[].content` 传 `[{type:text},{type:image_url:{url}}]` | 200，能描述图片 |
| 4 | 未知模型 | 请求 `model: gpt-9` | 400（demo 白名单拦截，不是 200 兜底） |
| 5 | 超长 | 12 万中文字符 | 200；13 万 → 400 `context too long`（demo 本地拦） |
| 6 | 计费 | 后台日志看 usage | 有 token 数（估算值） |
| 7 | 混合其他渠道 | 同分组再挂一个真 OpenAI 渠道 | 不影响（demo 渠道故障不会拖垮分组，只要设置了重试） |

### 2.6 运维要点

- **进程守护**：demo 挂了渠道就 5xx。Windows 用 `nssm` / 计划任务；或临时 `while(true){python demo_server.py}`
- **端口**：默认 8916，改 `PORT` 环境变量
- **并发**：`UPSTREAM_POOL` 默认 6。**这是为了绕开本机代理的并发隧道上限（≈6–7 条，x8 起 100% SSLEOF）**。
  - 若部署在**直连出口**的服务器上，可以调到 20–50（实测上游对阶梯 50 并发零 429）
  - demo 侧超出池大小的请求会排队，不会报错，只是延迟上升
- **日志**：`demo.log`（静默到底，只输出启动行）+ `/stats` 面板看 p50/p95/错误
- **重启**（Windows）：`netstat -ano | grep :8916` 拿 PID → `taskkill //PID <pid> //F`

### 2.7 故障排查表

| 现象 | 原因 | 处理 |
|---|---|---|
| new-api 渠道测试 502 `upstream connect failed ... SSLEOF` | 本机代理并发隧道打满 / 抖动 | 降 `UPSTREAM_POOL`、复测；确认出口代理可用 |
| 502 `upstream 401 auth_invalid` | JWT `exp` 用了毫秒 | 只能在代码里改秒级（`make_jwt` 已处理，别自己改） |
| 502 `upstream 400 request_invalid` | 请求体塞了上游不认的字段 | demo 已剥离 `stream` 等字段；若你改过代码，检查透传 |
| 400 `unknown model` | 模型名不在白名单 | 用 `chatai-default` 或 `GET /v1/models` 里的名字 |
| 读图 500 `code 15500` | 上游下载图片失败（图床被拒/被墙） | 换 `raw.githubusercontent.com` / `picsum.photos` 这类可下载的图床 |
| 中文乱码 / `bad json` | 用 Git Bash 的 curl 发中文 | 换 PowerShell `curl.exe` 或 python 发 |

---

## 3. 方案 B：原生渠道 type 74（长期方案）

### 3.1 为什么是 74

`constant/channel.go` 现有最大是 `ChannelTypeDuck = 73`，`constant/api_type.go` 里 `APITypeDuck` 之后只有 `APITypeDummy`（哨兵，不能新增在其后）。
**新渠道取 74**。

### 3.2 改动清单（6 处后端 + 1 处前端）

| # | 文件 | 改动 |
|---|---|---|
| 1 | `constant/channel.go` | 常量 `ChannelTypeChatAI3524 = 74` + `ChannelTypeNames` 里加 `"ChatAI3524"` |
| 2 | `constant/api_type.go` | 在 `APITypeDuck` 之后、`APITypeDummy` 之前加 `APITypeChatAI3524` |
| 3 | `common/api_type.go` | `switch channelType` 里加 `case constant.ChannelTypeChatAI3524: apiType = constant.APITypeChatAI3524` |
| 4 | `relay/relay_adaptor.go` | `switch` 里加 `case constant.APITypeChatAI3524: return &chatai3524.Adaptor{}` + import |
| 5 | `relay/channel/chatai3524/adaptor.go` | **新建**，主体实现（下面给完整骨架） |
| 6 | `relay/channel/chatai3524/adaptor_test.go` | **新建**，至少覆盖 JWT 签名 + 请求体白名单 + 响应解析 |
| 7 | `web/src/features/channels/constants.ts` | `74: 'ChatAI3524'`（渠道下拉框才会出现） |

> 建完跑：`go build ./... && go vet ./relay/channel/chatai3524/ && go test ./relay/channel/chatai3524/`

### 3.3 关键实现要点（踩过的坑，别自己再试一遍）

1. **JWT `exp` 必须是秒级 epoch**。APK 里是毫秒（`new Date().getTime()+900000`），照抄必 401。
2. **密钥是硬编码在 APK 里的 32 字节字符串**：`stteam-ikameglobal-chatapiopenai`（HS256）。
3. **请求体必须白名单**：上游 Jackson 开了严格模式，多一个 `stream` 字段就 400。
   只发 `model / messages / max_tokens / temperature`（可选 `top_p/n/stop/presence_penalty/frequency_penalty`）。
4. **`max_tokens` 上限 16384**（16385 → 400），适配器里要 `min()` 钳制。
5. **上下文上限 ≈127,948 中文字符**，建议 127000 截断。
6. **响应非 OpenAI 结构**：`{type, choices[{index,message{role,content},finish_reason}]}`，**没有 `id`/`usage`**。
   → `usage` 必须自己按字符估算，`id` 自己拼 `chatcmpl-xxx`。
7. **流式只能模拟**：拿完整响应后按句/按 12 字符切块下发 SSE（参考 `relay/channel/openchat/do_request.go` 的 `streamAsSSE`）。
8. **多模态要换域名**：`content` 数组里出现 `image_url` 时，改打
   `https://chat-ai-iaa.begamob.com/api/v3/chatCustom`，且 `content` 必须是 parts 数组、成功码是 **201**、响应多一层 `data`。

### 3.4 adaptor 骨架（可直接粘贴，按需补全）

```go
// relay/channel/chatai3524/adaptor.go
package chatai3524

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	relaycommon "github.com/lza6/new-api-Max/relay/common"
	"github.com/lza6/new-api-Max/relay/helper"
	"github.com/lza6/new-api-Max/relaykit/dto"
	"github.com/lza6/new-api-Max/relaykit/types"

	"github.com/gin-gonic/gin"
)

const (
	ChannelName = "ChatAI3524"
	textURL     = "https://chatapi.begamob.com/api/v1/chat"
	visionURL   = "https://chat-ai-iaa.begamob.com/api/v3/chatCustom"
	jwtSecret   = "stteam-ikameglobal-chatapiopenai"
	bundleID    = "com.chatbot.ai.aichat.openaibot.chat"
	appVersion  = "35.2.2"   // APK 内硬编码，35.2.4 的包也是这个串
	appBuild    = "352201"
	maxTokensCap = 16384
	maxCtxChars  = 127000
)

// ModelList 上游实测可用的 17 个模型名 + 1 个中性别名。
// 注意：这 17 个名字背后是同一个后端模型，别按名字定价。
var ModelList = []string{
	"chatai-default",
	"gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini",
	"gpt-5", "gpt-5-mini", "gpt-o3-mini", "gpt-3.5-turbo",
	"claude-4.5-opus", "claude-4.5-sonnet", "claude-3.7-sonnet",
	"gemini-3-pro", "gemini-2.5-flash",
	"deepseek", "grok-3", "llama4", "llama-3.1",
}

func b64u(b []byte) string { return base64.RawURLEncoding.EncodeToString(b) }

// signJWT exp 必须秒级，毫秒会被上游判 401 auth_invalid。
func signJWT() (string, error) {
	now := time.Now().Unix()
	header := b64u([]byte(`{"alg":"HS256","typ":"JWT"}`))
	payload, err := json.Marshal(map[string]any{
		"iat": now, "exp": now + 3600,
		"bundleId": bundleID, "os": "Android", "versionApp": appVersion,
	})
	if err != nil {
		return "", err
	}
	signing := header + "." + b64u(payload)
	mac := hmac.New(sha256.New, []byte(jwtSecret))
	mac.Write([]byte(signing))
	return signing + "." + b64u(mac.Sum(nil)), nil
}

type Adaptor struct {
	content     string
	promptChars int
}

func (a *Adaptor) Init(info *relaycommon.RelayInfo) {}

func (a *Adaptor) GetModelList() []string  { return ModelList }
func (a *Adaptor) GetChannelName() string  { return ChannelName }

func (a *Adaptor) GetRequestURL(info *relaycommon.RelayInfo) (string, error) {
	return textURL, nil // 视觉请求在 DoRequest 内改打 visionURL
}

func (a *Adaptor) SetupRequestHeader(c *gin.Context, req *http.Header, info *relaycommon.RelayInfo) error {
	jwt, err := signJWT()
	if err != nil {
		return err
	}
	did := "new-api-chatai"
	req.Set("Content-Type", "application/json")
	req.Set("Authorization", "Bearer "+jwt)
	req.Set("user-header", fmt.Sprintf(
		"bundleId:%s/versionApp:%s/OS:Android/osVersion:33/userId:/deviceId:%s",
		bundleID, appVersion, did))
	req.Set("User-Agent", fmt.Sprintf(
		"VersionApp:%s/AppId:%s/Build:%s/VersionSDK:33/OS:Android/UserAgent:okhttp/4.12.0userId:/deviceId:%s",
		appVersion, bundleID, appBuild, did))
	return nil
}

// ConvertOpenAIRequest 白名单透传：只发上游认的字段，多一个都 400。
func (a *Adaptor) ConvertOpenAIRequest(c *gin.Context, info *relaycommon.RelayInfo, r *dto.GeneralOpenAIRequest) (any, error) {
	if r == nil {
		return nil, errors.New("request is nil")
	}
	maxTokens := 1024
	if r.MaxTokens != nil {
		maxTokens = *r.MaxTokens
	}
	if maxTokens > maxTokensCap {
		maxTokens = maxTokensCap
	}
	msgs := make([]map[string]any, 0, len(r.Messages))
	chars := 0
	vision := false
	for _, m := range r.Messages {
		content := m.Content
		if c, ok := m.ParseContent(); ok {
			// 多模态：OpenAI parts → v3 parts（v3 只接受 parts 数组）
			parts, hasImg := toV3Parts(c)
			vision = vision || hasImg
			msgs = append(msgs, map[string]any{"role": m.Role, "content": parts})
			chars += len(fmt.Sprint(parts))
			continue
		}
		msgs = append(msgs, map[string]any{"role": m.Role, "content": m.StringContent()})
		chars += len(m.StringContent())
	}
	if chars > maxCtxChars {
		return nil, fmt.Errorf("context too long: %d chars > %d", chars, maxCtxChars)
	}
	body := map[string]any{"model": upstreamModel(info.UpstreamModelName),
		"messages": msgs, "max_tokens": maxTokens}
	if r.Temperature != nil {
		body["temperature"] = *r.Temperature
	}
	if vision {
		body["conversationId"] = fmt.Sprintf("newapi-%d", time.Now().UnixNano())
		body["max_token"] = maxTokens
		delete(body, "max_tokens")
	}
	info.SetTemp("chatai_vision", vision) // 供 DoRequest 选域名
	return body, nil
}

// DoRequest 按是否含图片选域名；视觉端点成功码是 201。
func (a *Adaptor) DoRequest(c *gin.Context, info *relaycommon.RelayInfo, body io.Reader) (any, error) {
	url := textURL
	if v, ok := info.GetTemp("chatai_vision"); ok && v == true {
		url = visionURL
	}
	req, err := http.NewRequest(http.MethodPost, url, body)
	if err != nil {
		return nil, err
	}
	h := make(http.Header)
	if err := a.SetupRequestHeader(c, &h, info); err != nil {
		return nil, err
	}
	req.Header = h
	client := &http.Client{Timeout: 180 * time.Second}
	return client.Do(req)
}

// DoResponse 解析非标准结构，usage 按字符估算，流式由本地切块模拟。
func (a *Adaptor) DoResponse(c *gin.Context, resp *http.Response, info *relaycommon.RelayInfo) (any, *types.NewAPIError) {
	if resp == nil || resp.Body == nil {
		return nil, types.NewError(fmt.Errorf("empty upstream response"), types.ErrorCodeBadResponse)
	}
	defer resp.Body.Close()

	raw, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		return nil, types.NewOpenAIError(err, types.ErrorCodeBadResponse, http.StatusBadGateway)
	}
	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		return nil, classifyUpstreamError(resp.StatusCode, string(raw))
	}

	var ur struct {
		Data *struct {
			Choices []struct {
				Message struct {
					Content string `json:"content"`
				} `json:"message"`
			} `json:"choices"`
		} `json:"data"`
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if e := json.Unmarshal(raw, &ur); e != nil {
		return nil, types.NewError(fmt.Errorf("chatai3524: bad json: %v", e), types.ErrorCodeBadResponse)
	}
	choices := ur.Choices
	if len(choices) == 0 && ur.Data != nil {
		choices = ur.Data.Choices
	}
	if len(choices) == 0 || strings.TrimSpace(choices[0].Message.Content) == "" {
		return nil, types.NewError(errors.New("chatai3524: empty content"), types.ErrorCodeBadResponse)
	}
	a.content = choices[0].Message.Content

	model := info.UpstreamModelName
	if model == "" {
		model = "chatai-default"
	}
	created := time.Now().Unix()
	usage := &dto.Usage{
		PromptTokens:     estTokens(a.promptChars),
		CompletionTokens: estTokens(len(a.content)),
		TotalTokens:      estTokens(a.promptChars) + estTokens(len(a.content)),
	}
	oai := &dto.OpenAITextResponse{
		Id: fmt.Sprintf("chatcmpl-chatai-%d", created), Model: model,
		Object: "chat.completion", Created: created,
		Choices: []dto.OpenAITextResponseChoice{{
			Index: 0, Message: dto.Message{Role: "assistant", Content: a.content}, FinishReason: "stop",
		}},
		Usage: *usage,
	}
	if info.IsStream {
		if e := streamAsSSE(c, oai); e != nil {
			return nil, types.NewOpenAIError(e, types.ErrorCodeBadResponse, http.StatusInternalServerError)
		}
		return usage, nil
	}
	c.JSON(http.StatusOK, oai)
	return usage, nil
}

func streamAsSSE(c *gin.Context, oai *dto.OpenAITextResponse) error {
	helper.SetEventStreamHeaders(c)
	id := oai.Id
	model := oai.Model
	role := &dto.ChatCompletionsStreamResponse{Id: id, Object: "chat.completion.chunk",
		Created: time.Now().Unix(), Model: model,
		Choices: []dto.ChatCompletionsStreamResponseChoice{{Index: 0,
			Delta: dto.ChatCompletionsStreamResponseChoiceDelta{Role: "assistant"}}}}
	if e := helper.ObjectData(c, role); e != nil {
		return e
	}
	text := oai.Choices[0].Message.StringContent()
	for i := 0; i < len(text); i += 12 {
		end := i + 12
		if end > len(text) {
			end = len(text)
		}
		chunk := &dto.ChatCompletionsStreamResponse{Id: id, Object: "chat.completion.chunk",
			Created: time.Now().Unix(), Model: model,
			Choices: []dto.ChatCompletionsStreamResponseChoice{{Index: 0}}}
		chunk.Choices[0].Delta.SetContentString(text[i:end])
		if e := helper.ObjectData(c, chunk); e != nil {
			return e
		}
	}
	stop := "stop"
	fin := &dto.ChatCompletionsStreamResponse{Id: id, Object: "chat.completion.chunk",
		Created: time.Now().Unix(), Model: model,
		Choices: []dto.ChatCompletionsStreamResponseChoice{{Index: 0,
			Delta: dto.ChatCompletionsStreamResponseChoiceDelta{}, FinishReason: &stop}}}
	if e := helper.ObjectData(c, fin); e != nil {
		return e
	}
	helper.Done(c)
	return nil
}

// 其余 Convert*Request 一律返回 "not supported"（与 duck/openchat 一致）
```

> 骨架里的 `ParseContent()` / `info.SetTemp/GetTemp` / `estTokens` / `toV3Parts` / `classifyUpstreamError`
> 需按当前仓库已有 API 对齐（`relaykit/dto` 与 `relaycommon` 的方法名可能随版本变化，编译报错时以仓库为准）。
> `relay/channel/openchat/do_request.go` 是**可直接抄的同构参考实现**（一次性响应 + 本地模拟 SSE）。

### 3.5 计费与模型配置

- 只给 `chatai-default` 配 ratio；17 个别名想要就给同样倍率
- `usage` 是估算值 → 别做精确对账，别开「按 token 严格扣费」的敏感策略

### 3.6 验收

```bash
go build ./... && go test ./relay/channel/chatai3524/ -run . -v
# 起服务后：
curl http://127.0.0.1:3000/v1/chat/completions -H "Authorization: Bearer sk-xxx" \
  -H "Content-Type: application/json" \
  -d '{"model":"chatai-default","messages":[{"role":"user","content":"只回一个字：好"}]}'
# 200 + 正文；再验 stream / 读图 / 超长 / 未知模型四条路径
```

---

## 4. 上游协议速查（详细版见 PROTOCOL.md）

| 项 | 值 |
|---|---|
| 文本端点 | `POST https://chatapi.begamob.com/api/v1/chat` |
| 视觉端点 | `POST https://chat-ai-iaa.begamob.com/api/v3/chatCustom`（201 + `data.choices`） |
| 鉴权 | `Authorization: Bearer <JWT-HS256>`，密钥 `stteam-ikameglobal-chatapiopenai`，`exp` **秒级** |
| 必带头 | `user-header` + `User-Agent`（见 §3.4 代码），`userId` 可空、`deviceId` 任意 |
| 请求体 | `{model, messages[{role,content}], max_tokens, temperature}`，**多一个字段就 400** |
| 响应体 | `{type, choices[{index,message{role,content},finish_reason}]}`，无 `id`/`usage` |
| 错误 | `401 auth_invalid` / `400 request_invalid` / `400 {timestamp,path,status,error,requestId}` |
| 上限 | `max_tokens ≤ 16384`；上下文 ≈ 127,948 中文字符 |
| 流式 | 无（带 `stream` 直接 400） |

---

## 5. 明确不要做的事

- ❌ 按模型名差异化定价（底层同一模型）
- ❌ 对外宣称「支持 17 个模型」或「支持 GPT-5 / Claude Opus 原厂」
- ❌ 把「流式」当卖点（是模拟的）
- ❌ 在绘图/视频上继续排期（上游已废）
- ❌ 在事实问答、法律医疗类场景主推（幻觉重，实测会编造不存在的书和作者）
