'use strict';
// One same-origin browser entry. No ROM execution, profile guessing or LC URLs.
(()=>{
 const $=id=>document.getElementById(id), api=new URL('../import-api/',location.href);
 let csrf='',rows=[],busy=false,lastToken='';
 const navigation=new URLSearchParams(location.search);
 let managedRows=[],focusedGame=navigation.get('game')||navigation.get('cover')||'',navigationApplied=false;
 async function request(path,options={}){
  const response=await fetch(new URL(path,api),{credentials:'same-origin',cache:'no-store',redirect:'error',...options});
  const data=await response.json();if(!response.ok)throw Error(data.error||'HTTP '+response.status);return data;
 }
 function post(path,value){return request(path,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(value)});}
 function node(tag,text,parent){const n=document.createElement(tag);if(text)n.textContent=text;if(parent)parent.append(n);return n;}
 function updateRow(row){
  if(!row.card)return;
  const mapperMissing=row.state==='ready'&&row.mapperSelect&&!row.mapperSelect.value;
  row.card.dataset.state=row.state;
  if(row.discardButton)row.discardButton.hidden=row.state!=='ready';
  row.rowStatus.textContent=mapperMissing?'Mapper wählen':row.coverPending?'Cover wird geprüft':({ready:'Importbereit',existing:'Vorhanden',imported:'Importiert',discarded:'Zurückgestellt',deferred:'Fehler / zurückgestellt'}[row.state]||row.state);
  row.rowTitle.textContent=row.titleInput?.value||row.title||'';
  row.rowTitle.hidden=!row.rowTitle.textContent||row.rowTitle.textContent===row.filename;
  const message=row.uiMessage||row.message||row.warning||(mapperMissing?'Atari-Mapper ausdrücklich auswählen.':'');
  row.rowMessage.textContent=message;row.rowMessage.hidden=!message;
  row.card.classList.toggle('needs-attention',Boolean(message)||Boolean(mapperMissing));
 }
 function summary(){
  rows.forEach(updateRow);
  const ready=rows.filter(r=>r.state==='ready').length,existing=rows.filter(r=>r.state==='existing').length;
  const imported=rows.filter(r=>r.state==='imported').length;
  $('status').textContent=`${rows.length} gefunden · ${ready} importbereit · ${existing} vorhanden · ${imported} importiert · ${rows.length-ready-existing-imported} zurückgestellt`;
  $('commit').disabled=busy||ready===0||rows.some(r=>r.coverPending||(r.state==='ready'&&r.mapperSelect&&!r.mapperSelect.value));$('files').disabled=busy;
 }
 function coverChoices(row,matches){
  row.select.replaceChildren();const none=node('option','Ohne Cover (Titel-Platzhalter)',row.select);none.value='';
  for(const m of matches){if(!m.hasCover)continue;const option=node('option',`${m.title} · Work #${m.id}`,row.select);option.value=String(m.id);}
  if(matches.length===1&&matches[0].hasCover)row.select.value=String(matches[0].id);
  row.select.onchange=async()=>{
   const generation=(row.coverGeneration||0)+1;row.coverGeneration=generation;row.coverSha256=null;
   if(row.blob)URL.revokeObjectURL(row.blob);row.image.hidden=true;row.coverPending=Boolean(row.select.value);summary();
   if(!row.select.value)return;
   try{const response=await fetch(new URL('cover?workId='+encodeURIComponent(row.select.value),api),{credentials:'same-origin',redirect:'error',cache:'no-store'});
    if(!response.ok)throw Error('Cover nicht verfügbar.');const blob=await response.blob();
    if(generation!==row.coverGeneration)return;
    const sha=response.headers.get('X-Cover-SHA256');if(!/^[a-f0-9]{64}$/.test(sha||''))throw Error('Coverprüfung fehlgeschlagen.');
    row.uiMessage='';row.coverSha256=sha;row.blob=URL.createObjectURL(blob);row.image.src=row.blob;row.image.hidden=false;
   }catch(e){if(generation===row.coverGeneration){row.select.value='';row.uiMessage=e.message+' Titel-Platzhalter wird verwendet.';$('result').textContent=row.uiMessage;}}
   finally{if(generation===row.coverGeneration){row.coverPending=false;summary();}}
  };
  row.select.onchange();
 }
 function draw(row,file){
  const card=node('details','',$('items'));card.className='import-row';row.card=card;row.filename=file.name;
  const heading=node('summary','',card);heading.className='import-summary';
  const name=node('span','',heading);name.className='import-name';node('strong',file.name,name);row.rowTitle=node('span','',name);row.rowTitle.className='import-title';
  const meta=node('span',[row.profile?.system,row.profile?.format?.toUpperCase()].filter(Boolean).join(' · '),heading);meta.className='import-meta';
  row.rowStatus=node('span','',heading);row.rowStatus.className='import-state';
  row.image=node('img','',heading);row.image.alt='Covervorschau';row.image.className='import-thumb';row.image.hidden=true;row.image.onerror=()=>{row.image.hidden=true;};
  row.rowMessage=node('span','',heading);row.rowMessage.className='import-notice';
  const body=node('div','',card);body.className='import-details';
  if(row.state!=='ready'){node('p',row.message||(row.state==='existing'?'Bereits vorhanden: '+row.title:'Zurückgestellt.'),body);return;}
  const label=node('label','Titel',body);label.className='import-title-field';row.titleInput=node('input','',label);row.titleInput.type='text';row.titleInput.value=row.title;row.titleInput.maxLength=300;
  node('p',`${row.profile.system} · ${row.profile.bytes} Bytes · SHA-256 ${row.profile.sha256}`,body).className='details';
  node('p',row.profile.system==='c64'?'VICE x64sc · C64 PAL · '+row.profile.format.toUpperCase()+' · Warp · Port 1':`${row.profile.mapper||'Mapper noch auswählen'} · Region ${row.profile.region==='auto'?'nicht bestimmt':row.profile.region}`,body).className='details';
  if(row.profile.mapperChoices){const label=node('label','Atari-Mapper ausdrücklich wählen (Dateigröße allein ist kein Nachweis)',body);row.mapperSelect=node('select','',label);node('option','Bitte passenden Mapper auswählen',row.mapperSelect).value='';for(const m of row.profile.mapperChoices)node('option',m+(['F8','F6','F4','EF'].includes(m)?' (SuperChip-RAM automatisch)':''),row.mapperSelect).value=m;row.mapperSelect.onchange=summary;}
  if(row.profile.programs)node('p',row.profile.programs.length+' T64-Programme: '+row.profile.programs.map(p=>p.name).join(' · ')+'. Auswahl vor dem Start im Player.',body).className='details';
  const coverGroup=node('div','',body);coverGroup.className='import-cover-group';
  const coverLabel=node('label','Level-Complete-Cover',coverGroup);row.select=node('select','',coverLabel);
  coverChoices(row,row.matches);if(row.warning)node('p',row.warning,body).className='warning';
  const search=node('button','Cover für diesen Titel suchen',coverGroup);search.type='button';search.onclick=async()=>{search.disabled=true;try{const r=await request('matches?title='+encodeURIComponent(row.titleInput.value));coverChoices(row,r.matches);if(r.warning)$('result').textContent=r.warning;}catch(e){row.uiMessage=e.message;updateRow(row);$('result').textContent=e.message;}finally{search.disabled=false;}};
  row.titleInput.addEventListener('input',()=>{coverChoices(row,[]);updateRow(row);});
  const ownLabel=node('label','Eigenes Cover (JPEG/PNG, maximal 2 MiB)',body),own=node('input','',ownLabel);ownLabel.className='import-own-cover';own.type='file';own.accept='.jpg,.jpeg,.png';
  own.onchange=async()=>{const file=own.files[0];if(!file)return;row.coverGeneration=(row.coverGeneration||0)+1;row.uploadToken=null;row.select.value='';row.coverPending=true;summary();try{
   const r=await upload(file);row.uploadToken=r.token;row.select.value='';row.coverSha256=null;
   if(row.blob)URL.revokeObjectURL(row.blob);row.image.src=new URL('uploaded-cover/'+r.token,api);row.image.hidden=false;
  }catch(e){row.uiMessage=e.message;updateRow(row);$('result').textContent=e.message;}finally{row.coverPending=false;summary();}};
  row.select.addEventListener('change',()=>{row.uploadToken=null;own.value='';});
  const discard=node('button','Nicht übernehmen',heading);row.discardButton=discard;discard.className='import-discard';discard.type='button';discard.onclick=async event=>{event.preventDefault();event.stopPropagation();try{await post('discard',{token:row.token});row.state='discarded';row.message=file.name+' zurückgestellt.';body.replaceChildren();node('p',row.message,body);row.image.hidden=true;summary();}catch(e){row.uiMessage=e.message;updateRow(row);$('result').textContent=e.message;}};
 }
 $('files').onchange=async()=>{
  const files=Array.from($('files').files);if(files.length>32){$('result').textContent='Bitte höchstens 32 Dateien auswählen.';return;}
  // Keep reviewed drafts until explicit discard or expiry; selecting again creates a fresh view.
  busy=true;rows=[];$('items').replaceChildren();$('result').textContent='';$('check').hidden=true;summary();const hashes=new Set();
  for(const file of files){let row;try{
   if(!/\.(bin|d64|prg|t64)$/i.test(file.name)||file.size>524288||!file.size)throw Error('Nur BIN/D64/PRG/T64 bis 512 KiB auswählen.');
   row=await request('preview',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-CSRF-Token':csrf,'X-Filename':encodeURIComponent(file.name)},body:file});
   if(row.state==='ready'&&hashes.has(row.profile.sha256)){await post('discard',{token:row.token});row={state:'existing',title:'Doppelte Auswahl im aktuellen Durchlauf'};}
   if(row.state==='ready')hashes.add(row.profile.sha256);
  }catch(e){row={state:'deferred',message:e.message};}
  rows.push(row);draw(row,file);summary();}
  busy=false;summary();
 };
 $('commit').onclick=async()=>{
  const ready=rows.filter(r=>r.state==='ready');if(!ready.length||busy)return;
  if(!window.confirm(`${ready.length} geprüfte Spiele jetzt übernehmen?`))return;
  busy=true;summary();lastToken=ready[0].token;
  try{const r=await post('commit',ready.map(x=>({token:x.token,title:x.titleInput.value,workId:x.select.value?Number(x.select.value):null,coverSha256:x.select.value?x.coverSha256:null,...(x.uploadToken?{uploadToken:x.uploadToken}:{}),...(x.mapperSelect?{mapper:x.mapperSelect.value}:{})})));
   $('result').textContent=`${r.games.length} Spiele übernommen. ${r.warnings.join(' ')} Zur Home Arcade wechseln und manuell starten.`;
   for(const x of ready)x.state='imported';summary();$('check').hidden=true;await managed();
  }catch(e){$('result').textContent=e.message+' Bei unterbrochener Verbindung zuerst Status prüfen.';$('check').hidden=false;}
  finally{busy=false;summary();}
 };
 $('check').onclick=async()=>{try{const r=await request('status/'+lastToken);$('result').textContent='Importstatus: '+r.state+(r.state==='committed'?' – Bibliothek aktualisieren.':' – bei Recovery-Konflikt keine weiteren Übernahmen versuchen.');}catch(e){$('result').textContent=e.message;}};
 async function managed(){
  if(!$('managed'))return;
  const data=await request('administration');$('managed').replaceChildren();managedRows=[];
  for(const game of data.games){const card=node('article','',$('managed'));card.className='manage-row';managedRows.push({game,card});
   const info=node('div','',card);info.className='manage-info';node('h3',game.title+' · '+game.system,info);
   const current=node('p','',info);current.className='current-cover details';
   if(game.cover){const url=new URL(game.cover,new URL('../',location.href));if(url.origin===location.origin&&url.pathname.startsWith(new URL('../covers/',location.href).pathname)){node('span','Aktuelles Cover: ',current);const link=node('a',url.pathname,current);link.href=url.href;link.target='_blank';link.rel='noopener';}else current.textContent='Coverpfad nicht verfügbar.';}else current.textContent='Kein Cover hinterlegt.';
   const controls=node('div','',card);controls.className='manage-controls';
   card.id='manage-'+game.id;
   const label=node('label','Eigenes Cover auswählen',controls),input=node('input','',label);input.type='file';input.accept='.jpg,.jpeg,.png';
   const image=node('img','',card);image.alt='Neue Covervorschau';image.hidden=true;
   const save=node('button','Cover übernehmen',controls);save.type='button';save.disabled=true;let token='';
   input.onchange=async()=>{save.disabled=true;token='';try{if(!input.files[0])return;const r=await upload(input.files[0]);token=r.token;image.src=new URL('uploaded-cover/'+token,api);image.hidden=false;save.disabled=false;}catch(e){$('result').textContent=e.message;}};
   save.onclick=async()=>{if(!token||!confirm('Cover für '+game.title+' ersetzen?'))return;save.disabled=true;try{await post('set-cover',{id:game.id,base:data.base,token});$('result').textContent='Cover für '+game.title+' aktualisiert.';await managed();}catch(e){$('result').textContent=e.message;save.disabled=false;}};
   if(!game.removable){node('p','Bestandsspiel – vor Löschen geschützt.',controls);continue;}
   const button=node('button','Spiel entfernen',controls);button.dataset.delete='true';button.type='button';button.onclick=async()=>{
    if(!window.confirm(`${game.title} (${game.system}) samt importierter ROM und Cover entfernen?`))return;
    button.disabled=true;try{await post('delete',{id:game.id,base:data.base});$('result').textContent=game.title+' entfernt.';await managed();}
    catch(e){$('result').textContent=e.message;button.disabled=false;}
   };
  }
  if(!data.games.length)node('p','Keine entfernbaren Importeinträge.', $('managed'));
  if(!navigationApplied){
   navigationApplied=true;
   const target=managedRows.find(({game})=>game.id===focusedGame);
   if(target&&$('managed-search'))$('managed-search').value=target.game.title;
   filterManaged();
   if(target){
    target.card.tabIndex=-1;target.card.classList.add('manage-target');target.card.scrollIntoView({block:'center'});
    const control=navigation.get('action')==='remove'?target.card.querySelector('[data-delete]'):target.card.querySelector('input[type=file]');
    (control||target.card).focus({preventScroll:true});
   }else if(focusedGame){$('result').textContent='Der angeforderte Spieleintrag ist nicht mehr vorhanden. Suche leeren, um alle Spiele anzuzeigen.';}
  }else filterManaged();
 }
 function filterManaged(){
  const q=($('managed-search')?.value||'').trim().toLocaleLowerCase('de');let count=0;
  for(const {game,card} of managedRows){card.hidden=!(game.title.toLocaleLowerCase('de').includes(q)&&(!focusedGame||game.id===focusedGame));if(!card.hidden)count++;}
  if($('managed-status'))$('managed-status').textContent=count+' von '+managedRows.length+' Spielen';
 }
 $('managed-search')?.addEventListener('input',()=>{focusedGame='';for(const {card} of managedRows)card.classList.remove('manage-target');filterManaged();});
 async function upload(file){if(file.size>2097152||!file.size)throw Error('Cover maximal 2 MiB.');return request('upload-cover',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-CSRF-Token':csrf},body:file});}
 if($('refresh-managed'))$('refresh-managed').onclick=()=>managed().catch(e=>{$('result').textContent=e.message;});
 request('session').then(async s=>{csrf=s.csrf;$('files').disabled=false;$('status').textContent='Dateien zur Vorschau auswählen.';await managed();}).catch(e=>{$('status').textContent=e.message;});
})();
