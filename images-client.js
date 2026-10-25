/* Clipboard photos are private local assets until the user sends a message. */
window.createCouncilImages=api=>{
 const bridge=window.CouncilBridge,$=id=>document.getElementById(id),esc=api.esc,cache=new Map(),loading=new Map(),pending=new WeakMap();
 const words={
  zh:{image:'图片',remove:'移除图片',uploading:'正在添加图片…',failed:'图片添加失败',limit:'每条消息最多 4 张图片，每张不超过 5 MB。',unsupported:'当前 Gemini / Antigravity 通道只支持文字；图片请切换到 Claude 或 Codex。',only:'请查看附图。',offline:'请先连接本地服务再添加图片。',retry:'图片未能加载',close:'关闭',ready:'可直接粘贴图片（⌘V）',loading:'请等待图片添加完成。'},
  ja:{image:'画像',remove:'画像を削除',uploading:'画像を追加中…',failed:'画像の追加に失敗',limit:'1メッセージ4枚まで、各5 MB以下です。',unsupported:'現在の Gemini / Antigravity はテキストのみです。画像には Claude または Codex を選んでください。',only:'添付画像を確認してください。',offline:'先にローカルサービスへ接続してください。',retry:'画像を読み込めません',close:'閉じる',ready:'画像を直接貼り付け（⌘V）',loading:'画像の追加が完了するまでお待ちください。'},
  en:{image:'Image',remove:'Remove image',uploading:'Adding image…',failed:'Could not add image',limit:'Up to 4 images per message, 5 MB each.',unsupported:'The current Gemini / Antigravity channel accepts text only; choose Claude or Codex for images.',only:'Please inspect the attached image.',offline:'Connect to the local service before adding images.',retry:'Image could not be loaded',close:'Close',ready:'Paste an image directly (⌘V)',loading:'Wait for the images to finish uploading.'}
 };
 const L=k=>(words[api.lang()]||words.en)[k];
 const draft=owner=>owner?.imageDraft||[];
 const busy=owner=>(pending.get(owner)||0)>0;
 function html(images=[],editable=false){return images.length?`<div class="message-images">${images.map(im=>`<span class="image-attachment"><button type="button" class="image-open" data-image-open="${esc(im.id)}" title="${esc(im.name||L('image'))}"><img class="image-thumb" data-image="${esc(im.id)}" ${cache.has(im.id)?`src="${cache.get(im.id)}"`:''} alt="${esc(im.name||L('image'))}"></button>${editable?`<button type="button" class="image-remove" data-image-remove="${esc(im.id)}" aria-label="${esc(L('remove'))}">×</button>`:''}</span>`).join('')}</div>`:''}
 async function load(id){if(cache.has(id))return cache.get(id);if(!loading.has(id))loading.set(id,bridge.request('images/'+encodeURIComponent(id)).then(im=>{const url='data:'+im.mime+';base64,'+im.data;cache.set(id,url);return url}).finally(()=>loading.delete(id)));return loading.get(id)}
 function hydrate(){document.querySelectorAll('img[data-image]').forEach(img=>{if(img.getAttribute('src')||img.dataset.loading)return;img.dataset.loading='true';load(img.dataset.image).then(url=>{if(img.isConnected)img.src=url}).catch(()=>{delete img.dataset.loading;img.alt=L('retry')})})}
 function tray(input,owner){if(!input)return;let el=input.parentElement.querySelector('.image-draft');if(!el){el=document.createElement('div');el.className='image-draft';input.before(el)}
  el.hidden=!draft(owner).length&&!busy(owner);el.innerHTML=html(draft(owner),true)+(busy(owner)?`<small>${L('uploading')}</small>`:'');
  el.onclick=e=>{const b=e.target.closest('[data-image-remove]');if(b&&owner){owner.imageDraft=draft(owner).filter(im=>im.id!==b.dataset.imageRemove);api.save();refresh()}};
  input.title=L('ready');
 }
 function refresh(){tray($('intervention'),api.mainOwner());tray($('sideQuestion'),api.sideOwner());hydrate();window.CouncilComposer?.refreshSend()}
 async function add(files,owner){if(!owner)return;if(!bridge.connected)return api.toast(L('offline'));
  const list=[...files].filter(f=>/^image\/(png|jpeg|gif|webp)$/.test(f.type));
  if(!list.length||list.some(f=>f.size>5*1024*1024)||draft(owner).length+list.length+(pending.get(owner)||0)>4)return api.toast(L('limit'));
  pending.set(owner,(pending.get(owner)||0)+list.length);refresh();
  for(const file of list){try{
   const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file)});
   // Decode before publishing a thumbnail; malformed files are not shown as valid photos.
   await new Promise((resolve,reject)=>{const im=new Image();im.onload=resolve;im.onerror=reject;im.src=data});
   const saved=await bridge.request('images',{name:file.name||L('image'),mime:file.type,data:data.split(',')[1]});
   cache.set(saved.id,data);owner.imageDraft=[...draft(owner),saved];api.save();await bridge.flush();
  }catch(e){api.toast(L('failed')+' · '+(e.detail||e.code||''))}finally{pending.set(owner,Math.max(0,(pending.get(owner)||0)-1));refresh()}}
 }
 function bind(input,ownerFn){input?.addEventListener('paste',e=>{
  const files=[...e.clipboardData?.items||[]].filter(x=>x.kind==='file'&&x.type.startsWith('image/')).map(x=>x.getAsFile()).filter(Boolean);
  if(!files.length)return;e.preventDefault();const owner=ownerFn(),text=e.clipboardData.getData('text/plain');if(text){input.setRangeText(text,input.selectionStart,input.selectionEnd,'end');input.dispatchEvent(new Event('input',{bubbles:true}))}add(files,owner);
 })}
 function canSend(owner,agents){if(busy(owner)){api.toast(L('loading'));return false}if(draft(owner).length&&agents.some(a=>a.provider==='gemini')){api.toast(L('unsupported'));return false}return true}
 function take(owner){const rows=structuredClone(draft(owner));owner.imageDraft=[];refresh();return rows}
 document.addEventListener('click',async e=>{const b=e.target.closest('[data-image-open]');if(!b)return;try{const url=await load(b.dataset.imageOpen);api.modal(L('image'),'',`<img class="image-full" src="${url}" alt="${esc(L('image'))}">`,`<button class="btn" id="closeImage">${L('close')}</button>`);$('closeImage').onclick=api.close}catch{api.toast(L('retry'))}});
 function refs(value,set=new Set()){
  if(!value||typeof value!=='object')return set;
  if(typeof value.id==='string'&&/^[a-f0-9]{64}\.(png|jpg|gif|webp)$/.test(value.id)&&typeof value.mime==='string')set.add(value.id);
  for(const child of Object.values(value))refs(child,set);return set;
 }
 async function exportBackup(data){const imageAssets=await Promise.all([...refs(data)].map(id=>bridge.request('images/'+id)));return {...data,...(imageAssets.length?{imageAssets}:{})}}
 async function importBackup(data){const required=refs(data.state);if((data.imageAssets||[]).length>100)throw Error(L('limit'));
  for(const im of data.imageAssets||[]){const saved=await bridge.request('images',im);if(saved.id!==im.id)throw Error('Image integrity mismatch')}
  await Promise.all([...required].map(load));return data;
 }
 bind($('intervention'),api.mainOwner);bind($('sideQuestion'),api.sideOwner);refresh();
 return {html,refresh,hydrate,add,canSend,take,busy,L,exportBackup,importBackup};
};
