'use strict';
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict'),path=require('node:path');
const data=new Map(),context={window:{},localStorage:{getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/game-profiles.js'),'utf8'),context);
const {Preference,map}=context.window.ArcadeGameProfiles;let checks=0;const check=(v,m)=>{assert(v,m);checks++;};
for(const system of ['c64','vcs2600'])for(const mode of ['standard',...(system==='c64'?['y-up']:['b-up','x-up','bx-up'])])for(const up of [false,true])for(let mask=0;mask<8;mask++){
 const buttons={1:!!(mask&1),2:!!(mask&2),3:!!(mask&4)},state={up,space:buttons[1]||buttons[2],fire:false,down:true},out=map(system,mode,state,buttons);
 const extra=system==='c64'?mode==='y-up'&&buttons[3]:(mode==='b-up'||mode==='bx-up')&&buttons[1]||(mode==='x-up'||mode==='bx-up')&&buttons[2];
 check(out.up===Boolean(up||extra),'all overlapping up sources OR together');check(out.space===state.space&&out.fire===state.fire&&out.down===state.down,'other channels unchanged');check(state.up===up,'input not mutated');
}
const game={id:'test',sha256:'a'.repeat(64)},p=new Preference(game,'c64');check(p.mode==='standard','default standard');p.set('y-up');check(new Preference(game,'c64').mode==='y-up','preference survives new instance');check(new Preference({...game,id:'other'},'c64').mode==='standard','game isolation');check(new Preference({...game,sha256:'b'.repeat(64)},'c64').mode==='standard','media isolation');check(new Preference(game,'vcs2600').mode==='standard','system isolation');p.set('standard');check(!data.size,'reset removes only own setting');data.set(p.key,'invalid');check(new Preference(game,'c64').mode==='standard','bad value safe default');assert.throws(()=>p.set('b-up'));checks++;
context.localStorage.setItem=()=>{throw Error('quota');};p.set('y-up');check(p.warning.includes('nur für diese Sitzung'),'write failure disclosed');context.localStorage.getItem=()=>{throw Error('denied');};check(new Preference(game,'c64').mode==='standard','read failure safe default');
console.log(JSON.stringify({result:'PASS',checks}));
