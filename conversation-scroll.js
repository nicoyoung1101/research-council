/* Viewport state is local to the UI; it never alters a discussion or calls a model. */
window.createConversationScroll=function(scroller,area,held){
 'use strict';
 let key=null,active=false,following=true,mutating=false,revision=0,lastTop=scroller.scrollTop,frame=0,touchY=null;
 const blocks='.prose p,.prose li,.prose pre,.prose h1,.prose h2,.prose h3';
 const atEnd=()=>scroller.scrollHeight-scroller.clientHeight-scroller.scrollTop<=3;
 const hold=()=>{following=false;revision++;mutating=false;cancelAnimationFrame(frame)};
 const nested=target=>{for(let el=target instanceof Element?target:null;el&&el!==scroller;el=el.parentElement){if(el.scrollHeight>el.clientHeight+2&&/(auto|scroll)/.test(getComputedStyle(el).overflowY))return true}return false};
 function setTop(top){scroller.scrollTo({top,behavior:'instant'});lastTop=scroller.scrollTop}
 function jumpLatest(){if(!active)return;revision++;following=true;mutating=true;cancelAnimationFrame(frame);setTop(scroller.scrollHeight);const token=revision;frame=requestAnimationFrame(()=>{if(token!==revision)return;setTop(scroller.scrollHeight);mutating=false})}
 // An upward gesture opts out immediately, even inside the old 60px threshold.
 scroller.addEventListener('wheel',e=>{if(e.deltaY<0&&!nested(e.target))hold()},{passive:true});
 scroller.addEventListener('touchstart',e=>{touchY=e.touches[0]?.clientY??null},{passive:true});
 scroller.addEventListener('touchmove',e=>{const y=e.touches[0]?.clientY;if(y!==undefined&&touchY!==null&&y>touchY&&!nested(e.target))hold();touchY=y??null},{passive:true});
 document.addEventListener('keydown',e=>{if(e.defaultPrevented||e.target.closest?.('input,textarea,select,[contenteditable="true"]')||e.target.closest?.('#modalOverlay.open,.side-chat'))return;if(['ArrowUp','PageUp','Home'].includes(e.key)||(e.key===' '&&e.shiftKey))hold()});
 scroller.addEventListener('scroll',()=>{const top=scroller.scrollTop;if(!mutating){if(top<lastTop-.5)following=false;else if(top>lastTop+.5&&atEnd())following=true}lastTop=top},{passive:true});
 function capture(nextKey,discussion=true){
  const changed=key!==nextKey;if(changed){key=nextKey;active=discussion;following=discussion;revision++;cancelAnimationFrame(frame)}
  const rect=scroller.getBoundingClientRect(),visible=el=>{const r=el.getBoundingClientRect();return r.bottom>rect.top&&r.top<rect.bottom&&el.getClientRects().length};
  const anchor=changed?null:([...area.querySelectorAll(blocks)].find(visible)||[...area.querySelectorAll('[data-flow-item]')].find(visible));
  const owner=anchor?.closest('[data-flow-item]'),index=owner&&anchor!==owner?[...owner.querySelectorAll(blocks)].indexOf(anchor):-1;
  const snapshot={key,revision,top:changed?0:scroller.scrollTop,follow:following&&discussion&&!held(),item:owner?.dataset.flowItem,index,offset:anchor?.getBoundingClientRect().top};
  mutating=true;return snapshot;
 }
 function restore(snapshot){
  const apply=()=>{if(snapshot.key!==key||snapshot.revision!==revision)return false;
   if(snapshot.follow&&!held())setTop(scroller.scrollHeight);
   else{const owner=[...area.querySelectorAll('[data-flow-item]')].find(el=>el.dataset.flowItem===snapshot.item),anchor=snapshot.index>=0?owner?.querySelectorAll(blocks)[snapshot.index]:owner;
    // Use current scrollTop: DOM replacement may already have clamped the old value.
    setTop(anchor&&snapshot.offset!==undefined?scroller.scrollTop+anchor.getBoundingClientRect().top-snapshot.offset:snapshot.top)}return true};
  apply();cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{if(snapshot.key!==key||snapshot.revision!==revision)return;if(snapshot.follow)apply();mutating=false});
 }
 const resize=new ResizeObserver(()=>{if(active&&following&&!mutating&&!held()&&!atEnd())jumpLatest()});resize.observe(scroller);resize.observe(area);
 return {capture,restore,hold,jumpLatest};
};
