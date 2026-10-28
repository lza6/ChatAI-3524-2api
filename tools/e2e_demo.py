# -*- coding: utf-8 -*-
"""demo 页真实浏览器验收（Playwright + Chromium）：非流式 + 流式各跑一次，关键状态截图。"""
import sys

from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8916'
errors, reqs_failed = [], []


def main():
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page()
        pg.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        pg.on('requestfailed', lambda r: reqs_failed.append(r.url + ' ' + str(r.failure)))

        pg.goto(BASE, wait_until='load')
        pg.wait_for_selector('#healthText')
        pg.wait_for_function("document.getElementById('healthText').textContent.includes('模型')",
                             timeout=15000)
        health = pg.inner_text('#healthText')
        models = pg.eval_on_selector_all('#model option', 'els => els.length')
        print(f'[1] 页面加载 OK · 健康: {health} · 模型选项: {models}')
        pg.screenshot(path='shot_1_idle.png', full_page=True)

        # 非流式
        pg.uncheck('#stream')
        pg.fill('#input', '用一句话介绍 HTTP 和 HTTPS 的区别')
        pg.click('#send')
        pg.wait_for_function(
            "(() => { const b = document.querySelectorAll('.msg.assistant .body');"
            " return b.length >= 2 && b[b.length-1].textContent.length > 8; })()", timeout=120000)
        txt = pg.eval_on_selector_all(".msg.assistant .body", "els => els[els.length-1].textContent")
        meta = pg.eval_on_selector_all(".msg.assistant .meta", "els => els.length ? els[els.length-1].textContent : ''")
        print(f'[2] 非流式回复 OK · len={len(txt)} · meta={meta}')
        print('    ', txt[:80].replace('\n', ' '))
        pg.screenshot(path='shot_2_nonstream.png', full_page=True)

        # 流式
        pg.check('#stream')
        pg.fill('#input', '数到 5，只输出数字')
        pg.click('#send')
        pg.wait_for_function(
            "(() => { const m = document.querySelectorAll('.msg.assistant .meta');"
            " return m.length >= 2 && m[m.length-1].textContent.includes('SSE'); })()", timeout=120000)
        txt2 = pg.eval_on_selector_all(".msg.assistant .body", "els => els[els.length-1].textContent")
        meta2 = pg.eval_on_selector_all(".msg.assistant .meta", "els => els[els.length-1].textContent")
        print(f'[3] 流式回复 OK · len={len(txt2)} · meta={meta2}')
        print('    ', txt2[:80].replace('\n', ' '))
        pg.screenshot(path='shot_3_stream.png', full_page=True)

        # 错误路径：未知模型走 UI 之外，直接验后端 + 统计面板刷新
        # 多模态读图
        pg.fill('#imgUrl', 'https://raw.githubusercontent.com/github/explore/main/topics/python/python.png')
        pg.fill('#input', '这张图里是什么？一句话')
        pg.click('#send')
        pg.wait_for_function(
            "(() => { const b = document.querySelectorAll('.msg.assistant .body');"
            " return b.length >= 3 && b[b.length-1].textContent.length > 6; })()", timeout=120000)
        txt3 = pg.eval_on_selector_all(".msg.assistant .body", "els => els[els.length-1].textContent")
        print(f'[4] 多模态读图 OK · {txt3[:60]}')
        pg.screenshot(path='shot_5_vision.png', full_page=True)
        pg.fill('#imgUrl', '')

        # 摘要模式
        pg.fill('#input', '人工智能是计算机科学的一个分支，它企图了解智能的实质并生产出以与人类智能相似方式'
                          '做出反应的智能机器，研究领域包括机器人、语言识别、图像识别、自然语言处理和专家系统。')
        pg.click('#summarize')
        pg.wait_for_function(
            "(() => { const b = document.querySelectorAll('.msg.assistant .body');"
            " return b.length >= 4 && b[b.length-1].textContent.length > 10; })()", timeout=120000)
        txt4 = pg.eval_on_selector_all(".msg.assistant .body", "els => els[els.length-1].textContent")
        print(f'[5] 摘要模式 OK · {txt4[:60]}')
        pg.screenshot(path='shot_6_summarize.png', full_page=True)

        pg.wait_for_timeout(5500)
        s_req = pg.inner_text('#sReq')
        s_ok = pg.inner_text('#sOk')
        p50 = pg.inner_text('#sP50')
        print(f'[6] 统计面板刷新 OK · 请求={s_req} 上游成功={s_ok} P50={p50}')
        pg.screenshot(path='shot_4_stats.png', full_page=True)

        br.close()

    print(f'[7] 控制台错误 {len(errors)} 条, 请求失败 {len(reqs_failed)} 条')
    for e in errors[:5]:
        print('   console:', e[:140])
    for r in reqs_failed[:5]:
        print('   failed:', r[:140])
    ok = len(errors) == 0 and len(reqs_failed) == 0
    print('== 浏览器验收', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
