'use strict';
// Presentation only; central validator and emulator start mechanisms unchanged.
(()=>{const describe=Arcade.describe;Arcade.describe=function(g){describe(g);if(g.system==='vcs2600'&&!['hero','pitfall'].includes(g.id)){const subtitle=document.getElementById('game-subtitle');if(subtitle)subtitle.textContent='Atari 2600';}};})();

// Optional navigation is independent of ROM loading and engine initialization.
(()=>{const link=document.getElementById('level-complete');if(!link)return;
 fetch(new URL('import-api/library-actions?view=links',Arcade.base),{credentials:'omit',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(3000)})
 .then(r=>{if(!r.ok)throw Error('Link unavailable');return r.json();})
 .then(data=>{if(typeof data.levelComplete!=='string')return;const url=new URL(data.levelComplete);if(!['http:','https:'].includes(url.protocol)||url.username||url.password)return;link.href=url.href;link.hidden=false;}).catch(()=>{});
})();
