/* Local Markdown rendering. CLI answers remain data; HTML and embedded media
   are never executed. The final HTML has a small, explicit element allowlist. */
(()=>{
 'use strict';
 const escape=text=>String(text??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
 function safeURL(value){
  const href=String(value||'').trim();
  if(!/^(https?:\/\/|#)/i.test(href)||/[\u0000-\u001f\u007f]/.test(href))return null;
  try{const url=new URL(href,location.href);return ['http:','https:'].includes(url.protocol)?href:null}catch{return null}
 }
 const parser=window.marked?.Marked?new window.marked.Marked({gfm:true,breaks:false,async:false,renderer:{
  html({text}){return escape(text)},
  link({href,title,tokens}){const label=this.parser.parseInline(tokens),safe=safeURL(href);return safe?`<a href="${escape(safe)}"${title?` title="${escape(title)}"`:''}>${label}</a>`:label},
  image({text}){return escape(text)}
 }}):null;
 const tags=new Set('P BR H1 H2 H3 H4 H5 H6 BLOCKQUOTE UL OL LI STRONG EM DEL HR A PRE CODE TABLE THEAD TBODY TR TH TD INPUT'.split(' '));
 const cache=new Map();
 function render(source){
  const text=String(source??''),lang=document.documentElement.lang,key=lang+'\0'+text;
  if(cache.has(key))return cache.get(key);
  let output;
  try{
   if(!parser)throw new Error('Markdown parser unavailable');
   const template=document.createElement('template');template.innerHTML=parser.parse(text);
   for(const el of template.content.querySelectorAll('*')){
    if(!tags.has(el.tagName)){el.replaceWith(document.createTextNode(el.textContent));continue}
    const href=el.getAttribute('href'),title=el.getAttribute('title'),start=el.getAttribute('start'),checked=el.hasAttribute('checked'),type=el.getAttribute('type'),alignment=el.getAttribute('align');
    for(const attr of [...el.attributes])el.removeAttribute(attr.name);
    if(el.tagName==='A'){
     const safe=safeURL(href);
     if(safe){el.setAttribute('href',safe);if(!safe.startsWith('#')){el.setAttribute('target','_blank');el.setAttribute('rel','noopener noreferrer')}}
     if(title)el.setAttribute('title',title);
    }
    if(el.tagName==='OL'&&/^\d{1,9}$/.test(start||''))el.setAttribute('start',start);
    if(['TH','TD'].includes(el.tagName)&&['left','center','right'].includes(alignment))el.setAttribute('align',alignment);
    if(el.tagName==='INPUT'){
     if(type!=='checkbox'){el.remove();continue}
     el.setAttribute('type','checkbox');el.setAttribute('disabled','');if(checked)el.setAttribute('checked','');
    }
   }
   for(const table of template.content.querySelectorAll('table')){
    const wrapper=document.createElement('div');wrapper.className='md-table';wrapper.tabIndex=0;wrapper.setAttribute('role','region');
    wrapper.setAttribute('aria-label',lang.startsWith('zh')?'表格，可横向滚动':lang.startsWith('ja')?'表（横にスクロールできます）':'Table, horizontally scrollable');
    table.replaceWith(wrapper);wrapper.appendChild(table);
   }
   output=template.innerHTML;
  }catch{output='<p>'+escape(text).replace(/\n/g,'<br>')+'</p>'}
  cache.set(key,output);if(cache.size>64)cache.delete(cache.keys().next().value);
  return output;
 }
 window.CouncilMarkdown={render};
})();
