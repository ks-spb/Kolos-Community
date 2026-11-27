"""Browser acceptance: full new request, independent acknowledgements, all modes isolated."""
from pathlib import Path
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from threading import Thread
import os, shutil, json
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'.test-output';OUT.mkdir(exist_ok=True)
class Quiet(SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=str(ROOT/'dist')))
Thread(target=server.serve_forever,daemon=True).start();url=f'http://127.0.0.1:{server.server_port}/'
inline=os.environ.get('KOLOS_INLINE_TEST')=='1'
def snap(page):
 return page.evaluate("""()=>{let value;document.dispatchEvent(new CustomEvent('kolos:residual:snapshot',{detail:{reply:v=>value=v}}));return value;}""")
def speed(page,v=100):page.locator('#rg-speed').evaluate('(e,v)=>{e.value=v;e.dispatchEvent(new Event("input",{bubbles:true}))}',str(v))
def paused(page):page.wait_for_function('document.querySelector("#rg-state").textContent==="На паузе"',timeout=30000)
def run(page,text):
 page.locator('#rg-query').fill(text);page.locator('#rg-start').click();paused(page)
with sync_playwright() as pw:
 browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'))
 ctx=browser.new_context(viewport={'width':1536,'height':1000},accept_downloads=True)
 page=ctx.new_page();page.set_default_timeout(12000);errors=[];urls=[]
 page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:urls.append(r.url));page.on('dialog',lambda d:d.accept())
 try:
  if inline:page.set_content((ROOT/'dist/index.html').read_text(encoding='utf-8'),wait_until='load')
  else:page.goto(url)
  page.wait_for_function('document.querySelector("#submit").disabled===false')
  # Freeze an unfinished original queue before entering the third mode.
  page.locator('#text-input').fill('абв');page.locator('#submit').click();page.wait_for_timeout(160)
  page.locator('#mode-disinhibition').click();page.wait_for_function('document.querySelector("#rg-demo").disabled===false')
  old_count=page.locator('#count-edges').text_content();page.wait_for_timeout(1100);assert page.locator('#count-edges').text_content()==old_count
  page.locator('#rg-demo').click();speed(page)
  assert 'различных вводов: 2' in page.locator('#rg-evidence').inner_text()
  run(page,'добавь траты 1354')
  assert page.locator('#rg-output').inner_text()=='1354';assert page.locator('#rg-confirmed').inner_text()=='1354'
  assert page.locator('#rg-count').inner_text()=='Подтверждено 17 / 17'
  assert 'Долговременные веса не менялись' in page.locator('#rg-message').inner_text()
  page.locator('#rg-fit').click();page.screenshot(path=str(OUT/'disinhibition-complete.png'))
  # On a new run pause freezes proposal, request occurrence and environment alike.
  page.locator('#rg-reset').click();speed(page,1000);page.locator('#rg-start').click();page.wait_for_timeout(200);page.locator('#rg-play').click();paused(page)
  frozen=snap(page);page.wait_for_timeout(1100);assert snap(page)==frozen
  before=len(snap(page)['engine']['operations']);page.locator('#rg-step').click()
  assert len(snap(page)['engine']['operations'])==before+1
  page.wait_for_timeout(300);assert len(snap(page)['engine']['operations'])==before+1
  page.locator('#rg-reset').click();speed(page);page.locator('#rg-ack-mode').select_option('manual')
  run(page,'добавь траты 1354')
  assert page.locator('#rg-output').inner_text()=='1';assert page.locator('#rg-confirmed').inner_text()=='—'
  assert page.locator('#rg-count').inner_text()=='Подтверждено 13 / 17'
  assert not page.locator('#rg-deliver').is_disabled()
  held=snap(page);page.wait_for_timeout(500);assert snap(page)==held
  page.screenshot(path=str(OUT/'disinhibition-awaiting-ack.png'))
  page.locator('#rg-deliver').click();assert page.locator('#rg-confirmed').inner_text()=='1'
  assert page.locator('#rg-count').inner_text()=='Подтверждено 14 / 17'
  page.locator('#rg-duplicate').click();assert page.locator('#rg-count').inner_text()=='Подтверждено 14 / 17'
  page.locator('#rg-play').click();paused(page);assert page.locator('#rg-output').inner_text()=='13'
  assert page.locator('#rg-confirmed').inner_text()=='1'
  # Switching modes with a pending confirmation must not run any hidden engine.
  third=snap(page);page.locator('#mode-signal').click();page.wait_for_timeout(350)
  assert page.locator('#sg-demo').is_visible()
  page.locator('#mode-sequential').click();assert page.locator('#text-input').input_value()=='абв'
  assert page.locator('#count-edges').text_content()==old_count
  page.locator('#mode-disinhibition').click();assert snap(page)==third
  # New sequence length and repeated zeros.
  page.locator('#rg-reset').click();page.locator('#rg-ack-mode').select_option('auto');run(page,'добавь траты 1001')
  assert page.locator('#rg-output').inner_text()=='1001'
  page.locator('#rg-reset').click();page.locator('#rg-shuffle').click();run(page,'добавь траты 54321')
  assert page.locator('#rg-output').inner_text()=='54321'
  # Missing object cannot consume the keyboard remainder.
  page.locator('#rg-reset').click();page.locator('[data-rgo="CALC"]').click();page.locator('#rg-hide').click();run(page,'добавь траты 1354')
  assert 'отсутствует' in page.locator('#rg-message').inner_text();assert page.locator('#rg-output').inner_text()=='—'
  assert page.locator('#rg-count').inner_text()=='Подтверждено 13 / 17'
  page.locator('#rg-show').click();page.locator('#rg-play').click();paused(page);assert page.locator('#rg-output').inner_text()=='1354'
  # Arbitrary context length and target learned through the actual record UI.
  page.locator('#rg-reset').click();page.locator('#rg-training').evaluate('e=>e.open=true')
  for value in ['1700','2345']:
   page.locator('#rg-demo-query').fill('отправь в окно '+value);page.locator('#rg-record').click()
   page.locator('[data-rgo="DOC"]').click();page.locator('#rg-keys').press_sequentially(value);page.keyboard.press('Escape')
   assert not page.locator('#rg-learn').is_disabled()
   page.locator('#rg-learn').click();page.locator('#rg-approve').click()
  run(page,'отправь в окно 1354');assert page.locator('#rg-output').inner_text()=='1354';assert page.locator('#rg-app').inner_text()=='Открыто: DOC'
  saved=snap(page)
  if not inline:
   page.wait_for_timeout(400);page.reload();page.locator('#mode-disinhibition').click();page.wait_for_function('document.querySelector("#rg-demo").disabled===false')
   assert snap(page)['engine']==saved['engine'];assert page.locator('#rg-output').inner_text()=='1354'
  # Timeline is read-only; exported log restores environment and memory, not effects in live app.
  saved=snap(page)
  page.locator('#rg-timeline').evaluate('e=>{e.value=3;e.dispatchEvent(new Event("input",{bubbles:true}))}')
  assert page.locator('#rg-history-banner').is_visible();assert snap(page)==saved
  page.locator('#rg-live').click()
  if inline:(OUT/'disinhibition-export.json').write_text(json.dumps(saved,ensure_ascii=False),encoding='utf-8')
  else:
   with page.expect_download() as download:page.locator('#rg-export').click()
   download.value.save_as(OUT/'disinhibition-export.json')
  assert json.loads((OUT/'disinhibition-export.json').read_text(encoding='utf-8'))==saved
  page.locator('#rg-clear').click();page.locator('#rg-file').set_input_files(str(OUT/'disinhibition-export.json'));page.wait_for_timeout(400)
  assert snap(page)['engine']==saved['engine']
  (OUT/'disinhibition-invalid.json').write_text('{"schema":"wrong"}')
  page.locator('#rg-file').set_input_files(str(OUT/'disinhibition-invalid.json'));page.wait_for_timeout(150);assert snap(page)['engine']==saved['engine']
  page.locator('#rg-view').select_option('memory');page.locator('#rg-fit').click();page.screenshot(path=str(OUT/'disinhibition-memory.png'))
  page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(500)
  assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),'mobile overflow'
  page.locator('#rg-view').select_option('input');page.locator('#rg-fit').click();page.screenshot(path=str(OUT/'disinhibition-mobile.png'),full_page=True)
  assert not errors,errors
  assert all(not u.startswith(('http:','https:')) or u.startswith(url) for u in urls),urls
  print(json.dumps({'result':'PASS','page_errors':errors,'external_requests':0,'indexeddb_reload':not inline,'mode':'inline' if inline else 'http',
    'scenarios':['full 1354','two shown examples','pause','one tick','manual ack','duplicate ack','all 3 modes','1001','54321','moved object','hidden object','own new context and target','history','JSON','reload','mobile']}),flush=True)
 except Exception as exc:
  print('FAIL',repr(exc),'PAGE ERRORS',errors,flush=True);page.screenshot(path=str(OUT/'disinhibition-failure.png'),full_page=True);raise
 finally:
  browser.close();server.shutdown()
