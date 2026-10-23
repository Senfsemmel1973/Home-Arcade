/* Arcade manifest adapter. Copyright (c) 2026 Harry Knechtel. SPDX-License-Identifier: MIT. Local runtime only. */
'use strict';
window.Arcade=(()=>{
 const base=new URL('./',document.currentScript.src);
 let pending;
 const slug=/^[a-z0-9]+(?:-[a-z0-9]+)*$/;
 const reserved=new Set(['constructor','prototype','__proto__']);
 function record(v){if(v===null||typeof v!=='object'||Array.isArray(v))return false;const p=Object.getPrototypeOf(v);return p===null||Object.getPrototypeOf(p)===null;}
 function keys(v,allowed){if(!record(v)||Reflect.ownKeys(v).some(k=>typeof k!=='string'||!allowed.includes(k)||!Object.getOwnPropertyDescriptor(v,k).enumerable||!('value' in Object.getOwnPropertyDescriptor(v,k))))throw Error('Unzulässige Manifestfelder.');}
 function text(v,max){return typeof v==='string'&&v.trim().length>0&&v.length<=max&&!/[\u0000-\u001f\u007f]/.test(v);}
 function filename(v){return text(v,240)&&/^[\p{L}\p{N}][\p{L}\p{N} .,'()!~_-]*$/u.test(v)&&!v.includes('..')&&!/[. ]$/.test(v)&&!/^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])[.]/i.test(v);}
 function mapperChoices(n){
  const fixed={CV:[2048,4096],E0:[8192],F0:[65536],FE:[8192],E7:[16384],F8:[8192],F6:[16384],F4:[32768],FA2:[24576,28672,32768],FA:[12288],X07:[65536],'0840':[8192],UA:[8192]};
  const a=[];if(n>=8&&n<=4096&&4096%n===0)a.push('4K');for(const [m,sizes] of Object.entries(fixed))if(sizes.includes(n))a.push(m);
  if(n===32768)a.push('FA2cu');if(n>=8192&&n<=65536&&n%4096===0)a.push('EF');if(n>=10240&&n<=10496)a.push('DPC');if(n>=2048&&n<=524288&&n%2048===0)a.push('3F','3E');if(n>=8192&&n<=262144&&n%4096===0)a.push('SB');return a;
 }
 function media(bytes,format){
  const b=bytes instanceof Uint8Array?bytes:new Uint8Array(bytes),word=o=>b[o]+256*b[o+1];
  const fail=message=>{throw Error(message);};
  if(format==='d64'){const o=17*21*256;if(b.length!==174848||b[o]!==18||b[o+1]!==1||b[o+2]!==65)fail('D64-BAM/Verzeichnis ungültig');return [];}
  if(format==='prg'){if(b.length<3||b.length>65537||word(0)<2||word(0)+b.length-2>65536)fail('PRG-Ladeadresse/Größe ungültig');return [];}
  if(format!=='t64'||b.length<96||b.length>524288)fail('T64-Größe ungültig');
  const magic=Array.from(b.slice(0,32)).map(c=>String.fromCharCode(c)).join('').split('\0')[0].trimEnd();
  const cap=word(34),used=word(36),dirEnd=64+cap*32;
  if(!['C64 tape image file','C64S tape image file','C64S tape file'].includes(magic)||![256,257].includes(word(32))||used<1||used>cap||cap>1024||dirEnd>b.length)fail('T64-Header ungültig');
  const entries=[],spans=[];for(let i=0;i<cap;i++){const o=64+i*32,e=b.slice(o,o+32);if(e[0]===0){if(e.some(c=>c!==0))fail('T64-Leereintrag ungültig');continue;}
   if(e[0]!==1||![2,130].includes(e[1])||e.slice(6,8).some(c=>c)||e.slice(12,16).some(c=>c))fail('T64-Dateityp ungültig');
   const start=word(o+2),end=word(o+4),offset=e[8]+e[9]*256+e[10]*65536+e[11]*16777216,stop=offset+end-start;
   if(start<2||end<=start||offset<dirEnd||stop>b.length||spans.some(([a,z])=>stop>a&&offset<z))fail('T64-Datenbereich ungültig');spans.push([offset,stop]);
   const name=Array.from(e.slice(16)).map(c=>c>=32&&c<=126?String.fromCharCode(c):'?').join('').replace(/^[ ?]+|[ ?]+$/g,'');entries.push({index:i,name:name||'Programm '+(i+1),loadAddress:start,bytes:end-start});
  }if(entries.length!==used)fail('T64-Eintragszähler ungültig');return entries;
 }
 // Native T64 loading; only move directory records in a volatile copy.
 function selectTape(bytes,index){const entries=media(bytes,'t64');if(!entries.some(e=>e.index===index))throw Error('T64-Programm nicht vorhanden');const b=new Uint8Array(bytes).slice(),record=b.slice(64+index*32,96+index*32);b.copyWithin(96,64,64+index*32);b.set(record,64);return b;}
 function validate(data){
  keys(data,['version','games']);
  if(data.version!==1||!Array.isArray(data.games)||data.games.length>10000)throw Error('Ungültiges Spielemanifest.');
  const ids=new Set(),roms=new Set(),files=new Set(),gameIds=new Set();
  for(const g of data.games){
   const common=['id','title','system','player','rom','format','bytes','sha256','source','serverFile','controls','instructions','cover'];
   keys(g,common.concat(['mapper','region','joyPort','loadProfile']));
   if(!text(g.id,64)||!slug.test(g.id)||reserved.has(g.id)||ids.has(g.id))throw Error('Ungültige oder doppelte Spiel-ID.');ids.add(g.id);
   if(!['vcs2600','c64'].includes(g.system))throw Error('Unbekanntes System.');
   keys(g,common.concat(g.system==='vcs2600'?['mapper','region']:['joyPort','loadProfile']));
   const player=g.system==='c64'?'c64/player.html':'atari/player.html';
   const format=g.system==='c64'?g.format:'bin';
   if(g.system==='c64'&&!['d64','prg','t64'].includes(format))throw Error('Unbekanntes C64-Format.');
   if(g.player!==player||g.format!==format||!text(g.rom,180)||!new RegExp('^roms/'+g.system+'/[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*[.]'+format+'$').test(g.rom)||!Number.isSafeInteger(g.bytes)||g.bytes<=0||typeof g.sha256!=='string'||g.sha256.length!==64||!/^[a-f0-9]{64}$/.test(g.sha256)||!text(g.title,300)||!text(g.controls,2000)||!text(g.instructions,8000))throw Error('Ungültiges Startprofil.');
   const romKey=g.rom.toLowerCase();if(roms.has(romKey))throw Error('Doppelter ROM-Pfad.');roms.add(romKey);
   if(g.cover!==undefined&&g.cover!=='covers/'+g.id+'.jpg')throw Error('Unzulässiger Coverpfad.');
   if(g.serverFile!==undefined&&(!filename(g.serverFile)||!g.serverFile.endsWith('.'+format)))throw Error('Unzulässiger Serverdateiname.');
   // Without explicit serverFile, future imports use the safe URL basename.
   const target=g.serverFile??g.rom.slice(g.rom.lastIndexOf('/')+1),targetKey=g.system+'/'+target.normalize('NFC').toLowerCase();
   if(files.has(targetKey))throw Error('Doppeltes ROM-Ziel.');files.add(targetKey);
   if(g.source!==undefined){const prefix='ROMs/'+g.system+'/';if(typeof g.source!=='string'||!g.source.startsWith(prefix)||!filename(g.source.slice(prefix.length))||!g.source.endsWith('.'+format)||(g.serverFile!==undefined&&g.source.slice(prefix.length)!==g.serverFile))throw Error('Unzulässige ROM-Quelle.');}
   if(g.system==='c64'){
    keys(g.loadProfile,['core','autostart','model','program','gameId']);
    if(![1,2].includes(g.joyPort)||(format==='d64'?g.bytes!==174848:format==='prg'?(g.bytes<3||g.bytes>65537):(g.bytes<96||g.bytes>524288))||g.loadProfile.core!=='vice_x64sc'||!['warp','enabled'].includes(g.loadProfile.autostart)||g.loadProfile.model!=='C64 PAL'||g.loadProfile.program!=='*'||!Number.isSafeInteger(g.loadProfile.gameId)||g.loadProfile.gameId<1||g.loadProfile.gameId>2147483647||gameIds.has(g.loadProfile.gameId))throw Error('Ungültiges C64-Ladeprofil.');gameIds.add(g.loadProfile.gameId);
   }else if(!mapperChoices(g.bytes).includes(g.mapper)||!['auto','PAL','NTSC'].includes(g.region))throw Error('Ungültiges Atari-Profil.');
  }
  return data.games;
 }
 function catalog(){return pending??=(async()=>{const r=await fetch(new URL('games.json',base).href,{cache:'no-store',credentials:'omit',redirect:'error'});if(!r.ok)throw Error('Spielemanifest HTTP '+r.status);return validate(await r.json());})();}
 async function resolve(system){const p=new URLSearchParams(location.search);if(p.getAll('system').length!==1||p.getAll('game').length!==1)throw Error('System und Spiel-ID bitte genau einmal angeben.');const g=(await catalog()).find(g=>g.system===p.get('system')&&g.id===p.get('game'));if(!g||(system&&g.system!==system))throw Error('Spiel nicht freigegeben. Bitte aus der Bibliothek wählen.');return g;}
 function link(g){const u=new URL('./',base);u.searchParams.set('system',g.system);u.searchParams.set('game',g.id);return u.href;}
 function describe(g){document.title=g.title+' · '+(g.system==='c64'?'C64':'Atari 2600')+' · Arcade';document.getElementById('game-title').textContent=g.title;document.getElementById('game-controls').textContent=g.controls;document.getElementById('game-instructions').textContent=g.instructions;const info=document.getElementById('rom-info');if(info)info.textContent='ROM unverändert · '+g.bytes+' Bytes · '+g.mapper+'-Mapper.';const subtitle=document.getElementById('game-subtitle');if(subtitle)subtitle.textContent=g.id==='hero'?'Helicopter Emergency Rescue Operation':'Dschungelabenteuer · PAL-Fassung';}
 // Back/forward cache must never resume an old engine, disk or held key.
 window.addEventListener('pageshow',e=>{if(e.persisted)location.reload();});
 function cover(g){return g.cover==='covers/'+g.id+'.jpg'?new URL(g.cover,base).href:null;}
 return {base,catalog,resolve,link,describe,validate,cover,mapperChoices,media,selectTape};
})();
