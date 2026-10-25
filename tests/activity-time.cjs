const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
let now=2000;class FakeDate extends Date {static now(){return now*1000}}
const ctx={window:{},Date:FakeDate,structuredClone};vm.runInNewContext(fs.readFileSync(require('path').join(__dirname,'../activity.js'),'utf8'),ctx);const api=ctx.window.CouncilActivity,a={id:'a',name:'Codex'};
let checks=0;function check(value,expected){assert.equal(value,expected);checks++}
for(const status of ['failed','complete','cancelled','interrupted']){
 const job={id:'j',created:100,status,updated:700,agents:[a],events:[],results:[],executionProgress:{a:{updated:680,output:'original failure'}}};
 now=2000;check(api.inspect(job,a).elapsed,600);now+=3*86400;check(api.inspect(job,a).elapsed,600);
 const saved=api.snapshot(job);check(api.inspect(saved,a).elapsed,600);check(api.html(saved,'zh',String).includes('结束时间'),true);
 check(api.html(saved,'zh',String).includes('最近更新'),false);
}
const job={id:'running',created:100,status:'running',agents:[a,{id:'b'}],results:[{agentId:'a',completedAt:220}],events:[],failures:[]};
now=250;check(api.inspect(job,a).elapsed,120);check(api.inspect(job,{id:'b'}).elapsed,150);now=300;check(api.inspect(job,a).elapsed,120);check(api.inspect(job,{id:'b'}).elapsed,200);
job.failures=[{agentId:'b',code:'timeout',at:270}];check(api.inspect(job,{id:'b'}).elapsed,170);check(api.inspect(job,{id:'b'}).phase,'failed');
const saved=api.snapshot(job);now=400;check(api.inspect(saved,a).elapsed,120);check(api.inspect(saved,{id:'b'}).elapsed,170);
job.status='failed';job.finishedAt=280;job.updated=900;job.failures=[];job.results=[];check(api.inspect(job,a).elapsed,180);
console.log(JSON.stringify({checks,passed:true}));
