/* Explicit next-speaker alternation across round boundaries. Fixture only. */
const fs=require('fs'),path=require('path'),os=require('os'),{spawn}=require('child_process'),assert=require('assert/strict');
const {chromium}=require(path.join(process.env.RC_NODE_MODULES||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'),'playwright'));
const root=path.resolve(__dirname,'..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'council-next-speaker-')),checks=[];
const check=(v,n)=>{assert.ok(v,n);checks.push(n)};
(async()=>{const child=spawn('python3',[path.join(__dirname,'ui_fixture.py'),data],{cwd:root});child.stderr.pipe(process.stderr);let browser;
try{
 const url=await new Promise((r,j)=>{child.stdout.once('data',b=>r(JSON.parse(b.toString()).url));child.once('exit',c=>j(Error('Fixture '+c)))});
 browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage({viewport:{width:1500,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(url);await page.waitForFunction(()=>!!window.RC_DEBUG);await page.locator('#focusToggle').click();
 await page.locator('#newSession').click();await page.locator('#addAgentRail').click();await page.locator('#engineSelect').selectOption('live');await page.locator('#registrySave').click();
 await page.locator('#intervention').fill('A reproducible question');await page.locator('#sendIntervention').click();await page.waitForFunction(()=>RC_DEBUG.getState().session.independentCount===2&&RC_DEBUG.getState().session.live.controller.status==='idle');
 const roster=await page.evaluate(()=>RC_DEBUG.getState().session.live.controller.roster.filter(a=>a.enabled&&a.role==='debater'));
 for(let i=0;i<4;i++){
  const before=await page.evaluate(()=>RC_DEBUG.getState().session.live.controller.calls),expected=roster[i%roster.length];
  check((await page.locator('#nextSpeaker').getAttribute('title')).includes(expected.name),'next-speaker tooltip identifies '+expected.name+' before call '+(i+1));
  await page.locator('#nextSpeaker').click();await page.waitForFunction(n=>{const v=RC_DEBUG.getState().session.live;return v.controller.calls===n+1&&v.controller.status!=='running'&&!v.starting},before);
  const r=await page.evaluate(()=>RC_DEBUG.getState().session.live.controller),last=r.turns.filter(t=>t.kind==='debate').at(-1);
  check(last.id===expected.id,'click '+(i+1)+' calls the expected member across round boundaries');
  check(r.calls===before+1,'click '+(i+1)+' calls exactly one member');
  if(i===1){await page.evaluate(()=>CouncilBridge.flush());await page.reload();await page.waitForFunction(()=>!!window.RC_DEBUG&&RC_DEBUG.getState().session.live.controller?.nextSpeaker);check((await page.locator('#nextSpeaker').getAttribute('title')).includes(roster[0].name),'next speaker survives reload after a complete round')}
 }
 const r=await page.evaluate(()=>RC_DEBUG.getState().session.live.controller);
 check(r.turns.filter(t=>t.kind==='debate').map(t=>t.id).join(',')===[...roster,...roster].map(a=>a.id).join(','),'no member speaks twice at a round boundary');
 for(const [lang,label] of [['zh','只让下一位成员讨论或评审'],['ja','次のメンバーが議論・レビュー'],['en','Ask the next member to discuss or review only']]){await page.locator('#langSelect').selectOption(lang);check((await page.locator('#nextSpeaker').getAttribute('title')).startsWith(label),'speaker preview localized in '+lang)}
 check(errors.length===0,'no JavaScript errors');console.log(JSON.stringify({checks,errors},null,2));
}finally{if(browser)await browser.close();child.kill('SIGINT');await new Promise(r=>child.once('exit',r));fs.rmSync(data,{recursive:true,force:true})}})().catch(e=>{console.error(e);process.exitCode=1});
