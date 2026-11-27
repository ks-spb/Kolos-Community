import {execFileSync,spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {createServer} from 'node:http';
import {fileURLToPath} from 'node:url';
import {dirname,resolve} from 'node:path';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const url='http://127.0.0.1:4173';
const openOnStart=process.argv.includes('--open');

function openBrowser(){
  const opener=spawn('explorer.exe',[url],{stdio:'ignore',windowsHide:true,detached:true});
  opener.on('error',error=>console.error(`Не удалось открыть браузер: ${error.message}`));
  opener.unref();
}

execFileSync(process.execPath,['build.mjs'],{cwd:root,stdio:'inherit'});
execFileSync(process.execPath,['signal/package.mjs'],{cwd:root,stdio:'inherit'});
execFileSync(process.execPath,['disinhibition/package.mjs'],{cwd:root,stdio:'inherit'});
execFileSync(process.execPath,['states/package.mjs'],{cwd:root,stdio:'inherit'});
const server=createServer((req,res)=>{if(req.url!=='/'&&req.url!=='/index.html'){res.writeHead(404);res.end();return;}
 res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','X-Kolos-Lab':'1'});res.end(readFileSync(resolve(root,'dist/index.html')));
});
server.on('error',async error=>{
  if(error.code==='EADDRINUSE'&&openOnStart){
    try{
      const response=await fetch(url,{signal:AbortSignal.timeout(2000)});
      if(response.headers.get('X-Kolos-Lab')==='1'){
        openBrowser();
        process.exit(0);
      }
    }catch{}
  }
  console.error(`Не удалось запустить лабораторию: ${error.message}`);
  process.exit(1);
});
server.listen(4173,'127.0.0.1',()=>{
  console.log(`Kolos: ${url}`);
  if(openOnStart)openBrowser();
});
