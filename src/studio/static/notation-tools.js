"use strict";
const palette = [
  ["whole","𝅝","Whole note"],["half","𝅗𝅥","Half note"],["quarter","♩","Quarter note"],
  ["eighth","♪","Eighth note"],["16th","𝅘𝅥𝅯","Sixteenth note"],["rest","𝄽","Quarter rest"],
  ["staccato","•","Staccato"],["tenuto","–","Tenuto"],["accent",">","Accent"],["fermata","𝄐","Fermata"]
];
let stamp=null, pointer=null;
const marks = new Set(["staccato","tenuto","accent","fermata"]);
function chooseStamp(tool){
  stamp=tool;
  for(const b of $("stamp-tools").children)b.setAttribute("aria-pressed",String(b.dataset.tool===tool));
}
function staffTarget(x,y){
  const page=document.elementFromPoint(x,y)?.closest(".score-page");
  if(!page)return null;
  let best=null, nearest=Infinity;
  for(const staff of page.querySelectorAll(".staff")){
    const paths=[...staff.querySelectorAll(":scope > path")].map(el=>el.getBoundingClientRect()).filter(r=>r.width>12&&r.height<2);
    if(paths.length!==5)continue;
    const top=paths[0],bottom=paths[4],gap=(bottom.top-top.top)/4;
    if(gap<=0||x<top.left||x>top.right)continue;
    const distance=Math.max(top.top-y,y-bottom.top,0);
    if(distance>gap*3||distance>=nearest)continue;
    const notes=[...staff.querySelectorAll(".note[id],.rest[id],.mRest[id]")].filter(el=>state.score.notes[el.id]);
    if(!notes.length)continue;
    const hit=document.elementFromPoint(x,y)?.closest(".note,.rest,.mRest");
    const anchor=notes.includes(hit)?hit:notes.reduce((a,b)=>Math.abs(x-a.getBoundingClientRect().x)<Math.abs(x-b.getBoundingClientRect().x)?a:b);
    best={anchor,top,bottom,gap};nearest=distance;
  }
  return best;
}
async function applyStamp(tool,x,y){
  const target=staffTarget(x,y);
  if(!target){toast("Choose a note or rest on the digital staff.");return;}
  const n=state.score.notes[target.anchor.id];
  if(marks.has(tool)){await edit("symbol",{nid:n.id,symbol:tool});return;}
  const [sign,line,shift]=n.clef;
  const ref={G:32,F:24,C:28}[sign];
  if(ref===undefined)throw Error("Pitch placement needs a treble, bass or C clef.");
  const pitch=ref+shift*7-2*(line-1)+Math.round((target.bottom.top-y)/(target.gap/2));
  const unit=tool==="rest"?"quarter":tool,length={whole:4,half:2,quarter:1,eighth:.5,"16th":.25}[unit];
  const bar=state.score.parts[n.part].measures[n.measure];
  const fraction=(x-target.top.left)/target.top.width;
  const offset=n.rest?Math.max(0,Math.min(n.duration-length,Math.floor((fraction*bar.length-n.offset)/length)*length)):0;
  await edit("place",{nid:n.id,unit,step:"CDEFGAB"[((pitch%7)+7)%7],octave:Math.floor(pitch/7),offset,rest:tool==="rest"});
}
for(const [tool,glyph,label] of palette){
  const button=document.createElement("button");
  button.type="button";button.dataset.tool=tool;button.textContent=glyph;button.title=label+" · drag or select then tap the staff";button.setAttribute("aria-label",label);button.setAttribute("aria-pressed","false");
  $("stamp-tools").append(button);
  button.onpointerdown=e=>{
    if(e.button!==0)return;
    pointer={id:e.pointerId,x:e.clientX,y:e.clientY,moved:false};
    button.setPointerCapture(e.pointerId);
  };
  button.onpointermove=e=>{
    if(!pointer||e.pointerId!==pointer.id)return;
    pointer.moved ||= Math.hypot(e.clientX-pointer.x,e.clientY-pointer.y)>5;
    if(!pointer.moved)return;
    const ghost=$("drag-pitch");ghost.hidden=false;ghost.textContent=glyph;ghost.style.left=e.clientX+"px";ghost.style.top=e.clientY+"px";
  };
  button.onpointerup=run(async e=>{
    if(!pointer||pointer.id!==e.pointerId)return;
    const moved=pointer.moved; pointer=null;$("drag-pitch").hidden=true;
    if(moved){chooseStamp(null);await applyStamp(tool,e.clientX,e.clientY);}
    else chooseStamp(stamp===tool?null:tool);
  });
  button.onpointercancel=()=>{pointer=null;$("drag-pitch").hidden=true;};
  button.onclick=e=>{if(e.detail===0)chooseStamp(stamp===tool?null:tool);};
}
$("pages").addEventListener("pointerdown",e=>{if(stamp&&!$("edit-strip").hidden)e.stopPropagation();},true);
$("pages").addEventListener("click",run(async e=>{
  if(!stamp||$("edit-strip").hidden)return;
  e.stopPropagation();const tool=stamp;chooseStamp(null);await applyStamp(tool,e.clientX,e.clientY);
}),true);
document.addEventListener("keydown",e=>{if(e.key==="Escape")chooseStamp(null);});
function navigation(open){
  document.body.classList.toggle("navigation-open",open);
  $("mobile-nav").setAttribute("aria-expanded",String(open));
}
$("mobile-nav").onclick=()=>navigation(!document.body.classList.contains("navigation-open"));
document.querySelector(".sidebar").addEventListener("click",e=>{if(e.target.closest("[data-score],[data-group],#library-nav,#trash-nav"))navigation(false);});
