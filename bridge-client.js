/* Same-origin client. The static demo still works without the Python service. */
(()=>{
  const client=window.CouncilBridge={connected:false,state:null,revision:0,token:null,error:null};
  let baseState=null;
  client.ready=(async()=>{
    if(!/^https?:$/.test(location.protocol))return;
    try{
      const response=await fetch('/api/bootstrap',{signal:AbortSignal.timeout(4000)});
      if(!response.ok)return;
      const data=await response.json();
      if(!data.token)return;
      Object.assign(client,{connected:true,state:data.state,revision:data.revision,token:data.token});
      baseState=structuredClone(data.state);
      if(data.state?.theme)try{localStorage.setItem('rc-theme-v09',data.state.theme)}catch{}
    }catch{}
  })();
  client.request=async(path,body)=>{
    await client.ready;
    if(!client.connected)throw {code:'bridge_offline'};
    const response=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-Council-Token':client.token},body:body===undefined?undefined:JSON.stringify(body)});
    const data=await response.json();
    if(!response.ok)throw data;
    return data;
  };
  let pending=null,timer=null,saving=false,conflict=false;
  const report=error=>{client.error=error;window.dispatchEvent(new CustomEvent('council-save-error',{detail:error}))};
  const flush=async()=>{
    clearTimeout(timer);timer=null;
    if(saving||conflict||!pending||!client.connected)return;
    saving=true;
    const state=pending;pending=null;
    try{
      const result=await client.request('state',{state,revision:client.revision});
      client.revision=result.revision;client.error=null;
      baseState=structuredClone(state);client.state=structuredClone(state);
    }catch(error){
      pending=pending||state;
      conflict=error.code==='state_conflict';report(error);
      if(!conflict)timer=setTimeout(flush,2500);
    }finally{saving=false;if(pending&&!timer&&!conflict)timer=setTimeout(flush,100)}
  };
  client.save=state=>{
    if(!saving&&!pending&&JSON.stringify(state)===JSON.stringify(baseState))return;
    pending=structuredClone(state);clearTimeout(timer);timer=setTimeout(flush,200);
  };
  client.flush=async()=>{while(saving)await new Promise(r=>setTimeout(r,30));await flush();if(client.error)throw client.error};
  // Explicit recovery preserves both sides of a conflicting edit instead of
  // overwriting the other window. Keep the last saved base separate from UI data.
  client.mergeRecovery=(base,local,remote)=>{
    const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
    const docMap=new Map(),sessionMap=new Map();
    const suffix={zh:'（恢复副本）',ja:'（復元コピー）',en:' (recovered copy)'}[local.lang]||' (recovered copy)';
    function mergeList(key,mapping){
      const previous=new Map((base?.[key]||[]).map(x=>[x.id,x]));
      const merged=new Map((remote?.[key]||[]).map(x=>[x.id,structuredClone(x)]));
      for(const raw of local[key]||[]){
        let item=structuredClone(raw),other=merged.get(item.id),old=previous.get(item.id);
        if(same(item,old))continue;
        if(other&&!same(other,old)&&!same(other,item)){
          const original=item.id;item.id=(key==='sessions'?'s-recovered-':'local-')+crypto.randomUUID();mapping.set(original,item.id);
          if(key==='sessions'){item.name+=suffix;window.detachCouncilUtilities?.(item);}
        }
        if(key==='sessions'){
          item.contextIds=(item.contextIds||[]).map(id=>docMap.get(id)||id);
          if(item.live?.error?.code==='state_conflict'){
            item.live.error=null;
            if(!item.live.pending){item.live.pendingRequest=null;item.live.pendingTask=null;delete item.live.starting}
          }
        }
        merged.set(item.id,item);
      }
      return [...merged.values()];
    }
    const library=mergeList('library',docMap),sessions=mergeList('sessions',sessionMap);
    return {...remote,...local,library,sessions,activeId:sessionMap.get(local.activeId)||local.activeId};
  };
  client.recover=async local=>{
    await client.ready;
    while(saving)await new Promise(r=>setTimeout(r,30));
    clearTimeout(timer);timer=null;
    for(let attempt=0;attempt<3;attempt++){
      const response=await fetch('/api/bootstrap',{cache:'no-store'});
      if(!response.ok)throw {code:'bridge_offline'};
      const latest=await response.json();client.token=latest.token;
      const merged=client.mergeRecovery(baseState,local,latest.state||{});
      try{
        const result=await client.request('state',{revision:latest.revision,state:merged});
        pending=null;conflict=false;client.error=null;client.revision=result.revision;
        baseState=structuredClone(merged);client.state=structuredClone(merged);
        window.dispatchEvent(new CustomEvent('council-state-recovered',{detail:merged}));
        return merged;
      }catch(error){if(error.code!=='state_conflict'||attempt===2)throw error}
    }
  };
  window.addEventListener('beforeunload',event=>{if(saving||pending){event.preventDefault();event.returnValue=''}});
})();
