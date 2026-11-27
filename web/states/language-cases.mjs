import {persistentGraph} from './environment.mjs';
/** Experiment 12 fixtures. Not imported by inference. */
import {prepareCapability} from './capability-cases.mjs';
export const LANGUAGE_PAIRS=[
 ['я хочу увидеть 1700 в поле','1700'],['я хочу увидеть 2345 в поле','2345'],
 ['пусть в поле будет 1700','1700'],['пусть в поле будет 2345','2345'],
 ['сделай в поле 1700 пожалуйста','1700'],['сделай в поле 2345 пожалуйста','2345']
];
export function prepareLanguage(phrase='я хочу увидеть 1354 в поле'){
 const e=prepareCapability(9).engine;
 for(const [text,value]of LANGUAGE_PAIRS)e.perform({kind:'language-teach',phrase:text,goal:{kind:'field',focus:'FIELD',value}});
 return {engine:e,phrase,operation:{kind:'language-start',phrase}};
}
export function runLanguageExperiment(){
 const p=prepareLanguage(),e=p.engine,frozen=JSON.stringify(persistentGraph(e.model.memory)),lex=JSON.stringify(e.model.languageMemory),world=JSON.stringify(e.model.world);
 e.perform(p.operation);for(let i=0;i<1200&&e.model.phase==='language'&&e.model.status==='running';i++)e.perform({kind:'tick'});
 const decoded=e.model.language.goal?.value==='1354'&&e.model.language.goal?.focus==='FIELD';
 for(let i=0;i<8&&e.model.status==='running';i++)e.perform({kind:'tick'});
 const dry=world===JSON.stringify(e.model.world)&&e.model.imagery?.ready>=.7&&e.model.imagery.match===0;
 if(e.model.imagery)e.perform({kind:'image-control',command:'act'});
 for(let i=0;i<600&&!['complete','blocked','failed','unknown','ambiguous','timeout','limit'].includes(e.model.status);i++)e.perform({kind:'tick'});
 const observed=e.model.status==='complete'&&e.model.world.output==='1354'&&e.model.imagery?.confirmations.length===1;
 const unchanged=frozen===JSON.stringify(persistentGraph(e.model.memory))&&lex===JSON.stringify(e.model.languageMemory);
 return {number:12,pass:!!(decoded&&dry&&observed&&unchanged),decoded,dry,observed,unchanged,phrase:p.phrase,goal:e.model.language.goal,
 clicks:e.model.world.effects.filter(r=>r.action.kind==='click').map(r=>r.action.object),output:e.model.world.output,engine:e};
}
