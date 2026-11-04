import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import http from 'node:http';
const { chromium } = await import(process.env.DORI_PLAYWRIGHT_MODULE || 'playwright');
const root=new URL('../../web/dist-visitor', import.meta.url).pathname;
const server=http.createServer(async(req,res)=>{try{const path=req.url.split('?')[0];res.setHeader('Content-Type',path.endsWith('.js')?'text/javascript':path.endsWith('.css')?'text/css':'text/html');res.end(await fs.readFile(root+(path==='/'||path==='/p'?'/index.html':path)));}catch{res.statusCode=404;res.end();}});await new Promise(resolve=>server.listen(5189,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream']});
const context=await browser.newContext({viewport:{width:390,height:844},permissions:['microphone']});
let paired=false, sent=[];
const wave=Buffer.alloc(32044);wave.write('RIFF');wave.writeUInt32LE(32036,4);wave.write('WAVEfmt ',8);wave.writeUInt32LE(16,16);wave.writeUInt16LE(1,20);wave.writeUInt16LE(1,22);wave.writeUInt32LE(16000,24);wave.writeUInt32LE(32000,28);wave.writeUInt16LE(2,32);wave.writeUInt16LE(16,34);wave.write('data',36);wave.writeUInt32LE(32000,40);
await context.route('**/*',async route=>{const url=new URL(route.request().url());
 if(url.pathname==='/api/session')return route.fulfill({status:paired?200:401,json:{state:'ACTIVE'}});
 if(url.pathname==='/api/pair'){assert.equal(route.request().postDataJSON().nonce,'test-nonce');paired=true;return route.fulfill({json:{expires_at:Date.now()/1000+900}})}
 if(url.pathname==='/api/audio/test')return route.fulfill({body:wave,contentType:'audio/wav'});
 return route.continue();
});
await context.routeWebSocket('**/ws/user',ws=>{ws.send(JSON.stringify({type:'robot_state',status:'READY'}));ws.onMessage(raw=>{const msg=JSON.parse(raw);sent.push(msg);
 if(msg.type==='ptt_audio'){assert.equal(msg.sample_rate,16000);assert.ok(Buffer.from(msg.audio_b64,'base64').length>16044);ws.send(JSON.stringify({type:'stt_text',data:'캠퍼스가 궁금해요'}));ws.send(JSON.stringify({type:'llm_text',data:'DGIST 캠퍼스를 소개할게요.'}));ws.send(JSON.stringify({type:'tts_audio',id:'test',url:'/api/audio/test'}));}
 if(msg.type==='command')ws.send(JSON.stringify({type:'robot_state',status:'READY'}));
});});
const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto('http://127.0.0.1:5189/p#test-nonce');
 await page.getByRole('heading',{name:'반가워요. 저는 DORI예요.'}).waitFor();
 assert.equal(new URL(page.url()).hash,'');
 assert.equal(await page.getByRole('button',{name:'DORI와 연결하기'}).isEnabled(),false);
 await page.getByRole('checkbox').check();await page.getByRole('button',{name:'DORI와 연결하기'}).click();
 await page.getByRole('heading',{name:'무엇이 궁금하세요?'}).waitFor();
 await page.getByRole('button',{name:'눌러서 말하기'}).click();await page.waitForTimeout(1400);
 await page.getByRole('button',{name:'말하기 마치기'}).click();
 await page.getByText('DGIST 캠퍼스를 소개할게요.').waitFor();
 await page.waitForTimeout(1600);
 assert.ok(sent.some(m=>m.type==='playback'&&m.status==='ended'));
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 await page.screenshot({path:'/tmp/dori-visitor-mobile.png'});
 await page.getByRole('button',{name:'현재 작업 취소'}).click();assert.ok(sent.some(m=>m.action==='STOP'));
 await page.getByRole('button',{name:'연결 종료',exact:true}).click();await page.getByRole('heading',{name:'대화를 마쳤어요.'}).waitFor();
 assert.ok(sent.some(m=>m.type==='end'));assert.deepEqual(errors,[]);
 console.log('PASS: mobile consent, pairing, WAV microphone, reply playback acknowledgment, STOP, end, layout');
}finally{await browser.close();server.close();}
