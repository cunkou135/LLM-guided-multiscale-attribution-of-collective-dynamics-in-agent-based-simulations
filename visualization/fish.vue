<template>
  <section class="fish-stage">
    <div class="fish-canvas-shell">
      <canvas ref="world" role="img" :aria-label="'鱼群主体场景，'+frame.agents.length+'条鱼和'+frame.predators.length+'条鲨鱼，step '+frame.step"
        @wheel.prevent="wheel" @pointerdown="down" @pointermove="move" @pointerup="up"></canvas>
      <div class="fish-canvas-top"><span class="fish-live"><i></i>{{playing?'运行中':'已暂停'}}</span><span>LOCAL INTERACTIONS / FISH SCHOOL</span></div>
      <div class="fish-compass">N<svg width="30" height="30" viewBox="0 0 34 34"><path d="M17 4L22 25L17 22L12 25Z" fill="currentColor"/></svg></div>
      <div class="fish-canvas-bottom"><div class="fish-legend"><span><i style="background:#87d8d3"></i>未受惊</span><span><i style="background:#ff9875"></i>直接受惊</span><span><i style="background:#e5c96f"></i>社会受惊</span><span><i style="background:#f28a63"></i>鲨鱼</span></div><span>点击查看个体 · 拖动平移 · 滚轮缩放</span></div>
      <div class="fish-selected" v-if="selectedAnimal"><div><span>INDIVIDUAL</span><button @click="selected=-1" aria-label="取消选择鱼群个体">×</button></div><h3>{{selectedPredator?'鲨鱼':'鱼'}} {{selected}}</h3><p>位置 {{selectedAnimal[1].toFixed(2)}}, {{selectedAnimal[2].toFixed(2)}}<br>朝向 {{(selectedAnimal[3]*180/Math.PI).toFixed(1)}}°<br><span v-if="!selectedPredator">{{['未受惊','直接受惊','社会受惊'][selectedAnimal[5]]}} · 感知邻居 {{neighbors.length}} 个</span></p></div>
    </div>
    <div class="fish-tools"><button :class="{active:follow}" @click="follow=!follow">◎ 跟随群体</button><button @click="fit">适应画面</button><button @click="saveSnapshot">保存场景截图</button><label><input type="checkbox" v-model="zones"/>感知范围</label><label><input type="checkbox" v-model="grid"/>空间网格</label><label><input type="checkbox" v-model="trailsEnabled"/>运动轨迹</label><span>{{fps}} FPS · 展示坐标不参与决策</span></div>
  </section>
