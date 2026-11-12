const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../../godseye/static/app.js'),'utf8');
function setup(checkpoints,runs=[],jobs=[]){
  const nodes=new Map(), calls=[];
  function el(tag='div'){return {tag,children:[],style:{},dataset:{},attrs:{},clientWidth:640,hidden:false,
    classList:{add(){}},setAttribute(k,v){this.attrs[k]=v;},append(...v){this.children.push(...v);},replaceChildren(...v){this.children=v;},focus(){this.focused=true;},prepend(v){this.children.unshift(v);},remove(){},
    set innerHTML(v){throw Error('Unsafe HTML '+v);}};}
  const $=id=>{if(!nodes.has(id))nodes.set(id,el());return nodes.get(id);};
  const ctx={$,state:{checkpoints,runs,jobs,mode:'local'},staticDemo:false,fmt:v=>v==null?'n/a':String(v),shortLabel:id=>checkpoints.find(c=>c.id===id)?.name||id,
    document:{createElement:el,createElementNS:(_,tag)=>el(tag),querySelector:()=>el()},
    showView:v=>calls.push(['view',v]),loadTensor:async()=>calls.push(['tensor']),sidebarCheckpoints(){},openRun:async id=>calls.push(['run',id]),
    CSS:{escape:s=>s},navigator:{},api(){throw Error('Selection must not mutate');}};
  vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('// Persisted-object board:'),source.indexOf('// Goal workflow:')),ctx);
  ctx.renderExperimentBoard();return {...ctx,nodes,calls};
}
const roots=[{id:'paper',name:'Original',parent:null},{id:'zero',name:'Zero',parent:null}];
test('only persisted ancestry and actual paired runs create graph objects and edges',async()=>{
  const cps=[...roots,{id:'a',name:'Ablated',parent:'paper',patch:'W3[0,1] = 0'},{id:'b',name:'Restored',parent:'a'}];
  const runs=[{id:'r1',base_id:'paper',candidate_id:'a',episodes:8,paired_mean_delta:-2,paired_se:1},{id:'r2',base_id:'a',candidate_id:'b',episodes:8,paired_mean_delta:2,paired_se:1}];
  const x=setup(cps,runs),graph=x.$('board-graph'),nodes=graph.children.filter(n=>n.dataset.objectId);
  assert.equal(nodes.length,6);assert.equal(graph.children[0].children.length,6);assert.equal(x.$('board-list').children.length,6);
  assert.equal(new Set(nodes.map(n=>n.style.left+':'+n.style.top)).size,6,'objects overlap');
  await nodes[2].onclick();assert.deepEqual(x.calls,[['view','workbench'],['tensor']]);assert.equal(x.$('inspect-model').value,'a');assert.equal(x.$('patch-base').value,'a');assert.equal(x.$('board-selection').focused,true);
  await nodes[4].onclick();assert.deepEqual(x.calls.slice(-2),[['run','r1'],['view','overview']]);
});
test('imported roots, missing parents, unevaluated checkpoints and cancelled jobs stay honest and inert',()=>{
  const x=setup([{id:'import',name:'<img onerror=bad>',parent:null,source_sha256:'abc'},{id:'orphan',name:'Unresolved',parent:'missing'}],[],[{id:'job',status:'cancelled',completed:1,total:4}]);
  const graph=x.$('board-graph');assert.equal(graph.children[0].children.length,0,'invented parent edge');
  assert.match(graph.children[1].children[2].textContent,/Imported original.*unverified.*no saved evaluation/);
  assert.equal(graph.children[1].children[1].textContent,'<img onerror=bad>');
  assert.match(graph.children[2].children[2].textContent,/Parent unavailable/);
  assert.match(x.$('board-activity').children[0].textContent,/cancelled.*no completed evidence/);
  assert.equal(graph.children.filter(n=>n.dataset.objectId?.startsWith('run:')).length,0);
});
test('list is a keyboard-operable alternative and Fit does not issue requests',()=>{
 const x=setup(roots);x.$('board-list').hidden=true;x.$('board-list-toggle').onclick();assert.equal(x.$('board-list').hidden,false);assert.equal(x.$('board-viewport').hidden,true);x.fitExperimentBoard();assert.deepEqual(x.calls,[]);
});
