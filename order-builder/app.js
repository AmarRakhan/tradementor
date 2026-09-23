(() => {
  const data = window.ORDER_DATA;
  const state = {
    view: 'packages',
    packageFilter: 'all',
    query: '',
    sort: 'az',
    packages: [],
    items: [],
    itemStatuses: {}
  };

  const categoryOrder = ['Laptops','Telefoons','iPads','Monitoren','Docks','Opladers','Toetsenbord / muizen','Tassen','Headsets','Telefoonaccessoires','iPad-accessoires','Accessoires','Verouderd'];
  const iconEmoji = {'Laptops':'💻','Telefoons':'📱','iPads':'▤','Monitoren':'🖥️','Docks':'▰','Opladers':'🔌','Toetsenbord / muizen':'⌨️','Tassen':'💼','Headsets':'🎧','Telefoonaccessoires':'📱','iPad-accessoires':'▤','Accessoires':'🔗','Verouderd':'📦'};
  const iconFor = c => {
    const emoji=iconEmoji[c]||'📦';
    const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="180" height="120" viewBox="0 0 180 120"><rect width="180" height="120" rx="12" fill="white"/><text x="90" y="79" text-anchor="middle" font-size="64" font-family="Segoe UI Emoji,Apple Color Emoji,sans-serif">${emoji}</text></svg>`;
    return 'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg);
  };
  const pkgThumb = p => iconFor(p.iconCategory || 'Laptops');
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const lower = s => String(s ?? '').toLocaleLowerCase('nl');

  function save(){
    try{ localStorage.setItem('amar-order-builder-v2', JSON.stringify({packages:state.packages,items:state.items,itemStatuses:state.itemStatuses})); }catch{}
  }
  function restore(){
    try{
      const saved = JSON.parse(localStorage.getItem('amar-order-builder-v2') || 'null');
      if(saved){ state.packages = Array.isArray(saved.packages)?saved.packages:[]; state.items = Array.isArray(saved.items)?saved.items:[]; state.itemStatuses = saved.itemStatuses && typeof saved.itemStatuses==='object' ? saved.itemStatuses : {}; }
    }catch{}
  }
  function toast(message){ const el=$('toast'); el.textContent=message; el.classList.add('show'); clearTimeout(toast.t); toast.t=setTimeout(()=>el.classList.remove('show'),1900); }

  function setView(view){
    state.view=view;
    document.body.classList.toggle('mode-packages',view==='packages');
    document.body.classList.toggle('mode-items',view==='items');
    $('tabPackages').classList.toggle('active',view==='packages');
    $('tabItems').classList.toggle('active',view==='items');
    $('packagesView').classList.toggle('hidden',view!=='packages');
    $('itemsView').classList.toggle('hidden',view!=='items');
    $('packageFilters').classList.toggle('hidden',view!=='packages');
    $('searchInput').placeholder=view==='packages'?'Zoek een pakket...':'Zoek een artikel...';
    $('searchInput').value=''; state.query='';
    render();
  }

  function packageSelected(index){ return state.packages.find(x=>x.index===index); }
  function itemSelected(code){ return state.items.find(x=>x.code===code); }

  function togglePackage(index){
    const pos=state.packages.findIndex(x=>x.index===index);
    if(pos>=0) state.packages.splice(pos,1); else state.packages.push({index,qty:1});
    save(); render();
  }
  function toggleItem(code){
    const pos=state.items.findIndex(x=>x.code===code);
    if(pos>=0) state.items.splice(pos,1); else state.items.push({code,qty:1,status:state.itemStatuses[code]||'Nieuw'});
    save(); render();
  }
  function setCatalogStatus(code,status){
    state.itemStatuses[code]=status;
    const sel=itemSelected(code); if(sel) sel.status=status;
    save(); renderItems(); renderOrder();
  }
  function setOrderItemStatus(code,status){
    state.itemStatuses[code]=status;
    const sel=itemSelected(code); if(sel) sel.status=status;
    save(); renderItems(); renderOrder();
  }
  function changeQty(kind,key,delta){
    const arr=kind==='package'?state.packages:state.items;
    const obj=kind==='package'?arr.find(x=>x.index===key):arr.find(x=>x.code===key);
    if(!obj)return; obj.qty+=delta; if(obj.qty<=0){ const i=arr.indexOf(obj); arr.splice(i,1); }
    save(); render();
  }
  function removeSelection(kind,key){
    const arr=kind==='package'?state.packages:state.items;
    const i=kind==='package'?arr.findIndex(x=>x.index===key):arr.findIndex(x=>x.code===key);
    if(i>=0)arr.splice(i,1); save(); render();
  }
  function clearOrder(){ state.packages=[]; state.items=[]; save(); render(); }

  function filteredPackages(){
    let list=data.packages.map((p,index)=>({...p,index}));
    if(state.packageFilter!=='all') list=list.filter(p=>p.badge===state.packageFilter);
    if(state.query) list=list.filter(p=>lower(p.name+' '+p.preview.join(' ')).includes(lower(state.query)));
    list.sort((a,b)=>state.sort==='az'?a.name.localeCompare(b.name,'nl'):b.name.localeCompare(a.name,'nl'));
    return list;
  }
  function renderPackages(){
    const list=filteredPackages();
    $('packagesEmpty').classList.toggle('hidden',list.length>0);
    $('packagesGrid').innerHTML=list.map(p=>{
      const selected=!!packageSelected(p.index);
      return `<button class="package-card ${selected?'selected':''}" type="button" data-package="${p.index}">
        <span class="check">✓</span>
        <div class="package-name">${esc(p.name)}</div>
        <span class="status-badge ${p.badge==='Refurb'?'refurb':''}">${esc(p.badge)}</span>
        <ul class="package-preview">${p.preview.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>
        <div class="package-count">${p.count} artikelen</div>
      </button>`;
    }).join('');
    document.querySelectorAll('[data-package]').forEach(el=>el.addEventListener('click',()=>togglePackage(+el.dataset.package)));
  }

  function filteredItems(){
    let list=data.items.slice();
    if(state.query) list=list.filter(x=>lower(x.name+' '+x.category).includes(lower(state.query)));
    list.sort((a,b)=>state.sort==='az'?a.name.localeCompare(b.name,'nl'):b.name.localeCompare(a.name,'nl'));
    return list;
  }
  function sectionClass(category,count){
    if(count>10) return 'wide';
    if(['Laptops','Telefoons','iPads'].includes(category)) return 'span4';
    if(category==='Monitoren') return 'span5';
    if(category==='Docks'||category==='Opladers') return 'span3';
    if(['Toetsenbord / muizen','Tassen','Headsets','Telefoonaccessoires','iPad-accessoires','Accessoires'].includes(category)) return 'span4';
    return '';
  }
  function renderItems(){
    const list=filteredItems();
    $('itemsEmpty').classList.toggle('hidden',list.length>0);
    const grouped=new Map(); list.forEach(it=>{ if(!grouped.has(it.category))grouped.set(it.category,[]); grouped.get(it.category).push(it); });
    const cats=[...grouped.keys()].sort((a,b)=>categoryOrder.indexOf(a)-categoryOrder.indexOf(b));
    $('categoriesGrid').innerHTML=cats.map(cat=>{
      const arr=grouped.get(cat); const sc=sectionClass(cat,arr.length);
      return `<section class="category-section ${sc}">
        <div class="category-title">${esc(cat)} (${arr.length})</div>
        <div class="product-grid">${arr.map(it=>{
          const sel=itemSelected(it.code); const status=sel?.status||state.itemStatuses[it.code]||'Nieuw';
          return `<button class="product-card ${sel?'selected':''}" type="button" data-item="${esc(it.code)}">
            <span class="check">✓</span>
            <div class="product-image-wrap"><img class="product-image" src="${iconFor(it.category)}" alt=""></div>
            <div class="product-name">${esc(it.name)}</div>
            <div class="product-category">${esc(it.category)}</div>
            <select class="status-select" data-status-code="${esc(it.code)}" aria-label="Voorraadstatus">
              <option ${status==='Nieuw'?'selected':''}>Nieuw</option>
              <option ${status==='Refurb'?'selected':''}>Refurb</option>
            </select>
          </button>`;
        }).join('')}</div>
      </section>`;
    }).join('');
    document.querySelectorAll('[data-item]').forEach(el=>el.addEventListener('click',e=>{ if(e.target.matches('select'))return; toggleItem(el.dataset.item); }));
    document.querySelectorAll('[data-status-code]').forEach(el=>{
      el.addEventListener('click',e=>e.stopPropagation());
      el.addEventListener('change',e=>{ e.stopPropagation(); setCatalogStatus(el.dataset.statusCode,el.value); });
    });
  }

  function expandedRows(){
    const rows=[];
    state.packages.forEach(sel=>{
      const p=data.packages[sel.index];
      p.items.forEach(it=>{ for(let q=0;q<sel.qty*(it.qty||1);q++) rows.push({code:it.code,status:it.status,label:it.label,source:p.name}); });
    });
    state.items.forEach(sel=>{
      const it=data.items.find(x=>x.code===sel.code); if(!it)return;
      for(let q=0;q<sel.qty;q++) rows.push({code:it.code,status:sel.status,label:it.name,source:'Los artikel'});
    });
    return rows;
  }
  function combinedContents(){
    const map=new Map(); expandedRows().forEach(r=>{ const k=r.label+'|'+r.status; const x=map.get(k)||{label:r.label,status:r.status,qty:0}; x.qty++; map.set(k,x); }); return [...map.values()];
  }
  function renderOrder(){
    const has=state.packages.length+state.items.length>0;
    $('orderEmpty').classList.toggle('hidden',has);
    $('orderList').classList.toggle('hidden',!has);
    const selectedCount=state.packages.length+state.items.length;
    $('orderCountLabel').textContent=has?`${selectedCount} selectie${selectedCount===1?'':'s'}`:'Nog niets geselecteerd';

    const cards=[];
    state.packages.forEach(sel=>{
      const p=data.packages[sel.index];
      cards.push(`<div class="order-card">
        <div class="order-thumb"><img src="${pkgThumb(p)}" alt=""></div>
        <div class="order-meta"><div class="order-name">${esc(p.name)}</div><div class="order-sub">Pakket</div>
          <div class="order-controls"><span class="status-badge ${p.badge==='Refurb'?'refurb':''}">${esc(p.badge)}</span>
          <span class="qty"><button type="button" data-qkind="package" data-key="${sel.index}" data-delta="-1">−</button><span>${sel.qty}</span><button type="button" data-qkind="package" data-key="${sel.index}" data-delta="1">+</button></span></div>
        </div>
        <button class="remove-order" type="button" data-rkind="package" data-rkey="${sel.index}">×</button>
      </div>`);
    });
    state.items.forEach(sel=>{
      const it=data.items.find(x=>x.code===sel.code); if(!it)return;
      cards.push(`<div class="order-card">
        <div class="order-thumb"><img src="${iconFor(it.category)}" alt=""></div>
        <div class="order-meta"><div class="order-name">${esc(it.name)}</div><div class="order-sub">${esc(it.category)}</div>
          <div class="order-controls"><select class="status-select" data-order-status="${esc(it.code)}"><option ${sel.status==='Nieuw'?'selected':''}>Nieuw</option><option ${sel.status==='Refurb'?'selected':''}>Refurb</option></select>
          <span class="qty"><button type="button" data-qkind="item" data-key="${esc(it.code)}" data-delta="-1">−</button><span>${sel.qty}</span><button type="button" data-qkind="item" data-key="${esc(it.code)}" data-delta="1">+</button></span></div>
        </div>
        <button class="remove-order" type="button" data-rkind="item" data-rkey="${esc(it.code)}">×</button>
      </div>`);
    });
    $('orderList').innerHTML=cards.join('');
    document.querySelectorAll('[data-qkind]').forEach(el=>el.addEventListener('click',()=>changeQty(el.dataset.qkind,el.dataset.qkind==='package'?+el.dataset.key:el.dataset.key,+el.dataset.delta)));
    document.querySelectorAll('[data-rkind]').forEach(el=>el.addEventListener('click',()=>removeSelection(el.dataset.rkind,el.dataset.rkind==='package'?+el.dataset.rkey:el.dataset.rkey)));
    document.querySelectorAll('[data-order-status]').forEach(el=>el.addEventListener('change',()=>setOrderItemStatus(el.dataset.orderStatus,el.value)));

    const combined=combinedContents();
    const showCombined=state.packages.length>0;
    $('packageContents').classList.toggle('hidden',!showCombined);
    $('expandedCount').textContent=showCombined?`(${expandedRows().length} artikelen)`:'';
    $('combinedRows').innerHTML=combined.slice(0,18).map(x=>`<div class="combined-row"><span>${esc(x.label)}</span><span class="n">${x.qty}</span></div>`).join('');

    const rows=expandedRows();
    const newCount=rows.filter(r=>r.status==='Nieuw').length, refurbCount=rows.length-newCount;
    $('sumArticles').textContent=new Set(rows.map(r=>r.code)).size;
    $('sumPieces').textContent=rows.length;
    $('sumNew').textContent=newCount;
    $('sumRefurb').textContent=refurbCount;
  }

  async function copyDynamics(){
    const rows=expandedRows(); if(!rows.length){toast('Selecteer eerst een pakket of artikel');return;}
    const txt=rows.map(r=>`${r.code}\t${r.status}`).join('\n');
    try{ await navigator.clipboard.writeText(txt); }
    catch{ const ta=document.createElement('textarea');ta.value=txt;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove(); }
    toast(`${rows.length} regels gekopieerd voor Dynamics`);
  }

  function renderCounts(){
    const n=data.packages.filter(p=>p.badge==='Nieuw').length, r=data.packages.length-n;
    $('allCount').textContent=`(${data.packages.length})`; $('newCount').textContent=`(${n})`; $('refurbCount').textContent=`(${r})`;
  }
  function render(){ renderCounts(); if(state.view==='packages')renderPackages(); else renderItems(); renderOrder(); }

  $('tabPackages').addEventListener('click',()=>setView('packages'));
  $('tabItems').addEventListener('click',()=>setView('items'));
  $('searchInput').addEventListener('input',e=>{state.query=e.target.value.trim();render();});
  $('sortSelect').addEventListener('change',e=>{state.sort=e.target.value;render();});
  document.querySelectorAll('[data-filter]').forEach(el=>el.addEventListener('click',()=>{state.packageFilter=el.dataset.filter;document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('active',x===el));renderPackages();}));
  $('clearOrder').addEventListener('click',clearOrder);
  $('copyButton').addEventListener('click',copyDynamics);
  const initial = new URLSearchParams(location.search).get('view')==='items' ? 'items' : 'packages';
  restore(); setView(initial);
})();