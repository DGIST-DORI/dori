export class RobotMap {
  constructor(canvas,onDestination){
    this.canvas=canvas;this.ctx=canvas.getContext('2d');this.onDestination=onDestination;
    this.view={x:0,y:0,scale:45};this.state=null;this.image=null;this.version=-1;this.loading=-1;this.fitted=false;this.follow=false;this.selected=null;
    new ResizeObserver(()=>this.resize()).observe(canvas);
    canvas.onpointerdown=e=>{if(e.button!==0)return;this.drag={x:e.clientX,y:e.clientY,view:{...this.view}};canvas.setPointerCapture(e.pointerId)};
    canvas.onpointermove=e=>{if(!this.drag)return;this.follow=false;this.view.x=this.drag.view.x-(e.clientX-this.drag.x)/this.view.scale;this.view.y=this.drag.view.y+(e.clientY-this.drag.y)/this.view.scale;this.draw()};
    canvas.onpointerup=e=>{if(this.drag&&Math.hypot(e.clientX-this.drag.x,e.clientY-this.drag.y)<5){const rect=canvas.getBoundingClientRect();for(const g of this.state?.destinations||[]){const p=this.screen(g.x,g.y);if(Math.hypot(p[0]-e.clientX+rect.left,p[1]-e.clientY+rect.top)<20){this.onDestination(g);break}}}this.drag=null};
    canvas.onpointercancel=()=>this.drag=null;
    canvas.onwheel=e=>{e.preventDefault();const r=canvas.getBoundingClientRect(),p=[e.clientX-r.left,e.clientY-r.top],before=this.world(...p);this.view.scale=Math.max(4,Math.min(500,this.view.scale*Math.exp(-e.deltaY*.001)));const after=this.world(...p);this.view.x+=before[0]-after[0];this.view.y+=before[1]-after[1];this.follow=false;this.draw()};
  }
  resize(){const r=this.canvas.getBoundingClientRect(),d=devicePixelRatio||1;this.w=r.width;this.h=r.height;this.canvas.width=r.width*d;this.canvas.height=r.height*d;this.draw()}
  reset(){this.image=null;this.version=-1;this.loading=-1;this.fitted=false;this.selected=null}
  screen(x,y){return [this.w/2+(x-this.view.x)*this.view.scale,this.h/2-(y-this.view.y)*this.view.scale]}
  world(x,y){return [this.view.x+(x-this.w/2)/this.view.scale,this.view.y-(y-this.h/2)/this.view.scale]}
  fit(){const m=this.state?.map;if(!m){if(this.state?.robot){[this.view.x,this.view.y]=this.state.robot}return}const b=m.known_bounds||[0,0,m.width*m.resolution,m.height*m.resolution],[x,y,a]=m.origin,c=Math.cos(a),s=Math.sin(a);this.view.x=x+c*(b[0]+b[2])/2-s*(b[1]+b[3])/2;this.view.y=y+s*(b[0]+b[2])/2+c*(b[1]+b[3])/2;const width=b[2]-b[0],height=b[3]-b[1];this.view.scale=Math.max(4,Math.min(this.w/(Math.abs(c)*width+Math.abs(s)*height+2),this.h/(Math.abs(s)*width+Math.abs(c)*height+2)));this.follow=false;this.fitted=true;this.draw()}
  update(state){this.state=state;const m=state.map;if(m&&m.version!==this.version&&m.version!==this.loading){this.loading=m.version;const image=new Image(),v=m.version;image.onload=()=>{if(this.state?.map?.version===v){this.image=image;this.version=v;if(!this.fitted)this.fit();this.draw()}this.loading=-1};image.onerror=()=>this.loading=-1;image.src='/api/map.png?v='+v}this.draw()}
  route(points){if(!points?.length)return;const c=this.ctx;c.beginPath();points.forEach((p,i)=>{const [x,y]=this.screen(...p);i?c.lineTo(x,y):c.moveTo(x,y)});c.strokeStyle='#5a8d72';c.lineWidth=2.5;c.stroke()}
  draw(){if(!this.w||!this.h)return;const c=this.ctx,s=this.state,d=devicePixelRatio||1;c.setTransform(d,0,0,d,0,0);c.clearRect(0,0,this.w,this.h);if(this.follow&&s?.robot)[this.view.x,this.view.y]=s.robot;
    if(s?.map&&this.image&&this.version===s.map.version){const m=s.map,[x,y,a]=m.origin,p=this.screen(x,y);c.save();c.translate(...p);c.scale(this.view.scale,-this.view.scale);c.rotate(a);c.translate(0,m.height*m.resolution);c.scale(m.resolution,-m.resolution);c.imageSmoothingEnabled=false;c.drawImage(this.image,0,0);c.restore()}
    const fresh=(s?.server_age??10)<2;if(fresh)this.route(s?.paths?.plan);
    for(const [i,g] of (s?.destinations||[]).entries()){const [x,y]=this.screen(g.x,g.y),selected=g.id===this.selected;c.beginPath();c.arc(x,y,selected?12:10,0,Math.PI*2);c.fillStyle=selected?'#296c58':'#fff';c.fill();c.strokeStyle='#568671';c.lineWidth=1.7;c.stroke();c.fillStyle=selected?'#fff':'#446c55';c.font='500 10px system-ui';c.textAlign='center';c.textBaseline='middle';c.fillText(String(i+1),x,y);c.textAlign='left';c.font='12px system-ui';const width=c.measureText(g.name).width;c.fillStyle='#ffffffeb';c.fillRect(x+14,y-11,width+10,22);c.fillStyle='#4a5e50';c.fillText(g.name,x+19,y)}
    if(s?.goal){const [x,y]=this.screen(...s.goal);c.beginPath();c.arc(x,y,16,0,Math.PI*2);c.strokeStyle='#ac7946';c.lineWidth=1.5;c.stroke();if(!s.goal_name){c.fillStyle='#8b643f';c.font='11px system-ui';c.textAlign='left';c.fillText('Goal',x+20,y)}}
    if(s?.robot){const [x,y]=this.screen(...s.robot);c.save();c.globalAlpha=fresh&&s.sensors?.odom?.age<.5?1:.35;c.translate(x,y);c.beginPath();c.arc(0,0,20,0,Math.PI*2);c.fillStyle='#245d8015';c.fill();c.rotate(-s.robot[2]);c.beginPath();c.moveTo(13,0);c.lineTo(-8,-8);c.lineTo(-4,0);c.lineTo(-8,8);c.closePath();c.fillStyle='#245d80';c.fill();c.restore()}
    const m=this.view.scale>80?1:this.view.scale>30?2:5,scale=document.getElementById('scale');scale.style.width=m*this.view.scale+'px';scale.textContent=m+' m';document.getElementById('map-empty').style.display=s?.map?'none':'grid';
  }
}
