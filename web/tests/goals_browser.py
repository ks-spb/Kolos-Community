"""Visual/control acceptance of goal capabilities on a real HTTP origin."""
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
from threading import Thread
import json, os, shutil
from playwright.sync_api import sync_playwright
INLINE=os.environ.get('KOLOS_INLINE_TEST')=='1'
CASES=[int(x) for x in os.environ['KOLOS_CASES'].split(',')] if os.environ.get('KOLOS_CASES') else list(range(5,11))
if not CASES or len(set(CASES))!=len(CASES) or any(n not in range(5,11) for n in CASES):
    raise ValueError('KOLOS_CASES must select unique goal cases 5..10')
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'.test-output';OUT.mkdir(exist_ok=True)
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*a):pass
server=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=str(ROOT/'dist')))
Thread(target=server.serve_forever,daemon=True).start();url=f'http://127.0.0.1:{server.server_port}/'
def snapshot(page):
    return page.evaluate("""()=>{let r;document.dispatchEvent(new CustomEvent('kolos:state:snapshot',{detail:{reply:v=>r=v}}));return r;}""")
def paused(page):page.wait_for_function('document.querySelector("#st-play-state").textContent==="На паузе"',timeout=45000)
def speed(page):page.locator('#st-speed').evaluate('(e)=>{e.value=100;e.dispatchEvent(new Event("input",{bubbles:true}))}')
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'))
    ctx=browser.new_context(viewport={'width':1560,'height':1040},accept_downloads=True);page=ctx.new_page();page.set_default_timeout(15000)
    errors=[];requests=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:requests.append(r.url));page.on('dialog',lambda d:d.accept())
    try:
        
        if INLINE:page.set_content((ROOT/'dist/index.html').read_text(encoding='utf-8'),wait_until='load')
        else:page.goto(url)
        page.evaluate('window.confirm=()=>true');page.locator('#mode-states').click();page.wait_for_function('!document.querySelector("#st-case-10").disabled')
        for n in CASES:
            print('CASE',n,'load',flush=True)
            page.locator(f'#st-case-{n}').click();speed(page)
            assert page.locator('#st-query').get_attribute('readonly') is not None
            page.locator('#st-start').click();print('RUNNING',n,flush=True);paused(page);print('COMPLETE',n,flush=True)
            assert page.locator('#st-message').get_attribute('data-state')=='complete',page.locator('#st-message').inner_text()
            assert page.locator('#st-goal').get_attribute('data-held')=='false'
            if n in (5,7,9):assert page.locator('#st-output').inner_text()==('3521' if n==5 else '2345')
            if n==10:assert 'Ошибка прогноза' in page.locator('#st-intent-status').inner_text()
            page.screenshot(path=str(OUT/f'goals-case-{n}.png'))
        print('SUITE',flush=True);before=snapshot(page);page.locator('#st-suite-ten').click()
        assert page.locator('[data-capability][data-result="PASS"]').count()==10
        assert snapshot(page)==before
        page.locator('#st-timeline').evaluate('e=>{e.value=10;e.dispatchEvent(new Event("input",{bubbles:true}))}')
        assert page.locator('#st-history-banner').is_visible();assert snapshot(page)==before
        page.locator('#st-live').click()
        print('BUILDER',flush=True);page.locator('#st-case-9').click();page.locator('#st-goal-builder').evaluate('e=>e.open=true')
        page.locator('#st-goal-target').select_option('field:FIELD');page.locator('#st-goal-value').fill('1001');page.locator('#st-goal-add').click()
        page.locator('#st-goal-start').click();paused(page);assert page.locator('#st-output').inner_text()=='1001'
        page.locator('#st-case-9').click();page.locator('#st-speed').evaluate('e=>{e.value=300;e.dispatchEvent(new Event("input",{bubbles:true}))}')
        page.locator('#st-start').click();page.wait_for_timeout(700);page.locator('#st-play').click();paused(page)
        fixed=snapshot(page);page.wait_for_timeout(600);assert snapshot(page)==fixed
        page.locator('#st-step').click();assert len(snapshot(page)['engine']['operations'])==len(fixed['engine']['operations'])+1
        speed(page);page.locator('#st-play').click();paused(page)
        saved=snapshot(page);page.wait_for_timeout(400)
        if not INLINE:
            page.reload();page.locator('#mode-states').click();page.wait_for_function('!document.querySelector("#st-case-10").disabled')
            assert snapshot(page)['engine']==saved['engine'];assert page.locator('#st-play-state').inner_text()=='На паузе'
        page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(500)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),'mobile overflow'
        page.screenshot(path=str(OUT/'goals-mobile.png'),full_page=True)
        assert not errors,errors
        assert not [r for r in requests if r.startswith(('https:','http:')) and not r.startswith(url)]
        report=dict(result='PASS',cases=CASES,full_goal_browser_suite=set(CASES)==set(range(5,11)),suite=10,goal_builder='1001',pause=True,one_tick=True,history_readonly=True,indexeddb_reload=not INLINE,mobile=True,page_errors=errors,external_requests=0)
        (OUT/'goals-browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False),flush=True)
    except Exception as exc:
        print('FAILURE',repr(exc),flush=True);print('PAGE ERRORS',errors,flush=True)
        if page.locator('#st-message').count():print('STATE',page.locator('#st-message').inner_text(),flush=True)
        page.screenshot(path=str(OUT/'goals-failure.png'),full_page=True);raise
    finally:browser.close();server.shutdown()
