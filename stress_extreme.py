# -*- coding: utf-8 -*-
"""
ChatAI 35.2.4 2API 网关 · 极限压测
- 阶梯并发 1/2/4/6/10/20/30/50（网关侧上游隧道池 UPSTREAM_POOL=6）
- 持续连发 3 轮 × 30（不 sleep）→ 429 / 5xx 探针
- 上下文边界复验（50k / 100k / 127k 中文字符，走网关）
- 全模型矩阵 17 个

用法: python stress_extreme.py [base_url]
"""
import json, statistics, sys, time
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8916'
OUT = []


def one(prompt, model='gpt-4o-mini', max_tokens=64, timeout=180):
    t0 = time.time()
    try:
        r = requests.post(BASE + '/v1/chat/completions',
                          json={'model': model, 'max_tokens': max_tokens,
                                'messages': [{'role': 'user', 'content': prompt}]},
                          timeout=timeout)
        return r.status_code, int((time.time() - t0) * 1000)
    except Exception as e:
        return 'EXC:' + type(e).__name__, int((time.time() - t0) * 1000)


def ladder(levels=(1, 2, 4, 6, 10, 20, 30, 50)):
    print('\n== 阶梯并发（prompt 极短，max_tokens=64）')
    print(f'{"并发":>4} {"200":>5} {"429":>4} {"5xx":>4} {"p50ms":>7} {"p95ms":>7} {"wallms":>7} {"RPS":>6}')
    for n in levels:
        t0 = time.time()
        with ThreadPoolExecutor(min(n, 64)) as ex:
            res = list(ex.map(lambda i: one(f'ping {i}', max_tokens=64), range(n)))
        wall = int((time.time() - t0) * 1000)
        codes = [c for c, _ in res]
        lat = sorted(ms for _, ms in res)
        p50 = lat[len(lat) // 2]
        p95 = lat[min(len(lat) - 1, int(len(lat) * 0.95))]
        row = {'level': n, 'ok': codes.count(200),
               'r429': codes.count(429), 'r5xx': sum(1 for c in codes if isinstance(c, int) and 500 <= c < 600),
               'p50': p50, 'p95': p95, 'wall': wall, 'rps': round(n / (wall / 1000), 2)}
        OUT.append({'test': 'ladder', **row})
        print(f'{n:>4} {row["ok"]:>5} {row["r429"]:>4} {row["r5xx"]:>4} '
              f'{p50:>7} {p95:>7} {wall:>7} {row["rps"]:>6}')


def sustain(rounds=3, per_round=30):
    print(f'\n== 持续连发 {rounds} 轮 × {per_round}（无间隔，客户端 6 路并发）')
    for rd in range(rounds):
        t0 = time.time()
        with ThreadPoolExecutor(6) as ex:
            res = list(ex.map(lambda i: one(f'round{rd}-{i}', max_tokens=32), range(per_round)))
        wall = int((time.time() - t0) * 1000)
        codes = [c for c, _ in res]
        lat = sorted(ms for _, ms in res)
        row = {'test': 'sustain', 'round': rd + 1, 'ok': codes.count(200),
               'r429': codes.count(429),
               'r5xx': sum(1 for c in codes if isinstance(c, int) and 500 <= c < 600),
               'p50': lat[len(lat) // 2], 'wall': wall,
               'rps': round(per_round / (wall / 1000), 2)}
        OUT.append(row)
        print(f'  轮{rd+1}: 200={row["ok"]}/{per_round} 429={row["r429"]} 5xx={row["r5xx"]} '
              f'p50={row["p50"]}ms wall={wall}ms rps={row["rps"]}')


def context():
    print('\n== 上下文边界复验（中文字符）')
    for n in (50000, 100000, 126000, 127900, 128000):
        st, ms = one('中' * n, max_tokens=32, timeout=300)
        print(f'  {n:>7} chars -> {st} ({ms} ms)')
        OUT.append({'test': 'context', 'chars': n, 'status': st, 'ms': ms})


def models():
    print('\n== 全模型矩阵')
    ids = [m['id'] for m in requests.get(BASE + '/v1/models', timeout=10).json()['data']]
    ok = 0
    for m in ids:
        st, ms = one('reply exactly: OK', model=m, max_tokens=32)
        mark = 'OK ' if st == 200 else 'ERR'
        ok += st == 200
        print(f'  [{mark}] {m:20s} {st} {ms:>6} ms')
        OUT.append({'test': 'model', 'model': m, 'status': st, 'ms': ms})
    print(f'  -> {ok}/{len(ids)} 模型可用')


def main():
    print(f'== ChatAI 35.2.4 2API 极限压测 @ {BASE}')
    ladder()
    sustain()
    context()
    models()
    open('extreme_results.json', 'w', encoding='utf-8').write(
        json.dumps(OUT, ensure_ascii=False, indent=2))
    print('\n-> extreme_results.json')


if __name__ == '__main__':
    main()
