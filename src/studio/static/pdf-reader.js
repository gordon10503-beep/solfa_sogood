/* PDF spreads with lazy rendering and page-normalized annotation history. */
window.StudioPDF = (() => {
  const $=id=>document.getElementById(id),redoByPage=new Map();
  let pdf=null,page=1,scoreId=null,marks=[],save=null,tool='pan',stroke=null,observer=null,slots=[],generation=0,comparison=false,savedDirection='vertical',selectedPages=[],request=0;
  const recentCanvases=new Set();
  let pendingSource;
  function previewCanvas(id,number){
    const image=new Image();
    image.src='/api/pdf-cover/'+id+(number===1?'':'?page='+number);
    return image.decode().then(()=>{
      const canvas=document.createElement('canvas');
      canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
      canvas.getContext('2d').drawImage(image,0,0);
      return canvas;
    }).catch(()=>null);
  }
  function preload(id){
    if(scoreId===id || pendingSource?.id===id)return;
    if(pendingSource?.task)void pendingSource.task.destroy().catch(()=>{});
    const pending={id};
    pendingSource=pending;
    pending.ready=import('/vendor/pdf.mjs').then(module=>{
      if(pendingSource!==pending)return null;
      module.GlobalWorkerOptions.workerSrc='/vendor/pdf.worker.mjs';
      pending.task=module.getDocument({url:'/api/source/'+id,isEvalSupported:false});
      return pending.task.promise;
    });
    // Start the first sheet independently of PDF.js font and worker setup.
    // Subsequent sheets and the fallback use the original document in PDF.js.
    pending.firstCanvas=previewCanvas(id,1);
    pending.ready.catch(()=>{});
  }
  function controls(){
    $('pdf-undo').disabled=!!stroke||!marks.some(m=>m.page===page);
    $('pdf-redo').disabled=!!stroke||!redoByPage.get(page)?.length;
    $('pdf-page-label').textContent=pdf?`${page} / ${pdf.numPages}`:'';
  }
  function draw(slot){
    slot.ink.replaceChildren();
    for(const mark of marks.filter(m=>m.page===slot.number)){
      const path=document.createElementNS('http://www.w3.org/2000/svg','polyline');
      for(const [name,value] of Object.entries({points:mark.points.map(p=>p.join(',')).join(' '),fill:'none',stroke:mark.tool==='highlight'?'#ffdc19':'#e13d4d','stroke-width':mark.tool==='highlight'?22:3,opacity:mark.tool==='highlight'?.35:1,'stroke-linecap':'round','stroke-linejoin':'round'}))path.setAttribute(name,String(value));
      slot.ink.appendChild(path);
    }
    controls();
  }
  function redraw(){slots.forEach(draw);}
  function point(svg,e){const r=svg.getBoundingClientRect();return [Math.max(0,Math.min(1000,(e.clientX-r.left)/r.width*1000)),Math.max(0,Math.min(1000,(e.clientY-r.top)/r.height*1000))];}
  function bind(slot){
    const svg=slot.ink;
    svg.onpointerdown=e=>{if(tool==='pan'||e.button!==0||stroke)return;page=slot.number;e.preventDefault();svg.setPointerCapture(e.pointerId);stroke={page,tool,points:[point(svg,e)]};marks.push(stroke);draw(slot);};
    svg.onpointermove=e=>{if(stroke?.page!==slot.number)return;stroke.points.push(point(svg,e));draw(slot);};
    svg.onpointerup=()=>{if(stroke?.page!==slot.number)return;if(stroke.points.length===1)stroke.points.push([stroke.points[0][0]+.1,stroke.points[0][1]+.1]);redoByPage.delete(page);stroke=null;draw(slot);save?.(structuredClone(marks));};
    svg.onpointercancel=()=>{if(stroke?.page===slot.number){marks.pop();stroke=null;draw(slot);}};
    slot.sheet.onpointerenter=()=>{if(!stroke){page=slot.number;controls();}};
  }
  async function pageCanvas(doc,number){
    const page=await doc.getPage(number),viewport=page.getViewport({scale:1.4});
    const canvas=document.createElement('canvas');canvas.width=viewport.width;canvas.height=viewport.height;
    await page.render({canvasContext:canvas.getContext('2d'),viewport}).promise;
    return canvas;
  }
  async function render(slot){
    if(slot.canvas||slot.rendering)return;slot.rendering=true;const ticket=generation,doc=pdf;
    try{
      if(slot.number===2 && slot.sheet.parentElement?.children.length===2)
        slot.prepared=previewCanvas(scoreId,2);
      const canvas=await slot.prepared || await pageCanvas(doc,slot.number);
      if(ticket!==generation||!slot.near)return;
      slot.sheet.style.setProperty('--sheet-ratio',canvas.width/canvas.height);slot.sheet.style.aspectRatio=`${canvas.width}/${canvas.height}`;slot.surface.replaceChildren(canvas);slot.canvas=canvas;
      slot.sheet.setAttribute('aria-busy','false');
    }catch(e){if(ticket===generation){slot.failed=true;slot.sheet.setAttribute('aria-busy','false');slot.surface.textContent='Could not render this page: '+e.message;}}
    finally{slot.prepared=null;slot.rendering=false;if(ticket===generation)pumpPages();}
  }
  const nearby=new Set();
  function pumpPages(){
    const bounds=$('score-scroll').getBoundingClientRect();
    const distance=slot=>{
      const r=slot.sheet.getBoundingClientRect();
      return Math.max(0,bounds.top-r.bottom,r.top-bounds.bottom,bounds.left-r.right,r.left-bounds.right);
    };
    const ordered=[...nearby].filter(s=>!s.canvas&&!s.rendering&&!s.failed).map(s=>[s,distance(s)]).sort((a,b)=>a[1]-b[1]);
    const capacity=2-slots.filter(s=>s.rendering).length;
    for(const [slot] of ordered.slice(0,Math.max(0,capacity)))void render(slot);
  }
  function arrange(){
    observer?.disconnect();
    nearby.clear();
    slots.forEach(s=>s.near=false);
    const host=$('pdf-pages'),width=comparison?1:(+$('pdf-layout').value||1),horizontal=!comparison&&$('pdf-direction').value==='horizontal';
    host.classList.toggle('horizontal',horizontal);host.style.setProperty('--pages-per-spread',width);
    const groups=[];
    const active=comparison&&selectedPages.length?selectedPages.map(n=>slots[n-1]).filter(Boolean):slots;
    for(let i=0;i<active.length;i+=width){const spread=document.createElement('div');spread.className='pdf-spread';active.slice(i,i+width).forEach(slot=>spread.appendChild(slot.sheet));groups.push(spread);}
    host.replaceChildren(...groups);$('pdf-direction').disabled=comparison;$('pdf-layout').disabled=comparison;
    observer=new IntersectionObserver(entries=>{
      for(const entry of entries){const slot=slots[+entry.target.dataset.page-1];slot.near=entry.isIntersecting;
        if(slot.near){recentCanvases.delete(slot);nearby.add(slot);}
        else nearby.delete(slot);
        if(!slot.near && slot.canvas){
          recentCanvases.add(slot);
          if(recentCanvases.size>2){
            const oldest=recentCanvases.values().next().value;
            recentCanvases.delete(oldest);oldest.surface.replaceChildren(oldest.loading);oldest.canvas=null;oldest.sheet.setAttribute('aria-busy','true');
          }
        }
      }
      pumpPages();
      const visible=slots.filter(s=>s.near).map(s=>({slot:s,r:s.sheet.getBoundingClientRect()})).filter(x=>x.r.bottom>0&&x.r.right>0).sort((a,b)=>Math.abs(a.r.top-$('score-scroll').getBoundingClientRect().top)-Math.abs(b.r.top-$('score-scroll').getBoundingClientRect().top));
      if(visible.length&&!stroke){page=visible[0].slot.number;controls();}
    },{root:$('score-scroll'),rootMargin:'250px',threshold:0});
    slots.forEach(s=>observer.observe(s.sheet));controls();scheduleTurns();
  }
  async function open(id,annotations,onSave,sizes=[],pages=[]){
    const token=++request;const pagesChanged=String(selectedPages)!==String(pages);selectedPages=pages||[];
    if(scoreId!==id||JSON.stringify(marks)!==JSON.stringify(annotations||[]))redoByPage.clear();
    marks=structuredClone(annotations||[]);save=onSave;
    if(scoreId!==id){
      preload(id);
      const pending=pendingSource;
      let next;
      try{next=await pending.ready;}
      catch(error){
        if(token!==request || pendingSource!==pending)return;
        pendingSource=null;
        throw error;
      }
      if(!next || token!==request || pendingSource!==pending)return;
      pendingSource=null;
      generation++;recentCanvases.clear();observer?.disconnect();const previous=pdf;pdf=next;scoreId=id;page=1;
      if(previous)void previous.destroy().catch(()=>{});
      slots=Array.from({length:pdf.numPages},(_,i)=>{
        const sheet=document.createElement('div'),surface=document.createElement('div'),ink=document.createElementNS('http://www.w3.org/2000/svg','svg');
        sheet.className='pdf-sheet';if(sizes?.[i]){sheet.style.aspectRatio=sizes[i].join('/');sheet.style.setProperty('--sheet-ratio',sizes[i][0]/sizes[i][1]);}sheet.dataset.page=i+1;surface.className='pdf-surface';
        ink.setAttribute('viewBox','0 0 1000 1000');ink.setAttribute('preserveAspectRatio','none');ink.classList.add('pdf-ink');ink.setAttribute('aria-label','Annotations on page '+(i+1));
        const label=document.createElement('span');label.className='pdf-sheet-number';label.textContent=i+1;
        const loading=document.createElement('span');
        loading.className='pdf-loading';loading.textContent='Loading page '+(i+1)+'…';
        surface.append(loading);sheet.setAttribute('aria-busy','true');
        sheet.append(surface,ink,label);const slot={number:i+1,sheet,surface,ink,loading,prepared:i===0?pending.firstCanvas:null};bind(slot);return slot;
      });arrange();
    }else if(pagesChanged)arrange();
    setTool(tool);redraw();scheduleTurns();
  }
  function setTool(next){tool=next;slots.forEach(s=>{s.ink.style.touchAction=tool==='pan'?'auto':'none';s.ink.style.pointerEvents=tool==='pan'?'none':'auto';});document.querySelectorAll('[data-ink]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.ink===tool)));}
  document.querySelectorAll('[data-ink]').forEach(b=>b.onclick=()=>setTool(tool===b.dataset.ink?'pan':b.dataset.ink));
  const host=$('pdf-pages'), turns=$('pdf-turns');
  function currentSpread(){
    const groups=host.children;
    if(host.classList.contains('horizontal') && groups.length>1){
      const stride=groups[1].offsetLeft-groups[0].offsetLeft;
      if(stride>0)return Math.min(groups.length-1,Math.round(host.scrollLeft/stride));
    }
    const horizontal=host.classList.contains('horizontal');
    const bounds=pane.getBoundingClientRect();
    const probe=horizontal?host.getBoundingClientRect().left+host.clientWidth/2:bounds.top+bounds.height/2;
    for(let i=0;i<groups.length;i++){
      const rect=groups[i].getBoundingClientRect();
      if((horizontal?rect.right:rect.bottom)>probe)return i;
    }
    return groups.length-1;
  }
  function positionTurns(){
    turns.hidden=comparison||!host.classList.contains('horizontal')||document.body.dataset.page!=='original';
    if(turns.hidden||!$('pdf-reader').getClientRects().length)return;
    const rect=$('pdf-reader').getBoundingClientRect(), viewport=pane.getBoundingClientRect();
    turns.style.left=Math.max(0,rect.left)+'px';
    turns.style.right=Math.max(0,document.documentElement.clientWidth-rect.right)+'px';
    turns.style.top=(Math.max(0,viewport.top)+Math.min(innerHeight,viewport.bottom))/2+'px';
    const i=currentSpread();
    $('pdf-prev').disabled=i<=0;
    $('pdf-next').disabled=i>=host.children.length-1;
  }
  let frame;
  function scheduleTurns(){
    if(!frame)frame=requestAnimationFrame(()=>{frame=0;positionTurns();});
  }
  function navigate(delta){
    const target=host.children[currentSpread()+delta];
    if(!target)return;
    page=Number(target.firstElementChild.dataset.page);
    const behavior=matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth';
    if(host.classList.contains('horizontal'))host.scrollTo({left:target.offsetLeft,behavior});
    else{
      const offset=pane.classList.contains('spread-focus')?$('pdf-controls').offsetHeight:0;
      pane.scrollTo({top:pane.scrollTop+target.getBoundingClientRect().top-pane.getBoundingClientRect().top-offset,behavior});
    }
    controls();
  }
  $('pdf-prev').onclick=()=>navigate(-1);$('pdf-next').onclick=()=>navigate(1);
  let drag=null;
  host.addEventListener('pointerdown',e=>{
    drag=null;
    if(tool!=='pan'||!e.isPrimary||e.button!==0)return;
    drag={id:e.pointerId,x:e.clientX,y:e.clientY};
    host.setPointerCapture(e.pointerId);
  });
  host.addEventListener('pointerup',e=>{
    if(drag?.id!==e.pointerId)return;
    const dx=e.clientX-drag.x,dy=e.clientY-drag.y;
    drag=null;
    if(tool==='pan'&&Math.abs(dx)>=48&&Math.abs(dx)>1.5*Math.abs(dy))navigate(dx<0?1:-1);
  });
  host.addEventListener('lostpointercapture',()=>{drag=null;});
  host.addEventListener('pointercancel',()=>{drag=null;});
  $('pdf-layout').onchange=$('pdf-direction').onchange=()=>{if(pdf)arrange();};
  $('pdf-undo').onclick=()=>{if(stroke)return;const i=marks.findLastIndex(m=>m.page===page);if(i>=0){const history=redoByPage.get(page)||[];history.push({index:i,mark:marks.splice(i,1)[0]});redoByPage.set(page,history);redraw();save?.(structuredClone(marks));}};
  $('pdf-redo').onclick=()=>{if(stroke)return;const entry=redoByPage.get(page)?.pop();if(entry){marks.splice(Math.min(entry.index,marks.length),0,entry.mark);redraw();save?.(structuredClone(marks));}};
  const pane=$('score-scroll');
  const resize=new ResizeObserver(scheduleTurns);
  resize.observe(pane);resize.observe(host);resize.observe($('pdf-reader'));
  host.addEventListener('scroll',scheduleTurns,{passive:true});
  document.addEventListener('scroll',scheduleTurns,{capture:true,passive:true});
  let previousLayout;
  function focusSpread(enabled){
    const anchor=slots[page-1];
    if(enabled)pane.prepend($('pdf-controls'));
    else $('edit-strip').before($('pdf-controls'));
    pane.classList.toggle('spread-focus',enabled);
    $('pdf-controls').classList.remove('spread-tools-open');
    $('spread-tools').setAttribute('aria-expanded','false');
    $('spread-focus').setAttribute('aria-pressed',String(enabled));
    const label=enabled?'Exit full-page view':'Full-page view';
    $('spread-focus').title=label;
    $('spread-focus').setAttribute('aria-label',label);
    if(enabled){
      previousLayout=$('pdf-layout').value;
      if(innerWidth>innerHeight)$('pdf-layout').value='2';
    }else if(previousLayout)$('pdf-layout').value=previousLayout;
    if(pdf)arrange();
    requestAnimationFrame(()=>anchor?.sheet.parentElement?.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'}));
  }
  $('spread-focus').onclick=()=>focusSpread(!pane.classList.contains('spread-focus'));
  $('spread-tools').onclick=()=>$('spread-tools').setAttribute('aria-expanded',String($('pdf-controls').classList.toggle('spread-tools-open')));
  $('spread-play').onclick=()=>$('play').click();
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&pane.classList.contains('spread-focus'))focusSpread(false);});
  function setComparison(value){if(comparison===value)return;if(value){savedDirection=$('pdf-direction').value;$('pdf-direction').value='vertical';}else $('pdf-direction').value=savedDirection;comparison=value;if(pdf)arrange();}
  return {open,setComparison,preload};
})();
