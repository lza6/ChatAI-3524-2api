# -*- coding: utf-8 -*-
"""
ChatAI (com.chatbot.ai.aichat.openaibot.chat v35.2.4) 上游协议独立探针
不依赖 demo_server，直接复刻 APK 内 JWT-HS256 自签鉴权打上游。

用法:
  python probe_upstream.py            # 全量探测
  python probe_upstream.py --quick    # 只测鉴权 + 单模型
"""
import base64, hashlib, hmac, json, os, sys, time

import requests

UPSTREAM = 'https://chatapi.begamob.com'
JWT_SECRET = b'stteam-ikameglobal-chatapiopenai'
BUNDLE = 'com.chatbot.ai.aichat.openaibot.chat'
# APK 内硬编码版本串（35.2.4 的 APK 里仍是 35.2.2/build 352201，见 OpenAiUtils.java）
VERSION = '35.2.2'
BUILD = '352201'

MODELS = ['gpt-4o', 'gpt-4o-mini', 'gpt-5', 'gpt-5-mini', 'gpt-4.1', 'gpt-4.1-mini',
          'gpt-o3-mini', 'gpt-3.5-turbo', 'deepseek', 'grok-3', 'gemini-2.5-flash',
          'gemini-3-pro', 'llama-3.1', 'llama4', 'claude-3.7-sonnet',
          'claude-4.5-sonnet', 'claude-4.5-opus']


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b'=').decode()


def make_jwt(unit='s', ttl=900, version_app=VERSION):
    """unit='s' 秒级 / 'ms' 毫秒级（APK 内 jc.java 用 Date.getTime() 毫秒）"""
    now = int(time.time() * (1000 if unit == 'ms' else 1))
    ttl = ttl * (1000 if unit == 'ms' else 1)
    header = {'alg': 'HS256', 'typ': 'JWT'}
    payload = {'iat': now, 'exp': now + ttl, 'bundleId': BUNDLE,
               'os': 'Android', 'versionApp': version_app}
    h = b64u(json.dumps(header, separators=(',', ':')).encode())
    p = b64u(json.dumps(payload, separators=(',', ':')).encode())
    sig = b64u(hmac.new(JWT_SECRET, f'{h}.{p}'.encode(), hashlib.sha256).digest())
    return f'{h}.{p}.{sig}'


def headers(jwt):
    did = 'probe-3524'
    return {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + jwt,
        'user-header': f'bundleId:{BUNDLE}/versionApp:{VERSION}/OS:Android/osVersion:33/userId:/deviceId:{did}',
        'User-Agent': f'VersionApp:{VERSION}/AppId:{BUNDLE}/Build:{BUILD}/VersionSDK:33/OS:Android/UserAgent:okhttp/4.12.0userId:/deviceId:{did}',
    }


def chat(model, content='say ok', jwt=None, extra=None, timeout=60):
    body = {'model': model, 'messages': [{'role': 'user', 'content': content}],
            'max_tokens': 64, 'temperature': 0.7}
    if extra:
        body.update(extra)
    t0 = time.time()
    r = requests.post(UPSTREAM + '/api/v1/chat', json=body,
                      headers=headers(jwt or make_jwt()), timeout=timeout)
    return r, round((time.time() - t0) * 1000)


def main():
    quick = '--quick' in sys.argv
    print(f'== upstream {UPSTREAM} bundle={BUNDLE} versionApp={VERSION}')

    # 1) getTime
    try:
        r = requests.get(UPSTREAM + '/api/getTime', timeout=15,
                         headers={'User-Agent': 'okhttp/4.12.0'})
        print(f'[getTime] {r.status_code} {r.text[:120]}')
    except Exception as e:
        print(f'[getTime] EXC {e}')

    # 2) 鉴权单位探针: 秒级 / 毫秒级 / 无签名 / 空
    for unit in ('s', 'ms'):
        r, ms = chat('gpt-4o-mini', 'ping', jwt=make_jwt(unit=unit))
        print(f'[jwt-{unit}] {r.status_code} {ms}ms {r.text[:160]}')
    r = requests.post(UPSTREAM + '/api/v1/chat', json={'model': 'gpt-4o-mini',
                      'messages': [{'role': 'user', 'content': 'ping'}]},
                      headers={'Content-Type': 'application/json'}, timeout=30)
    print(f'[no-auth] {r.status_code} {r.text[:160]}')
    r = requests.post(UPSTREAM + '/api/v1/chat', json={'model': 'gpt-4o-mini',
                      'messages': [{'role': 'user', 'content': 'ping'}]},
                      headers=headers('bad.token.here'), timeout=30)
    print(f'[bad-jwt] {r.status_code} {r.text[:160]}')

    if quick:
        return

    # 3) 模型矩阵
    ok = []
    for m in MODELS:
        try:
            r, ms = chat(m, 'reply with exactly: OK')
            if r.status_code == 200:
                try:
                    content = r.json()['choices'][0]['message']['content'][:40]
                except Exception:
                    content = r.text[:60]
                print(f'[model] {m:20s} 200 {ms:6d}ms  {content!r}')
                ok.append(m)
            else:
                print(f'[model] {m:20s} {r.status_code} {r.text[:120]}')
        except Exception as e:
            print(f'[model] {m:20s} EXC {e}')
    print(f'== models OK {len(ok)}/{len(MODELS)}: {ok}')

    # 4) 无效模型兜底
    r, ms = chat('nonexistent-xyz', 'ping')
    print(f'[bogus-model] {r.status_code} {r.text[:160]}')

    # 5) 错误路径
    r = requests.post(UPSTREAM + '/api/v1/chat', json={'model': 'gpt-4o-mini'},
                      headers=headers(make_jwt()), timeout=30)
    print(f'[no-messages] {r.status_code} {r.text[:160]}')
    r, ms = chat('gpt-4o-mini', 'x' * 5000)
    print(f'[long-5k] {r.status_code} {ms}ms')

    # 6) 其它端点可达性
    for path in ('/api/v1/chat_v4', '/api/v2/chat', '/api/v1/completion',
                 '/v1/chat/completions', '/v1/models'):
        try:
            if path == '/v1/models':
                rr = requests.get(UPSTREAM + path, headers=headers(make_jwt()), timeout=20)
            else:
                rr = requests.post(UPSTREAM + path, json={'model': 'gpt-4o-mini',
                                   'messages': [{'role': 'user', 'content': 'hi'}]},
                                   headers=headers(make_jwt()), timeout=30)
            print(f'[probe] {path:24s} {rr.status_code} {rr.text[:100]}')
        except Exception as e:
            print(f'[probe] {path:24s} EXC {e}')


if __name__ == '__main__':
    main()
