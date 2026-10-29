import {RobotMap} from './user-map.js';
import {Microphone,audioBase64} from './microphone.js';
const $=id=>document.getElementById(id);
const client=globalThis.crypto?.randomUUID?.()||`guest-${Date.now()}-${Math.random().toString(36).slice(2)}`;
let state=null,csrf='',instance=null,version=null,lastUpdate=0,heartbeat=false,busy=false,sequence=0,sound=true;
let history=[],placeVersion='',microphone=null,listening=false,requestingMic=false,voiceReady=false,announced=null,wasActive=false,completed=null,relativeTrip=false;
const map=new RobotMap($('map'),goal=>navigate(goal).catch(showError));
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function speak(text){if(!sound)return;if(!globalThis.speechSynthesis){$('voice-status').textContent='This browser cannot play spoken replies.';return}speechSynthesis.cancel();speechSynthesis.resume();const u=new SpeechSynthesisUtterance(text);u.lang='en-US';u.rate=1.;const v=speechSynthesis.getVoices().find(v=>v.lang==='en-US');if(v)u.voice=v;u.onerror=e=>{if(!['canceled','interrupted'].includes(e.error))$('voice-status').textContent='Spoken reply could not play. Check this site’s sound permission or use another browser.'};speechSynthesis.speak(u)}
function message(text,role='robot'){const item=document.createElement('div');item.className='message '+role;item.textContent=text;$('messages').append(item);while($('messages').children.length>9)$('messages').firstChild.remove();$('messages').scrollTop=$('messages').scrollHeight;}
function showError(error){if(error.name==='AbortError')return;message(error.message||'Please try again.','error');$('voice-status').textContent='You can try another request.';}
async function post(path,data,timeout=4000){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Dori-Control':csrf},body:JSON.stringify(data),signal:AbortSignal.timeout(timeout)});const body=await response.json();if(!response.ok)throw Error(body.error||'Request failed.');return body;}
function command(action,extra={}){return post('api/command',{action,client,...extra})}
function assertCurrent(token){if(token!==sequence)throw new DOMException('Request cancelled','AbortError')}
async function waitFor(predicate,token,timeout=6000){const end=Date.now()+timeout;while(Date.now()<end){assertCurrent(token);if(Date.now()-lastUpdate>2000)throw Error('The robot connection was interrupted.');if(predicate())return;await delay(100)}throw Error('Dori did not accept the request. Please try again.')}
async function navigate(goal,token=null){
  if(goal.kind==='relative'&&(state?.values?.active||JSON.parse(state?.values?.retry||'{}').state==='waiting'))throw Error('Stop the current trip before requesting a relative move.');
  if(token===null){if(busy)return;token=++sequence}assertCurrent(token);busy=true;completed=null;updateButtons();
  try{
    if(!state||Date.now()-lastUpdate>2000)throw Error('The robot is not connected.');
    if(state.control_owner&&state.control_owner!==client)throw Error('Another browser is controlling Dori.');
    if(state.readiness?.length)throw Error('Dori is not ready to move. Please ask the operator to check its position.');
    if(!state.values?.enabled||state.control_owner!==client){await command('enable');await waitFor(()=>state.control_owner===client&&state.values?.enabled,token)}
    assertCurrent(token);map.selected=goal.id||null;
    const relative=goal.kind==='relative';
    const result=relative?await command('relative_goal',{distance_m:goal.distance_m}):await command('named_goal',{id:goal.id});assertCurrent(token);
    await waitFor(()=>{if(state.goal_revision<=result.goal_revision)return false;const status=state.values?.goal_status||'';if(/^(rejected|send_error|server_unavailable)/.test(status)||status.endsWith('status=6'))throw Error('Dori could not start this trip.');return state.values?.active&&status.startsWith('accepted:')},token);
    announced=goal.name;relativeTrip=relative;wasActive=true;const reply=relative?result.reply:'I will move to '+goal.name+'.';message(reply);speak(reply);history.push({role:'model',text:reply});
  }catch(error){if(token===sequence&&state?.control_owner===client)await command('stop').catch(()=>{});throw error}
  finally{if(token===sequence){busy=false;updateButtons()}}
}
async function stop(){sequence++;busy=false;announced=null;wasActive=false;microphone?.cancel();globalThis.speechSynthesis?.cancel();updateButtons();try{await command('stop');message('Stopped.');$('voice-status').textContent='Speak in English, or type below.';speak('Stopped.')}catch(error){showError(error)}}
async function ask(text){
  text=text.trim();if(!text||busy)return;
  if(/^(stop|stop please|please stop|cancel|cancel navigation|emergency stop)[.!]?$/i.test(text)){message(text,'user');await stop();return}
  const token=++sequence;busy=true;updateButtons();message(text,'user');$('voice-status').textContent='Thinking…';
  try{
    const result=await post('api/chat',{text,history},20000);assertCurrent(token);history.push({role:'user',text});history=history.slice(-6);
    if(result.action==='navigate'){const goal=state?.destinations?.find(g=>g.id===result.destination_id);if(!goal)throw Error('That destination has changed. Please choose it again.');await navigate(goal,token)}
    else if(result.action==='move_relative'){await navigate({kind:'relative',distance_m:result.distance_m,name:`${result.distance_m} m forward`},token)}
    else if(result.action==='stop'){await stop()}
    else{message(result.reply);speak(result.reply);history.push({role:'model',text:result.reply})}
    if(token===sequence)$('voice-status').textContent='Speak in English, or type below.';
  }catch(error){showError(error)}finally{if(token===sequence){busy=false;updateButtons()}}
}
function updateButtons(){const online=Date.now()-lastUpdate<2000;$('send').disabled=busy||listening||requestingMic||!online;$('listen').disabled=busy||requestingMic||!online||!microphone||!voiceReady;for(const b of $('places').querySelectorAll('button'))b.disabled=busy||!online;}
function renderPlaces(){const goals=state.destinations||[],key=JSON.stringify(goals)+String(map.selected);if(key===placeVersion)return;placeVersion=key;$('places').replaceChildren();$('place-count').textContent=`${goals.length} ${goals.length===1?'place':'places'}`;
  if(!goals.length){const p=document.createElement('p');p.className='empty-places';p.textContent='Your operator can add destinations on the administrator page.';$('places').append(p);return}
  goals.forEach((goal,i)=>{const b=document.createElement('button');b.className='place'+(map.selected===goal.id?' selected':'');b.title='Go to '+goal.name;const number=document.createElement('span');number.className='place-number';number.textContent=i+1;const name=document.createElement('span');name.className='place-name';name.textContent=goal.name;const arrow=document.createElement('span');arrow.className='place-arrow';arrow.textContent='↗';b.append(number,name,arrow);b.onclick=()=>navigate(goal).catch(showError);$('places').append(b)})}
function renderStatus(){const v=state.values||{},ready=!state.readiness?.length;let feedback={},retry={};try{feedback=JSON.parse(v.feedback||'{}');retry=JSON.parse(v.retry||'{}')}catch{}
  const waiting=v.enabled&&retry.state==='waiting';
  $('trip-dot').className=ready?'live':'';
  $('trip-label').textContent=v.active?'ON THE WAY':'ROBOT STATUS';
  $('trip-title').textContent=v.active?`Moving${state.goal_name?(state.goal_kind==='relative'?' ':' to ')+state.goal_name:''}`:completed?'You have arrived':ready?'Where to?':'Getting ready';
  $('trip-detail').textContent=v.active?(Number.isFinite(feedback.distance_remaining)?`${feedback.distance_remaining.toFixed(1)} m remaining · Follow the route on the map.`:'Following the route on the map.'):completed?`Dori is at ${completed}.`:ready?'Choose a place or ask Dori.':'Waiting for the robot to be ready.';
  if(v.active&&v.drive==='rear_obstacle')$('trip-detail').textContent='Paused. There is an obstacle behind Dori.';
  if(v.active&&v.drive==='stale_odom')$('trip-detail').textContent='Paused while Dori checks its position.';
  if(waiting){$('trip-label').textContent='WAITING TO RETRY';$('trip-title').textContent=`Waiting${state.goal_name?' to reach '+state.goal_name:''}`;$('trip-detail').textContent=`Checking the route again in ${Math.ceil(retry.remaining_seconds||0)} s · Retry ${retry.attempt}/${retry.max_attempts}. You can stop at any time.`;}
  if(announced&&wasActive&&!v.active&&!waiting){const status=v.goal_status||'';
    if(status.endsWith('status=4')){completed=announced;const reply=relativeTrip?'I have finished the move.':'I have arrived at '+announced+'.';message(reply);speak(reply);command('stop').catch(()=>{});announced=null;wasActive=false}
    else if(status.endsWith('status=6')){message('I could not reach that destination after retrying. Please choose another place.','error');command('stop').catch(()=>{});announced=null;wasActive=false}
    else if(!v.enabled||status.endsWith('status=5')){announced=null;wasActive=false}
  }
  $('position').textContent=state.robot?`Dori · ${state.robot[0].toFixed(1)}, ${state.robot[1].toFixed(1)} m`:'Position unavailable';
}
async function update(){try{
  const response=await fetch('api/state',{signal:AbortSignal.timeout(2000)});if(!response.ok)throw Error();const next=await response.json();if(next.server_age>2)throw Error();
  if(instance!==next.instance_id){if(instance!==null){sequence++;busy=false;announced=null;wasActive=false;history=[]}map.reset();placeVersion='';instance=next.instance_id}
  if(version&&version!==next.ui_version){location.reload();return}version=next.ui_version;state=next;csrf=state.csrf;lastUpdate=Date.now();$('connection').textContent='Connected';$('connection-dot').className='live';map.update(state);renderPlaces();renderStatus();
  if(state.control_owner===client&&!heartbeat){heartbeat=true;command('heartbeat').catch(()=>{}).finally(()=>heartbeat=false)}
}catch{$('connection').textContent='Disconnected';$('connection-dot').className='';$('trip-title').textContent='Connection lost';$('trip-detail').textContent='Waiting to reconnect to Dori.';if(state){state.server_age=10;map.update(state)}}finally{updateButtons();setTimeout(update,250)}}
async function processRecording(blob){
  const token=sequence;busy=true;updateButtons();$('voice-status').textContent='Transcribing…';
  try{if(blob.size<100)throw Error('The recording was empty. Please try again.');
    const result=await post('api/transcribe',{audio:await audioBase64(blob),mime_type:blob.type},25000);assertCurrent(token);
    if(!result.transcript)throw Error('I could not hear any clear speech. Please try again.');
    busy=false;await ask(result.transcript);
  }catch(error){showError(error)}finally{if(token===sequence){busy=false;updateButtons()}}
}
function microphoneError(error){
  const text=error.name==='NotAllowedError'?'Microphone permission was denied. Allow the microphone for this site in your browser settings.':error.name==='NotFoundError'?'No microphone was found. Connect one and try again.':error.name==='NotReadableError'?'The microphone is in use by another app. Close it and try again.':error.message||'Could not start the microphone.';
  $('voice-status').textContent=text;message(text,'error');
}
function setupSpeech(session){voiceReady=session.voice_ready;
  if(!window.isSecureContext){$('voice-status').textContent='Microphone access requires HTTPS. Text requests still work here.';if(session.voice_url){$('secure-link').href=session.voice_url;$('secure-link').hidden=false}return}
  if(!Microphone.supported()){$('voice-status').textContent='This browser cannot record audio. You can type your request below.';return}
  microphone=new Microphone(processRecording,phase=>{listening=phase==='recording';requestingMic=phase==='requesting';$('listen').classList.toggle('listening',listening);$('listen').querySelector('span').textContent=listening?'Finish recording':requestingMic?'Allow microphone…':'Speak to Dori';
    if(listening)$('voice-status').textContent='Listening. Tap Finish recording when done. Up to 15 seconds.';
    else if(requestingMic)$('voice-status').textContent='Allow microphone access in your browser.';
    updateButtons();},microphoneError);
  if(!voiceReady)$('voice-status').textContent='Voice navigation is not configured yet.';
}
$('listen').onclick=()=>{if(listening){microphone.finish();return}globalThis.speechSynthesis?.cancel();microphone.start()};
window.addEventListener('pagehide',()=>microphone?.cancel());
$('stop').onclick=stop;$('fit').onclick=()=>{map.fit();$('follow').classList.remove('active')};$('follow').onclick=()=>{map.follow=!map.follow;$('follow').classList.toggle('active',map.follow);map.draw()};
$('sound').onclick=()=>{sound=!sound;$('sound').textContent=sound?'Sound on':'Sound off';$('sound').setAttribute('aria-pressed',String(sound));if(!sound)globalThis.speechSynthesis?.cancel()};
$('chat-form').onsubmit=e=>{e.preventDefault();const text=$('message').value;$('message').value='';ask(text)};
document.addEventListener('keydown',e=>{if(e.key==='Escape')stop()});
fetch('api/session').then(r=>r.json()).then(session=>{csrf=session.csrf;setupSpeech(session);update()}).catch(()=>{$('connection').textContent='Disconnected';update()});
