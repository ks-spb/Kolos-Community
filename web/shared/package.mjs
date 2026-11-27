/** Standalone shared-memory experiment. Exactly the same inference modules. */
import {stripModuleSyntax} from '../bundle-source.mjs';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
const shDir=dirname(fileURLToPath(import.meta.url));
const shFiles=['../states/environment','../states/targeting','../states/backward','../states/dynamics','../states/route-selection','../states/experience','../states/imagery','../states/goal-network','../states/language','../states/core','../neurons/snapshot','../neurons/view','fixture','suite','app'];
const shJS=shFiles.map(p=>stripModuleSyntax(readFileSync(resolve(shDir,p+'.mjs'),'utf8'))).join('\n');
let shHTML=readFileSync(resolve(shDir,'index.html'),'utf8');
shHTML=shHTML.replace('<link rel="stylesheet" href="../neurons/style.css">',()=>'<style>'+readFileSync(resolve(shDir,'../neurons/style.css'),'utf8')+'</style>');
shHTML=shHTML.replace('<link rel="stylesheet" href="style.css">',()=>'<style>'+readFileSync(resolve(shDir,'style.css'),'utf8')+'</style>');
shHTML=shHTML.replace('<script type="module" src="app.mjs"></script>',()=>`<script>(()=>{'use strict';\n${shJS}\n})();</script>`);
mkdirSync(resolve(shDir,'../dist'),{recursive:true});writeFileSync(resolve(shDir,'../dist/shared.html'),shHTML);
console.log('Built shared.html: one learned memory, all twelve probes, no external runtime.');
