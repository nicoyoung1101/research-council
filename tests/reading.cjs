/* Rendering and readability regression checks. Uses the isolated fixture, never a subscription CLI. */
const fs=require('fs'),path=require('path'),os=require('os'),{spawn}=require('child_process'),assert=require('assert/strict');
let playwright;try{playwright=require('playwright')}catch{playwright=require(path.join(process.env.RC_NODE_MODULES||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'),'playwright'))}
const root=path.resolve(__dirname,'..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'council-reading-')),checks=[];
const check=(value,name)=>{assert.ok(value,name);checks.push(name)};
(async()=>{
 const child=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'ui_fixture.py'),data],{cwd:root});child.stderr.pipe(process.stderr);let browser;
 try{
  const url=await new Promise((resolve,reject)=>{child.stdout.once('data',chunk=>resolve(JSON.parse(chunk.toString()).url));child.once('exit',code=>reject(Error('Fixture exited '+code)))});
  browser=await playwright.chromium.launch({headless:true,executablePath:process.env.RC_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const context=await browser.newContext({viewport:{width:1600,height:1080}}),page=await context.newPage(),errors=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(!r.url().startsWith(url.split('/index.html')[0])&&!r.url().startsWith('data:'))external.push(r.url())});
  await page.goto(url);await page.waitForFunction(()=>!!window.RC_DEBUG);await page.locator('#langSelect').selectOption('zh');
  const unsafe='# 标题\n\n<script>window.mdInjected=1</script>\n\n<img src="https://example.org/tracker" onerror="alert(1)">\n\n[危险](javascript:alert%281%29) ![远程图片](https://example.org/image.png)\n\n[安全](https://example.org/paper)\n\n```html\n<div>example</div>\n```';
  const safe=await page.evaluate(source=>{const t=document.createElement('template');t.innerHTML=CouncilMarkdown.render(source);return {html:t.innerHTML,forbidden:t.content.querySelectorAll('script,img,iframe,svg,style,object').length,links:[...t.content.querySelectorAll('a')].map(a=>({href:a.getAttribute('href'),rel:a.getAttribute('rel')})),code:t.content.querySelector('pre code')?.textContent}},unsafe);
  check(safe.forbidden===0&&!safe.links.some(a=>a.href?.startsWith('javascript:')),'model HTML and unsafe links cannot create executable elements');
  check(safe.links.some(a=>a.href==='https://example.org/paper'&&a.rel.includes('noopener')),'safe citations remain usable');
  check(safe.code==='<div>example</div>\n','code blocks preserve literal text');
  await page.locator('#focusToggle').click();await page.locator('#addAgentRail').click();await page.locator('#engineSelect').selectOption('live');
  for(const card of await page.locator('.registry-card').all())await card.locator('[data-field=rules]').fill('READING_TEST');
  await page.locator('#registrySave').click();await page.locator('#advance').click();
  await page.waitForFunction(()=>RC_DEBUG.getState().session.independentCount===2&&!RC_DEBUG.getState().session.live.pending);
  const answer=page.locator('.opinion .prose').first();
  check(await answer.locator('h1').count()===1&&await answer.locator('h2').count()===1,'answers render real headings');
  check(await answer.locator('strong').count()>0&&await answer.locator('ol li').count()===5,'emphasis and nested lists render structurally');
  check(await answer.locator('.md-table table tbody tr').count()===3,'Markdown tables become structured rows and columns');
  check(await answer.locator('blockquote').count()===1,'quotations render separately');
  check(!(await answer.textContent()).includes('## 本轮判断'),'Markdown delimiters are removed from reading view');
  const typography=await answer.evaluate(el=>({font:parseFloat(getComputedStyle(el).fontSize),paragraph:parseFloat(getComputedStyle(el.querySelector('p')).fontSize),color:getComputedStyle(el).color,space:getComputedStyle(el.querySelector('p')).whiteSpace}));
  check(typography.font===15&&typography.paragraph===15&&typography.space==='normal','body is 15px with semantic paragraph wrapping');
  check(typography.color==='rgb(225, 233, 226)','dark mode uses high-contrast reading text');
  fs.mkdirSync(path.join(root,'test-results'),{recursive:true});await page.locator('#jumpLatest').click();await page.locator('.opinion').first().evaluate(el=>el.scrollIntoView({block:'start'}));
  await page.screenshot({path:path.join(root,'test-results','reading-dark.png')});
  await page.locator('#themeSelect').selectOption('light');
  check(await answer.evaluate(el=>getComputedStyle(el).color)==='rgb(37, 51, 44)','light mode uses dark reading text');
  await page.screenshot({path:path.join(root,'test-results','reading-light.png')});
  await page.locator('#runModeSelect').selectOption('semi');await page.locator('#advance').click();
  await page.waitForFunction(()=>RC_DEBUG.getState().session.stage==='debate'&&RC_DEBUG.getState().session.turnIndex===2&&!RC_DEBUG.getState().session.live.pending);
  check(await page.locator('.turn-box.prose h1').count()===2,'debate replies use the same Markdown renderer');
  await page.locator('[data-quote="0"]').click();check((await page.locator('#quoteDraft').textContent()).includes('# 先明确问题')&&!(await page.locator('#intervention').inputValue()).includes('# 先明确问题'),'quote attachment preserves Markdown without filling the message field');
  await page.locator('#editNotes').click();await page.locator('#notesEdit').fill('# 手动笔记\n\n**保留原文**\n\n- 一条记录');await page.locator('#editNotes').click();
  check(await page.locator('#notesRead .prose h1').count()===1&&await page.locator('#notesRead .prose strong').count()===1,'editable notes also render Markdown');
  await page.locator('#editNotes').click();check((await page.locator('#notesEdit').inputValue()).includes('**保留原文**'),'formatting never rewrites stored Markdown');await page.locator('#editNotes').click();
  await page.setViewportSize({width:540,height:1080});
  check(await page.locator('.cards').evaluate(el=>el.scrollWidth<=el.clientWidth+1),'tables do not cause horizontal scrolling of the discussion');
  check(await page.locator('.opinion .prose').first().evaluate(el=>parseFloat(getComputedStyle(el).fontSize))===15,'narrow windows retain a readable 15px body');
  check(await page.locator('.opinion .md-table').first().evaluate(el=>el.scrollWidth>el.clientWidth),'wide tables scroll only inside their own region');
  check(external.length===0,'rendering does not fetch external Markdown media or a CDN');
  const fallback=await page.evaluate(source=>{const marked=window.marked,renderer=window.CouncilMarkdown;try{window.marked=undefined;(0,eval)(source);return CouncilMarkdown.render('<script>bad()</script>\n**plain**')}finally{window.marked=marked;window.CouncilMarkdown=renderer}},fs.readFileSync(path.join(root,'markdown.js'),'utf8'));
  check(fallback.includes('&lt;script&gt;')&&fallback.includes('**plain**'),'a missing parser degrades to escaped readable text without blocking controls');
  check(errors.length===0,'no JavaScript errors');console.log(JSON.stringify({checks,errors},null,2));
 }finally{if(browser)await browser.close();child.kill('SIGINT');await new Promise(r=>child.once('exit',r));fs.rmSync(data,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
