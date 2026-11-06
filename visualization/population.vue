<template>
  <section class="population-scene">
    <div class="population-stage">
      <div class="scene-toolbar">
        <span><b>主体网络</b> · {{ frame.nodes.length.toLocaleString() }} 位真实主体</span>
        <div>
          <button aria-label="放大主体网络" @click="zoomAt(1.25)">＋</button>
          <button aria-label="缩小主体网络" @click="zoomAt(0.8)">−</button>
          <button @click="resetView">复位视图</button>
          <button @click="captureCanvas">保存网络截图</button>
        </div>
      </div>
      <canvas ref="canvas" class="population-canvas" role="img"
        :aria-label="'Covasim实际主体网络，'+frame.nodes.length+'个节点，step '+frame.step"
        @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerUp"
        @pointerleave="pointerLeave" @wheel.prevent="wheel"></canvas>
      <div class="scene-footnote">
        <span>拖动平移 · 滚轮缩放 · 点击查看主体。布局为固定网络坐标，不代表真实地理位置。</span>
        <span>潜在接触：显示 {{ visibleEdges.length }} / {{ eligibleEdges.length }} 条去重边</span>
      </div>
    </div>
    <aside class="population-inspector">
      <div class="inspector-label">CONTACT LAYERS / 实际接触</div>
      <label v-for="(description,layer) in frame.layer_legend" :key="layer" class="layer-option">
        <input type="checkbox" :value="layer" v-model="layers" />
        <span class="layer-line" :style="{background:description[1]}"></span>{{ description[0] }}
      </label>
      <label class="local-option"><input type="checkbox" v-model="localOnly" />只显示所选主体的接触边</label>
      <p class="small-note">背景边按层确定性限量显示；选中主体优先展示真实邻接边。虚线为其近期已记录接触。</p>
      <div class="inspector-label">DISEASE STATE / 原生状态</div>
      <div v-for="(description,key) in frame.state_legend" :key="key" v-if="key!=='other'||stateCounts[key]" class="state-key">
        <span class="state-dot" :style="{background:description[1]}"></span>
        <span>{{ description[0] }}</span><b>{{ stateCounts[key] || 0 }}</b>
      </div>
      <p class="small-note">颜色优先级：死亡 → 恢复 → 传染 → 暴露 → 易感。蓝圈：已诊断；紫圈：检疫。红色脉冲仅来自本时点新增感染日志。</p>
      <div class="inspector-label">RESIDENT / 主体查询</div>
      <form class="resident-search" @submit.prevent="search">
        <input aria-label="搜索Covasim主体ID" v-model="query" placeholder="输入真实 UID，例如 565" />
        <button type="submit">定位</button>
      </form>
      <div class="search-message" v-if="searchMessage">{{ searchMessage }}</div>
      <div v-if="selectedNode" class="resident-detail">
        <h3>主体 {{ selectedNode.id }} <button aria-label="取消选中主体" @click="selected_uid=-1">×</button></h3>
        <div class="resident-status" :style="{color:frame.state_legend[selectedNode.state][1]}">{{ frame.state_legend[selectedNode.state][0] }}</div>
        <p>{{ selectedNode.age.toFixed(1) }} 岁 · 原生 sex={{ selectedNode.sex }}</p>
        <p>已诊断 {{ selectedNode.diagnosed?'是':'否' }} · 检疫 {{ selectedNode.quarantined?'是':'否' }}</p>
        <p>症状 {{ selectedNode.symptomatic?'是':'否' }} · 重症 {{ selectedNode.severe?'是':'否' }} · 危重 {{ selectedNode.critical?'是':'否' }}</p>
        <p>当前所选层接触对象 {{ neighborIds.length }} 人</p>
        <div class="neighbor-list">
          <button v-for="uid in neighborIds.slice(0,18)" :key="uid" @click="select(uid)">{{ uid }}</button>
        </div>
      </div>
      <p v-else class="small-note">点击网络中的任意圆点，或按原生 UID 搜索。全部节点始终保留。</p>
      <div class="capture-controls">
        <label><input type="checkbox" v-model="recording" />记录浏览器演示帧</label>
        <p class="small-note">只保存实际显示的 Canvas；每个已显示仿真日一帧，可生成连续日 GIF。</p>
        <div role="status" class="capture-status">{{ captureMessage }}</div>
      </div>
    </aside>
  </section>
