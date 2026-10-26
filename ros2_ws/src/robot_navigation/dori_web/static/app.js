'use strict';
const $ = id => document.getElementById(id);
const canvas = $('map'), ctx = canvas.getContext('2d');
const client = crypto.randomUUID ? crypto.randomUUID() : `browser-${Date.now()}-${Math.random().toString(36).slice(2)}`;
let editingDestination=null, destinationVersion='';
let uiVersion = null, previousFrame = null, serverInstance = null;
let csrf = '', state = null, lastUpdate = 0, tool = 'pan', selected = null, dragging = null;
let mapImage = null, imageVersion = -1, loadingVersion = -1, fitted = false, follow = false;
let view = {x:0, y:0, scale:55}, size = {w:0,h:0}, heartbeat = false;
const modes = {monitor:'상태 보기', mapping:'매핑', navigation:'자율주행'};
const reasons = {waiting_for_reverse_stop:"후진 전 정지 확인",rear_obstacle:"후진 정지 · 뒤쪽 장애물",rear_scan_unknown:"후진 정지 · 뒤쪽 LiDAR 확인 불가",reverse_without_recovery:"후진 복구 대기",waiting_for_straight_reverse:"후진 전 회전 정지 대기",disabled:'주행 비활성', no_active_goal:'목표 대기', driving:'주행 중', stale_odom:'위치 추정 지연', stale_scan:'라이다 수신 지연', stale_nav_command:'Nav2 명령 대기', waiting_for_tf:'좌표 변환 대기', stale_hardware_feedback:'CAN 피드백 지연', hardware_inhibited:'하드웨어 보호 정지', waiting_for_hardware_auto_mode:'AUTO 모드 전환 대기', hardware_scale_unverified:'구동 설정 확인 대기'};
const qualities = {tracking:'정상', scan_timeout:'스캔 미수신', waiting_for_laser_tf:'장착 TF 대기', too_few_points:'유효점 부족', insufficient_overlap:'겹침 부족', degenerate_geometry:'환경 특징 부족', poor_fit:'정합 불량', not_converged:'정합 미수렴', implausible_motion:'이동 추정 이상', tracking_lost_restart_required:'추적 소실 · 초기 위치를 다시 적용하세요',relocalizing:'지도 재정합 중'};
function notice(text, error=false) { $('notice').textContent=text; $('notice').classList.toggle('error',error); }
async function command(action, extra={}) {
  if (!csrf) throw new Error('연결을 기다리세요');
  const response = await fetch('/api/command', {method:'POST', headers:{'Content-Type':'application/json','X-Dori-Control':csrf}, body:JSON.stringify({action,client,...extra}), signal:AbortSignal.timeout(3000)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '명령 실패');
  if (result.message) notice(result.message);
  return result;
}
function perform(action, extra={}) { return command(action,extra).catch(error=>notice(error.message,true)); }
function setTool(value) {
  tool=value; selected=null; dragging=null;
  document.querySelectorAll('[data-tool]').forEach(b=>b.classList.toggle('selected',b.dataset.tool===tool));
  canvas.classList.toggle('selecting',tool!=='pan');
  $('selection-title').textContent=tool==='initial_pose'?'대략적인 초기 위치':tool==='goal'?'목표 지정':'위치 선택';
  $('send-pose').textContent=tool==='initial_pose'?'초기 위치 적용':tool==='goal'?'이 목표로 이동':'위치를 선택하세요';
  updateButtons(); draw();
}
function updateButtons() {
  const online=Date.now()-lastUpdate<1500, nav=online&&state?.mode==='navigation';
  document.querySelectorAll('[data-tool]').forEach(b=>b.disabled=b.dataset.tool!=='pan'&&!nav);
  $('enable').disabled=!nav||!!state?.readiness?.length||!!state?.values?.enabled;
  $('enable').textContent=state?.values?.enabled?'주행 활성화됨':'주행 활성화';
  $('send-pose').disabled=!nav||tool==='pan'||(tool==='goal'&&(!state?.values?.enabled||state?.control_owner!==client));
}
function world(point) { return [view.x+(point[0]-size.w/2)/view.scale,view.y-(point[1]-size.h/2)/view.scale]; }
function screen(point) { return [size.w/2+(point[0]-view.x)*view.scale,size.h/2-(point[1]-view.y)*view.scale]; }
function local(event) { const r=canvas.getBoundingClientRect(); return [event.clientX-r.left,event.clientY-r.top]; }
function fit() {
  if(state?.map){ const m=state.map, [x,y,a]=m.origin, w=m.width*m.resolution, h=m.height*m.resolution;
    view.x=x+Math.cos(a)*w/2-Math.sin(a)*h/2; view.y=y+Math.sin(a)*w/2+Math.cos(a)*h/2;
    const bw=Math.abs(w*Math.cos(a))+Math.abs(h*Math.sin(a)),bh=Math.abs(w*Math.sin(a))+Math.abs(h*Math.cos(a));
    view.scale=Math.max(2,Math.min(size.w/(bw+1),size.h/(bh+1))); fitted=true;
  } else if(state?.robot) {view.x=state.robot[0];view.y=state.robot[1];}
  follow=false; $('follow').classList.remove('selected'); draw();
}
function resize(){ const r=canvas.getBoundingClientRect(),d=window.devicePixelRatio||1;size={w:r.width,h:r.height};canvas.width=Math.round(r.width*d);canvas.height=Math.round(r.height*d);draw(); }
function line(points,color,width=2) { if(!points?.length)return;ctx.beginPath();points.forEach((p,i)=>{const [x,y]=screen(p);i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke(); }
function arrow(p,color,fill=true) { const [x,y]=screen(p);ctx.save();ctx.translate(x,y);ctx.rotate(-p[2]);ctx.beginPath();ctx.moveTo(14,0);ctx.lineTo(-10,-8);ctx.lineTo(-6,0);ctx.lineTo(-10,8);ctx.closePath();ctx.fillStyle=color;ctx.strokeStyle=color;ctx.lineWidth=2;fill?ctx.fill():ctx.stroke();ctx.restore(); }
function draw(){ if(!size.w)return; const d=window.devicePixelRatio||1;ctx.setTransform(d,0,0,d,0,0);ctx.clearRect(0,0,size.w,size.h);
  if(follow&&state?.robot){view.x=state.robot[0];view.y=state.robot[1];}
  if(state?.map&&mapImage&&imageVersion===state.map.version){const m=state.map,[x,y,a]=m.origin,[sx,sy]=screen([x,y]);ctx.save();ctx.translate(sx,sy);ctx.scale(view.scale,-view.scale);ctx.rotate(a);ctx.translate(0,m.height*m.resolution);ctx.scale(m.resolution,-m.resolution);ctx.imageSmoothingEnabled=false;ctx.drawImage(mapImage,0,0);ctx.restore();}
  if($('show-grid').checked){const spacing=view.scale>25?1:5,lo=world([0,size.h]),hi=world([size.w,0]);ctx.strokeStyle='#71818a16';ctx.lineWidth=1;ctx.beginPath();for(let x=Math.ceil(lo[0]/spacing)*spacing;x<hi[0];x+=spacing){let px=screen([x,0])[0];ctx.moveTo(px,0);ctx.lineTo(px,size.h)}for(let y=Math.ceil(lo[1]/spacing)*spacing;y<hi[1];y+=spacing){let py=screen([0,y])[1];ctx.moveTo(0,py);ctx.lineTo(size.w,py)}ctx.stroke();}
  const fresh=Date.now()-lastUpdate<1500;
  if(fresh&&$('show-path').checked){line(state?.paths?.plan,'#4a8667');line(state?.paths?.local_plan,'#8c9e50',1.5)}
  if(fresh&&$('show-scan').checked){ctx.fillStyle='#c47145';for(const p of state?.scan||[]){const [x,y]=screen(p);ctx.fillRect(x-1,y-1,2,2)}}
  if(state?.robot){ctx.globalAlpha=fresh&&state?.sensors?.odom?.age<.5?1:.3;const [x,y]=screen(state.robot);ctx.beginPath();ctx.arc(x,y,Math.max(5,.3*view.scale),0,2*Math.PI);ctx.fillStyle='#2c688b14';ctx.strokeStyle='#2c688b70';ctx.fill();ctx.stroke();arrow(state.robot,'#205d83');ctx.globalAlpha=1;}
  for(const g of state?.destinations||[]){const [gx,gy]=screen([g.x,g.y]);ctx.fillStyle='#5b7180';ctx.beginPath();ctx.arc(gx,gy,4,0,2*Math.PI);ctx.fill();ctx.font='11px system-ui';ctx.fillText(g.name,gx+7,gy-7);}
  if(state?.goal)arrow(state.goal,'#547960',false);if(selected)arrow(selected,tool==='initial_pose'?'#8b6b3e':'#355f87');
  const metres=view.scale>50?1:view.scale>10?5:10;$('scale').style.width=`${metres*view.scale}px`;$('scale').textContent=`${metres} m`;
}
function updateSelection(p){selected=p;['x','y','yaw'].forEach((k,i)=>$('input-'+k).value=(i===2?p[i]*180/Math.PI:p[i]).toFixed(i===2?1:2));draw()}
canvas.addEventListener('pointerdown',e=>{if(e.button!==0)return;const p=local(e);dragging={start:p,view:{...view},world:world(p)};canvas.setPointerCapture(e.pointerId);if(tool!=='pan')updateSelection([...dragging.world,0]);});
canvas.addEventListener('pointermove',e=>{const p=local(e),w=world(p);$('pointer').textContent=`x ${w[0].toFixed(2)}  y ${w[1].toFixed(2)}`;if(!dragging)return;if(tool==='pan'){follow=false;$('follow').classList.remove('selected');view.x=dragging.view.x-(p[0]-dragging.start[0])/view.scale;view.y=dragging.view.y+(p[1]-dragging.start[1])/view.scale;draw()}else updateSelection([...dragging.world,Math.atan2(w[1]-dragging.world[1],w[0]-dragging.world[0])]);});
canvas.addEventListener('pointerup',()=>{dragging=null});canvas.addEventListener('pointercancel',()=>{dragging=null});
canvas.addEventListener('wheel',e=>{e.preventDefault();const p=local(e),before=world(p);view.scale=Math.max(2,Math.min(600,view.scale*Math.exp(-e.deltaY*.001)));const after=world(p);view.x+=before[0]-after[0];view.y+=before[1]-after[1];follow=false;draw()},{passive:false});
document.querySelectorAll('[data-tool]').forEach(b=>b.addEventListener('click',()=>setTool(b.dataset.tool)));
$('fit').onclick=fit;$('follow').onclick=()=>{follow=!follow;$('follow').classList.toggle('selected',follow);draw()};
$('stop').onclick=()=>perform('stop');$('enable').onclick=()=>perform('enable');
document.addEventListener('keydown',e=>{if(e.key==='Escape')perform('stop')});
$('pose-form').onsubmit=e=>{e.preventDefault();if(tool==='pan')return;perform(tool,{x:Number($('input-x').value),y:Number($('input-y').value),yaw:Number($('input-yaw').value)*Math.PI/180});};
for(const k of ['x','y','yaw'])$('input-'+k).addEventListener('input',()=>{const p=[Number($('input-x').value),Number($('input-y').value),Number($('input-yaw').value)*Math.PI/180];if(p.every(Number.isFinite)){selected=p;draw()}});
for(const k of ['scan','path','grid'])$('show-'+k).onchange=draw;
function resetView(){mapImage=null;imageVersion=-1;loadingVersion=-1;fitted=false;previousFrame=null;selected=null;dragging=null;follow=false;view={x:0,y:0,scale:55};setTool('pan');draw();}
$('reset-view').onclick=()=>{resetView();notice('화면을 초기화했습니다. 최신 데이터를 불러옵니다.');};
function formatVelocity(v,normalized=false){return v?`${v[0].toFixed(2)}${normalized?'':' m/s'} / ${v[1].toFixed(2)}${normalized?'':' rad/s'}`:'—'}
async function update(){try{
  const response=await fetch('/api/state',{signal:AbortSignal.timeout(2000)});if(!response.ok)throw Error('HTTP '+response.status);
  state=await response.json();if(state.server_age>2)throw Error('ROS 상태 갱신 중단');csrf=state.csrf||csrf;if(serverInstance!==state.instance_id){resetView();serverInstance=state.instance_id;} if(uiVersion&&uiVersion!==state.ui_version){location.reload();return;}uiVersion=state.ui_version;lastUpdate=Date.now();$('connection').textContent='연결됨';$('connection-dot').className='ok';$('mode').textContent=modes[state.mode];
  if(previousFrame!==state.frame){view={x:0,y:0,scale:55};fitted=false;previousFrame=state.frame;if(state.map)fit();}
  $('empty').style.display=state.map||state.robot||state.scan?.length?'none':'flex';$('frame').textContent=`${state.frame==='laser'?'원시 라이다 · 위치 추정 대기 · ':''}좌표계 ${state.frame||'odom'} · 단위 m`;
  ['x','y','yaw'].forEach((k,i)=>$('pose-'+k).textContent=state.robot?(state.robot[i]*(i===2?180/Math.PI:1)).toFixed(i===2?1:2):'—');
  const v=state.values||{};$('robot-state').textContent=['대기','주행','변형','일시정지','비상정지','오류'][v.action]||'미수신';
  $('state-detail').textContent=`${v.control===1?'AUTO':v.control===0?'MANUAL':'제어 미연결'}${Number.isFinite(v.pitch_deg)?' · 몸체 pitch '+v.pitch_deg.toFixed(1)+'°':''}`;
  const list=$('sensor-list');list.replaceChildren();for(const [key,label,limit] of [['scan','LiDAR',.8],['odom','Odometry',.5],['imu','IMU',.5]]){const sensor=state.sensors?.[key],age=sensor?.age,row=document.createElement('div');row.className='sensor';const l=document.createElement('span');l.className='label';const dot=document.createElement('i');dot.className=age!==null&&age>=-.05&&age<limit?'ok':'';l.append(dot,document.createTextNode(label));const reading=document.createElement('span');reading.className='reading';reading.textContent=age===null||age===undefined?'미수신':`${sensor.hz.toFixed(1)} Hz / ${Math.max(0,age*1000).toFixed(0)} ms`;if(age>limit)reading.classList.add('warn');row.append(l,reading);list.append(row)}
  let quality={};try{quality=JSON.parse(v.odometry||'{}')}catch{}$('odom-quality').textContent=qualities[quality.state]||quality.state||'미수신';$('quality-detail').textContent=quality.rmse_m!==undefined?`잔차 ${(quality.rmse_m*1000).toFixed(1)} mm · 겹침 ${(quality.overlap*100).toFixed(0)}% · ${quality.processing_ms.toFixed(0)} ms`:state.scan_error||'—';
  $('manual-velocity').textContent=formatVelocity(state.velocities?.manual_velocity,true);
  $('can-state').textContent=state.hardware?.fresh?'수신 정상':'피드백 없음 / 드라이버 확인';
  const joints=state.joints||{}, wheel=name=>state.hardware?.fresh&&joints[name]?.age<.5&&Number.isFinite(joints[name]?.velocity)?joints[name].velocity.toFixed(2):'—';
  const control=state.wheel_control||{}, pair=field=>['left_wheel_joint','right_wheel_joint'].map(name=>Number.isFinite(control[name]?.[field])?control[name][field].toFixed(2):'—').join(' / ');
  $('wheel-target').textContent=pair('target_velocity');$('wheel-torque').textContent=pair('compensation_torque');
  $('wheel-velocity').textContent=`${wheel('left_wheel_joint')} / ${wheel('right_wheel_joint')}`;
  $('gimbal-target').textContent=Number.isFinite(v.gimbal_target)?v.gimbal_target.toFixed(1)+'°':'—';
  $('gimbal-position').textContent=joints.motor_5_joint?.age<.5?(joints.motor_5_joint.position*180/Math.PI).toFixed(1)+'°':'—';
  try{const m=JSON.parse(v.motion||'null'),labels={stop:'정지',start:'출발',track:'추종',brake:'감속'};$('motion-phase').textContent=m?`${m.recovering?'후진 복구 · ':''}${labels[m.linear.phase]} / ${labels[m.angular.phase]}`:'—';$('motion-fit').textContent=m?`직진 ${m.linear.response_gain.toFixed(2)} · 회전 ${m.angular.response_gain.toFixed(2)} (${m.linear.learned_samples+m.angular.learned_samples} 표본)`:'—'}catch{}
  $('localization-status').textContent=state.localization?.state==='ready'?'마지막 수동 정합 · '+state.localization.message:state.localization?.message||'';
  const alignment=state.auto_alignment, check=alignment?.last_check;
  $('auto-alignment-status').textContent=alignment?.enabled?alignment.message+(check?` · 최근 점검 일치율 ${Math.round(check.matched_fraction*100)}%`:''):'자동 지도 정합 꺼짐';
  $('nav-state').textContent=v.enabled?'활성':'비활성';$('nav-velocity').textContent=formatVelocity(state.velocities?.nav_velocity);$('drive-velocity').textContent=formatVelocity(state.velocities?.drive_velocity,true);$('goal-status').textContent=v.goal_status||'—';$('drive-status').textContent=reasons[v.drive]||v.drive||'주행 브리지 미수신';$('readiness').textContent=state.mode==='navigation'?(state.readiness||[]).join(' · '):'목표 지정은 주행 세션에서 사용할 수 있습니다.';
  try{const retry=JSON.parse(v.retry||'{}');if(v.enabled&&retry.state==='waiting')$('goal-status').textContent=`경로 재시도 ${retry.attempt}/${retry.max_attempts} · ${Math.ceil(retry.remaining_seconds||0)}초 후`;}catch{}
  if(state.map&&state.map.version!==imageVersion&&state.map.version!==loadingVersion){const version=state.map.version;loadingVersion=version;const image=new Image();image.onload=()=>{if(state.map?.version===version){mapImage=image;imageVersion=version;if(!fitted)fit();draw()}loadingVersion=-1};image.onerror=()=>loadingVersion=-1;image.src=`/api/map.png?v=${version}`;}
  if(state.control_owner===client&&!heartbeat){heartbeat=true;command('heartbeat').catch(e=>notice(e.message,true)).finally(()=>heartbeat=false)}
  renderDestinations();updateButtons();draw();
}catch(error){$('connection').textContent='연결 끊김';$('connection-dot').className='';updateButtons();draw();}finally{setTimeout(update,200)}}
new ResizeObserver(resize).observe(canvas);
fetch('/api/session').then(r=>r.json()).then(s=>{csrf=s.csrf;notice('지도: 드래그 이동 · 휠 확대/축소');update()}).catch(e=>{notice('서버 연결 실패: '+e.message,true);update()});

function renderDestinations(){
  const items=state?.destinations||[],version=JSON.stringify(items);if(version===destinationVersion)return;destinationVersion=version;
  const list=$('destinations');list.replaceChildren();
  for(const g of items){const row=document.createElement('div');row.className='destination-row';const select=document.createElement('button');select.textContent=g.name;select.onclick=()=>{setTool('goal');updateSelection([g.x,g.y,g.yaw]);editingDestination=g.id;$('destination-name').value=g.name;$('save-destination').textContent='목표 수정 저장';$('pose-form').scrollIntoView({block:'nearest'});};
    const remove=document.createElement('button');remove.textContent='삭제';remove.onclick=()=>{perform('delete_destination',{id:g.id}).then(()=>{if(editingDestination===g.id)clearDestination()})};row.append(select,remove);list.append(row);}
}
function clearDestination(){editingDestination=null;$('destination-name').value='';$('save-destination').textContent='선택 위치 저장';}
$('new-destination').onclick=()=>{clearDestination();setTool('goal');notice('지도에서 새 목표 위치와 방향을 선택하세요');};
$('destination-form').onsubmit=async e=>{e.preventDefault();const x=$('input-x').value,y=$('input-y').value;if(!x||!y){notice('먼저 지도에서 위치를 선택하세요',true);return;}
  try{const r=await command('save_destination',{name:$('destination-name').value,x:Number(x),y:Number(y),yaw:Number($('input-yaw').value)*Math.PI/180,...(editingDestination?{id:editingDestination}:{})});editingDestination=r.destination.id;$('save-destination').textContent='목표 수정 저장';}catch(error){notice(error.message,true);}};
