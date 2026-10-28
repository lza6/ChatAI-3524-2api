# -*- coding: utf-8 -*-
"""
ChatAI (com.chatbot.ai.aichat.openaibot.chat v35.2.4) → OpenAI 兼容 2API 网关 (demo)
上游: https://chatapi.begamob.com  POST /api/v1/chat
鉴权: 客户端自签 JWT-HS256（密钥硬编码在 APK 的 ax.bx.cx.jc 里），无账号/无设备绑定

端点:
  POST /v1/chat/completions   OpenAI 兼容（非流式 + 网关侧 SSE 模拟流式）
  GET  /v1/models             17 个实测可用模型
  GET  /health /stats         本地健康与统计
  GET  /api/getTime           上游时间戳透传
  GET  /                      demo 页

端口 8916
"""
import base64, hashlib, hmac, json, os, queue, threading, time

import requests
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = 'https://chatapi.begamob.com'
# 多模态（图片输入）走另一台机器：NestJS 服务，返回 201 + {success,status_code,request_id,data:{choices}}
UPSTREAM_V3 = 'https://chat-ai-iaa.begamob.com'
V3_PATH = '/api/v3/chatCustom'
JWT_SECRET = b'stteam-ikameglobal-chatapiopenai'
BUNDLE = 'com.chatbot.ai.aichat.openaibot.chat'
VERSION = '35.2.2'          # APK 内 OpenAiUtils 硬编码（35.2.4 的包未更新版本串）
BUILD = '352201'
MAX_TOKENS_CAP = 16384      # 上游硬上限：16384 过 / 16385 → 400 request_invalid
CTX_CHAR_CAP = 127000       # 上游硬上限 ≈ 127,948 中文字符（网关留 1K 余量）

# 17 个实测 200 的模型（ModelGpt 枚举里去掉 3 个图片模型名）
MODELS = ['gpt-4o', 'gpt-4o-mini', 'gpt-5', 'gpt-5-mini', 'gpt-4.1', 'gpt-4.1-mini',
          'gpt-o3-mini', 'gpt-3.5-turbo', 'deepseek', 'grok-3', 'gemini-2.5-flash',
          'gemini-3-pro', 'llama-3.1', 'llama4', 'claude-3.7-sonnet',
          'claude-4.5-sonnet', 'claude-4.5-opus']
MODEL_SET = set(MODELS)

stats_lock = threading.Lock()
stats = {'requests': 0, 'upstream_ok': 0, 'upstream_err': 0, 'latency_ms': [],
         'errors': []}

# 上游连接池：本机出网代理的并发隧道上限约 6-7 条（对任意 HTTPS 站点同样复现），
# 因此固定持有 POOL_SIZE 条 keep-alive 会话轮流借用，避免每个请求新建隧道把上限打满。
POOL_SIZE = int(os.environ.get('UPSTREAM_POOL', 6))
_pool = queue.Queue()
for _ in range(POOL_SIZE):
    _s = requests.Session()
    _s.headers.update({'Connection': 'keep-alive'})
    _pool.put(_s)


def _borrow():
    return _pool.get()


def _give_back(sess, nice=True):
    """nice=False 表示连接可能已损坏，换一条新会话放回池里"""
    if not nice:
        try:
            sess.close()
        except Exception:
            pass
        sess = requests.Session()
        sess.headers.update({'Connection': 'keep-alive'})
    _pool.put(sess)


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b'=').decode()


def make_jwt(ttl=900):
    """exp 必须是【秒】级 epoch；毫秒级上游直接 401 auth_invalid（实测）"""
    now = int(time.time())
    h = b64u(json.dumps({'alg': 'HS256', 'typ': 'JWT'}, separators=(',', ':')).encode())
    p = b64u(json.dumps({'iat': now, 'exp': now + ttl, 'bundleId': BUNDLE,
                         'os': 'Android', 'versionApp': VERSION},
                        separators=(',', ':')).encode())
    sig = b64u(hmac.new(JWT_SECRET, f'{h}.{p}'.encode(), hashlib.sha256).digest())
    return f'{h}.{p}.{sig}'


