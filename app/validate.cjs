'use strict';
// The existing Phase-A validator is the only manifest schema implementation.
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
try {
 const source=fs.readFileSync(path.join(__dirname,'../schema/manifest.js'),'utf8');
 const ctx={URL,URLSearchParams,window:{addEventListener(){}},document:{currentScript:{src:'http://localhost/emulator/manifest.js'}}};
 vm.runInNewContext(source,ctx,{timeout:1000});
 const input=fs.readFileSync(0,'utf8');if(Buffer.byteLength(input)>2097152)throw Error('Manifest too large');
 ctx.window.Arcade.validate(JSON.parse(input));process.stdout.write('OK');
} catch(e) {process.stderr.write(e.message);process.exitCode=1;}