</template>

<script>
module.exports = {
  data() {
    return {layers:['h','s','w','c'],localOnly:false,query:'',searchMessage:'',
      recording:false,captureMessage:'',width:900,cssHeight:650,
      zoom:1,panX:0,panY:0,drag:null,hover:-1,pulseStart:0,
      lastFrame:'',lastCapture:'',raf:0,captureTimer:0,observer:null};
  },
  computed: {
    nodeMap() { return new Map(this.frame.nodes.map(n=>[n.id,n])); },
    positionMap() { return new Map(this.scene_layout.nodes.map(n=>[n[0],[n[1],n[2]]])); },
    selectedNode() { return this.nodeMap.get(this.selected_uid); },
    eligibleEdges() { return this.frame.contacts.filter(e=>this.layers.includes(e[2])); },
    visibleEdges() {
      const related=e=>e[0]===this.selected_uid||e[1]===this.selected_uid;
      const priority=this.selected_uid>=0?this.eligibleEdges.filter(related):[];
      if(this.localOnly) return priority.slice(0,this.max_edges);
      const result=priority.slice(0,this.max_edges), background=this.eligibleEdges.filter(e=>!related(e));
      // Interleave layers so a dense workplace layer cannot exclude a sparse one.
      const groups=this.layers.map(l=>background.filter(e=>e[2]===l));
      let index=0;
      while(result.length<this.max_edges && groups.some(g=>index<g.length)) {
        for(const g of groups) if(index<g.length && result.length<this.max_edges) result.push(g[index]);
        index++;
      }
      return result;
    },
    neighborIds() {
      if(this.selected_uid<0) return [];
      return [...new Set(this.eligibleEdges.filter(e=>e[0]===this.selected_uid||e[1]===this.selected_uid)
        .map(e=>e[0]===this.selected_uid?e[1]:e[0]))].sort((a,b)=>a-b);
    },
    stateCounts() {
      const counts={};for(const n of this.frame.nodes) counts[n.state]=(counts[n.state]||0)+1;return counts;
    }
  },
  watch: {
    'frame.step'() {this.$nextTick(()=>this.receiveFrame());},
    'frame.run_id'() {this.lastCapture='';this.resetView();this.$nextTick(()=>this.receiveFrame());},
    'frame.recent_contacts'() {this.requestDraw();},
    scene_layout() {this.resetView();},
    layers() {this.requestDraw();},
    localOnly() {this.requestDraw();},
    selected_uid() {this.requestDraw();},
    recording(value) {if(value) {this.lastCapture='';this.queueCapture();}},
    height() {this.resize();}
  },
  mounted() {
    this.observer=new ResizeObserver(()=>this.resize());this.observer.observe(this.$refs.canvas);
    this.resize();this.receiveFrame();
  },
  beforeDestroy() {
    if(this.observer)this.observer.disconnect();cancelAnimationFrame(this.raf);clearTimeout(this.captureTimer);
  },
  methods: {
    receiveFrame() {
      const key=this.frame.run_id+':'+this.frame.step;
      if(key!==this.lastFrame) {this.lastFrame=key;this.pulseStart=performance.now();this.queueCapture();}
      this.requestDraw();
    },
    resize() {
      const canvas=this.$refs.canvas;if(!canvas)return;
      this.width=canvas.clientWidth||900;this.cssHeight=Math.min(this.height,Math.max(380,window.innerHeight-canvas.getBoundingClientRect().top-130));
      canvas.style.height=this.cssHeight+'px';const dpr=Math.min(window.devicePixelRatio||1,2);
      canvas.width=Math.round(this.width*dpr);canvas.height=Math.round(this.cssHeight*dpr);
      this.requestDraw();
    },
    point(uid) {
      const p=this.positionMap.get(uid);if(!p)return null;
      const x=this.width/2+(p[0]*(this.width-90)/2)*this.zoom+this.panX;
      const y=(this.cssHeight+88)/2+(p[1]*(this.cssHeight-160)/2)*this.zoom+this.panY;
      return [x,y];
    },
    requestDraw() {if(!this.raf)this.raf=requestAnimationFrame(t=>{this.raf=0;this.draw(t);});},
    draw(now) {
      const canvas=this.$refs.canvas;if(!canvas)return;
      const ctx=canvas.getContext('2d'),dpr=canvas.width/this.width;
      ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,this.width,this.cssHeight);
      ctx.fillStyle='#091b25';ctx.fillRect(0,0,this.width,this.cssHeight);
      // A real-frame header is included in browser captures, not composited later.
      ctx.fillStyle='#c8dedb';ctx.font='600 14px "Microsoft YaHei",sans-serif';
      ctx.fillText('Covasim 2.0.0  ·  '+this.frame.date+'  ·  day '+this.frame.native_day+' / step '+this.frame.step,22,27);
      ctx.font='12px "Microsoft YaHei",sans-serif';ctx.fillStyle='#80a7ae';
      ctx.fillText(this.frame.nodes.length+' 个真实主体 · '+this.frame.infections.length+' 条本时点新增感染记录 · 固定网络布局，非地理坐标',22,49);
      let lx=22;
      for(const key of Object.keys(this.frame.state_legend)) {
        if(key==='other'&&!this.stateCounts[key])continue;
        const [label,color]=this.frame.state_legend[key];ctx.fillStyle=color;ctx.beginPath();ctx.arc(lx+4,70,4,0,Math.PI*2);ctx.fill();
        ctx.fillStyle='#475569';ctx.fillText(label+' '+(this.stateCounts[key]||0),lx+14,74);lx+=86;
      }
      ctx.save();ctx.beginPath();ctx.rect(0,90,this.width,this.cssHeight-110);ctx.clip();
      for(const layer of this.layers) {
        ctx.beginPath();
        for(const e of this.visibleEdges) if(e[2]===layer) {
          const a=this.point(e[0]),b=this.point(e[1]);if(!a||!b)continue;ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);
        }
        ctx.strokeStyle=this.frame.layer_legend[layer][1];ctx.globalAlpha=this.selected_uid>=0 ? .12 : .20;
        ctx.lineWidth=.65;ctx.stroke();
      }
      ctx.globalAlpha=1;
      if(this.selected_uid>=0) {
        for(const e of this.visibleEdges) if(e[0]===this.selected_uid||e[1]===this.selected_uid) {
          const a=this.point(e[0]),b=this.point(e[1]);if(!a||!b)continue;
          ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.lineWidth=1.5;ctx.strokeStyle=this.frame.layer_legend[e[2]][1];ctx.stroke();
        }
        ctx.setLineDash([3,4]);ctx.globalAlpha=.5;
        for(const e of this.frame.recent_contacts) if(this.layers.includes(e[2])) {
          const a=this.point(e[0]),b=this.point(e[1]);if(!a||!b)continue;
          ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.strokeStyle=this.frame.layer_legend[e[2]][1];ctx.stroke();
        }
        ctx.setLineDash([]);ctx.globalAlpha=1;
      }
      const phase=(now-this.pulseStart)/this.pulse_ms, active=phase>=0&&phase<1;
      if(active) for(const e of this.frame.infections) if(e.source!==null) {
        const a=this.point(e.source),b=this.point(e.target);if(!a||!b)continue;
        ctx.strokeStyle='rgba(242,138,99,'+(1-phase*.7)+')';ctx.lineWidth=2.2;
        ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke();
        const t=(phase*2)%1;ctx.fillStyle='#f28a63';ctx.beginPath();ctx.arc(a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t,3.5,0,Math.PI*2);ctx.fill();
      }
      const neighbors=new Set(this.neighborIds),newIds=new Set(this.frame.infections.map(e=>e.target));
      for(const node of this.frame.nodes) {
        const p=this.point(node.id);if(!p)continue;
        const selected=node.id===this.selected_uid, adjacent=neighbors.has(node.id);
        const r=(selected?6:adjacent?4.2:3.1)*Math.min(1.55,Math.sqrt(this.zoom));
        ctx.globalAlpha=this.selected_uid>=0&&!selected&&!adjacent ? .35 : 1;
        ctx.fillStyle=this.frame.state_legend[node.state][1];ctx.beginPath();ctx.arc(...p,r,0,Math.PI*2);ctx.fill();
        if(node.diagnosed) {ctx.strokeStyle='#9ac9f2';ctx.lineWidth=1;ctx.beginPath();ctx.arc(...p,r+1.4,0,Math.PI*2);ctx.stroke();}
        if(node.quarantined) {ctx.strokeStyle='#cfb7e8';ctx.lineWidth=1;ctx.beginPath();ctx.arc(...p,r+3,0,Math.PI*2);ctx.stroke();}
        if(selected||node.id===this.hover) {ctx.globalAlpha=1;ctx.strokeStyle='#e1f3e8';ctx.lineWidth=2;ctx.beginPath();ctx.arc(...p,r+4.5,0,Math.PI*2);ctx.stroke();}
        if(active&&newIds.has(node.id)) {ctx.globalAlpha=1-phase;ctx.strokeStyle='#f28a63';ctx.lineWidth=1.8;ctx.beginPath();ctx.arc(...p,r+4+phase*12,0,Math.PI*2);ctx.stroke();}
      }
      ctx.globalAlpha=1;ctx.restore();
      const labelUid=this.hover>=0?this.hover:this.selected_uid;
      if(this.nodeMap.has(labelUid)) {
        const n=this.nodeMap.get(labelUid);ctx.fillStyle='#c8dedb';ctx.font='12px "Microsoft YaHei",sans-serif';
        ctx.fillText('UID '+n.id+' · '+this.frame.state_legend[n.state][0]+' · '+n.age.toFixed(1)+' 岁',22,this.cssHeight-12);
      }
      ctx.fillStyle='#80a7ae';ctx.font='11px sans-serif';ctx.textAlign='right';
      ctx.fillText(this.visibleEdges.length+' / '+this.eligibleEdges.length+' recorded contact edges',this.width-18,this.cssHeight-12);ctx.textAlign='left';
      if(active&&this.frame.infections.length)this.requestDraw();
    },
    resetView() {this.zoom=1;this.panX=0;this.panY=0;this.requestDraw();},
    zoomAt(factor,x,y) {
      x=x===undefined?this.width/2:x;y=y===undefined?(this.cssHeight+88)/2:y;
      const next=Math.max(.4,Math.min(8,this.zoom*factor)),ratio=next/this.zoom;
      this.panX=x-this.width/2-(x-this.width/2-this.panX)*ratio;
      this.panY=y-(this.cssHeight+88)/2-(y-(this.cssHeight+88)/2-this.panY)*ratio;
      this.zoom=next;this.requestDraw();
    },
    wheel(event) {const box=this.$refs.canvas.getBoundingClientRect();this.zoomAt(Math.exp(-event.deltaY*.001),event.clientX-box.left,event.clientY-box.top);},
    pointerDown(event) {this.drag={x:event.offsetX,y:event.offsetY,px:this.panX,py:this.panY,moved:false};this.$refs.canvas.setPointerCapture(event.pointerId);},
    nearest(x,y) {
      let closest=-1,distance=144;
      for(const n of this.frame.nodes) {const p=this.point(n.id);const d=(p[0]-x)**2+(p[1]-y)**2;if(d<distance){distance=d;closest=n.id;}}
      return closest;
    },
    pointerMove(event) {
      if(this.drag) {const dx=event.offsetX-this.drag.x,dy=event.offsetY-this.drag.y;this.panX=this.drag.px+dx;this.panY=this.drag.py+dy;this.drag.moved=this.drag.moved||Math.abs(dx)+Math.abs(dy)>4;}
      else this.hover=this.nearest(event.offsetX,event.offsetY);
      this.requestDraw();
    },
    pointerUp(event) {if(this.drag&&!this.drag.moved){const id=this.nearest(event.offsetX,event.offsetY);if(id>=0)this.select(id);}this.drag=null;},
    pointerLeave() {this.hover=-1;this.requestDraw();},
    select(uid) {this.selected_uid=uid;this.query=String(uid);this.searchMessage='';this.requestDraw();},
    search() {const uid=Number(this.query);if(Number.isInteger(uid)&&this.nodeMap.has(uid))this.select(uid);else this.searchMessage='当前实际人口中没有此 UID。';},
    queueCapture() {
      clearTimeout(this.captureTimer);
      if(this.recording)this.captureTimer=setTimeout(()=>{if(this.lastCapture!==this.lastFrame){this.lastCapture=this.lastFrame;this.captureCanvas();}},180);
    },
    captureCanvas() {
      this.draw(performance.now());
      this.event_capture({run_id:this.frame.run_id,step:this.frame.step,native_day:this.frame.native_day,
        date:this.frame.date,node_count:this.frame.nodes.length,state_counts:this.stateCounts,
        state_sha256:this.frame.state_sha256,layout_sha256:this.scene_layout.sha256,
        infection_event_indices:this.frame.infections.map(e=>e.event_index),
        displayed_contacts:this.visibleEdges.length,eligible_contacts:this.eligibleEdges.length,
        layers:this.layers.slice(),width:this.width,height:this.cssHeight,
        png:this.$refs.canvas.toDataURL('image/png')});
      this.captureMessage='已发送 step '+this.frame.step+' 的真实浏览器画面';
    }
  }
};
</script>

