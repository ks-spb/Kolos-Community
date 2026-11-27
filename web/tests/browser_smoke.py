"""Optional end-to-end smoke test. pip install playwright; playwright install chromium.
Run from web/: python tests/browser_smoke.py. Uses a temporary local HTTP server; no external network needed.
"""
import json
import os
from pathlib import Path
import shutil
import threading
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.test-output'
OUT.mkdir(exist_ok=True)

def speed(page, value):
    page.locator('#speed').evaluate('(e,v)=>{e.value=v;e.dispatchEvent(new Event("input",{bubbles:true}))}',str(value))
def wait_idle(page):
    page.wait_for_function('document.querySelector("#submit").disabled===false',timeout=20000)
def export_data(page):
    with page.expect_download() as dl:
        page.locator('#export').click()
    path=OUT/'experiment.json';dl.value.save_as(path)
    return json.loads(path.read_text())
class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args): pass
server = ThreadingHTTPServer(('127.0.0.1',0), partial(QuietHandler,directory=str(ROOT/'dist')))
threading.Thread(target=server.serve_forever,daemon=True).start()
base_url=f'http://127.0.0.1:{server.server_port}/'
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'))
    context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
    page=context.new_page();errors=[];network=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:network.append(r.url))
    page.on('dialog',lambda d:d.accept())
    inline = os.environ.get('KOLOS_INLINE_TEST') == '1'
    if inline:
        page.set_content((ROOT/'dist/index.html').read_text(),wait_until='load')
    else:
        page.goto(base_url)
    wait_idle(page)
    page.screenshot(path=str(OUT/'initial-desktop.png'))
    # Pause freezes both memory and pulse, step commits exactly one event.
    speed(page,1000);page.locator('#text-input').fill('абв');page.locator('#submit').click()
    page.wait_for_timeout(280);page.locator('#play').click()
    assert not page.locator('#text-input').is_disabled(),'input must be editable while execution is paused'
    assert not page.locator('#submit').is_disabled(),'submit must allow replacing a paused queue'
    frozen=page.locator('#count-edges').inner_text();pos=page.locator('.pulse').get_attribute('cx')
    page.wait_for_timeout(1150)
    assert page.locator('#count-edges').inner_text()==frozen,'memory ran while paused'
    assert page.locator('.pulse').get_attribute('cx')==pos,'pulse moved while paused'
    speed(page,250);page.locator('#step').click();page.wait_for_timeout(600)
    assert int(page.locator('#count-edges').inner_text())==int(frozen)+1,'step did not commit one event'
    page.wait_for_timeout(300)
    assert int(page.locator('#count-edges').inner_text())==int(frozen)+1,'step ran ahead'
    page.locator('#play').click();wait_idle(page)
    assert page.locator('#count-edges').inner_text()=='3'
    assert page.locator('#count-nodes').inner_text()=='6'
    page.locator('#positive').click();wait_idle(page)
    page.locator('#new-attempt').click();wait_idle(page)
    page.locator('#text-input').fill('аб');page.locator('#submit').click();wait_idle(page)
    page.locator('#continue').click();wait_idle(page)
    assert page.locator('#answer').inner_text()=='в'
    assert page.locator('#count-edges').inner_text()=='9'
    assert page.locator('#current-name').inner_text()=='Успех'
    page.locator('#journal-toggle').click();page.wait_for_timeout(350);page.locator('#fit').click()
    page.screenshot(path=str(OUT/'demo-desktop.png'))
    original=export_data(page)
    # History replay cannot train again.
    page.locator('#replay').click();page.wait_for_timeout(3200)
    assert page.locator('#step-count').inner_text()=='9 / 9'
    assert export_data(page)['commands']==original['commands']
    assert page.locator('#live').is_visible()
    page.locator('#live').click()
    # Real IndexedDB requires a non-opaque origin; inline sandbox mode tests
    # unavailable-storage handling and validates persistence by JSON roundtrip.
    if not inline:
        page.wait_for_timeout(500);page.reload();wait_idle(page)
        assert page.locator('#count-edges').inner_text()=='9'
        assert page.locator('#answer').inner_text()=='в'
        assert export_data(page)['commands']==original['commands']
    else:
        assert page.locator('#save-state').evaluate('e=>e.classList.contains("warning")')
    # Import an actual exported file after clearing.
    (OUT/'original.json').write_text(json.dumps(original,ensure_ascii=False))
    page.locator('#clear').click();assert page.locator('#count-edges').inner_text()=='0'
    page.locator('#import-file').set_input_files(str(OUT/'original.json'))
    page.wait_for_function('document.querySelector("#count-edges").textContent==="9"')
    assert export_data(page)['commands']==original['commands']
    # Invalid input is rejected without losing current memory.
    (OUT/'bad.json').write_text('{"schema":"bad"}')
    page.locator('#import-file').set_input_files(str(OUT/'bad.json'));page.wait_for_timeout(150)
    assert page.locator('#count-edges').inner_text()=='9'
    # Repeated links grouped visually, but IDs stay distinct.
    page.locator('#clear').click();speed(page,250)
    page.locator('#text-input').fill('ааа');page.locator('#submit').click();wait_idle(page)
    assert page.locator('[data-edge="4:4"] .edge-label').text_content()=='5, 6'
    assert page.locator('#count-edges').inner_text()=='3'
    assert page.locator('#graph [data-node]').count()==4
    # Reverse directions stay separate.
    page.locator('#clear').click();page.locator('#text-input').fill('абаб');page.locator('#submit').click();wait_idle(page)
    assert page.locator('[data-edge="4:5"] .edge-label').text_content()=='5, 7'
    assert page.locator('[data-edge="5:4"] .edge-label').text_content()=='6'
    assert page.locator('[data-edge="4:5"] .edge').get_attribute('d')!=page.locator('[data-edge="5:4"] .edge').get_attribute('d')
    # Virtual screen: train CALC click + 1700, move CALC, replay safely.
    page.locator('#clear').click();speed(page,250)
    page.locator('#text-input').fill('добавь траты 1700');page.locator('#submit').click();wait_idle(page)
    page.locator('#train-start').click()
    page.locator('.screen-object[data-name="CALC"]').click()
    page.locator('#virtual-keyboard').type('1700')
    page.keyboard.press('Escape')
    assert not page.locator('#train-save').is_disabled()
    page.locator('#train-save').click();wait_idle(page)
    page.locator('#positive').click();wait_idle(page)
    page.locator('#new-attempt').click();wait_idle(page)
    page.locator('#reset-screen').click();page.locator('#shuffle-screen').click()
    page.locator('#text-input').fill('добавь траты 1700');page.locator('#submit').click();wait_idle(page)
    page.locator('#continue').click();wait_idle(page)
    assert page.locator('#current-name').inner_text()=='Успех'
    assert page.locator('#screen-opened').inner_text()=='Открыто: CALC'
    assert page.locator('#screen-display').inner_text()=='Ввод: 1700'
    # If CALC is hidden, CHECK must stop the chain before CLICK/KEY.
    page.locator('#new-attempt').click();wait_idle(page);page.locator('#reset-screen').click()
    page.locator('.screen-object[data-name="CALC"]').click();page.locator('#hide-object').click()
    page.locator('#text-input').fill('добавь траты 1700');page.locator('#submit').click();wait_idle(page)
    page.locator('#continue').click();wait_idle(page)
    assert 'не найден' in page.locator('#screen-alert').inner_text()
    assert page.locator('#screen-opened').inner_text()=='Рабочий стол'
    assert page.locator('#screen-display').inner_text()==''
    page.locator('#show-objects').click()
    # Mobile: no overflow and controls fit viewport.
    page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(300);page.locator('#fit').click()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),'horizontal mobile overflow'
    page.screenshot(path=str(OUT/'mobile.png'))
    assert not errors,errors
    assert all(u.startswith(base_url) or not u.startswith(('https:','http:')) for u in network),network
    print(json.dumps({'result':'PASS','mode':'inline' if inline else 'http','indexeddb_reload_verified':not inline,'page_errors':errors,'external_requests':0,'screenshots':str(OUT)},ensure_ascii=False))
    context.close();browser.close();server.shutdown()
