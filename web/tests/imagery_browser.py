"""Real HTTP browser check for shared representations and motor-inhibited imagery."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from pathlib import Path
import json, shutil, os
from playwright.sync_api import sync_playwright
INLINE=os.environ.get('KOLOS_INLINE_TEST')=='1'
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'.test-output';OUT.mkdir(exist_ok=True)
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*a):pass
server=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=str(ROOT/'dist')))
Thread(target=server.serve_forever,daemon=True).start();url=f'http://127.0.0.1:{server.server_port}/'
def snapshot(p):
    return p.evaluate("()=>{let r;document.dispatchEvent(new CustomEvent('kolos:state:snapshot',{detail:{reply:v=>r=v}}));return r;}")
def pause(p):p.wait_for_function('document.querySelector("#st-play-state").textContent==="На паузе"',timeout=45000)
def speed(p):p.locator('#st-speed').evaluate('e=>{e.value=100;e.dispatchEvent(new Event("input",{bubbles:true}))}')
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'))
    p=browser.new_page(viewport={'width':1580,'height':1100});errors=[];requests=[]
    p.on('pageerror',lambda e:errors.append(str(e)));p.on('request',lambda r:requests.append(r.url));p.on('dialog',lambda d:d.accept())
    try:
        if INLINE:p.set_content((ROOT/'dist/index.html').read_text(encoding='utf8'))
        else:p.goto(url)
        p.locator('#mode-states').click();p.wait_for_function('!document.querySelector("#st-image-demo").disabled')
        speed(p);p.locator('#st-image-demo').click();pause(p)
        assert p.locator('#st-image-panel').get_attribute('data-mode')=='imagine'
        assert p.locator('#st-output').inner_text()=='—'
        assert p.locator('#st-screen').get_attribute('data-surface')=='window'
        assert p.locator('#st-goal').get_attribute('data-held')=='true'
        assert p.locator('#st-image-nodes [data-i]').count()>=6
        assert p.locator('#st-image-nodes [data-repr]').evaluate_all('(xs)=>xs.some(e=>Number(e.dataset.i)>.9&&Number(e.dataset.s)===0)')
        p.screenshot(path=str(OUT/'imagery-before.png'),full_page=True)
        before=snapshot(p);p.wait_for_timeout(500);assert snapshot(p)==before
        p.locator('#st-image-rest').click();pause(p)
        assert p.locator('#st-image-nodes [data-i]').evaluate_all('(xs)=>xs.every(e=>Number(e.dataset.i)<.01)')
        p.locator('#st-image-act').click();pause(p)
        assert p.locator('#st-output').inner_text()=='2345'
        assert p.locator('#st-message').get_attribute('data-state')=='complete'
        assert p.locator('#st-goal').get_attribute('data-held')=='false'
        assert 'Подтверждений от среды: 1' in p.locator('#st-image-summary').inner_text()
        assert p.locator('#st-image-nodes [data-present=true]').count()>=6
        p.screenshot(path=str(OUT/'imagery-after.png'),full_page=True)
        done=snapshot(p);p.locator('#st-image-test').click();assert p.locator('[data-imagery-result=PASS]').count()==1;assert snapshot(p)==done
        p.locator('#st-timeline').evaluate('e=>{e.value=12;e.dispatchEvent(new Event("input",{bubbles:true}))}')
        assert p.locator('#st-history-banner').is_visible();assert snapshot(p)==done
        p.locator('#st-live').click();p.wait_for_timeout(600)
        if not INLINE:
            p.reload();p.locator('#mode-states').click();p.wait_for_function('!document.querySelector("#st-image-demo").disabled')
            assert snapshot(p)['engine']==done['engine'];assert p.locator('#st-play-state').inner_text()=='На паузе'
        p.set_viewport_size({'width':390,'height':844});p.wait_for_timeout(300)
        assert p.evaluate('document.documentElement.scrollWidth<=innerWidth'),'mobile overflow'
        p.screenshot(path=str(OUT/'imagery-mobile.png'),full_page=True)
        assert not errors,errors
        assert not [r for r in requests if r.startswith(('http:','https:')) and not r.startswith(url)]
        report=dict(result='PASS',imagery_no_effects=True,source_separation=True,fade=True,realized='2345',history_readonly=True,reload=not INLINE,mode='inline' if INLINE else 'http',mobile=True,errors=errors)
        (OUT/'imagery-browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report))
    finally:
        browser.close();server.shutdown()
