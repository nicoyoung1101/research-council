from pathlib import Path
import os, shutil
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).parent
ARTIFACTS=ROOT/'test-results'
ARTIFACTS.mkdir(exist_ok=True)
html=(ROOT/'index.html').read_text()
html=html.replace('<link rel="stylesheet" href="themes.css">','<style>'+(ROOT/'themes.css').read_text()+'</style>')
for name in ['bridge-client.js','council-runtime.js']:
 html=html.replace(f'<script src="{name}"></script>','<script>'+(ROOT/name).read_text()+'</script>')
html=html.replace('<script src="app.js"></script>','<script>'+(ROOT/'app.js').read_text()+'</script>')
html=html.replace('<script src="theme.js"></script>','<script>'+(ROOT/'theme.js').read_text()+'</script>')
errors=[]
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path=os.environ.get('RC_CHROME') or shutil.which('chromium') or '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',args=['--no-sandbox'])
 context=browser.new_context(viewport={'width':1600,'height':960},device_scale_factor=1)
 page=context.new_page()
 page.evaluate("""() => { const mem={}; Object.defineProperty(window,'localStorage',{configurable:true, value:{ getItem:k=>mem[k]??null, setItem:(k,v)=>{mem[k]=String(v)}, removeItem:k=>{delete mem[k]} }}); }""")
 page.on('pageerror', lambda e: errors.append(str(e)))
 page.set_content(html,wait_until='load');page.wait_for_timeout(350)
 assert page.locator('html').get_attribute('data-theme')=='dark'
 assert page.locator('#themeSelect').input_value()=='dark'
 assert page.locator('#agentSummary').count()==1
 page.screenshot(path=str(ARTIFACTS/'preview-dark-main.png'),full_page=False)
 # Verify the pinned title collapses as the internal discussion scrolls.
 page.locator('#stageArea').evaluate('(x)=>{x.style.minHeight="1400px"}')
 page.locator('#scroll').evaluate('(x)=>{x.scrollTop=300; x.dispatchEvent(new Event("scroll"))}')
 page.wait_for_timeout(250)
 assert 'compact' in (page.locator('#fixedFlowWrap').get_attribute('class') or ''), 'compact pinned header not triggered'
 page.screenshot(path=str(ARTIFACTS/'preview-dark-compact.png'),full_page=False)
 page.locator('#scroll').evaluate('(x)=>{x.scrollTop=0; x.dispatchEvent(new Event("scroll"))}')
 page.locator('#stageArea').evaluate('(x)=>{x.style.minHeight=""}')
 page.wait_for_timeout(200)
 # Agent registry dialog
 page.locator('#addAgentRail').click();page.wait_for_timeout(250)
 assert page.locator('#modalOverlay').evaluate('(x)=>getComputedStyle(x).display')=='flex'
 page.screenshot(path=str(ARTIFACTS/'preview-dark-agents.png'),full_page=False)
 page.locator('#closeModal').click()
 # Advance to debate (independent stage can be full on initial demo)
 page.locator('#advance').click();page.wait_for_timeout(180)
 for _ in range(2):
  page.locator('#nextSpeaker').click(); page.wait_for_timeout(110)
 page.screenshot(path=str(ARTIFACTS/'preview-dark-debate.png'),full_page=False)
 # Work flow
 page.locator('#workTab').click();page.wait_for_timeout(200)
 page.screenshot(path=str(ARTIFACTS/'preview-dark-work.png'),full_page=False)
 # light mode unchanged and theme persistent
 page.locator('#themeSelect').select_option('light')
 assert page.locator('html').get_attribute('data-theme')=='light'
 page.screenshot(path=str(ARTIFACTS/'preview-light.png'),full_page=False)
 page.set_content(html,wait_until='load');page.wait_for_timeout(300)
 assert page.locator('#themeSelect').input_value()=='light', 'Theme is not persistent'
 page.locator('#themeSelect').select_option('auto')
 assert page.locator('#themeSelect').input_value()=='auto'
 page.locator('#langSelect').select_option('ja');page.wait_for_timeout(200)
 assert page.locator('#themeSelect option[value="dark"]').inner_text()=='ダーク'
 page.locator('#langSelect').select_option('en');page.wait_for_timeout(200)
 assert page.locator('#themeSelect option[value="dark"]').inner_text()=='Dark'
 assert not errors, errors
 browser.close()

print('PASS: startup dark, sticky header, dialog, debate, work, light, persisted theme, auto, multilingual, no JS errors')
