import {mkdirSync,writeFileSync} from 'node:fs';
import {runLanguageExperiment} from '../states/language-cases.mjs';
const out=new URL('../.test-output/',import.meta.url);mkdirSync(out,{recursive:true});
const {engine,...report}=runLanguageExperiment();
writeFileSync(new URL('language-report.json',out),JSON.stringify(report,null,2));
writeFileSync(new URL('language-trace.json',out),JSON.stringify(engine.events));
console.log(JSON.stringify(report));if(!report.pass)process.exitCode=1;
