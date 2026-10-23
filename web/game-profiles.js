/* G5: optional, origin-local input preferences; never part of native snapshots. */
'use strict';
window.ArcadeGameProfiles=(()=>{
 const allowed=system=>system==='c64'?['standard','y-up']:['standard','b-up','x-up','bx-up'];
 function map(system,mode,state,buttons){
  const extra=system==='c64'?mode==='y-up'&&buttons[3]:((mode==='b-up'||mode==='bx-up')&&buttons[1])||((mode==='x-up'||mode==='bx-up')&&buttons[2]);
  return {...state,up:Boolean(state.up||extra)};
 }
 class Preference{
  constructor(game,system){this.system=system;this.mode='standard';this.warning='';this.key='home-arcade-input-profile-v1:'+JSON.stringify([system,game.id,game.sha256]);try{const value=localStorage.getItem(this.key);if(allowed(system).includes(value))this.mode=value;}catch{this.warning='Profilablage nicht verfügbar; Änderungen gelten nur für diese Sitzung.';}}
  set(mode){if(!allowed(this.system).includes(mode))throw Error('Ungültiges Spielprofil.');this.mode=mode;try{if(mode==='standard')localStorage.removeItem(this.key);else localStorage.setItem(this.key,mode);this.warning='';}catch{this.warning='Profil nicht dauerhaft gespeichert; gilt nur für diese Sitzung.';}}
  apply(state,buttons){return map(this.system,this.mode,state,buttons);}
  label(){return ({standard:'Standard','y-up':'Y zusätzlich Hoch','b-up':'B zusätzlich Hoch','x-up':'X zusätzlich Hoch','bx-up':'B/X zusätzlich Hoch'})[this.mode];}
 }
 return {Preference,map,allowed};
})();