def upstream_headers():
    did = 'demo-3524-gateway'
    jwt = make_jwt()
    return {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + jwt,
        'user-header': (f'bundleId:{BUNDLE}/versionApp:{VERSION}/OS:Android'
                        f'/osVersion:33/userId:/deviceId:{did}'),
        'User-Agent': (f'VersionApp:{VERSION}/AppId:{BUNDLE}/Build:{BUILD}'
                       f'/VersionSDK:33/OS:Android/UserAgent:okhttp/4.12.0'
                       f'userId:/deviceId:{did}'),
    }


def _record(err=None, latency=None):
    with stats_lock:
        if err:
            stats['upstream_err'] += 1
            stats['errors'].append(err[:160])
            del stats['errors'][:-20]
        else:
            stats['upstream_ok'] += 1
        if latency is not None:
            stats['latency_ms'].append(latency)
            del stats['latency_ms'][:-500]


def _post(path, body, host=None, timeout=120, retries=1, ok=(200,)):
    """统一上游 POST：固定连接池借还 + 连接层异常单次重试（不重试 HTTP 4xx/5xx）。
    返回 (json_dict, elapsed_ms)。"""
    host = host or UPSTREAM
    t0 = time.time()
    last = None
    sess = _borrow()
    healthy = True
    try:
        for attempt in range(retries + 1):
            try:
                r = sess.post(host + path, json=body,
                              headers=upstream_headers(), timeout=timeout)
            except requests.RequestException as e:
                last = e
                healthy = False      # 丢掉可能已损坏的 keep-alive 连接
                if attempt < retries:
                    _give_back(sess, nice=False)
                    sess = _borrow()
                    healthy = True
                    time.sleep(0.3)
                continue
            ms = int((time.time() - t0) * 1000)
            if r.status_code not in ok:
                raise RuntimeError(f'upstream {r.status_code}: {r.text[:200]}')
            return r.json(), ms
    finally:
        _give_back(sess, nice=healthy)
    raise RuntimeError(f'upstream connect failed: {type(last).__name__}: {str(last)[:160]}')


def upstream_chat(model, messages, max_tokens, temperature, timeout=120, retries=1):
    """调上游 /api/v1/chat。上游只吃 model/messages/max_tokens/temperature
    等白名单字段，多余字段（如 stream）会 400。"""
    body = {'model': model, 'messages': messages,
            'max_tokens': max_tokens, 'temperature': temperature}
    data, ms = _post('/api/v1/chat', body, timeout=timeout, retries=retries)
    return data['choices'][0]['message']['content'], ms


def has_image(messages):
    for m in messages:
        if isinstance(m.get('content'), list):
            for part in m['content']:
                if isinstance(part, dict) and part.get('type') in ('image_url', 'image'):
                    return True
    return False


def to_v3_parts(messages):
    """OpenAI 风格 messages → v3 的 content parts（v3 只接受 [{type:text|image_url}]）"""
    out = []
    for m in messages:
        role = m.get('role') or 'user'
        if role not in ('user', 'assistant', 'system'):
            role = 'user'
        content = m.get('content')
        if isinstance(content, str):
            parts = [{'type': 'text', 'text': content}]
        else:
            parts = []
            for p in content or []:
                if not isinstance(p, dict):
                    continue
                if p.get('type') in ('image_url', 'image'):
                    url = p.get('image_url') or p.get('image') or {}
                    if isinstance(url, dict):
                        url = url.get('url') or ''
                    if url:
                        parts.append({'type': 'image_url', 'image_url': {'url': url}})
                else:
                    parts.append({'type': 'text', 'text': p.get('text', '')})
        out.append({'role': role, 'content': parts})
    return out