<style>
.population-scene{display:grid;grid-template-columns:minmax(0,1fr) 260px;gap:16px;width:100%;align-items:start;color:#273441;font-size:13px}
.population-stage{min-width:0;border:1px solid #dce4e9;background:#fbfcfd;border-radius:5px;overflow:hidden}
.scene-toolbar{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid #e5eaf0;gap:8px;flex-wrap:wrap;background:white}
.scene-toolbar button,.resident-search button,.neighbor-list button{border:1px solid #d9e2e9;background:white;border-radius:3px;padding:4px 8px;color:#334155;margin-left:4px}
.population-canvas{display:block;width:100%;touch-action:none;cursor:crosshair}
.scene-footnote{display:flex;justify-content:space-between;padding:9px 14px;gap:10px;flex-wrap:wrap;border-top:1px solid #e5eaf0;font-size:11px;color:#65748b}
.population-inspector{padding:3px 6px;max-height:calc(100vh - 190px);overflow-y:auto}.inspector-label{font-size:10px;letter-spacing:.08em;color:#64748b;margin:8px 0 10px;font-weight:600}
.layer-option{display:flex;align-items:center;gap:9px;margin:8px 0}.layer-line{width:24px;height:2px;display:inline-block}.local-option{display:flex;gap:8px;margin-top:16px;font-size:12px}
.small-note{font-size:11px;color:#748397;line-height:1.65;margin:9px 0 18px}.state-key{display:flex;align-items:center;gap:10px;padding:3px 0}.state-key b{font-weight:500;margin-left:auto}.state-dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.resident-search{display:flex;gap:4px}.resident-search input{width:100%;min-width:0;border:1px solid #d9e2e9;border-radius:3px;padding:6px;font-size:12px}.resident-search button{flex-shrink:0}
.resident-detail{margin:14px 0}.resident-detail h3{font-size:15px;font-weight:500}.resident-detail h3 button{float:right}.resident-detail p{font-size:12px;margin:7px 0;color:#64748b}.resident-status{font-size:13px;margin-top:6px}.neighbor-list{display:flex;flex-wrap:wrap;gap:4px}.neighbor-list button{font-size:11px;margin:0;padding:2px 5px}.capture-controls{border-top:1px solid #dce4e9;padding-top:13px;margin-top:18px;font-size:12px}.capture-status,.search-message{font-size:11px;color:#0072b2;margin-top:7px}
@media(max-width:1050px){.population-scene{grid-template-columns:minmax(0,1fr) 210px}}
@media(max-width:760px){.population-scene{grid-template-columns:minmax(0,1fr)}.population-inspector{display:grid;grid-template-columns:1fr 1fr;gap:5px 18px}.population-canvas{min-height:480px}}
</style>
