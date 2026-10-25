/* Scroll and pointer geometry regression; metadata/inference services are not called. */
const fs=require('fs'),path=require('path'),os=require('os'),{spawn}=require('child_process'),assert=require('assert/strict');
let pw;try{pw=require('playwright')}catch{pw=require(path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))}
const root=path.resolve(__dirname,'..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'council-side-size-')),checks=[];
const check=(v,n)=>{assert.ok(v,n);checks.push(n)};
(async()=>{const child=spawn('python3',[path.join(__dirname,'ui_fixture.py'),data],{cwd:root});child.stderr.pipe(process.stderr);let browser;
try{
 const url=await new Promise((resolve,reject)=>{child.stdout.once('data',d=>resolve(JSON.parse(d.toString()).url));child.once('exit',c=>reject(Error('fixture '+c)))});
 browser=await pw.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage({viewport:{width:1600,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url);await page.waitForFunction(()=>!!window.RC_DEBUG);
 await page.evaluate(()=>{const s=RC_DEBUG.getState().session;s.subChats=[{id:'size-fixture',provider:'codex',model:'gpt-6.1-sol',web:true,source:'Claude · selected evidence',quote:'A selected research excerpt.',messages:[{role:'user',text:'Explain the evidence.'},{role:'assistant',provider:'codex',model:'gpt-6.1-sol',text:Array.from({length:45},(_,i)=>'## Evidence '+(i+1)+'\n\nA long research explanation with enough detail to verify independent scrolling and reading position.').join('\n\n')}]}]});
 await page.locator('#langSelect').selectOption('zh');await page.locator('#langSelect').selectOption('en');await page.evaluate(()=>CouncilBridge.flush());
 const before=await page.evaluate(()=>JSON.stringify(RC_DEBUG.getState().session.live));
 await page.locator('#sideChatHistory').click();const rect=()=>page.locator('#sideChat').boundingBox();let r=await rect();
 check(r.width===420&&r.height===934,'default side panel fits below the top bar');
 check(await page.locator('#sideHistory').evaluate(el=>el.scrollHeight>el.clientHeight&&getComputedStyle(el).overscrollBehaviorY==='contain'),'long side messages have a contained scroll region');
 let history=await page.locator('#sideHistory').boundingBox(),scroll=await page.locator('#sideHistory').evaluate(el=>el.scrollTop);
 await page.mouse.move(history.x+history.width/2,history.y+history.height/2);await page.mouse.wheel(0,-600);await page.waitForFunction(y=>document.getElementById('sideHistory').scrollTop<y,scroll);
 check(await page.locator('#sideHistory').evaluate(el=>el.scrollTop)<scroll,'trackpad/wheel scrolls the side transcript');
 await page.locator('#sideQuestion').fill('Keep this unsent draft.');
 async function dragHandle(axis,dx,dy){const b=await page.locator('#sideResize-'+axis).boundingBox();await page.mouse.move(b.x+b.width/2,b.y+b.height/2);await page.mouse.down();await page.mouse.move(b.x+b.width/2+dx,b.y+b.height/2+dy,{steps:8});await page.mouse.up()}
 await dragHandle('width',-160,0);let sized=await rect();check(sized.width===580&&sized.height===r.height,'dragging left edge changes width only');
 await dragHandle('height',0,160);sized=await rect();check(sized.height===774&&sized.width===580,'dragging top edge changes height only');
 await dragHandle('both',-80,100);sized=await rect();check(sized.width===660&&sized.height===674,'top-left corner changes width and height together');
 check(await page.locator('#sideQuestion').inputValue()==='Keep this unsent draft.'&&await page.locator('#sideProvider').inputValue()==='codex'&&await page.locator('#sideModel').inputValue()==='gpt-6.1-sol'&&await page.evaluate(()=>RC_DEBUG.getState().session.subChats.at(-1).web===true),'resizing preserves draft, provider, model and default web access');
 await page.locator('#sideResize-width').focus();await page.keyboard.press('ArrowLeft');await page.locator('#sideResize-height').focus();await page.keyboard.press('ArrowDown');sized=await rect();check(sized.width===680&&sized.height===654,'resize handles also work with keyboard arrows');
 await page.locator('#sideClose').click();await page.locator('#sideChatHistory').click();r=await rect();check(r.width===680&&r.height===654,'close and reopen preserves side panel size');
 await page.evaluate(()=>CouncilBridge.flush());await page.reload();await page.waitForFunction(()=>!!window.RC_DEBUG);await page.locator('#sideChatHistory').click();r=await rect();check(r.width===680&&r.height===654,'side panel size survives reload');
 check(await page.locator('#sideQuestion').inputValue()==='Keep this unsent draft.','unsent side draft survives reload');
 await page.locator('#sideHistory').evaluate(el=>{el.scrollTop=180});await page.waitForFunction(()=>document.getElementById('sideHistory').scrollTop===180);
 await page.evaluate(()=>{RC_DEBUG.getState().session.subChats[0].messages.push({role:'assistant',provider:'codex',text:'A new completed answer arrived while reading earlier evidence.'})});await page.locator('#langSelect').selectOption('zh');
 check(Math.abs(await page.locator('#sideHistory').evaluate(el=>el.scrollTop)-180)<2,'new answer and localization preserve earlier reading position');
 await dragHandle('width',-40,0);check(Math.abs(await page.locator('#sideHistory').evaluate(el=>el.scrollTop)-180)<2,'resizing does not jump transcript to the latest answer');
 await page.locator('#sideHistory').evaluate(el=>{el.scrollTop=el.scrollHeight});await page.waitForFunction(()=>{const el=document.getElementById('sideHistory');return el.scrollHeight-el.clientHeight-el.scrollTop<2});
 await page.evaluate(()=>{RC_DEBUG.getState().session.subChats[0].messages.push({role:'assistant',provider:'codex',text:'## Latest answer\n\n'+('A new evidence paragraph.\n\n').repeat(12)})});await page.locator('#langSelect').selectOption('en');
 check(await page.locator('#sideHistory').evaluate(el=>el.scrollHeight-el.clientHeight-el.scrollTop<2),'following the latest reply continues scrolling when a new answer arrives');
 await page.locator('#sideHistory').evaluate(el=>{el.scrollTop=0});const mainScroll=await page.locator('#scroll').evaluate(el=>el.scrollTop);history=await page.locator('#sideHistory').boundingBox();await page.mouse.move(history.x+80,history.y+80);await page.mouse.wheel(0,-1200);await page.waitForTimeout(100);
 check(await page.locator('#scroll').evaluate(el=>el.scrollTop)===mainScroll,'wheel at transcript boundary does not scroll the main debate');
 const preferred=await rect();await page.setViewportSize({width:320,height:400});r=await rect();
 check(r.x>=0&&r.y>=44&&r.x+r.width<=320&&r.y+r.height<=400,'resized panel stays inside a small viewport');
 check(await page.locator('#sideHistory').evaluate(el=>el.clientHeight>30)&&await page.locator('#sideSend').isVisible(),'small panel keeps transcript and send controls accessible');
 await page.setViewportSize({width:1600,height:1000});await page.waitForFunction(p=>{const r=document.getElementById('sideChat').getBoundingClientRect();return r.width===p.width&&r.height===p.height},preferred);r=await rect();check(r.width===preferred.width&&r.height===preferred.height,'restoring window size restores preferred panel dimensions');
 for(const [lang,name] of [['zh','恢复默认大小'],['ja','既定のサイズに戻す'],['en','Restore default size']]){await page.locator('#langSelect').selectOption(lang);check(await page.locator('#sideReset').getAttribute('aria-label')===name,'resize controls localized in '+lang)}
 for(const theme of ['light','dark']){await page.locator('#themeSelect').selectOption(theme);check(await page.locator('#sideResize-width').evaluate(el=>getComputedStyle(el).cursor)==='ew-resize','visible resize handles support '+theme);fs.mkdirSync(path.join(root,'test-results'),{recursive:true});await page.screenshot({path:path.join(root,'test-results','side-size-'+theme+'.png')})}
 await page.locator('#sideReset').click();r=await rect();check(r.width===420&&r.height===934,'reset button restores default dimensions');
 await page.locator('#sideResize-width').focus();await page.keyboard.press('ArrowLeft');await page.keyboard.press('Home');r=await rect();check(r.width===420&&r.height===934,'Home key restores default size from a resize handle');
 check(await page.evaluate(()=>JSON.stringify(RC_DEBUG.getState().session.live))===before,'side scrolling and sizing leave main debate state unchanged');
 check(errors.length===0,'no JavaScript errors');console.log(JSON.stringify({checks,errors},null,2));
}finally{if(browser)await browser.close();child.kill('SIGINT');await new Promise(r=>child.once('exit',r));fs.rmSync(data,{recursive:true,force:true})}})().catch(e=>{console.error(e);process.exitCode=1});