def upstream_chat_v3(model, messages, max_tokens, timeout=180):
    """多模态聊天：POST chat-ai-iaa.begamob.com/api/v3/chatCustom（NestJS，成功返回 201）
    要求 messages[i].content 必须是 [{type:"text"|"image_url"}]，纯字符串会被 400 拒绝。"""
    body = {'model': model, 'conversationId': 'gw-' + b64u(os.urandom(8)),
            'messages': to_v3_parts(messages), 'max_token': max_tokens}
    data, ms = _post(V3_PATH, body, host=UPSTREAM_V3, timeout=timeout, ok=(200, 201))
    data = data.get('data') or data
    return data['choices'][0]['message']['content'], ms


def upstream_summarize(text, model='gpt-4o-mini', timeout=180):
    """文本摘要：POST /api/v1/summarize_text → {requestId, summaryText, suggestList, code}"""
    body = {'model': model, 'messages': [{'role': 'user', 'content': text}], 'max_tokens': 1024}
    data, ms = _post('/api/v1/summarize_text', body, timeout=timeout)
    return data, ms


def normalize_messages(raw):
    """只保留 role/content，丢弃 tool_calls 等上游不认的字段；非 user/assistant/system 视为 user"""
    out = []
    for m in raw:
        role = m.get('role') or 'user'
        if role not in ('user', 'assistant', 'system'):
            role = 'user'
        c = m.get('content')
        if isinstance(c, list):   # OpenAI 多模态数组降级为纯文本
            c = '\n'.join(p.get('text', '') for p in c if isinstance(p, dict))
        out.append({'role': role, 'content': c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)})
    return out


