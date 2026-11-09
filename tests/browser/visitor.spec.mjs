import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import http from 'node:http';
const { chromium } = await import(process.env.DORI_PLAYWRIGHT_MODULE || 'playwright');
const root=process.env.DORI_VISITOR_DIST_ROOT || new URL('../../web/dist-visitor', import.meta.url).pathname;
const server=http.createServer(async(req,res)=>{try{const path=req.url.split('?')[0];res.setHeader('Content-Type',path.endsWith('.js')?'text/javascript':path.endsWith('.css')?'text/css':'text/html');res.end(await fs.readFile(root+(path==='/'||path==='/p'?'/index.html':path)));}catch{res.statusCode=404;res.end();}});await new Promise(resolve=>server.listen(5189,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream']});
const context=await browser.newContext({viewport:{width:390,height:844},permissions:['microphone']});
let paired=false, claimed=false, failPreparation=true, failText=true, claimCalls=0, sent=[];
let sttProvider='whisper', streamMode='automatic', activeStream=null;
let userSocket;
const destinations=[{id:'gate6',name:'e6 gate'},{id:'stair',name:'stair'}];
await context.addInitScript(() => {
 window.microphoneRequests=0;
 const original=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
 navigator.mediaDevices.getUserMedia=async (...args)=>{
   window.microphoneRequests++;
   if(!window.testSpeechEndpoint)return original(...args);
   const audio=new AudioContext(), source=audio.createOscillator(), gain=audio.createGain();
   const destination=audio.createMediaStreamDestination();
   source.frequency.value=220;gain.gain.value=0;
   source.connect(gain);gain.connect(destination);source.start();await audio.resume();
   if(window.testSpeechEndpoint==='speech'){
     gain.gain.setValueAtTime(.08,audio.currentTime+.15);
     gain.gain.setValueAtTime(0,audio.currentTime+.75);
   }
   for(const track of destination.stream.getTracks()){
     const stop=track.stop.bind(track);track.stop=()=>{stop();audio.close();};
   }
   return destination.stream;
 };
});
const wave=Buffer.alloc(32044);wave.write('RIFF');wave.writeUInt32LE(32036,4);wave.write('WAVEfmt ',8);wave.writeUInt32LE(16,16);wave.writeUInt16LE(1,20);wave.writeUInt16LE(1,22);wave.writeUInt32LE(16000,24);wave.writeUInt32LE(32000,28);wave.writeUInt16LE(2,32);wave.writeUInt16LE(16,34);wave.write('data',36);wave.writeUInt32LE(32000,40);
await context.route('**/*',async route=>{const url=new URL(route.request().url());
 if(url.pathname==='/api/session')return route.fulfill({status:paired?200:401,json:{state:'ACTIVE'}});
 if(url.pathname==='/api/pair/claim'){
   if(route.request().method()==='POST'){assert.equal(route.request().postDataJSON().nonce,'test-nonce');claimed=true;claimCalls++;}
   return route.fulfill({status:claimed?200:410,json:claimed?{expires_in:120,expires_at:Date.now()/1000+120}: {detail:'expired'}});
 }
 if(url.pathname==='/api/pair'){
   assert.ok(claimed);assert.deepEqual(route.request().postDataJSON(),{consent:true});
   if(failPreparation){failPreparation=false;return route.fulfill({status:503,json:{detail:'not ready'}})}
   paired=true;return route.fulfill({json:{expires_at:Date.now()/1000+900}})
 }
 if(url.pathname==='/api/audio/test')return route.fulfill({body:wave,contentType:'audio/wav'});
 return route.continue();
});
await context.routeWebSocket('**/ws/user',ws=>{userSocket=ws;ws.send(JSON.stringify({type:'robot_state',status:'READY',stt_provider:sttProvider,destinations}));ws.onMessage(raw=>{const msg=JSON.parse(raw);sent.push(msg);
 const streamReply=()=>{
   ws.send(JSON.stringify({type:'stt_closed',id:activeStream.id,reason:'azure_final'}));
   if(streamMode==='error')ws.send(JSON.stringify({type:'error',code:'stt_failed',message:'음성 인식 연결을 다시 시도해 주세요.'}));
   else {ws.send(JSON.stringify({type:'stt_text',data:'Azure로 인식한 질문'}));ws.send(JSON.stringify({type:'llm_text',data:'Azure 음성으로 받은 답변'}));}
   ws.send(JSON.stringify({type:'robot_state',status:'READY'}));activeStream=null;
 };
 if(msg.type==='stt_start'){
   assert.equal(msg.format,'pcm16');assert.equal(msg.sample_rate,16000);
   activeStream={id:msg.id,seq:0};
   ws.send(JSON.stringify({type:'stt_closed',id:'old-stream-id',reason:'azure_final'}));
   ws.send(JSON.stringify({type:'stt_ready',id:msg.id}));
 }
 if(msg.type==='stt_chunk'&&activeStream){
   assert.equal(msg.id,activeStream.id);assert.equal(msg.seq,activeStream.seq++);
   const pcm=Buffer.from(msg.audio_b64,'base64');assert.ok(pcm.length>0&&pcm.length<=3200);assert.equal(pcm.length%2,0);
   assert.notEqual(pcm.subarray(0,4).toString(),'RIFF');
   if(activeStream.seq>=30&&['automatic','error'].includes(streamMode))streamReply();
 }
 if(msg.type==='stt_end'&&activeStream){assert.equal(msg.seq,activeStream.seq);streamReply();}
 if(msg.type==='stt_cancel')activeStream=null;
 if(msg.type==='ptt_audio'){assert.equal(msg.sample_rate,16000);assert.ok(Buffer.from(msg.audio_b64,'base64').length>16044);ws.send(JSON.stringify({type:'stt_text',data:'캠퍼스가 궁금해요'}));ws.send(JSON.stringify({type:'llm_text',data:'DGIST 캠퍼스를 소개할게요.'}));ws.send(JSON.stringify({type:'robot_state',status:'SPEAKING'}));ws.send(JSON.stringify({type:'tts_audio',id:'test',url:'/api/audio/test'}));}
 if(msg.type==='text'){
   assert.equal(msg.text,'도서관에 대해 알려 주세요');
   if(failText){failText=false;ws.send(JSON.stringify({type:'error',code:'text_rejected',message:'잠시 후 다시 보내 주세요.'}));return;}
   ws.send(JSON.stringify({type:'user_text',data:msg.text}));
   ws.send(JSON.stringify({type:'llm_text',data:'글로 보낸 질문에 답할게요.'}));
   ws.send(JSON.stringify({type:'robot_state',status:'SPEAKING'}));
   ws.send(JSON.stringify({type:'tts_audio',id:'test',url:'/api/audio/test'}));
 }
 if(msg.type==='navigate'){
   assert.equal(msg.destination_id,'gate6');
   ws.send(JSON.stringify({type:'user_text',data:'e6 gate 안내해줘'}));
   ws.send(JSON.stringify({type:'llm_text',data:'e6 gate(으)로 안내하겠습니다.'}));
   ws.send(JSON.stringify({type:'robot_state',status:'NAVIGATING',destination:'gate6'}));
 }
 if(msg.type==='playback'&&msg.status==='ended')ws.send(JSON.stringify({type:'robot_state',status:'READY'}));
 if(msg.type==='command'){activeStream=null;ws.send(JSON.stringify({type:'robot_state',status:'READY'}));}
});});
const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
try{
 await page.clock.install();
 await page.goto('http://127.0.0.1:5189/p#test-nonce');
 await page.getByRole('heading',{name:'반가워요. 저는 DORI예요.'}).waitFor();
 assert.equal(new URL(page.url()).hash,'');
 assert.equal(await page.getByRole('button',{name:'DORI와 연결하기'}).isEnabled(),false);
 await page.getByText(/QR 확인 완료/).waitFor();
 assert.equal(claimCalls,1);assert.equal(paired,false);
 const logo=page.getByRole('img',{name:'DORI',exact:true});
 await logo.waitFor();assert.ok(await logo.evaluate(img=>img.complete&&img.naturalWidth>0));
 assert.ok((await logo.getAttribute('src')).startsWith('data:image/svg+xml'));
 await page.clock.fastForward(40000); // Reading consent spans a full QR rotation.
 await page.getByRole('checkbox').check();await page.getByRole('button',{name:'DORI와 연결하기'}).click();
 await page.getByRole('alert').filter({hasText:'음성 서비스'}).waitFor();
 assert.equal(claimCalls,1);assert.equal(paired,false);
 assert.equal(await page.getByRole('button',{name:'DORI와 연결하기'}).isEnabled(),true);
 await page.screenshot({path:'/tmp/dori-visitor-consent-logo.png'});
 await page.getByRole('button',{name:'DORI와 연결하기'}).click();
 await page.getByRole('heading',{name:'무엇이 궁금하세요?'}).waitFor();
 const composer=page.getByRole('textbox',{name:'텍스트로 이야기하기'}),sendButton=page.getByRole('button',{name:'전송',exact:true});
 assert.equal(await composer.getAttribute('maxlength'),'1000');
 assert.equal(await sendButton.isEnabled(),false);
 await composer.fill('   ');assert.equal(await sendButton.isEnabled(),false);
 await composer.fill('도서관에 대해 알려 주세요');
 await composer.dispatchEvent('compositionstart');
 await composer.dispatchEvent('keydown',{key:'Enter',code:'Enter',keyCode:229,isComposing:true});
 assert.equal(sent.filter(m=>m.type==='text').length,0);
 await composer.dispatchEvent('compositionend');
 await composer.press('Shift+Enter');assert.ok((await composer.inputValue()).includes('\n'));
 await composer.fill('도서관에 대해 알려 주세요');
 await composer.press('Enter');
 await page.getByRole('alert').filter({hasText:'잠시 후 다시 보내 주세요.'}).waitFor();
 assert.equal(await composer.inputValue(),'도서관에 대해 알려 주세요');
 await sendButton.click();
 await page.getByText('글로 보낸 질문에 답할게요.').waitFor();
 assert.equal(await composer.inputValue(),'');
 assert.equal(await page.evaluate(()=>window.microphoneRequests),0);
 await page.getByRole('heading',{name:'무엇이 궁금하세요?'}).waitFor();
 assert.equal(await page.locator('.messages').getByText('도서관에 대해 알려 주세요',{exact:true}).count(),1);
 assert.equal(sent.filter(m=>m.type==='text').length,2);
 await page.screenshot({path:'/tmp/dori-visitor-text.png'});
 const gate=page.getByRole('button',{name:'e6 gate ↗',exact:true});
 await composer.fill('작성 중인 질문');
 await gate.click();
 await page.getByRole('heading',{name:'목적지로 안내하고 있어요'}).waitFor();
 assert.equal(sent.filter(m=>m.type==='navigate').length,1);
 assert.equal(await composer.inputValue(),'작성 중인 질문');
 assert.equal(await gate.isEnabled(),false);
 assert.equal(await sendButton.isEnabled(),false);
 assert.equal(await page.getByRole('button',{name:'눌러서 말하기'}).isEnabled(),false);
 assert.equal(await page.evaluate(()=>window.microphoneRequests),0);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 await page.screenshot({path:'/tmp/dori-visitor-navigation.png'});
 await page.getByRole('button',{name:'현재 작업 취소'}).click();
 await page.getByRole('heading',{name:'무엇이 궁금하세요?'}).waitFor();
 await gate.click();
 await page.getByRole('heading',{name:'목적지로 안내하고 있어요'}).waitFor();
 userSocket.send(JSON.stringify({type:'robot_state',status:'ARRIVED'}));
 await page.getByRole('heading',{name:'목적지에 도착했어요'}).waitFor();
 userSocket.send(JSON.stringify({type:'robot_state',status:'READY'}));
 userSocket.send(JSON.stringify({type:'destinations',destinations:[]}));
 await gate.waitFor({state:'detached'});
 await composer.fill('');
 await page.getByRole('button',{name:'눌러서 말하기'}).click();await page.waitForTimeout(1400);
 await page.getByRole('button',{name:'말하기 마치기'}).click();
 await page.getByText('DGIST 캠퍼스를 소개할게요.').waitFor();
 await page.waitForTimeout(1600);
 assert.ok(sent.some(m=>m.type==='playback'&&m.status==='ended'));
 await page.getByRole('heading',{name:'무엇이 궁금하세요?'}).waitFor();
 const before=sent.filter(m=>m.type==='ptt_audio').length;
 await page.evaluate(()=>{window.testSpeechEndpoint='speech';});
 const started=Date.now();
 await page.getByRole('button',{name:'눌러서 말하기'}).click();
 await page.getByRole('heading',{name:'DORI가 답하고 있어요'}).waitFor({timeout:5000});
 assert.ok(Date.now()-started<5000,'automatic endpoint must not wait for the ten-second limit');
 assert.equal(sent.filter(m=>m.type==='ptt_audio').length,before+1);
 const recorded=Buffer.from(sent.filter(m=>m.type==='ptt_audio').at(-1).audio_b64,'base64');
 assert.ok(recorded.length<40044,'trailing silence must be trimmed');
 await page.getByRole('heading',{name:'무엇이 궁금하세요?'}).waitFor();
 await page.evaluate(()=>{window.testSpeechEndpoint='silence';});
 await page.getByRole('button',{name:'눌러서 말하기'}).click();
 await page.getByRole('alert').filter({hasText:'음성이 감지되지 않았습니다.'}).waitFor({timeout:7000});
 assert.equal(sent.filter(m=>m.type==='ptt_audio').length,before+1,'silence must not be submitted');
 sttProvider='azure';await page.reload();
 await page.getByRole('heading',{name:'무엇이 궁금하세요?'}).waitFor();
 await page.evaluate(()=>{window.testSpeechEndpoint='speech';});
 const oldUploads=sent.filter(m=>m.type==='ptt_audio').length;
 await page.getByRole('button',{name:'눌러서 말하기'}).click();
 await page.waitForTimeout(2100);
 assert.equal(await page.getByRole('button',{name:'말하기 마치기'}).isVisible(),true,'Azure capture must survive more than 800ms of silence and a stale close event');
 await page.getByText('Azure 음성으로 받은 답변').waitFor();
 assert.equal(sent.filter(m=>m.type==='ptt_audio').length,oldUploads);
 const automaticId=sent.filter(m=>m.type==='stt_start').at(-1).id;
 assert.equal(sent.some(m=>m.type==='stt_end'&&m.id===automaticId),false,'service endpoint stops capture without a second manual submission');
 const frames=sent.filter(m=>m.type==='stt_chunk').length;
 await page.waitForTimeout(350);assert.equal(sent.filter(m=>m.type==='stt_chunk').length,frames);
 streamMode='error';await page.getByRole('button',{name:'눌러서 말하기'}).click();
 await page.getByRole('alert').filter({hasText:'음성 인식 연결을 다시 시도해 주세요.'}).waitFor();
 assert.equal(await page.getByRole('button',{name:'눌러서 말하기'}).isEnabled(),true);
 streamMode='manual';await page.getByRole('button',{name:'눌러서 말하기'}).click();await page.waitForTimeout(450);
 await page.getByRole('button',{name:'말하기 마치기'}).click();
 await page.getByRole('heading',{name:'무엇이 궁금하세요?'}).waitFor();
 assert.ok(sent.some(m=>m.type==='stt_end'));
 streamMode='cancel';await page.getByRole('button',{name:'눌러서 말하기'}).click();await page.waitForTimeout(350);
 await page.getByRole('button',{name:'현재 작업 취소'}).click();
 const stoppedFrames=sent.filter(m=>m.type==='stt_chunk').length;
 await page.waitForTimeout(350);assert.equal(sent.filter(m=>m.type==='stt_chunk').length,stoppedFrames);
 assert.equal(await page.getByRole('button',{name:'눌러서 말하기'}).isEnabled(),true);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 await page.screenshot({path:'/tmp/dori-visitor-mobile.png'});
 await page.getByRole('button',{name:'현재 작업 취소'}).click();assert.ok(sent.some(m=>m.action==='STOP'));
 await page.getByRole('button',{name:'연결 종료',exact:true}).click();await page.getByRole('heading',{name:'대화를 마쳤어요.'}).waitFor();
 assert.ok(sent.some(m=>m.type==='end'));assert.deepEqual(errors,[]);
 paired=false;
 await page.goto('http://127.0.0.1:5189/p#test-nonce');
 await page.getByText(/QR 확인 완료/).waitFor();
 await page.getByRole('checkbox').check();
 await page.clock.fastForward(121000);
 await page.getByText(/이 페이지를 새로고침해도/).waitFor();
 assert.equal(await page.getByRole('button',{name:'DORI와 연결하기'}).isEnabled(),false);
 console.log('PASS: pairing, text, destination selection by ID, navigation states/cancel, map invalidation, legacy WAV, Azure PCM streaming, silence tolerance, stale stream events, service endpoint, error recovery, manual finish, playback, mobile layout');
}finally{await browser.close();server.close();}
