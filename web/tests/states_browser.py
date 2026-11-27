"""Browser acceptance of four state/goal scenarios on the packaged app (HTTP by default)."""
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
from threading import Thread
import json, os, shutil
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'.test-output'; OUT.mkdir(exist_ok=True)
class Quiet(SimpleHTTPRequestHandler):
 def log_message(self,*args): pass
server=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=str(ROOT/'dist')))
Thread(target=server.serve_forever,daemon=True).start();url=f'http://127.0.0.1:{server.server_port}/';inline=os.environ.get('KOLOS_INLINE_TEST')=='1'
def snap(page):
 return page.evaluate("""()=>{let r;document.dispatchEvent(new CustomEvent('kolos:state:snapshot',{detail:{reply:v=>r=v}}));return r;}""")
def speed(page,v=100): page.locator('#st-speed').evaluate('(e,v)=>{e.value=v;e.dispatchEvent(new Event("input",{bubbles:true}))}',str(v))
def paused(page): page.wait_for_function('document.querySelector("#st-play-state").textContent==="На паузе"',timeout=45000)
def load(page,i): page.locator(f'#st-case-{i}').click();speed(page)
def run(page): page.locator('#st-start').click();paused(page)
with sync_playwright() as pw:
 browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'))
 ctx=browser.new_context(viewport={'width':1560,'height':1000},accept_downloads=True);page=ctx.new_page();page.set_default_timeout(10000)
 errors=[];urls=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:urls.append(r.url));page.on('dialog',lambda d:d.accept())
 try:
  if inline:page.set_content((ROOT/'dist/index.html').read_text(),wait_until='load')
  else:page.goto(url)
  page.wait_for_function('!document.querySelector("#submit").disabled')
  page.locator('#text-input').fill('абв');page.locator('#submit').click();page.wait_for_timeout(180)
  page.locator('#mode-states').click();page.wait_for_function('!document.querySelector("#st-case-1").disabled')
  old_count=page.locator('#count-edges').inner_text();page.wait_for_timeout(1000);assert page.locator('#count-edges').inner_text()==old_count
  # Case 1, only A-selected + Enter opens the opaque window.
  load(page,1);assert page.locator('[data-stobj="A"]').is_visible();assert page.locator('[data-stobj="X"]').count()==0
  before=snap(page);run(page);assert 'завершена' in page.locator('#st-message').inner_text()
  assert page.locator('#st-screen').get_attribute('data-surface')=='window';assert page.locator('[data-stobj="A"]').count()==0
  assert page.locator('[data-stobj="X"]').is_visible();assert page.locator('[data-stobj="D"]').is_visible()
  assert len([x for x in snap(page)['engine']['operations'] if x['kind']=='teach'])==2
  # Case 2 closes that window via an observed X icon.
  load(page,2);run(page);assert page.locator('#st-screen').get_attribute('data-surface')=='desk';assert page.locator('[data-stobj="A"]').is_visible()
  # Case 3, stop during the goal wave to capture real neural-state contributions.
  load(page,3);speed(page,150);page.locator('#st-start').click()
  page.wait_for_function('document.querySelector("#st-message").textContent.includes("Волна")',timeout=25000)
  page.locator('#st-play').click();paused(page);assert page.locator('#st-goal').get_attribute('data-held')=='true'
  wave=snap(page);page.screenshot(path=str(OUT/'states-goal-wave.png'));page.wait_for_timeout(600);assert snap(page)==wave
  old_ops=len(wave['engine']['operations']);page.locator('#st-step').click();assert len(snap(page)['engine']['operations'])==old_ops+1
  page.wait_for_timeout(300);assert len(snap(page)['engine']['operations'])==old_ops+1
  speed(page);page.locator('#st-play').click();paused(page);assert page.locator('#st-screen').get_attribute('data-surface')=='window'
  assert page.locator('#st-goal').get_attribute('data-held')=='false';assert 'завершена' in page.locator('#st-message').inner_text()
  original=snap(page);assert len([o for o in original['engine']['operations'] if o['kind']=='teach'])==2
  page.locator('#st-fit').click();page.screenshot(path=str(OUT/'states-test3-complete.png'))
  # Case 4 exposes 5432 earlier, but only trains expense command 1700, not 2345.
  load(page,4);ops=snap(page)['engine']['operations'];assert len([o for o in ops if o['kind']=='expose'])==1
  teach=[o for o in ops if o['kind']=='teach'];assert len(teach)==1 and teach[0]['record']['query']=='добавь траты 1700'
  assert page.locator('#st-query').input_value()=='добавь траты 2345';run(page);assert page.locator('#st-output').inner_text()=='2345'
  assert page.locator('#st-input-count').inner_text()=='17 / 17';page.screenshot(path=str(OUT/'states-test4-2345.png'))
  # Running suite is read-only for current memory and verifies all 4, not animation-only demo.
  frozen=snap(page);page.locator('#st-suite').click();assert page.locator('[data-result="PASS"]').count()==4;assert snap(page)==frozen
  # Manual close ack: the physical desk appears, original command stays held until delivery.
  load(page,2);page.locator('#st-ack-mode').select_option('manual');run(page)
  for _ in range(4):
   if page.locator('#st-screen').get_attribute('data-surface')=='desk':break
   page.locator('#st-deliver').click();page.locator('#st-play').click();paused(page)
  assert page.locator('#st-screen').get_attribute('data-surface')=='desk';assert page.locator('#st-goal').get_attribute('data-held')=='true'
  assert not page.locator('#st-deliver').is_disabled();frozen=snap(page);page.wait_for_timeout(500);assert snap(page)==frozen
  page.screenshot(path=str(OUT/'states-waiting-ack.png'));page.locator('#st-deliver').click();page.locator('#st-play').click();paused(page);assert page.locator('#st-goal').get_attribute('data-held')=='false'
  # Own demonstrations through actual UI, with Enter acting on selected A.
  page.locator('#st-clear').click();page.locator('#st-desk').click();page.locator('#st-teaching').evaluate('e=>e.open=true')
  page.locator('#st-query').fill('моя первая');page.locator('#st-record').click();page.locator('[data-stobj="A"]').click()
  assert page.locator('#st-screen').get_attribute('data-surface')=='desk';page.locator('#st-enter').click()
  assert page.locator('#st-screen').get_attribute('data-surface')=='window';page.locator('#st-stop').click();page.locator('#st-learn').click()
  page.locator('#st-window').click();page.locator('#st-query').fill('моя вторая');page.locator('#st-record').click();page.locator('[data-stobj="X"]').click()
  page.keyboard.press('Escape');page.locator('#st-learn').click();page.locator('#st-query').fill('моя первая');run(page)
  assert page.locator('#st-screen').get_attribute('data-surface')=='window';assert 'завершена' in page.locator('#st-message').inner_text()
  # All four modes still exist; former queue is frozen.
  frozen=snap(page);page.locator('#mode-signal').click();assert page.locator('#sg-recall').is_visible()
  page.locator('#mode-disinhibition').click();assert page.locator('#rg-demo').is_visible()
  page.locator('#mode-sequential').click();assert page.locator('#text-input').input_value()=='абв';assert page.locator('#count-edges').inner_text()==old_count
  page.locator('#mode-states').click();assert snap(page)==frozen
  # Save/restore actual origin storage and export.
  if not inline:
   page.wait_for_timeout(500);page.reload();page.locator('#mode-states').click();page.wait_for_function('!document.querySelector("#st-case-1").disabled')
   assert snap(page)['engine']==frozen['engine'];assert page.locator('#st-play-state').inner_text()=='На паузе'
  saved=snap(page);page.locator('#st-timeline').evaluate('e=>{e.value=1;e.dispatchEvent(new Event("input",{bubbles:true}))}')
  assert page.locator('#st-history-banner').is_visible();assert snap(page)==saved;page.locator('#st-live').click()
  if inline:(OUT/'states-export.json').write_text(json.dumps(saved,ensure_ascii=False))
  else:
   with page.expect_download() as d:page.locator('#st-export').click()
   d.value.save_as(OUT/'states-export.json')
  page.locator('#st-clear').click();page.locator('#st-file').set_input_files(str(OUT/'states-export.json'));page.wait_for_timeout(400);assert snap(page)['engine']==saved['engine']
  (OUT/'states-invalid.json').write_text('{"schema":"bad"}');page.locator('#st-file').set_input_files(str(OUT/'states-invalid.json'));page.wait_for_timeout(200);assert snap(page)['engine']==saved['engine']
  # No layout overflow on narrow screens; fourth mode tabs wrap.
  page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(500);assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),'Mobile horizontal overflow'
  page.screenshot(path=str(OUT/'states-mobile.png'),full_page=True)
  assert not errors,errors;external=[u for u in urls if u.startswith(('http:','https:')) and not u.startswith(url)];assert not external,external
  report={'result':'PASS','page_errors':errors,'external_requests':0,'indexeddb_reload_verified':not inline,'scenarios':['test1','test2','test3 learned detour','test4 previous digit exposure','real goal wave','pause','single tick','manual receipt','own training with Enter','all modes','immutable suite','history','JSON','reload','mobile']}
  (OUT/'states-browser-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))
 except Exception as err:
  print('ERROR',repr(err),flush=True);print('PAGE_ERRORS',errors,flush=True)
  page.screenshot(path=str(OUT/'states-failure.png'),full_page=True);raise
 finally:browser.close();server.shutdown()
