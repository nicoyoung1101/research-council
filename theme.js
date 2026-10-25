/* Standalone theme controller — deliberately separate from the debate engine. */
(()=>{
  'use strict';
  const control=document.getElementById('themeSelect');
  const language=document.getElementById('langSelect');
  const symbol=document.getElementById('themeSymbol');
  if(!control)return;
  const labels={
    zh:{light:'浅色',dark:'深色',auto:'跟随系统',title:'外观'},
    ja:{light:'ライト',dark:'ダーク',auto:'システム',title:'外観'},
    en:{light:'Light',dark:'Dark',auto:'System',title:'Appearance'}
  };
  let preference='dark';
  try{preference=localStorage.getItem('rc-theme-v09')||'dark'}catch(_){ }
  if(!['dark','light','auto'].includes(preference))preference='dark';
  const mq=window.matchMedia?.('(prefers-color-scheme: dark)');
  const actual=()=>preference==='auto'?(mq?.matches?'dark':'light'):preference;
  function updateLocale(){
    const current=labels[language?.value]||labels.zh;
    for(const op of control.options)op.textContent=current[op.value];
    control.setAttribute('aria-label',current.title);
    control.parentElement.title=current.title;
    control.value=preference;
  }
  function updateTheme(){
    const applied=actual();
    document.documentElement.dataset.theme=applied;
    document.documentElement.style.colorScheme=applied;
    symbol.textContent=applied==='dark'?'☾':'☼';
    updateLocale();
  }
  control.addEventListener('change',()=>{
    preference=control.value;
    try{localStorage.setItem('rc-theme-v09',preference)}catch(_){ }
    updateTheme();window.dispatchEvent(new Event('council-theme-change'));
  });
  language?.addEventListener('change',updateLocale);
  if(mq){if(mq.addEventListener)mq.addEventListener('change',()=>{if(preference==='auto')updateTheme()});
    else if(mq.addListener)mq.addListener(()=>{if(preference==='auto')updateTheme()});}
  updateTheme();
  window.RC_THEME={refreshLocale:updateLocale,getPreference:()=>preference,getApplied:actual,setPreference:(v)=>{
    if(!['dark','light','auto'].includes(v))throw Error('Invalid theme');
    preference=v;try{localStorage.setItem('rc-theme-v09',preference)}catch(_){} updateTheme();
  }};
  window.CouncilBridge?.ready.then(()=>{const saved=window.CouncilBridge.state?.theme;if(saved)window.RC_THEME.setPreference(saved);updateLocale()});
})();
