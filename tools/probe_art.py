# -*- coding: utf-8 -*-
"""
ChatAI 35.2.4 · 绘图链路探针（第二轮）
关键发现：APK 里 art 域拦截器 pj.java 的 AES 解密是**死代码**——
  key = "4203810110384606017206701107750526203160832801170748406508524" 是 61 字节，
  AES 只接受 16/24/32 字节 → cipher.init 抛 InvalidKeyException → 被 catch 吞掉，
  最终 OpenAI-Organization 头 = 本地缓存的 time_stamp（就是 /api/getTime 的毫秒 token）。

用法: python tools/probe_art.py
"""
import json, sys, time

import requests

sys.path.insert(0, __file__.rsplit('tools', 1)[0] + 'tools')
from probe_upstream import make_jwt, BUNDLE, VERSION, BUILD  # noqa: E402

CHATAPI = 'https://chatapi.begamob.com'
ARTAPI = 'https://aiapi-art.begamob.com'
ART_MODELS = {'IMAGINE_V1': 27, 'IMAGINE_V3': 28, 'REALISTIC': 29,
              'IMAGINE_V4': 30, 'CREATIVE_V4': 31, 'ANIME_V5': 34}


def server_time():
    r = requests.get(CHATAPI + '/api/getTime', timeout=15,
                     headers={'User-Agent': 'okhttp/4.12.0'})
    return str(r.json()['token'])


def art_headers(ts=None, with_org=False):
    ts = ts or server_time()
    h = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + make_jwt(),
        'User-Agent': (f'VersionApp:{VERSION}/AppId:{BUNDLE}/Build:{BUILD}'
                       f'/VersionSDK:33/OS:Android/UserAgent:okhttp/4.12.0'
                       f'userId:/deviceId:art-probe'),
        'timestamp': ts,
    }
    if with_org:
        h['OpenAI-Organization'] = ts        # 解密失败 → 实际就是时间戳
    return h


def gen(prompt, model_id=30, style_id=0, aspect='1:1', timeout=180, **kw):
    body = {'prompt': prompt, 'model_id': model_id, 'style_id': style_id,
            'aspect_ratio': aspect}
    body.update(kw)
    t0 = time.time()
    r = requests.post(ARTAPI + '/api/v1/generate_art', json=body,
                      headers=art_headers(with_org=True), timeout=timeout)
    return r, round((time.time() - t0) / 1000, 1)


def main():
    print('== 1) 头部必要性对照（空体，看 400 还是 401）')
    for label, kw in (('无 timestamp/Organization', {}),
                      ('只 timestamp', {}), ('timestamp + Organization', {})):
        h = {'Content-Type': 'application/json',
             'Authorization': 'Bearer ' + make_jwt(),
             'User-Agent': 'okhttp/4.12.0'}
        ts = server_time()
        if label != '无 timestamp/Organization':
            h['timestamp'] = ts
        if label == 'timestamp + Organization':
            h['OpenAI-Organization'] = ts
        try:
            r = requests.post(ARTAPI + '/api/v1/generate_art', json={}, headers=h, timeout=30)
            print(f'  {label:28s} -> {r.status_code} {r.text[:130]}')
        except Exception as e:
            print(f'  {label:28s} -> EXC {type(e).__name__}')

    print('\n== 2) 真实出图（IMAGINE_V4=30, 1:1）')
    r, sec = gen('a red apple on a wooden table, soft light')
    print(f'  status={r.status_code} {sec}s  {r.text[:400]}')
    if r.status_code == 200:
        open('art_raw.json', 'w', encoding='utf-8').write(r.text)
        try:
            d = r.json()
            data = d.get('data') or d
            urls = []
            def walk(o):
                if isinstance(o, dict):
                    for k, v in o.items():
                        if k in ('url', 'image', 'image_url', 'imageUrl') and isinstance(v, str):
                            urls.append(v)
                        walk(v)
                elif isinstance(o, list):
                    for v in o:
                        walk(v)
            walk(d)
            print('   图片 URL:', urls[:4])
        except Exception as e:
            print('   parse fail', e)

    print('\n== 3) 参数/模型边界')
    for mid, name in ART_MODELS.items():
        r, sec = gen('a cat', model_id=mid, timeout=180)
        print(f'  {name:12s} id={mid:<3} -> {r.status_code} {sec}s {r.text[:110]}')
    for aspect in ('9:16', '16:9', '3:4', 'bad'):
        r, sec = gen('a cat', aspect=aspect, timeout=180)
        print(f'  aspect={aspect:6s} -> {r.status_code} {sec}s {r.text[:90]}')
    r, sec = gen('', timeout=60)
    print(f'  空 prompt      -> {r.status_code} {r.text[:110]}')
    r, sec = gen('a cat', model_id=999, timeout=60)
    print(f'  model_id=999   -> {r.status_code} {r.text[:110]}')


if __name__ == '__main__':
    main()