</template>
<script>
module.exports={
 data(){return{current:null,previous:null,received:0,interval:80,lastReceived:0,selected:-1,zoom:4,cameraX:0,cameraY:0,follow:true,grid:true,zones:true,trailsEnabled:false,
  width:1000,height:500,drag:null,raf:0,observer:null,oldAgents:new Map(),oldSharks:new Map(),trails:new Map(),sprites:new Map(),fps:0,frameCount:0,fpsSince:0};},
 computed:{selectedAnimal(){return this.frame.agents.find(a=>a[0]===this.selected)||this.frame.predators.find(a=>a[0]===this.selected);},
  selectedPredator(){return this.frame.predators.some(a=>a[0]===this.selected);},
  neighbors(){const a=this.selectedAnimal;return a?this.frame.agents.filter(b=>b[0]!==a[0]&&Math.hypot(b[1]-a[1],b[2]-a[2])<=this.frame.fish.R_s):[];}},
 watch:{'frame.step'(){this.$nextTick(()=>this.receive());},'frame.run_id'(){this.current=null;this.selected=-1;this.trails.clear();this.$nextTick(()=>this.receive());},playing(value){if(!value)this.received=0;}},
 mounted(){this.follow=this.settings.follow_camera;this.grid=this.settings.show_grid;this.zones=this.settings.show_zones;this.trailsEnabled=this.settings.show_trails;this.zoom=this.settings.zoom;
  this.observer=new ResizeObserver(()=>this.resize());this.observer.observe(this.$refs.world);this.resize();this.receive();this.raf=requestAnimationFrame(t=>this.draw(t));},
 beforeDestroy(){cancelAnimationFrame(this.raf);if(this.observer)this.observer.disconnect();},
 methods:{
  receive(){const now=performance.now();if(this.current&&this.current.run_id===this.frame.run_id&&this.current.step===this.frame.step)return;
   this.previous=this.current;this.oldAgents=new Map((this.previous?this.previous.agents:[]).map(a=>[a[0],a]));this.oldSharks=new Map((this.previous?this.previous.predators:[]).map(a=>[a[0],a]));
   this.current=this.frame;this.interval=Math.max(30,Math.min(1000,now-this.lastReceived));this.lastReceived=now;this.received=now;
   if(!this.previous){this.cameraX=this.frame.center[0];this.cameraY=this.frame.center[1];}
   for(const a of this.frame.agents){let list=this.trails.get(a[0])||[];list.push([a[1],a[2]]);if(list.length>this.settings.trail_length)list.shift();this.trails.set(a[0],list);}},
  resize(){const c=this.$refs.world;if(!c)return;this.width=c.clientWidth||1000;this.height=Math.max(340,Math.min(this.settings.height,window.innerHeight-c.getBoundingClientRect().top-185));
   c.style.height=this.height+'px';const dpr=Math.min(window.devicePixelRatio||1,2);c.width=this.width*dpr;c.height=this.height*dpr;},
  project(x,y){return[this.width/2+(x-this.cameraX)*this.zoom,this.height/2-(y-this.cameraY)*this.zoom];},
  interpolate(a,map,t){const old=map.get(a[0]);if(!old||!this.playing)return a;const dh=Math.atan2(Math.sin(a[3]-old[3]),Math.cos(a[3]-old[3]));return[a[0],old[1]+(a[1]-old[1])*t,old[2]+(a[2]-old[2])*t,old[3]+dh*t,a[4],a[5]];},
  animal(ctx,a,predator,now){const [x,y]=this.project(a[1],a[2]);if(x< -40||x>this.width+40||y< -40||y>this.height+40)return;
   const size=predator?this.settings.predator_size:this.settings.agent_size,color=predator?this.settings.predator_color:a[5]===1?'#ff9875':a[5]===2?'#e5c96f':this.settings.fish_color;
   if(!predator){const key=color+':'+size;let sprite=this.sprites.get(key);if(!sprite){const cell=Math.ceil(size*3+4),dpr=2,tile=cell*dpr,atlas=document.createElement('canvas');atlas.width=tile*16;atlas.height=tile*8;const c=atlas.getContext('2d');
    for(let angle=0;angle<128;angle++){c.save();c.translate((angle%16+.5)*tile,(Math.floor(angle/16)+.5)*tile);c.scale(dpr,dpr);c.rotate(-angle*Math.PI/64);c.fillStyle=color;c.beginPath();c.moveTo(size,0);c.bezierCurveTo(size*.2,-size*.42,-size*.4,-size*.3,-size*.65,0);c.bezierCurveTo(-size*.4,size*.3,size*.2,size*.42,size,0);c.fill();c.globalAlpha=.7;c.beginPath();c.moveTo(-size*.55,0);c.lineTo(-size*1.05,-size*.38);c.lineTo(-size*.92,0);c.lineTo(-size*1.05,size*.38);c.closePath();c.fill();c.restore();}sprite={atlas,tile,cell};this.sprites.set(key,sprite);}
    const angle=((Math.round(a[3]*64/Math.PI)%128)+128)%128;ctx.drawImage(sprite.atlas,angle%16*sprite.tile,Math.floor(angle/16)*sprite.tile,sprite.tile,sprite.tile,x-sprite.cell/2,y-sprite.cell/2,sprite.cell,sprite.cell);
   }else{ctx.save();ctx.translate(x,y);ctx.rotate(-a[3]);ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(size,0);ctx.bezierCurveTo(size*.2,-size*.42,-size*.4,-size*.3,-size*.65,0);ctx.bezierCurveTo(-size*.4,size*.3,size*.2,size*.42,size,0);ctx.fill();ctx.beginPath();ctx.moveTo(-size*.55,0);ctx.lineTo(-size*1.05,-size*.38+Math.sin(now/140+a[0])*size*.12);ctx.lineTo(-size*.92,0);ctx.lineTo(-size*1.05,size*.38);ctx.closePath();ctx.fill();ctx.beginPath();ctx.moveTo(0,0);ctx.lineTo(-size*.35,-size*.65);ctx.lineTo(size*.3,0);ctx.fill();ctx.restore();}
   if(a[0]===this.selected){ctx.strokeStyle='#d9f4df';ctx.lineWidth=1;ctx.beginPath();ctx.arc(x,y,size+6,0,Math.PI*2);ctx.stroke();}},
  draw(now){this.raf=requestAnimationFrame(t=>this.draw(t));const canvas=this.$refs.world;if(!canvas||!this.current||document.hidden)return;const ctx=canvas.getContext('2d'),dpr=canvas.width/this.width;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle=this.settings.fish_background;ctx.fillRect(0,0,this.width,this.height);
   const t=this.playing?Math.min(1,(now-this.received)/this.interval):1;
   if(this.follow){const before=this.previous?this.previous.center:this.current.center;const x=before[0]+(this.current.center[0]-before[0])*t,y=before[1]+(this.current.center[1]-before[1])*t;this.cameraX+=(x-this.cameraX)*this.settings.camera_smoothing;this.cameraY+=(y-this.cameraY)*this.settings.camera_smoothing;}
   if(this.grid){const spacing=10*this.zoom,ox=((this.width/2-this.cameraX*this.zoom)%spacing+spacing)%spacing,oy=((this.height/2+this.cameraY*this.zoom)%spacing+spacing)%spacing;ctx.beginPath();for(let x=ox;x<this.width;x+=spacing){ctx.moveTo(x,0);ctx.lineTo(x,this.height);}for(let y=oy;y<this.height;y+=spacing){ctx.moveTo(0,y);ctx.lineTo(this.width,y);}ctx.strokeStyle='#79b9bd';ctx.globalAlpha=.07;ctx.lineWidth=.7;ctx.stroke();ctx.globalAlpha=1;}
   if(this.trailsEnabled){ctx.strokeStyle=this.settings.fish_color;ctx.lineWidth=.6;ctx.globalAlpha=this.settings.trail_opacity;for(const list of this.trails.values()){ctx.beginPath();list.forEach((p,i)=>{const [x,y]=this.project(...p);if(i)ctx.lineTo(x,y);else ctx.moveTo(x,y);});ctx.stroke();}ctx.globalAlpha=1;}
   if(this.selectedAnimal&&this.zones){const a=this.selectedAnimal,[x,y]=this.project(a[1],a[2]);ctx.save();ctx.setLineDash([3,5]);ctx.lineWidth=.8;for(const [r,color] of [[this.frame.fish.R_s,'#9ab9a3'],[this.frame.fish.r_a,'#71b7b0'],[this.frame.fish.r_r,'#df9f79']]){ctx.beginPath();ctx.arc(x,y,r*this.zoom,0,Math.PI*2);ctx.strokeStyle=color;ctx.globalAlpha=.45;ctx.stroke();}ctx.globalAlpha=.2;ctx.strokeStyle='#9ed7c8';ctx.beginPath();for(const b of this.neighbors){ctx.moveTo(x,y);ctx.lineTo(...this.project(b[1],b[2]));}ctx.stroke();ctx.restore();}
   for(const a of this.current.agents)this.animal(ctx,this.interpolate(a,this.oldAgents,t),false,now);
   for(const a of this.current.predators)this.animal(ctx,this.interpolate(a,this.oldSharks,t),true,now);
   this.frameCount++;if(!this.fpsSince)this.fpsSince=now;if(now-this.fpsSince>1000){this.fps=Math.round(this.frameCount*1000/(now-this.fpsSince));this.frameCount=0;this.fpsSince=now;}},
  fit(){const all=this.frame.agents.concat(this.frame.predators),xs=all.map(a=>a[1]),ys=all.map(a=>a[2]),left=Math.min(...xs),right=Math.max(...xs),bottom=Math.min(...ys),top=Math.max(...ys);this.cameraX=(left+right)/2;this.cameraY=(bottom+top)/2;this.zoom=Math.max(.15,Math.min(25,Math.min(this.width/(right-left+20),this.height/(top-bottom+20))*.8));},
  saveSnapshot(){this.event_capture({run_id:this.frame.run_id,step:this.frame.step,model:'fish',model_time:this.frame.time,node_count:this.frame.agents.length+this.frame.predators.length,png:this.$refs.world.toDataURL('image/png')});},
  wheel(e){this.zoom=Math.max(.15,Math.min(30,this.zoom*Math.exp(-e.deltaY*.001)));},
  down(e){this.drag={x:e.offsetX,y:e.offsetY,cx:this.cameraX,cy:this.cameraY,moved:false};this.$refs.world.setPointerCapture(e.pointerId);},
  move(e){if(!this.drag)return;const dx=e.offsetX-this.drag.x,dy=e.offsetY-this.drag.y;if(Math.abs(dx)+Math.abs(dy)>4){this.drag.moved=true;this.follow=false;this.cameraX=this.drag.cx-dx/this.zoom;this.cameraY=this.drag.cy+dy/this.zoom;}},
  up(e){if(this.drag&&!this.drag.moved){let best=-1,dist=196;for(const a of this.frame.agents.concat(this.frame.predators)){const [x,y]=this.project(a[1],a[2]),d=(x-e.offsetX)**2+(y-e.offsetY)**2;if(d<dist){dist=d;best=a[0];}}this.selected=best;}this.drag=null;}
 }
};
</script>
<style>
.fish-canvas-shell{position:relative;overflow:hidden;border-radius:9px;background:#091b25;box-shadow:0 12px 25px -20px #213b49}.fish-canvas-shell canvas{width:100%;display:block;touch-action:none;cursor:grab}.fish-canvas-top,.fish-canvas-bottom{position:absolute;left:21px;right:21px;display:flex;justify-content:space-between;align-items:center;pointer-events:none;color:#80a7ae;font-size:10px}.fish-canvas-top{top:20px}.fish-canvas-top>span:last-child{font:9px Georgia,serif;letter-spacing:2px}.fish-canvas-bottom{bottom:18px;font-size:9px}.fish-live{display:flex;align-items:center;gap:7px}.fish-live i{width:6px;height:6px;border-radius:50%;background:#75c1af;box-shadow:0 0 9px #73c0a83d}.fish-legend{display:flex;gap:16px}.fish-legend span{display:flex;gap:6px;align-items:center}.fish-legend i{width:5px;height:5px;border-radius:50%}.fish-compass{position:absolute;right:20px;top:60px;color:#618c93;font:9px Georgia;display:flex;align-items:center;flex-direction:column;gap:5px;pointer-events:none}.fish-selected{position:absolute;top:58px;left:21px;min-width:190px;background:#f6f5edf2;padding:15px 17px;border-radius:7px;color:#243a39;box-shadow:0 4px 18px #0002}.fish-selected>div{display:flex;align-items:center;justify-content:space-between;font-size:9px;letter-spacing:1.7px;color:#7c8883}.fish-selected button{border:0;background:none;font-size:18px}.fish-selected h3{font:22px Georgia,serif;margin:8px 0}.fish-selected p{font-size:10px;line-height:1.8;margin:0;color:#7c8883}.fish-tools{display:flex;align-items:center;gap:8px;margin:12px 0;color:#7c8883;font-size:11px;flex-wrap:wrap}.fish-tools button{background:transparent;border:1px solid transparent;padding:7px 10px;border-radius:5px;color:#7c8883}.fish-tools button.active{background:#e3ece0;border-color:#c9d8c6;color:#27776c}.fish-tools label{display:flex;align-items:center;gap:6px}.fish-tools input{accent-color:#27776c}.fish-tools>span{margin-left:auto;font-size:9px}
@media(max-width:760px){.fish-canvas-bottom>span{display:none}.fish-legend{gap:8px}.fish-selected{min-width:150px}}
</style>
