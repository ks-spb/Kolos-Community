"""Real HTTP check: teach paired language, input only text, observe I, then actions."""
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
from pathlib import Path
import json,shutil,os
from playwright.sync_api import sync_playwright
INLINE=os.environ.get('KOLOS_INLINE_TEST')=='1'
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'.test-output';OUT.mkdir(exist_ok=True)
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*a):pass
server=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=str(ROOT/'dist')))
Thread(target=server.serve_forever,daemon=True).start();url=f'http://127.0.0.1:{server.server_port}/'
def snapshot(p):return p.evaluate("()=>{let r;document.dispatchEvent(new CustomEvent('kolos:state:snapshot',{detail:{reply:v=>r=v}}));return r;}")
def pause(p):p.wait_for_function('document.querySelector("#st-play-state").textContent==="На паузе"',timeout=90000)
with sync_playwright() as pw:
    b=pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'))
    p=b.new_page(viewport={'width':1580,'height':1200});errors=[];requests=[]
    p.on('pageerror',lambda e:errors.append(str(e)));p.on('request',lambda r:requests.append(r.url));p.on('dialog',lambda d:d.accept())
    try:
        p.set_content((ROOT/'dist/index.html').read_text(encoding='utf8')) if INLINE else p.goto(url)
        p.locator('#mode-states').click();p.wait_for_function('!document.querySelector("#st-language-demo").disabled')
        p.locator('#st-language-panel > summary').click();p.locator('#st-language-demo').click()
        p.wait_for_timeout(850);p.locator('#st-play').click();pause(p)
        early=snapshot(p);p.wait_for_timeout(400);assert snapshot(p)==early,'pause changed language dynamics'
        p.locator('#st-step').click();assert len(snapshot(p)['engine']['operations'])==len(early['engine']['operations'])+1
        assert p.locator('#st-language-graph [data-language-edge]').count()>0
        p.locator('#st-play').click();pause(p)
        assert 'FIELD = 1354' in p.locator('#st-language-decoded').inner_text()
        assert p.locator('#st-output').inner_text()=='—'
        assert p.locator('#st-image-panel').get_attribute('data-mode')=='imagine'
        assert p.locator('#st-image-nodes [data-i]').evaluate_all('(xs)=>xs.some(n=>+n.dataset.i>.9&&+n.dataset.s===0)')
        p.screenshot(path=str(OUT/'language-before.png'),full_page=True)
        p.locator('#st-image-act').click();pause(p)
        assert p.locator('#st-output').inner_text()=='1354'
        assert p.locator('#st-message').get_attribute('data-state')=='complete'
        assert 'Подтверждений от среды: 1' in p.locator('#st-image-summary').inner_text()
        p.screenshot(path=str(OUT/'language-after.png'),full_page=True)
        done=snapshot(p);p.locator('#st-language-test').click();assert p.locator('[data-language-result="PASS"]').count()==1;assert snapshot(p)==done
        p.wait_for_timeout(500)
        if not INLINE:
            p.reload();p.locator('#mode-states').click();p.wait_for_function('!document.querySelector("#st-language-demo").disabled')
            assert snapshot(p)['engine']==done['engine'];assert p.locator('#st-play-state').inner_text()=='На паузе'
            p.locator('#st-language-panel > summary').click()
        p.locator('#st-language-phrase').fill('не хочу увидеть 1354 в поле');p.locator('#st-language-act').click();pause(p)
        assert p.locator('#st-message').get_attribute('data-state')=='unknown'
        assert p.locator('#st-image-panel').is_hidden()
        p.locator('#st-reset').click();p.locator('#st-language-training > summary').click()
        p.locator('#st-language-target').select_option('field:FIELD')
        for val in ['1700','2345']:
            p.locator('#st-language-train-phrase').fill('zorp '+val+' glip');p.locator('#st-language-value').fill(val);p.locator('#st-language-teach').click()
        assert 'zorp 2345 glip' in p.locator('#st-language-lessons').inner_text()
        p.locator('#st-language-training > summary').click()
        p.locator('#st-language-phrase').fill('zorp 3521 glip');p.locator('#st-language-read').click();pause(p)
        assert 'FIELD = 3521' in p.locator('#st-language-decoded').inner_text()
        assert p.locator('#st-output').inner_text()=='1354'
        p.set_viewport_size({'width':390,'height':844});p.wait_for_timeout(250)
        assert p.evaluate('document.documentElement.scrollWidth<=innerWidth'),'mobile overflow'
        p.screenshot(path=str(OUT/'language-mobile.png'),full_page=True)
        assert not errors,errors
        external=[r for r in requests if r.startswith(('http:','https:')) and not r.startswith(url)];assert not external
        report=dict(result='PASS',text_only_inference=True,heldout='1354',learned_pairs_ui=True,unknown_no_image=True,pause=True,step=True,reload=not INLINE,mode='inline' if INLINE else 'http',mobile=True,page_errors=errors,external_requests=len(external))
        (OUT/'language-browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report))
    finally:b.close();server.shutdown()
