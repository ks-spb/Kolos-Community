/** Pack the second engine into the existing standalone application. No legacy core edits. */
import {stripModuleSyntax} from '../bundle-source.mjs';
import {readFileSync,writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname,resolve} from 'node:path';
const here=dirname(fileURLToPath(import.meta.url));
const destination=resolve(here,'../dist/index.html');
const input=process.argv[2]?resolve(process.argv[2]):destination;
let legacy=readFileSync(input,'utf8');
if(legacy.includes('id="sg-root"'))throw new Error('Signal already packaged. Run the legacy build first.');
if(!legacy.includes('void initialize();'))throw new Error('Legacy entrypoint changed: verify pause/snapshot adapter.');
legacy=legacy.replace('void initialize();',`document.addEventListener('kolos:legacy:pause', (e) => {
  if (virtualLab.isTraining()) { e.preventDefault(); return; }
  halt(); void saveNow();
});
document.addEventListener('kolos:legacy:snapshot', (e) => { if (e.detail && typeof e.detail.reply === 'function') e.detail.reply(getExperiment()); });
void initialize();`);
// Legacy shortcuts must not resume a hidden engine from the signal canvas.
const legacyShortcut = "document.addEventListener('keydown', e => {";
if (!legacy.includes(legacyShortcut)) throw new Error('Legacy keyboard entrypoint changed: verify mode isolation.');
legacy = legacy.replace(legacyShortcut, legacyShortcut + "\n  if (document.body.dataset.kolosMode === 'signal') return;");
const core=stripModuleSyntax(readFileSync(resolve(here,'core.mjs'),'utf8'));
const ui=stripModuleSyntax(readFileSync(resolve(here,'ui.mjs'),'utf8'));
const css=readFileSync(resolve(here,'style.css'),'utf8');
// The simulator must never extend across feedback/playback controls in short
// windows or when the journal is open. Scroll its body, not the whole overlay.
const legacyLayoutFix=`
body[data-kolos-mode="sequential"] .simulator-panel{display:flex;flex-direction:column;max-height:calc(100% - 20px)}
body[data-kolos-mode="sequential"] .simulator-heading{flex-shrink:0}
body[data-kolos-mode="sequential"] .simulator-body{min-height:0;overflow-y:auto;overscroll-behavior:contain}
body[data-kolos-mode="sequential"] .feedback-bar{position:relative;z-index:10;background:var(--bg)}
body[data-kolos-mode="sequential"] .playback{position:relative;z-index:11}
@media(max-width:720px){body[data-kolos-mode="sequential"] .simulator-panel{max-height:58vh}}
`;
const bar=`<nav id="kolos-modes" aria-label="Режим выполнения"><span class="mode-caption">ДВИЖОК</span><button id="mode-sequential" aria-pressed="true">Последовательный</button><button id="mode-signal" aria-pressed="false">Распространение сигнала</button><small>Раздельная память · исходные правила сохранены</small></nav>`;
legacy=legacy.replace('<body>','<body data-kolos-mode="sequential">'+bar);
const switcher=`
function switchKolosMode(next) {
  if(next==='signal' && !document.dispatchEvent(new CustomEvent('kolos:legacy:pause',{cancelable:true}))){alert('Сначала сохраните или сбросьте запись обучения в последовательном режиме.');return;}
  if(!document.dispatchEvent(new CustomEvent('kolos:mode',{detail:{mode:next},cancelable:true})))return;
  document.body.dataset.kolosMode=next;
  document.getElementById('sg-root').hidden=next!=='signal';
  document.getElementById('mode-sequential').setAttribute('aria-pressed',String(next==='sequential'));
  document.getElementById('mode-signal').setAttribute('aria-pressed',String(next==='signal'));
}
document.getElementById('mode-sequential').onclick=()=>switchKolosMode('sequential');
document.getElementById('mode-signal').onclick=()=>switchKolosMode('signal');`;
const extension=`<style>${css}\n${legacyLayoutFix}</style><section id="sg-root" hidden></section><script>(()=>{'use strict';\n${core}\n${ui}\nmountSignalLab();\n${switcher}\n})();</script>`;
writeFileSync(destination,legacy.replace('</body>',()=>extension+'</body>'));
console.log('Packed sequential + signal engines into one offline HTML.');
