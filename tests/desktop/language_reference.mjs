import {prepareLanguage} from '../../web/states/language-cases.mjs';
const p=prepareLanguage(),e=p.engine,m=e.model;
const result={learning:e.operations.filter(o=>['teach','expose'].includes(o.kind)),worldLessons:m.lessons,exposures:m.exposures,languageLessons:m.languageMemory.lessons,observed:m.observed,phrase:p.phrase,trace:[]};
e.perform(p.operation);
for(let i=0;i<1200&&e.model.phase==='language'&&e.model.status==='running';i++){
 const event=e.perform({kind:'tick'});result.trace.push({kind:event.kind,language:structuredClone(e.model.language),imagery:structuredClone(e.model.imagery)});
}
console.log(JSON.stringify(result));