def est_tokens(text):
    """粗略估算：中文 1 字≈1 token，ASCII 4 字符≈1 token"""
    if not text:
        return 0
    n_cjk = sum(1 for ch in text if '一' <= ch <= '鿿')
    return n_cjk + (len(text) - n_cjk) // 4 + 1


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'ChatAI-3524-2API'

    def log_message(self, fmt, *args):
        pass

    def _json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _err(self, code, msg, etype='invalid_request_error'):
        return self._json(code, {'error': {'message': msg, 'type': etype, 'code': code}})

    def do_GET(self):
        with stats_lock:
            stats['requests'] += 1
        path = self.path.split('?')[0]
        if path == '/':
            html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'demo.html')
            html = open(html_path, 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return
        if path == '/health':
            return self._json(200, {'status': 'ok', 'service': 'chatai-3524-2api',
                                    'upstream': UPSTREAM, 'upstream_v3': UPSTREAM_V3,
                                    'vision': True, 'summarize': True,
                                    'models': len(MODELS),
                                    'ts': int(time.time() * 1000)})
        if path == '/v1/models':
            return self._json(200, {'object': 'list',
                                    'data': [{'id': m, 'object': 'model', 'owned_by': 'begamob'}
                                             for m in MODELS]})
        if path == '/stats':
            with stats_lock:
                lat = sorted(stats['latency_ms'])
                p50 = lat[len(lat) // 2] if lat else 0
                p95 = lat[int(len(lat) * 0.95)] if lat else 0
                return self._json(200, {'requests': stats['requests'],
                                        'upstream_ok': stats['upstream_ok'],
                                        'upstream_err': stats['upstream_err'],
                                        'p50_ms': p50, 'p95_ms': p95,
                                        'errors': stats['errors'][-5:]})
        if path == '/api/getTime':
            try:
                r = requests.get(UPSTREAM + '/api/getTime', timeout=10,
                                 headers={'User-Agent': 'okhttp/4.12.0'})
                return self._json(200, r.json())
            except Exception as e:
                return self._err(502, str(e)[:200])
        return self._err(404, 'not found: ' + path)

    def do_POST(self):
        with stats_lock:
            stats['requests'] += 1
        path = self.path.split('?')[0]
        if path not in ('/v1/chat/completions', '/v1/summarize'):
            return self._err(404, 'not found: ' + path)
        try:
            n = int(self.headers.get('Content-Length') or 0)
            req = json.loads(self.rfile.read(n) or b'{}')
        except Exception as e:
            return self._err(400, 'bad json: ' + str(e))

        if path == '/v1/summarize':
            text = req.get('text')
            if not text and req.get('messages'):
                text = '\n'.join(str(m.get('content', '')) for m in req['messages'])
            if not text:
                return self._err(400, 'text is required')
            if len(text) > CTX_CHAR_CAP:
                return self._err(400, f'context too long: {len(text)} chars > {CTX_CHAR_CAP}')
            try:
                data, ms = upstream_summarize(text, req.get('model') or 'gpt-4o-mini')
            except Exception as e:
                _record(err=str(e))
                return self._err(502, 'upstream: ' + str(e)[:200], 'upstream_error')
            _record(latency=ms)
            return self._json(200, {'summary': data.get('summaryText', ''),
                                    'suggestions': data.get('suggestList') or [],
                                    'upstream_request_id': data.get('requestId'),
                                    'x_upstream_ms': ms})

        model = req.get('model')
        if not model:
            return self._err(400, 'model is required')
        if model not in MODEL_SET:
            # 上游对未知模型会静默兜底成默认模型并返回 200，网关侧必须自己白名单拦截
            return self._err(400, f'unknown model: {model}; see GET /v1/models')

        raw_messages = req.get('messages') or []
        messages = normalize_messages(raw_messages)
        if not messages:
            return self._err(400, 'messages is required')
        vision = has_image(raw_messages)
        total_chars = sum(len(m['content']) for m in messages)
        if total_chars > CTX_CHAR_CAP:
            return self._err(400, f'context too long: {total_chars} chars > {CTX_CHAR_CAP}')

        try:
            max_tokens = int(req.get('max_tokens') or req.get('max_completion_tokens') or 1024)
        except (TypeError, ValueError):
            return self._err(400, 'max_tokens must be an integer')
        max_tokens = max(1, min(max_tokens, MAX_TOKENS_CAP))
        try:
            temperature = float(req.get('temperature', 0.7))
        except (TypeError, ValueError):
            return self._err(400, 'temperature must be a number')
        temperature = max(0.0, min(temperature, 2.0))

        try:
            if vision:
                content, ms = upstream_chat_v3(model, raw_messages, max_tokens)
            else:
                content, ms = upstream_chat(model, messages, max_tokens, temperature)
        except Exception as e:
            _record(err=str(e))
            return self._err(502, 'upstream: ' + str(e)[:200], 'upstream_error')
        _record(latency=ms)

        cid = 'chatcmpl-' + b64u(os.urandom(9))
        created = int(time.time())
        prompt_tokens = est_tokens(''.join(m['content'] for m in messages))
        completion_tokens = est_tokens(content)
        usage = {'prompt_tokens': prompt_tokens, 'completion_tokens': completion_tokens,
                 'total_tokens': prompt_tokens + completion_tokens}

        if not req.get('stream'):
            return self._json(200, {
                'id': cid, 'object': 'chat.completion', 'created': created, 'model': model,
                'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': content},
                             'finish_reason': 'stop'}],
                'usage': usage,
                'x_upstream_ms': ms,
            })

        # 上游不支持流式（带 stream 字段直接 400）→ 网关侧按标点/字符切块模拟 SSE
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True

        def sse(delta, finish=None, with_usage=False):
            ev = {'id': cid, 'object': 'chat.completion.chunk', 'created': created,
                  'model': model,
                  'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
            if with_usage:
                ev['usage'] = usage
            self.wfile.write(b'data: ' + json.dumps(ev, ensure_ascii=False).encode() + b'\n\n')
            self.wfile.flush()

        try:
            sse({'role': 'assistant', 'content': ''})
            buf = ''
            for ch in content:
                buf += ch
                if ch in '，。！？、\n；：,.!?;: ' or len(buf) >= 12:
                    sse({'content': buf})
                    buf = ''
                    time.sleep(0.008)
            if buf:
                sse({'content': buf})
            sse({}, finish='stop', with_usage=True)
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8916))
    print(f'ChatAI 35.2.4 2API demo on http://127.0.0.1:{port}  upstream={UPSTREAM}  models={len(MODELS)}')
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
