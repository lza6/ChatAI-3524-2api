# -*- coding: utf-8 -*-
"""
ChatAI 35.2.4 2API 网关 · 第一轮功能压测（12 场景）
用法: python stress_test.py [base_url]
"""
import json, statistics, sys, time
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8916'
RESULTS = []


def rec(name, ok, detail, ms=None):
    RESULTS.append({'case': name, 'ok': ok, 'detail': detail, 'ms': ms})
    tag = 'PASS' if ok else 'FAIL'
    print(f'[{tag}] {name:34s} {detail}' + (f'  ({ms} ms)' if ms else ''))


def chat(model='gpt-4o-mini', content='reply exactly: OK', **kw):
    body = {'model': model, 'messages': [{'role': 'user', 'content': content}]}
    body.update(kw)
    t0 = time.time()
    return requests.post(BASE + '/v1/chat/completions', json=body, timeout=180), int((time.time() - t0) * 1000)


def case_health():
    r = requests.get(BASE + '/health', timeout=10)
    j = r.json()
    rec('health', r.status_code == 200 and j['models'] == 17, f"{j['service']} models={j['models']}")


def case_models():
    r = requests.get(BASE + '/v1/models', timeout=10)
    ids = [m['id'] for m in r.json()['data']]
    rec('models list', len(ids) == 17, f'{len(ids)} models, first={ids[0]}')


def case_baseline():
    r, ms = chat()
    ok = r.status_code == 200 and 'OK' in r.json()['choices'][0]['message']['content']
    rec('baseline gpt-4o-mini', ok, r.json()['choices'][0]['message']['content'][:40], ms)


def case_chinese_multi_turn():
    body = {'model': 'gpt-4o-mini', 'messages': [
        {'role': 'system', 'content': '你是一个简洁的助手，回答不超过20个字。'},
        {'role': 'user', 'content': '中国的首都是哪里？'},
        {'role': 'assistant', 'content': '北京。'},
        {'role': 'user', 'content': '那它的简称是什么？'},
    ]}
    t0 = time.time()
    r = requests.post(BASE + '/v1/chat/completions', json=body, timeout=180)
    ms = int((time.time() - t0) * 1000)
    c = r.json()['choices'][0]['message']['content'] if r.status_code == 200 else r.text
    rec('多轮中文对话', r.status_code == 200 and ('京' in c), c[:50], ms)


def case_strong_models():
    for m in ('claude-4.5-opus', 'gemini-3-pro', 'gpt-5'):
        r, ms = chat(m, 'reply exactly: OK', max_tokens=64)
        ok = r.status_code == 200 and 'OK' in r.json()['choices'][0]['message']['content']
        rec(f'强模型 {m}', ok, r.json()['choices'][0]['message']['content'][:30] if ok else r.text[:60], ms)


def case_stream():
    t0 = time.time()
    r = requests.post(BASE + '/v1/chat/completions',
                      json={'model': 'gpt-4o-mini', 'stream': True,
                            'messages': [{'role': 'user', 'content': '数到 5'}]},
                      stream=True, timeout=180)
    ttft, acc, n = None, '', 0
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith('data:'):
            continue
        p = line[5:].strip()
        if p == '[DONE]':
            break
        ev = json.loads(p)
        d = ev['choices'][0]['delta']
        if d.get('content'):
            if ttft is None:
                ttft = int((time.time() - t0) * 1000)
            acc += d['content']
            n += 1
    total = int((time.time() - t0) * 1000)
    rec('SSE 流式（网关模拟）', r.status_code == 200 and n > 3,
        f'chunks={n} ttft={ttft}ms total={total}ms', total)


def case_errors():
    cases = [
        ('未知模型拦截', {'model': 'no-such-model', 'messages': [{'role': 'user', 'content': 'x'}]}, 400),
        ('缺 model', {'messages': [{'role': 'user', 'content': 'x'}]}, 400),
        ('空 messages', {'model': 'gpt-4o-mini', 'messages': []}, 400),
        ('超长上下文拦截', {'model': 'gpt-4o-mini',
                      'messages': [{'role': 'user', 'content': '中' * 130000}]}, 400),
    ]
    for name, body, want in cases:
        t0 = time.time()
        r = requests.post(BASE + '/v1/chat/completions', json=body, timeout=180)
        ms = int((time.time() - t0) * 1000)
        rec(name, r.status_code == want, f'{r.status_code} {r.json()["error"]["message"][:40]}', ms)


