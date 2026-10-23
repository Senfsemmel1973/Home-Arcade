/* Shared UI input boundary. No emulator injection. */
'use strict';
window.ArcadeInput=(()=>{
 class Router{
  constructor({action,status,neutralize=()=>{},gameInput=()=>{}}){this.action=action;this.status=status;this.neutralize=neutralize;this.gameInput=gameInput;this.context='grid';this.owner=null;this.previous={};this.blocked=true;this.direction='';this.next=0;this.active=false;this.suspended=false;}
  reset(){this.blocked=true;this.previous={};this.direction='';this.neutralize();}
  setContext(context){this.context=context;this.reset();}
  suspend(){this.suspended=true;this.reset();}
  resume(){this.suspended=false;this.reset();}
  choose(index){this.owner=index;this.active=false;this.reset();}
  poll(pads,now){
   const available=Array.from(pads||[]).filter(p=>p&&p.connected!==false);
   let pad=available.find(p=>p.index===this.owner);
   if(!pad){if(this.owner!==null){this.status('Controller getrennt – neu verbinden und Tasten loslassen.');this.active=false;this.reset();this.owner=null;}pad=available.find(p=>p.mapping==='standard');if(!pad){if(available.length)this.status('Abweichende Controllerbelegung – Diagnose erforderlich.');return;}this.owner=pad.index;this.ownerId=pad.id;this.reset();}
   if(this.ownerId!==pad.id){this.ownerId=pad.id;this.active=false;this.reset();}
   if(pad.mapping!=='standard'){this.status('Abweichende Controllerbelegung – Diagnose erforderlich.');return;}
   if(this.suspended)return;
   const buttons={};for(let i=0;i<16;i++){const value=pad.buttons[i]?.value??(pad.buttons[i]?.pressed?1:0);buttons[i]=this.previous[i]?value>=.4:value>=.6;}
   const axis=(n)=>Number.isFinite(pad.axes[n])?pad.axes[n]:0;
   const neutral=!Object.values(buttons).some(Boolean)&&[0,1,2,3].every(n=>Math.abs(axis(n))<.35);
   if(this.blocked){this.previous=buttons;if(neutral)this.blocked=false;return;}
   const edges=Object.keys(buttons).filter(i=>buttons[i]&&!this.previous[i]).map(Number);this.previous=buttons;
   const threshold=this.direction? .35:.55;
   let dir=buttons[12]?'up':buttons[13]?'down':buttons[14]?'left':buttons[15]?'right':Math.abs(axis(1))>=threshold?(axis(1)<0?'up':'down'):Math.abs(axis(0))>=threshold?(axis(0)<0?'left':'right'):'';
   if(!this.active&&(edges.length||dir||Math.abs(axis(3))>.55)){this.active=true;this.reset();this.action('activate');return;}
   if(!this.active)return;
   if(this.context==='game'){
    const commands={8:'view',9:'menu',11:'pause'};
    const command=edges.find(i=>commands[i]);
    if(command!==undefined){this.action(commands[command]);if(this.blocked)return;}
    this.gameInput(buttons,[axis(0),axis(1),axis(2),axis(3)],now);return;
   }
   if(edges.length){const names={0:'confirm',1:'back',2:'edit',3:'search',4:'filterPrevious',5:'filterNext',6:'pagePrevious',7:'pageNext',8:'view',9:'menu'};for(const edge of edges){if(names[edge]){this.action(names[edge]);break;}}if(this.blocked)return;}
   if(dir!==this.direction){this.direction=dir;this.next=now+350;if(dir)this.action(dir);}else if(dir&&now>=this.next){this.next=now+120;this.action(dir);}
   if(this.context==='grid'&&Math.abs(axis(3))>.35)this.action('scroll',axis(3));
  }
 }
 return{Router};
})();
