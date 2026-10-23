/* Pinned native codecs, only in-memory engine calls. */
'use strict';
window.ArcadeSnapshots=(()=>{
 const png=bytes=>{if(!(bytes instanceof Uint8Array)||bytes.length<32||bytes.length>16*1024*1024||[137,80,78,71,13,10,26,10].some((v,i)=>bytes[i]!==v))throw Error('Kein gültiges PNG-Bild erzeugt.');return bytes;};
 const sameContext=c=>{if(!c||![1,2].includes(c.port)||typeof c.keyboard!=='boolean'||!(c.tapeEntry===null||Number.isInteger(c.tapeEntry)&&c.tapeEntry>=0))throw Error('Ungültige C64-Startzuordnung.');};
 const vice=bytes=>{if(!(bytes instanceof Uint8Array)||bytes.length<64)throw Error('Kein vollständiger VICE-Zustand.');const text=(offset,length)=>String.fromCharCode(...bytes.subarray(offset,offset+length));const size=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength).getUint32(12,true),end=16+Math.ceil(size/8)*8;if(text(0,7)!=='RASTATE'||bytes[7]!==1||text(8,4)!=='MEM '||text(16,19)!=='VICE Snapshot File\x1a'||end+8!==bytes.length||text(end,4)!=='END '||new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength).getUint32(end+4,true)!==0)throw Error('VICE-Zustandsstruktur ungültig.');return bytes;};
 function c64({game,getEngine,getContext,restoreContext}){
  return{identity:{system:'c64',gameId:game.id,romSha256:game.sha256,engine:'emulatorjs-4.2.3/vice-3.9-5e885db/g4-v1',format:'vice-native-v1'},context:getContext,
   capture(){const e=getEngine();if(!e?.started)throw Error('C64 noch nicht bereit.');return vice(e.gameManager.getState());},
   validate(record){vice(record.payload);sameContext(record.context);if(record.context.tapeEntry!==getContext().tapeEntry)throw Error('Dieses T64-Programm zuerst auswählen und den Player neu starten.');},
   async load(record,signal){this.validate(record);if(document.hidden||signal?.aborted)throw Error('Seite zuerst wieder anzeigen.');const e=getEngine(),gm=e.gameManager,fs=gm.FS,path='/game.state',read=fs.read,close=fs.close;let consumed=0,closed=false;const volume=e.muted?0:e.volume;gm.FS.writeFile(path,record.payload);gm.clearEJSResetTimer();
    // The pinned loader queues an FS task. Feed its loop under the host's
    // modal input lock, with audio muted; JS playing state remains paused.
    fs.read=function(stream,...args){const count=read.call(this,stream,...args);if(stream.path===path)consumed+=count;return count;};
    fs.close=function(stream){const isState=stream.path===path;const result=close.call(this,stream);if(isState&&consumed>=record.payload.length)closed=true;return result;};
    try{e.setVolume(0);const result=gm.functions.loadState('game.state',0);if(result!==0)throw Error('VICE-Ladeaufruf fehlgeschlagen.');gm.toggleMainLoop(1);const end=performance.now()+3000;while(!closed&&performance.now()<end){if(document.hidden||signal?.aborted)throw Error('Laden unterbrochen.');await new Promise(resolve=>setTimeout(resolve,20));}if(!closed)throw Error('VICE hat die Zustandsdatei nicht vollständig gelesen.');vice(gm.getState());restoreContext(record.context);return result;}finally{gm.toggleMainLoop(0);fs.read=read;fs.close=close;e.setVolume(volume);try{fs.unlink(path);}catch{}}
   },
   async screenshot(signal){const canvas=getEngine().canvas;if(!canvas?.width||!canvas.height||signal.aborted)throw Error('Kein C64-Bild verfügbar.');const blob=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('C64-Bildaufnahme dauerte zu lange.')),3000);canvas.toBlob(value=>{clearTimeout(timer);value?resolve(value):reject(Error('C64-Bildaufnahme fehlgeschlagen.'));},'image/png');});if(signal.aborted)throw Error('Bildaufnahme abgebrochen.');return png(new Uint8Array(await blob.arrayBuffer()));}
  };
 }
 function vcs({game,getRoom}){
  const nativeCodec=()=>{const codec=new jt.LocalStorageSaveStateMedia(getRoom());return codec;};
  const decode=payload=>{const state=nativeCodec().loadStateFile(payload);if(!state||state.v!==2||!state.ca||!state.t||!state.p||!state.r||!state.c||!['PAL','NTSC'].includes(state.vs))throw Error('Javatari-Spielstand ungültig oder inkompatibel.');return state;};
  return{identity:{system:'vcs2600',gameId:game.id,romSha256:game.sha256,engine:'javatari-e4ea03d72013973f-g4-v1',format:'javatari-jst-v2'},context:()=>({}),
   capture(){const room=getRoom();if(!room.console.powerIsOn)throw Error('VCS zuerst einschalten.');const state=room.console.saveState();state.v=2;let encoded;const codec=nativeCodec();codec.connectPeripherals({startDownloadBinary(name,data){encoded=data;}});codec.saveStateFile('Home Arcade',state);if(typeof encoded!=='string')throw Error('Javatari konnte den Zustand nicht serialisieren.');const bytes=Uint8Array.from(encoded,c=>c.charCodeAt(0));decode(bytes);return bytes;},
   validate(record){decode(record.payload);},
   load(record){decode(record.payload);const room=getRoom();if(!room.console.getSavestateSocket().loadStateFile(record.payload))throw Error('Javatari konnte den Zustand nicht laden.');if(room.console.getCartridgeSocket().inserted()?.format.name!==game.mapper)throw Error('Geladener Cartridge-Typ passt nicht.');},
   screenshot(){const url=getRoom().screen.getScreenCapture();if(typeof url!=='string'||!url.startsWith('data:image/png;base64,'))throw Error('Kein VCS-Videosignal verfügbar.');return png(Uint8Array.from(atob(url.split(',')[1]),c=>c.charCodeAt(0)));}
  };
 }
 return{c64,vcs,png,vice};
})();