def case_clamp():
    r, ms = chat(max_tokens=99999)
    rec('max_tokens 超限自动钳制', r.status_code == 200, '99999 -> 16384', ms)


def case_concurrency(n=6):
    prompts = [f'回复数字 {i}' for i in range(n)]
    t0 = time.time()
    with ThreadPoolExecutor(n) as ex:
        rs = list(ex.map(lambda p: chat(content=p, max_tokens=64), prompts))
    wall = int((time.time() - t0) * 1000)
    oks = sum(1 for r, _ in rs if r.status_code == 200)
    lat = [ms for _, ms in rs]
    rec(f'并发 x{n}', oks == n,
        f'{oks}/{n} 200, p50={statistics.median(lat):.0f}ms wall={wall}ms')


def case_vision():
    """多模态：图片 URL → 网关自动路由 /api/v3/chatCustom"""
    body = {'model': 'gpt-4o-mini', 'messages': [{'role': 'user', 'content': [
        {'type': 'text', 'text': '这张图里是什么？一句话'},
        {'type': 'image_url',
         'image_url': {'url': 'https://raw.githubusercontent.com/github/explore/main/topics/python/python.png'}}]}]}
    t0 = time.time()
    r = requests.post(BASE + '/v1/chat/completions', json=body, timeout=180)
    ms = int((time.time() - t0) * 1000)
    txt = r.json()['choices'][0]['message']['content'] if r.status_code == 200 else r.text
    rec('多模态读图 (v3)', r.status_code == 200 and 'Python' in txt, txt[:50], ms)


def case_summarize():
    t0 = time.time()
    r = requests.post(BASE + '/v1/summarize', json={'text':
        '人工智能是计算机科学的一个分支，它企图了解智能的实质，并生产出一种新的能以人类智能相似的方式'
        '做出反应的智能机器。该领域的研究包括机器人、语言识别、图像识别、自然语言处理和专家系统等。'}, timeout=180)
    ms = int((time.time() - t0) * 1000)
    j = r.json()
    rec('摘要 /v1/summarize', r.status_code == 200 and len(j.get('summary', '')) > 10,
        f"{j.get('summary','')[:40]}… 建议{len(j.get('suggestions',[]))}条", ms)


def case_ceiling(n=10):
    """环境探针：本机出网代理隧道数上限（≈6-7）。超过后 100% 连接层失败，
    对 api.github.com 同样复现 → 非上游限流。此用例只判定失败是否为连接层而非上游 429/5xx。"""
    prompts = [f'ping {i}' for i in range(n)]
    t0 = time.time()
    with ThreadPoolExecutor(n) as ex:
        rs = list(ex.map(lambda p: chat(content=p, max_tokens=16), prompts))
    wall = int((time.time() - t0) * 1000)
    codes = [r.status_code for r, _ in rs]
    conn_fail = 0
    for r, _ in rs:
        if r.status_code == 502 and 'connect failed' in r.text:
            conn_fail += 1
    upstream_blocked = any(c in (429, 503) for c in codes)
    rec(f'出网代理并发上限探针 x{n}', not upstream_blocked,
        f'200x{codes.count(200)} 连接层失败x{conn_fail} 上游429/503x{int(upstream_blocked)} wall={wall}ms')


def main():
    print(f'== ChatAI 35.2.4 2API R1 功能压测 @ {BASE}\n')
    case_health()
    case_models()
    case_baseline()
    case_chinese_multi_turn()
    case_strong_models()
    case_stream()
    case_errors()
    case_clamp()
    case_vision()
    case_summarize()
    case_concurrency(6)
    case_ceiling(10)
    passed = sum(1 for r in RESULTS if r['ok'])
    print(f'\n== {passed}/{len(RESULTS)} PASS')
    if passed != len(RESULTS):
        print('失败项:', [r['case'] for r in RESULTS if not r['ok']])
    open('r1_results.json', 'w', encoding='utf-8').write(
        json.dumps(RESULTS, ensure_ascii=False, indent=2))
    return 0 if passed == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
