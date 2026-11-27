"""UI acceptance. HTTP by default; in-memory mode for offline build rendering.
Neither mode operates the user's desktop. Tests execute the actual JS engine.
"""
import json
import os
import shutil
import sys
import tempfile
import copy
import time
import threading
from functools import partial
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.test-output'/'neurons';OUT.mkdir(parents=True,exist_ok=True)
IN_MEMORY=os.environ.get('KOLOS_NEURON_IN_MEMORY')=='1'
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=str(ROOT)))
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()

def mount(page,filename):
    if IN_MEMORY:page.set_content((ROOT/'dist'/filename).read_text(encoding='utf-8'))
    else:page.goto(f'http://127.0.0.1:{server.server_port}/dist/{filename}')

def wait_frames(page, count):
    # Poll through the debugger API; Playwright wait_for_function evaluates a
    # string in-page and is deliberately blocked by the live server CSP.
    end=time.monotonic()+10
    while time.monotonic()<end:
        if page.evaluate('() => globalThis.kolosNeuronScope?.frames.length ?? 0')>=count:return
        page.wait_for_timeout(100)
    raise AssertionError(f'Live viewer did not receive {count} frames')

try:
 with sync_playwright() as p:
    options={'headless':True}
    if os.environ.get('KOLOS_NEURON_BROWSER'):options['executable_path']=os.environ['KOLOS_NEURON_BROWSER']
    browser=p.chromium.launch(**options)
    page=browser.new_page(viewport={'width':1640,'height':1120});page.set_default_timeout(10000);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    mount(page,'neurons.html');page.wait_for_selector('[data-node]')
    assert page.evaluate('kolosNeuronScope.engine.model.world.effects.length')==0
    page.locator('[data-scope=speed]').fill('100');page.locator('[data-scope=speed]').dispatch_event('input')
    page.locator('[data-scope=play]').click()
    page.wait_for_function('kolosNeuronScope.engine.model.tick>=8 && !kolosNeuronScope.playing')
    assert page.evaluate('kolosNeuronScope.engine.model.world.effects.length')==0
    assert page.evaluate('kolosNeuronScope.engine.model.imagery.ready')>.99
    pause=page.evaluate('kolosNeuronScope.engine.model.tick');particles=page.locator('[data-nv=particles]').inner_html();page.wait_for_timeout(300)
    assert page.evaluate('kolosNeuronScope.engine.model.tick')==pause
    assert page.locator('[data-nv=particles]').inner_html()==particles
    print('imagery phase passed',flush=True);page.locator('[data-nv=layer]').select_option('image')
    assert page.evaluate('(()=>{const v=kolosNeuronScope.view,ps=v.nodes.map(n=>v.positions[n.id]);return ps.every((a,i)=>ps.every((b,j)=>i===j||Math.hypot(a.x-b.x,a.y-b.y)>=100))})()')
    page.get_by_role('button',name='1: 2',exact=True).click(force=True)
    assert page.locator('[data-nv=details]').inner_text()!=''
    page.screenshot(path=str(OUT/'image-I-without-S.png'),full_page=True)
    page.locator('[data-scope=rest]').click();page.wait_for_function('!kolosNeuronScope.playing && kolosNeuronScope.engine.model.imagery.ready<0.01')
    assert page.evaluate('kolosNeuronScope.engine.model.world.effects.length')==0
    page.locator('[data-nv=layer]').select_option('overview')
    print('fade passed',flush=True);page.locator('[data-scope=act]').click()
    page.wait_for_function('kolosNeuronScope.engine.model.status==="complete"',timeout=30000)
    assert page.evaluate('kolosNeuronScope.engine.model.world.output')=='2345'
    assert page.evaluate('kolosNeuronScope.engine.model.imagery.confirmations[0].source')=='external'
    print('achieved',flush=True);final=page.evaluate('JSON.stringify(kolosNeuronScope.engine.model)')
    page.locator('[data-scope=timeline]').fill('2');page.locator('[data-scope=timeline]').dispatch_event('input');page.wait_for_timeout(200)
    assert page.locator('[data-scope=act]').is_disabled()
    assert page.evaluate('JSON.stringify(kolosNeuronScope.engine.model)')==final
    page.locator('[data-scope=step]').click();assert page.evaluate('JSON.stringify(kolosNeuronScope.engine.model)')==final
    page.locator('[data-scope=latest]').click();page.screenshot(path=str(OUT/'confirmed-2345.png'),full_page=True)
    # Stored recording is a read-only viewer, not an executable scenario import.
    page.evaluate('window.nvRecord={schema:"kolos-neuron-recording/1",frames:kolosNeuronScope.frames};kolosNeuronScope.openRecord(nvRecord)')
    page.locator('[data-scope=step]').click();assert page.evaluate('JSON.stringify(kolosNeuronScope.engine.model)')==final
    page.evaluate('nvRecord.frames[0].nodes[0].label="<img src=x onerror=window.nvInjected=1>";kolosNeuronScope.openRecord(nvRecord)')
    assert page.evaluate('window.nvInjected||0')==0
    print('history passed',flush=True);page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(OUT/'mobile.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth')<=395
    # Integration uses the very same engine that backs the existing lab.
    page.close();page=browser.new_page(viewport={'width':1640,'height':1120});page.set_default_timeout(10000);page.on('pageerror',lambda e:errors.append(str(e)));mount(page,'index.html')
    print('lab loading',flush=True);page.locator('#mode-states').click();page.wait_for_function('!document.getElementById("st-image-demo").disabled')
    page.locator('#st-image-demo').click();page.wait_for_timeout(100)
    page.locator('#st-neurons').click();page.wait_for_selector('dialog.nv-modal[open]')
    page.locator('dialog.nv-modal [data-scope=step]').click()
    page.locator('dialog.nv-modal [data-scope=close]').click()
    assert page.locator('dialog.nv-modal').count()==0
    # Standalone language fixture still yields a grounded image then uses test 11.
    page.close();page=browser.new_page(viewport={'width':1640,'height':1120});page.set_default_timeout(10000);page.on('pageerror',lambda e:errors.append(str(e)));mount(page,'neurons.html');page.locator('[data-scope=demo]').select_option('12');page.locator('[data-scope=reset]').click()
    page.evaluate('for(let i=0;i<1000 && kolosNeuronScope.engine.model.phase==="language";i++)kolosNeuronScope.step()')
    assert page.evaluate('kolosNeuronScope.engine.model.imagery.source.kind')=='language'
    assert page.evaluate('kolosNeuronScope.engine.model.language.goal.value')=='1354'
    assert page.evaluate('kolosNeuronScope.engine.model.world.effects.length')==0
    page.locator('[data-nv=layer]').select_option('language');page.screenshot(path=str(OUT/'language.png'),full_page=True)
    # The live server carries actual Python engine snapshots, not an OS-control API.
    live_verified=False
    if not IN_MEMORY:
        sys.path.insert(0,str(ROOT.parent))
        from kolos_states.neuron_server import NeuronServer
        from kolos_states.neuron_trace import NeuronTraceWriter
        from kolos_states.capabilities import prepare
        from kolos_states.simulator import observe
        with tempfile.TemporaryDirectory() as directory:
            ipc=Path(directory);live=NeuronServer(ROOT.parent,ipc,'browser-proof');writer=NeuronTraceWriter(ipc,'browser-proof')
            try:
                engine,world,request=prepare(9);engine.imagine(request['goals'],observe(world));writer.capture(engine)
                for _ in range(8):engine.tick();writer.capture(engine)
                frozen=copy.deepcopy(engine.model)
                page.close();page=browser.new_page(viewport={'width':1640,'height':1120});page.set_default_timeout(10000);page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(live.url);wait_frames(page,9)
                assert page.evaluate('kolosNeuronScope.live')
                assert page.evaluate('kolosNeuronScope.frames.at(-1).ready')>.99
                assert page.locator('[data-scope=act]').is_hidden()
                assert page.locator('[data-scope=rest]').is_hidden()
                page.locator('[data-scope=play]').click()
                assert not page.evaluate('kolosNeuronScope.follow')
                cursor=page.evaluate('kolosNeuronScope.cursor')
                assert engine.model==frozen
                # Core can advance independently while viewer pause holds the camera frame.
                for _ in range(3):engine.tick();writer.capture(engine)
                wait_frames(page,12)
                assert page.evaluate('kolosNeuronScope.cursor')==cursor
                assert not world['effects']
                page.locator('[data-scope=latest]').click();page.screenshot(path=str(OUT/'python-live-readonly.png'),full_page=True)
                live_verified=True
            finally:live.close()
    assert not errors,errors
    result={'result':'PASS','mode':'in-memory-offline-bundle' if IN_MEMORY else 'http','actual_engine_11':'2345','same_lab_engine':True,
            'image_without_effect':True,'fade':True,'pause_no_ticks':True,'history_no_effects':True,'recording_readonly':True,
            'unknown_text_escaped':True,'mobile_width':True,'language_to_image':'1354','live_python_http':live_verified,'page_errors':errors}
    (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result))
    browser.close()
finally:server.shutdown();server.server_close()
