'use strict';
(async()=>{
 const topButton=document.getElementById('back-to-top');
 function topVisibility(){if(topButton)topButton.hidden=window.scrollY<Math.max(600,innerHeight*.8);}
 window.addEventListener('scroll',topVisibility,{passive:true});window.addEventListener('resize',topVisibility);topVisibility();
 topButton?.addEventListener('click',()=>window.scrollTo({top:0,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'}));
 const status=document.getElementById('status'),params=new URLSearchParams(location.search);
 try{
  if(params.has('system')||params.has('game')){const g=await Arcade.resolve();const u=new URL(g.player,Arcade.base);u.searchParams.set('v','standalone-1.0.0-rc1');u.searchParams.set('system',g.system);u.searchParams.set('game',g.id);location.replace(u.href);return;}
  const games=await Arcade.catalog(),list=document.getElementById('games'),search=document.getElementById('search');let system='all';
  // Home Arcade: UI Fix - Ver. 1.0.1. Browser preferences only.
  const size=document.getElementById('tile-size'),sizeValue=document.getElementById('tile-size-value'),sort=document.getElementById('sort-order');
  const preferenceKey='lc-home-arcade-ui-1.0.1';
  try{const saved=JSON.parse(localStorage.getItem(preferenceKey)||'{}');if(size&&Number.isInteger(saved.size)&&saved.size>=200&&saved.size<=400&&saved.size%10===0)size.value=String(saved.size);if(sort&&['asc','desc'].includes(saved.sort))sort.value=saved.sort;}catch{}
  function tileSize(){const value=size?.value||'260';document.documentElement.style.setProperty('--tile-min',value+'px');if(sizeValue)sizeValue.value=value+' px';size?.setAttribute('aria-valuetext',value+' Pixel');}
  function remember(){try{localStorage.setItem(preferenceKey,JSON.stringify({size:Number(size?.value||260),sort:sort?.value||'asc'}));}catch{}}
  const collator=new Intl.Collator('de',{sensitivity:'base',numeric:true});
  function orderCards(){const direction=sort?.value==='desc'?-1:1;for(const {card} of [...cards].sort((a,b)=>direction*collator.compare(a.g.title,b.g.title)||collator.compare(a.g.id,b.g.id)))list.append(card);}
  tileSize();
  const tiles={};
  const cards=games.map(g=>{
   const card=document.createElement('article');card.className='game-card '+g.system;
   const art=document.createElement('div');art.className='card-art';art.setAttribute('aria-hidden','true');art.textContent=tiles[g.id]??g.title;
   const cover=Arcade.cover(g);{const img=document.createElement('img');img.className='card-cover';img.alt='';let fallback=false;img.onerror=()=>{if(cover&&!fallback){fallback=true;img.src=cover;}else img.remove();};img.src=new URL('import-api/asset-cover/'+g.id,Arcade.base);art.append(img);}
   const title=document.createElement('h2');title.textContent=g.title;
   const actions=document.createElement('div');actions.className='card-actions';const play=document.createElement('a');play.className='play';play.href=Arcade.link(g);play.textContent='Spielen ↗';actions.append(play);
   const links=document.createElement('div');links.className='lc-link';const label=document.createElement('label');label.htmlFor='link-'+g.id;label.textContent='Play-Link für LC';const url=document.createElement('textarea');url.id=label.htmlFor;url.readOnly=true;url.rows=3;url.spellcheck=false;url.value=Arcade.link(g);url.addEventListener('focus',()=>url.select());
   const copy=document.createElement('button');copy.type='button';copy.textContent='Link kopieren';copy.setAttribute('aria-label','Play-Link für '+g.title+' kopieren');const message=document.createElement('span');message.className='copy-status';message.setAttribute('role','status');
   copy.addEventListener('click',async()=>{try{if(!navigator.clipboard?.writeText)throw Error('Clipboard unavailable');await navigator.clipboard.writeText(url.value);message.textContent='Link kopiert.';}catch{url.focus();url.select();message.textContent='Link markiert – mit Strg+C oder dem Kopiermenü kopieren.';}});
   links.append(label,url,copy,message);card.append(art,title,actions,links);list.append(card);return{g,card};
  });
  orderCards();
  let controller;
  size?.addEventListener('input',()=>{tileSize();remember();});
  sort?.addEventListener('change',()=>{orderCards();remember();render();});
  async function api(path,options={}){const r=await fetch(new URL('import-api/'+path,Arcade.base),{credentials:'same-origin',cache:'no-store',...options});const v=await r.json();if(!r.ok)throw Error(v.error||'Anmeldung erforderlich.');return v;}
  function managementLink(g,action){const u=new URL('import/',Arcade.base);u.searchParams.set('game',g.id);u.searchParams.set('action',action);u.hash='manage';return u.href;}
  for(const {g,card} of cards){const coverLink=document.createElement('a');coverLink.textContent='Cover ändern';coverLink.href=managementLink(g,'cover');card.querySelector('.card-actions').append(coverLink);}
  const actionsReady=api('library-actions');actionsReady.then(data=>{for(const {g,card} of cards){if(!data.ids.includes(g.id))continue;const button=document.createElement('button');button.type='button';button.textContent='🗑';button.title='Spiel entfernen';button.setAttribute('aria-label',g.title+' entfernen');card.querySelector('.card-actions').append(button);button.onclick=()=>{location.assign(managementLink(g,'remove'));};}}).catch(()=>{});
  function render(){const q=search.value.trim().toLocaleLowerCase('de');let count=0;for(const {g,card} of cards){const visible=card.dataset.deleted!=='true'&&(system==='all'||g.system===system)&&(g.title+' '+g.system).toLocaleLowerCase('de').includes(q);card.hidden=!visible;if(visible)count++;}status.textContent=count+' von '+cards.filter(x=>x.card.dataset.deleted!=='true').length+' Spielen';document.getElementById('empty').hidden=count!==0;controller?.refresh();}
  search.addEventListener('input',render);for(const b of document.querySelectorAll('[data-system]'))b.addEventListener('click',()=>{system=b.dataset.system;for(const other of document.querySelectorAll('[data-system]'))other.setAttribute('aria-pressed',String(other===b));render();});render();
  if(window.ArcadeLibraryController&&window.ArcadeInput)controller=ArcadeLibraryController({cards,search,size,sort,list,render,managementLink,actionsReady,applyView(){tileSize();orderCards();remember();render();}});
 }catch(e){status.textContent=e.message;document.getElementById('empty').textContent='Bitte zur Bibliothek ohne URL-Parameter zurückkehren oder Manifest prüfen.';document.getElementById('empty').hidden=false;}
})();
