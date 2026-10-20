// Exercise the website's actual polling code without making AI or HTTP requests.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const html=fs.readFileSync('backend/results.html','utf8');
const source=html.slice(html.indexOf('let cancelReportWatch='),html.indexOf("$('investigate').onclick="));
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
function fixture(replies){
 const timers=new Map(),messages={textContent:''},company={value:'hul'},shown=[],busy=[],calls=[];
 let next=0;
 const hub=()=>({listeners:new Map(),addEventListener(n,f){this.listeners.set(n,f);},removeEventListener(n,f){if(this.listeners.get(n)===f)this.listeners.delete(n);}});
 const document=hub(),window=hub();document.visibilityState='visible';
 const context=vm.createContext({Date,Number,String,Error,AbortController,document,window,loadVersion:1,
  setTimeout(fn,ms){const id=++next;timers.set(id,{fn,ms});return id;},clearTimeout(id){timers.delete(id);},
  $(id){return id==='company'?company:id==='message'?messages:{replaceChildren(){}};},
  setFreshBusy(v){busy.push(v);},showResearchReport(s){shown.push(s);},
  async api(path,body,options){calls.push({path,body});const result=replies.shift();if(result==='hang')return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(Error('Timeout'))));if(result instanceof Error)throw result;assert.ok(result,'Unexpected additional request');return result;}
 });
 vm.runInContext(source,context);
 return {context,timers,messages,shown,busy,calls,document,window,
  async start(){vm.runInContext('waitForResearch({report_id:"r1",status_url:"/status"},"hul",1)',context);await flush();},
  async tick(ms){const entry=[...timers].find(([,t])=>t.ms===ms);assert.ok(entry,'Expected timer '+ms);timers.delete(entry[0]);await entry[1].fn();await flush();}
 };
}
const running={id:'r1',company:'hul',status:'running',created_at:new Date().toISOString()};
const complete={...running,status:'partial',pdf_url:'/report.pdf'};
{
 const f=fixture([running,complete]);await f.start();
 assert.match(f.messages.textContent,/Preparing.*min/);
 await f.window.listeners.get('focus')();await flush();
 assert.equal(f.shown.length,1);assert.equal(f.timers.size,0);assert.equal(f.window.listeners.size,0);
 assert.deepEqual(f.busy,[false]);
}
{
 const f=fixture(['hang',complete]);await f.start();
 f.window.listeners.get('focus')();await flush();assert.equal(f.calls.length,1,'No overlapping status requests');
 await f.tick(12000);assert.match(f.messages.textContent,/Connection interrupted/);
 await f.tick(1800);assert.equal(f.shown.length,1);assert.equal(f.calls.length,2);
 assert.ok(f.calls.every(c=>c.body===undefined),'Recovery must never start another investigation');
}
{
 const f=fixture([running,complete]);await f.start();f.context.loadVersion=2;
 await f.tick(1800);assert.equal(f.shown.length,0);assert.equal(f.calls.length,1);assert.equal(f.timers.size,0);
}
{
 const failure=Object.assign(Error('Report not found'),{status:404});
 const f=fixture([failure]);await f.start();assert.equal(f.timers.size,0);assert.match(f.messages.textContent,/not found/);
}
{
 const f=fixture([running,complete]);await f.start();
 f.document.visibilityState='hidden';f.document.listeners.get('visibilitychange')();await flush();assert.equal(f.calls.length,1);
 f.document.visibilityState='visible';f.document.listeners.get('visibilitychange')();await flush();assert.equal(f.shown.length,1);
}
console.log('Passed: timeout recovery, tab resume, no duplicate investigations, stale-run isolation, terminal completion and missing report.');
