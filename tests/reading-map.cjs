/* Reading maps use semantic DOM anchors and do not invoke any model. */
const fs=require('fs'),path=require('path'),os=require('os'),{spawn}=require('child_process'),assert=require('assert/strict');
let pw;try{pw=require('playwright')}catch{pw=require(path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))}
const root=path.resolve(__dirname,'..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'council-map-')),checks=[];
const check=(v,n)=>{assert.ok(v,n);checks.push(n)};
(async()=>{const child=spawn('python3',[path.join(__dirname,'ui_fixture.py'),data],{cwd:root});child.stderr.pipe(process.stderr);let browser;
try{
 const url=await new Promise((resolve,reject)=>{child.stdout.once('data',d=>resolve(JSON.parse(d.toString()).url));child.once('exit',c=>reject(Error('fixture '+c)))});
 browser=await pw.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage({viewport:{width:1600,height:1000},reducedMotion:'reduce'}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url);await page.waitForFunction(()=>!!window.RC_DEBUG);
 await page.evaluate(()=>{const s=RC_DEBUG.getState().session,answer=n=>'# '+n+'\n\n'+Array.from({length:3},(_,i)=>'## Evidence '+(i+1)+'\n\n'+('A paragraph explaining the evidence and its uncertainty. ').repeat(14)).join('\n\n');s.engine='live';s.view='debate';s.stage='debate';s.independentCount=2;s.debateRound=7;s.turnIndex=0;s.paused=true;s.live={roster:structuredClone(s.agentRoster),independent:{claude:{text:answer('Claude independent view')},codex:{text:answer('Codex independent view')}},pending:null,error:null};s.shownTurns=Array.from({length:12},(_,i)=>({type:'agent',id:i%2?'codex':'claude',round:Math.floor(i/2)+1,text:answer('Review '+(i+1))}));s.subChats=[{id:'long-side',source:'Claude',quote:'Selected evidence',provider:'gemini',model:'default',messages:[{role:'user',text:'Explain this.'},{role:'assistant',provider:'gemini',text:Array.from({length:30},(_,i)=>'## Side section '+(i+1)+'\n\n'+('A focused explanation of the selected evidence. ').repeat(8)).join('\n\n')}]},{id:'short-side',source:'Claude',quote:'A short excerpt.',provider:'gemini',model:'default',messages:[]}]});
 await page.locator('#langSelect').selectOption('zh');await page.locator('#langSelect').selectOption('en');await page.locator('#scroll').evaluate(el=>el.scrollTop=0);
 await page.locator('#chatPositionMap').waitFor({state:'visible'});await page.waitForFunction(()=>document.querySelector('#chatPositionMap button')?.getAttribute('aria-current')==='location');
 const main=page.locator('#chatPositionMap'),marks=main.locator('button');
 check(await marks.count()>40,'main map includes published messages and section headings');
 check(await main.locator('[aria-current=location]').count()===1,'exactly one current reading anchor is announced');
 check(await marks.first().getAttribute('tabindex')==='0','map uses one keyboard tab stop');
 const label=await marks.nth(24).getAttribute('aria-label');await marks.nth(24).hover();check(await main.locator('.reading-map-preview').textContent()===label,'hover preview identifies agent, round and content');
 await marks.nth(24).click();await page.waitForFunction(()=>document.getElementById('scroll').scrollTop>1000&&document.querySelector('#chatPositionMap button:first-child')?.getAttribute('aria-current')!=='location');
 check(await marks.first().getAttribute('aria-current')===null,'current tick follows click-to-jump navigation');
 const anchorOffset=await page.evaluate(()=>{const a=[...document.querySelector('#stageArea').querySelectorAll('[data-flow-item],.opinion,.turn,.synthesis,.prose h1,.prose h2,.prose h3')].filter(el=>el.getClientRects().length&&el.offsetHeight)[24];return a.getBoundingClientRect().top-document.getElementById('scroll').getBoundingClientRect().top});check(Math.abs(anchorOffset-12)<3,'click jumps the correct heading to the reading viewport');
 await marks.first().focus();await page.keyboard.press('End');await page.waitForFunction(()=>{const el=document.getElementById('scroll');return el.scrollHeight-el.scrollTop-el.clientHeight<5&&document.querySelector('#chatPositionMap button:last-child')?.getAttribute('aria-current')==='location'});
 check(await marks.last().getAttribute('aria-current')==='location','End key jumps to the final message and highlights its tick');
 await page.keyboard.press('Home');await page.waitForFunction(()=>document.getElementById('scroll').scrollTop<500);check(await main.locator('[aria-current=location]').count()===1,'Home key returns to the first message');
 const mainBeforeSide=await page.locator('#scroll').evaluate(el=>el.scrollTop);
 await page.locator('#sideChatHistory').click();check(!(await page.locator('#sidePositionMap').isVisible()),'short side chat hides unnecessary position map');
 await page.locator('#sideList').selectOption('long-side');await page.locator('#sidePositionMap').waitFor({state:'visible'});const side=page.locator('#sidePositionMap');
 check(await side.locator('button').count()===33,'side map includes source, messages and all section headings');
 await page.waitForFunction(()=>document.querySelector('#sidePositionMap button:last-child')?.getAttribute('aria-current')==='location');
 await side.locator('button').first().click();await page.waitForFunction(()=>document.getElementById('sideHistory').scrollTop===0);
 check(await page.locator('#scroll').evaluate(el=>el.scrollTop)===mainBeforeSide,'side navigation changes only its own transcript');
 await page.locator('#sideResize-height').press('ArrowDown');await page.waitForFunction(()=>{const n=document.getElementById('sidePositionMap').getBoundingClientRect(),h=document.getElementById('sideHistory').getBoundingClientRect();return n.top>=h.top&&n.bottom<=h.bottom});
 check(await side.evaluate(el=>{const n=el.getBoundingClientRect(),h=document.getElementById('sideHistory').getBoundingClientRect();return n.right<=h.right&&n.left>=h.left}),'side map stays within resized transcript bounds');
 const count=await side.locator('button').count();await page.evaluate(()=>RC_DEBUG.getState().session.subChats[0].messages.push({role:'assistant',provider:'gemini',text:'## New response\n\nNew evidence from a completed response.'}));await page.locator('#langSelect').selectOption('zh');await page.waitForFunction(n=>document.querySelectorAll('#sidePositionMap button').length>n,count);
 check(await side.locator('button').count()===count+2,'new published response and heading update side ticks');
 check(await page.locator('#sideHistory').evaluate(el=>el.scrollTop)===0,'map update preserves an earlier reading position');
 for(const [lang,title] of [['zh','讨论位置导航'],['ja','議論の現在位置'],['en','Discussion position navigation']]){await page.locator('#langSelect').selectOption(lang);await page.waitForFunction(t=>document.getElementById('chatPositionMap').getAttribute('aria-label')===t,title);check(await main.getAttribute('aria-label')===title,'position navigation localized in '+lang)}
 await page.locator('#sideClose').click();await page.locator('#sidePositionMap').waitFor({state:'hidden'});check(!await side.isVisible(),'closing side chat hides its map');
 for(const theme of ['dark','light']){await page.locator('#themeSelect').selectOption(theme);await main.locator('[aria-current=location]').waitFor();check(await main.locator('button.current').evaluate(el=>getComputedStyle(el,'::after').opacity)==='1','current tick remains visible in '+theme);fs.mkdirSync(path.join(root,'test-results'),{recursive:true});await page.screenshot({path:path.join(root,'test-results','reading-map-'+theme+'.png')})}
 await page.locator('#workTab').click();await main.waitFor({state:'hidden'});check(!await main.isVisible(),'discussion map hides in Work view');await page.locator('#debateTab').click();await main.waitFor({state:'visible'});
 await page.setViewportSize({width:540,height:800});await page.waitForFunction(()=>{const a=document.getElementById('chatPositionMap').getBoundingClientRect(),s=document.getElementById('scroll').getBoundingClientRect();return a.left>=s.left&&a.right<=s.right&&a.top>=s.top&&a.bottom<=s.bottom});check(await main.isVisible(),'map remains usable inside a narrow reading viewport');
 check(!fs.existsSync(path.join(data,'jobs'))||fs.readdirSync(path.join(data,'jobs')).length===0,'navigation never invokes research models');
 check(errors.length===0,'no JavaScript errors');console.log(JSON.stringify({checks,errors},null,2));
}finally{if(browser)await browser.close();child.kill('SIGINT');await new Promise(r=>child.once('exit',r));fs.rmSync(data,{recursive:true,force:true})}})().catch(e=>{console.error(e);process.exitCode=1});
