"""Actual browser execution of all twelve on one shared memory.

KOLOS_SHARED_IN_MEMORY=1 only renders the offline bundle; it does not claim to
verify browser-origin storage or native HTTP integration. CI uses real HTTP.
"""
import json
import os
from pathlib import Path
import threading
import tempfile
import sys
from functools import partial
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.test-output/shared';OUT.mkdir(parents=True,exist_ok=True)
IN_MEMORY=os.environ.get('KOLOS_SHARED_IN_MEMORY')=='1'
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=str(ROOT)))
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with sync_playwright() as p:
    options={'headless':True}
    if os.environ.get('KOLOS_NEURON_BROWSER'):options['executable_path']=os.environ['KOLOS_NEURON_BROWSER']
    browser=p.chromium.launch(**options)
    page=browser.new_page(viewport={'width':1600,'height':1150});page.set_default_timeout(15000)
    errors=[];external=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:external.append(r.url) if r.url.startswith('http') and not r.url.startswith('http://127.0.0.1:') else None)
    if IN_MEMORY:page.set_content((ROOT/'dist/shared.html').read_text(encoding='utf-8'))
    else:page.goto(f'http://127.0.0.1:{server.server_port}/dist/shared.html')
    page.wait_for_selector('[data-node]')
    print('shared: initial loaded',flush=True)
    signature=page.evaluate('kolosSharedLab.session.signature')
    assert page.evaluate('kolosSharedLab.session.engine.model.lessons.length')==18
    assert page.evaluate('kolosSharedLab.session.engine.model.world.effects.length')==0
    page.screenshot(path=str(OUT/'shared-initial.png'),full_page=True)
    for _ in range(8):page.locator('[data-sh=step]').click()
    assert page.evaluate('kolosSharedLab.session.engine.model.imagery.ready')>.99
    assert page.evaluate('kolosSharedLab.session.engine.model.world.effects.length')==0
    page.locator('[data-nv=layer]').select_option('image')
    page.screenshot(path=str(OUT/'shared-image-I-before-S.png'),full_page=True)
    tick=page.evaluate('kolosSharedLab.session.engine.model.tick');page.wait_for_timeout(200)
    assert page.evaluate('kolosSharedLab.session.engine.model.tick')==tick
    page.locator('[data-nv=layer]').select_option('all')
    assert page.evaluate('kolosSharedLab.view.nodes.length===kolosSharedLab.view.frame.nodes.length')
    assert 'лимит отображения' not in page.locator('[data-nv=count]').inner_text()
    page.locator('[data-nv=layer]').select_option('overview')
    print('shared: I-only and full-memory view verified',flush=True)
    page.locator('[data-sh=check]').click()
    page.wait_for_function('kolosSharedLab.report.length===12 && !kolosSharedLab.busy',timeout=120000)
    assert page.locator('[data-sh=score]').inner_text()=='12 / 12'
    assert page.evaluate('kolosSharedLab.session.signature')==signature
    report=page.evaluate('kolosSharedLab.report')
    assert all(r['pass'] for r in report)
    assert len({r['instance'] for r in report})==1
    assert len({r['memoryBefore'] for r in report}|{r['memoryAfter'] for r in report})==1
    page.screenshot(path=str(OUT/'shared-all-12-pass.png'),full_page=True)
    print('shared: all twelve passed on one engine',flush=True)
    frozen=page.evaluate('JSON.stringify(kolosSharedLab.session.engine.model)')
    page.locator('[data-record="3"]').click();page.locator('[data-sh=step]').click()
    assert page.evaluate('JSON.stringify(kolosSharedLab.session.engine.model)')==frozen
    page.locator('[data-sh=speed]').fill('50');page.locator('[data-sh=speed]').dispatch_event('input')
    page.locator('[data-sh=watch]').click();page.wait_for_timeout(500);page.locator('[data-sh=watch]').click()
    assert page.evaluate('JSON.stringify(kolosSharedLab.session.engine.model)')==frozen
    page.locator('[data-sh=latest]').click()
    # Saved memory contains no runnable world changes/start actions.
    print('shared: history has no execution',flush=True)
    saved=page.evaluate('kolosSharedLab.session.export()')
    assert all(op['kind'] in ('teach','expose','config','weight','language-teach','language-weight') for op in saved['learning'])
    page.locator('[data-sh=transfer]').click();page.wait_for_function('kolosSharedLab.transferResult?.pass && !kolosSharedLab.busy',timeout=30000)
    assert page.evaluate('kolosSharedLab.transferResult.output')=='4512'
    assert page.evaluate('kolosSharedLab.session.signature')==signature
    page.screenshot(path=str(OUT/'shared-transfer.png'),full_page=True)
    print('shared: cross-family transfer passed',flush=True)
    reload_verified=False
    if not IN_MEMORY:
        page.reload();page.wait_for_selector('[data-node]')
        assert page.evaluate('kolosSharedLab.session.signature')==signature
        assert page.evaluate('kolosSharedLab.session.engine.model.world.effects.length')==0
        assert page.locator('[data-sh=score]').inner_text()=='0 / 12'
        reload_verified=True
    page.set_viewport_size({'width':390,'height':844})
    page.screenshot(path=str(OUT/'shared-mobile.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth')<=395
    native_source=False
    if not IN_MEMORY:
        sys.path.insert(0,str(ROOT.parent))
        from kolos_states.neuron_server import NeuronServer
        with tempfile.TemporaryDirectory() as directory:
            live=NeuronServer(ROOT.parent,Path(directory),'shared-browser-proof')
            try:
                native=browser.new_page(viewport={'width':1600,'height':1150})
                native.on('pageerror',lambda e:errors.append(str(e)))
                native.on('request',lambda r:external.append(r.url) if r.url.startswith('http') and not r.url.startswith('http://127.0.0.1:') else None)
                native.goto(f'http://127.0.0.1:{live.server.server_port}/web/shared/index.html')
                native.wait_for_selector('[data-node]')
                assert native.evaluate('kolosSharedLab.session.signature')==signature
                for _ in range(8):native.locator('[data-sh=step]').click()
                assert native.evaluate('kolosSharedLab.session.engine.model.imagery.ready')>.99
                assert native.evaluate('kolosSharedLab.session.engine.model.world.effects.length')==0
                native_source=True
                native.screenshot(path=str(OUT/'shared-from-glaz-server.png'),full_page=True)
                native.close()
            finally:
                live.close()
    assert not errors,errors
    assert not external,external
    summary=dict(result='PASS',mode='in-memory' if IN_MEMORY else 'http',oneEngine=True,twelvePassed=True,
                 wholeMemoryVisible=True,historyHasNoEffects=True,transfer='4512',storageReload=reload_verified,
                 mobile=True,glazStaticServer=native_source,pageErrors=errors,externalRequests=external)
    (OUT/'browser.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'browser-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False));browser.close()
finally:server.shutdown();server.server_close()
