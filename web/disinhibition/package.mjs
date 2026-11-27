/** Third engine adapter; existing sequential and signal sources remain unchanged. */
import {stripModuleSyntax} from '../bundle-source.mjs';
import {readFileSync,writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname,resolve} from 'node:path';
const dir=dirname(fileURLToPath(import.meta.url)),dest=resolve(dir,'../dist/index.html');
let html=readFileSync(dest,'utf8');
if(!html.includes('function switchKolosMode(next)')||html.includes('id="rg-root"'))throw Error('Expected a freshly packaged two-engine application');
html=html.replace('<small>Раздельная память · исходные правила сохранены</small>','<button id="mode-disinhibition" aria-pressed="false">Снятие торможения</button><small>Раздельная память · исходные правила сохранены</small>');
html=html.replace("if (document.body.dataset.kolosMode === 'signal') return;","if (document.body.dataset.kolosMode !== 'sequential') return;");
html=html.replace("if(next==='signal' && !document.dispatchEvent", "if(next!=='sequential' && !document.dispatchEvent");
html=html.replace("document.getElementById('sg-root').hidden=next!=='signal';", "document.getElementById('sg-root').hidden=next!=='signal';\n  document.getElementById('rg-root').hidden=next!=='disinhibition';\n  document.getElementById('mode-disinhibition').setAttribute('aria-pressed',String(next==='disinhibition'));");
html=html.replace("document.getElementById('mode-signal').onclick=()=>switchKolosMode('signal');", "document.getElementById('mode-signal').onclick=()=>switchKolosMode('signal');\ndocument.getElementById('mode-disinhibition').onclick=()=>switchKolosMode('disinhibition');");
const js=['environment','learning','core','demo','ui'].map(name=>stripModuleSyntax(readFileSync(resolve(dir,name+'.mjs'),'utf8'))).join('\n');
const css=readFileSync(resolve(dir,'style.css'),'utf8');
html=html.replace('</body>',()=>`<style>${css}</style><section id="rg-root" hidden></section><script>(()=>{'use strict';\n${js}\nmountResidualLab();})();</script></body>`);
writeFileSync(dest,html);console.log('Packed disinhibition engine; three independent modes, no external assets.');
