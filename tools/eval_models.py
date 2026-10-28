# -*- coding: utf-8 -*-
"""
ChatAI 35.2.4 上游 · 17 模型真实能力评测
7 个探针：身份自述 / 精确算术 / 小数比较 / JSON 严格格式 / 代码生成 / 30K 长文定位 / 中文表达
可自动判分的（算术、比较、JSON、代码、针）直接判，其余留原文供人工看。
"""
import json, re, statistics, sys, time
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8916'
NEEDLE = 'BLUE-FALCON-7734'
FILLER = ('这是一段用于测试长上下文检索能力的填充文本。模型需要对无关内容保持忽略，'
          '并在最后准确回忆出被埋入的关键信息。') * 1000   # ≈ 40K 字符（网关上限 127K，留余量）
PROBES = {
    'identity': '你是哪个模型？由哪家公司训练？版本号是什么？只回答一句话，不要客套。',
    'arith':    '只输出一个数字，不要任何解释和单位：1234 × 5678 = ?',
    'compare':  '9.11 和 9.9 哪个更大？只输出较大的那个数。',
    'json':     '严格只输出一个 JSON 对象，不要 markdown 代码块、不要解释：'
                '字段为 capital(字符串)、population_million(数字)，内容填法国。',
    'code':     '用 Python 写一个判断字符串是否回文的函数 is_pal(s)，要求 O(1) 额外空间。只给代码，不要解释。',
    'needle':   '下面是一大段无关文本，请阅读后回答：里面提到的项目代号是什么？只输出代号。\n\n'
                + FILLER + '\n\n补充一句：本项目的项目代号是 ' + NEEDLE + '，请记住。\n\n'
                '问题：项目代号是什么？只输出代号。',
    'zh':       '用 100 字左右向高中生解释什么是量子纠缠。',
}


def ask(model, probe, timeout=300):
    body = {'model': model, 'messages': [{'role': 'user', 'content': PROBES[probe]}],
            'max_tokens': 700, 'temperature': 0.3}
    t0 = time.time()
    r = requests.post(BASE + '/v1/chat/completions', json=body, timeout=timeout)
    ms = int((time.time() - t0) * 1000)
    if r.status_code != 200:
        return {'probe': probe, 'ok': False, 'ms': ms, 'raw': 'HTTP %d %s' % (r.status_code, r.text[:120])}
    return {'probe': probe, 'ok': True, 'ms': ms,
            'text': r.json()['choices'][0]['message']['content'],
            'tokens': r.json().get('usage', {}).get('completion_tokens', 0)}


def grade(probe, text):
    """返回 (是否通过, 一句话说明)"""
    t = (text or '').strip()
    if probe == 'arith':
        return ('7006652' in t.replace(',', '').replace(' ', '')), t[:40]
    if probe == 'compare':
        return bool(re.search(r'\b9\.9\b', t)) and not re.search(r'^9\.11', t), t[:40]
    if probe == 'json':
        s = re.sub(r'^```(json)?|```$', '', t, flags=re.M).strip()
        try:
            d = json.loads(s)
            ok = isinstance(d.get('capital'), str) and isinstance(d.get('population_million'), (int, float))
            return ok, f'JSON ok: {d.get("capital")}/{d.get("population_million")}'
        except Exception:
            return False, 'JSON 不合法: ' + t[:50].replace('\n', ' ')
    if probe == 'code':
        has_def = 'def is_pal' in t
        no_alloc = ('s[::-1]' not in t) and ('reversed(' not in t.replace('reversed(s)', 'reversed(s)'))
        return (has_def and no_alloc), ('有 def' if has_def else '无 def') + ('' if no_alloc else ' / 用了切片')
    if probe == 'needle':
        return NEEDLE in t, t[:40]
    return None, t[:60]


def run_model(model):
    out = {'model': model, 'probes': {}}
    for p in PROBES:
        res = ask(model, p)
        if res['ok']:
            verdict, note = grade(p, res['text'])
            res['pass'] = verdict
            res['note'] = note
        out['probes'][p] = res
    return out


def main():
    models = [m['id'] for m in requests.get(BASE + '/v1/models', timeout=10).json()['data']]
    print(f'== 评测 {len(models)} 个模型 × {len(PROBES)} 个探针\n')
    results = []
    with ThreadPoolExecutor(4) as ex:
        for r in ex.map(run_model, models):
            results.append(r)
            auto = [p for p in ('arith', 'compare', 'json', 'code', 'needle')]
            got = sum(1 for p in auto if r['probes'][p].get('pass'))
            lat = [v['ms'] for v in r['probes'].values() if v.get('ok')]
            print(f"{r['model']:20s} 自动判分 {got}/5  p50={statistics.median(lat) if lat else 0:.0f}ms")
            for p in auto:
                v = r['probes'][p]
                print(f"    {p:8s} {'OK ' if v.get('pass') else 'ERR'} {str(v.get('note'))[:60]}")
    open('eval_results.json', 'w', encoding='utf-8').write(json.dumps(results, ensure_ascii=False, indent=2))
    print('\n-> eval_results.json')


if __name__ == '__main__':
    main()
