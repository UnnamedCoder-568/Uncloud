import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / 'chat-actions-2026-10-15'
OUT.mkdir(exist_ok=True)
HTML = '''<main style="padding:48px;min-height:100vh;background:var(--bg);color:var(--text)">
<div class="chat-message-list column flex flex-col pt-4 pb-12">
<div id="first" class="chat-message self-start max-w-[85%]">
  <div class="text-sm px-1">The message stays aligned while its controls appear.</div>
  <div id="actions1" class="chat-message-actions flex items-center gap-1 px-1 text-[10px] text-[var(--text-faint)]">
    <button class="pill h-7 px-2">Copy</button><button class="pill h-7 px-2">Note</button><button class="pill h-7 px-2">Chisel</button>
  </div>
</div>
<div id="user" class="chat-message self-end max-w-[80%]"><div class="bg-[var(--bg-raised)] border border-[var(--border)] rounded-2xl rounded-br-sm px-4 py-2.5 text-sm">And the next message stays in place?</div></div>
<div id="second" class="chat-message self-start max-w-[85%]">
  <div class="text-sm px-1">Yes. Only the hovered answer’s actions appear.</div>
  <div id="actions2" class="chat-message-actions flex items-center gap-1 px-1 text-[10px] text-[var(--text-faint)]">
    <button class="pill h-7 px-2">Copy</button><button class="pill h-7 px-2">Note</button><button class="pill h-7 px-2">Chisel</button>
  </div>
</div></div></main>'''


def prepare(page):
    page.goto('http://127.0.0.1:1437/dev/markdown-preview.html')
    page.locator('.md-code').first.wait_for()
    page.evaluate('''() => { const meta = document.createElement('meta'); meta.name = 'viewport'; meta.content = 'width=device-width, initial-scale=1'; document.head.append(meta); }''')
    page.evaluate('(html) => { document.getElementById("root").innerHTML = html; }', HTML)


def state(page):
    return page.evaluate('''() => ({
      opacity: [...document.querySelectorAll('.chat-message-actions')].map(el => getComputedStyle(el).opacity),
      pointers: [...document.querySelectorAll('.chat-message-actions')].map(el => getComputedStyle(el).pointerEvents),
      boxes: ['first','actions1','user','second','actions2'].map(id => {
        const r=document.getElementById(id).getBoundingClientRect();
        return {id,x:r.x,y:r.y,width:r.width,height:r.height};
      })
    })''')


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    try:
        desktop = browser.new_context(viewport={'width':1200, 'height':700})
        page = desktop.new_page()
        prepare(page)
        page.mouse.move(1190, 690)
        idle = state(page)
        assert idle['opacity'] == ['0', '0'], idle
        assert idle['pointers'] == ['none', 'none'], idle
        boxes = {box['id']: box for box in idle['boxes']}
        assert boxes['user']['y'] - boxes['first']['y'] - boxes['first']['height'] == 40
        assert boxes['second']['y'] - boxes['user']['y'] - boxes['user']['height'] == 40
        assert page.locator('#actions1').evaluate('(el) => getComputedStyle(el).position') == 'absolute'
        page.screenshot(path=str(OUT / 'desktop-idle.png'))
        page.locator('#first').hover()
        hover = state(page)
        assert hover['opacity'] == ['1', '0'], hover
        assert hover['pointers'] == ['auto', 'none'], hover
        assert hover['boxes'] == idle['boxes'], 'Hover moved the messages'
        page.screenshot(path=str(OUT / 'desktop-hover.png'))
        page.locator('#actions1 button').first.hover()
        assert state(page)['opacity'] == ['1', '0'], 'Controls disappeared on the pointer path'
        page.locator('#actions1 button').first.click()
        page.locator('#actions1 button').first.evaluate('(el) => el.blur()')
        page.mouse.move(1190, 690)
        assert state(page)['opacity'] == ['0', '0']
        page.locator('#actions2 button').first.focus()
        focus = state(page)
        assert focus['opacity'] == ['0', '1'], focus
        assert focus['boxes'] == idle['boxes'], 'Focus moved the messages'
        page.locator('#actions2 button').first.evaluate('(el) => el.blur()')
        assert state(page)['opacity'] == ['0', '0']
        desktop.close()

        touch = browser.new_context(viewport={'width':390, 'height':700}, has_touch=True, is_mobile=True)
        page = touch.new_page()
        prepare(page)
        coarse = state(page)
        assert coarse['opacity'] == ['1', '1'], coarse
        assert coarse['pointers'] == ['auto', 'auto'], coarse
        boxes = {box['id']: box for box in coarse['boxes']}
        assert boxes['user']['y'] - boxes['first']['y'] - boxes['first']['height'] == 56
        assert boxes['actions1']['y'] + boxes['actions1']['height'] <= boxes['user']['y'], 'Touch controls overlap next turn'
        assert page.locator('#actions1 button').first.bounding_box()['height'] >= 44
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Horizontal overflow'
        page.screenshot(path=str(OUT / 'touch.png'))
        touch.close()
        report = {'scope':'Actual app CSS in an isolated browser fixture; no inference or user browser session.',
                  'desktop_idle':idle,'desktop_hover':hover,'keyboard_focus':focus,'touch':coarse,
                  'layout_shift_px':0,'desktop_gap_px':40,'mobile_gap_px':56,'passed':True}
        (OUT / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'passed': True,'layout_shift_px': 0,'screenshots':str(OUT)}))
    finally:
        browser.close()
