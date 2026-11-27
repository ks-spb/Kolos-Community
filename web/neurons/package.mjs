/** Offline diagnostic application, bundled from the SAME States modules. */
import {stripModuleSyntax} from '../bundle-source.mjs';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
const ndir=dirname(fileURLToPath(import.meta.url));
const files=['../states/environment','../states/targeting','../states/backward','../states/dynamics','../states/route-selection','../states/experience','../states/imagery','../states/goal-network','../states/language','../states/core','../states/capability-cases','../states/imagery-cases','../states/language-cases','snapshot','view','app'];
const js=files.map(p=>stripModuleSyntax(readFileSync(resolve(ndir,p+'.mjs'),'utf8'))).join('\n');
let html=readFileSync(resolve(ndir,'index.html'),'utf8');
html=html.replace('<link rel="stylesheet" href="style.css">',()=>'<style>'+readFileSync(resolve(ndir,'style.css'),'utf8')+'</style>');
html=html.replace('<script type="module" src="app.mjs"></script>',()=>`<script>(()=>{'use strict';\n${js}\n})();</script>`);
mkdirSync(resolve(ndir,'../dist'),{recursive:true});writeFileSync(resolve(ndir,'../dist/neurons.html'),html);
console.log('Built offline neuron viewer from the existing States/Imagery/Language engines.');
