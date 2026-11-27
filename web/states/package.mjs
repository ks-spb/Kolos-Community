/** Add an isolated state/goal experiment without altering the three previous engines. */
import {stripModuleSyntax} from '../bundle-source.mjs';
import {readFileSync,writeFileSync} from 'node:fs';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
const dir=dirname(fileURLToPath(import.meta.url)),dest=resolve(dir,'../dist/index.html');
let html=readFileSync(dest,'utf8');
if(!html.includes('id="rg-root"')||html.includes('id="st-root"'))throw Error('Rebuild the three-mode application before packaging states');
html=html.replace('<small>Раздельная память · исходные правила сохранены</small>','<button id="mode-states" aria-pressed="false">Состояния и цели</button><small>Раздельная память · исходные правила сохранены</small>');
html=html.replace("document.getElementById('rg-root').hidden=next!=='disinhibition';", "document.getElementById('rg-root').hidden=next!=='disinhibition';\n  document.getElementById('st-root').hidden=next!=='states';\n  document.getElementById('mode-states').setAttribute('aria-pressed',String(next==='states'));");
html=html.replace("document.getElementById('mode-disinhibition').onclick=()=>switchKolosMode('disinhibition');", "document.getElementById('mode-disinhibition').onclick=()=>switchKolosMode('disinhibition');\ndocument.getElementById('mode-states').onclick=()=>switchKolosMode('states');");
const js=['environment','targeting','backward','dynamics','route-selection','experience','imagery','goal-network','language','core','capability-cases','imagery-cases','language-cases','../neurons/snapshot','../neurons/view','../neurons/app','ui'].map(n=>stripModuleSyntax(readFileSync(resolve(dir,n+'.mjs'),'utf8'))).join('\n');
const css=readFileSync(resolve(dir,'style.css'),'utf8')+'\n'+readFileSync(resolve(dir,'../neurons/style.css'),'utf8');
html=html.replace('</body>',()=>`<style>${css}</style><section id="st-root" hidden></section><script>(()=>{'use strict';\n${js}\nmountStateLab();})();</script></body>`);
writeFileSync(dest,html);console.log('Packed four isolated engines: state/goal activation + acknowledged disinhibition.');
