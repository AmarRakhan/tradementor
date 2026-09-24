(() => {
  const data = window.ORDER_DATA;
  const state = {
    view: 'packages',
    packageFilter: 'all',
    query: '',
    sort: 'az',
    packages: [],
    items: [],
    itemStatuses: {},
    catalogAdditions: [],
    deletedItemCodes: [],
    learnedAliases: {},
    customPackages: []
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
    try{
      localStorage.setItem('amar-order-builder-v2', JSON.stringify({
        packages:state.packages,
        items:state.items,
        itemStatuses:state.itemStatuses,
        catalogAdditions:state.catalogAdditions,
        deletedItemCodes:state.deletedItemCodes,
        learnedAliases:state.learnedAliases,
        customPackages:state.customPackages
      }));
    }catch{}
  }
  function restore(){
    try{
      const saved = JSON.parse(localStorage.getItem('amar-order-builder-v2') || 'null');
      if(saved){
        state.packages = Array.isArray(saved.packages)?saved.packages:[];
        state.items = Array.isArray(saved.items)?saved.items:[];
        state.itemStatuses = saved.itemStatuses && typeof saved.itemStatuses==='object' ? saved.itemStatuses : {};
        state.catalogAdditions = Array.isArray(saved.catalogAdditions)?saved.catalogAdditions:[];
        state.deletedItemCodes = Array.isArray(saved.deletedItemCodes)?saved.deletedItemCodes:[];
        state.learnedAliases = saved.learnedAliases && typeof saved.learnedAliases==='object' ? saved.learnedAliases : {};
        state.customPackages = Array.isArray(saved.customPackages)?saved.customPackages:[];
        state.customPackages.forEach(pkg=>{
          if(!data.packages.some(p=>p.customId&&p.customId===pkg.customId)) data.packages.push(pkg);
        });
      }
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
    $('packageAdminActions')?.classList.toggle('hidden',view!=='packages');
    $('itemAdminActions').classList.toggle('hidden',view!=='items');
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

  function catalogItems(){
    const deleted=new Set(state.deletedItemCodes);
    const base=data.items.filter(x=>!deleted.has(x.code));
    const extra=state.catalogAdditions.slice();
    return [...base,...extra];
  }
  function getCatalogItem(code){ return catalogItems().find(x=>x.code===code); }

  function filteredItems(){
    let list=catalogItems().slice();
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
      const excluded=new Set(sel.excludedCodes||[]);
      p.items.filter(it=>!excluded.has(it.code)).forEach(it=>{
        for(let q=0;q<sel.qty*(it.qty||1);q++) rows.push({code:it.code,status:it.status,label:it.label,source:p.name});
      });
    });
    state.items.forEach(sel=>{
      const it=getCatalogItem(sel.code); if(!it)return;
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
        <div class="order-meta"><div class="order-name">${esc(p.name)}</div><div class="order-sub">Pakket${(sel.excludedCodes||[]).length?' · '+(sel.excludedCodes||[]).map(code=>code==='MD3J4ZM/A'?'zonder 20W-lader':'zonder '+code).join(', '):''}</div>
          <div class="order-controls"><span class="status-badge ${p.badge==='Refurb'?'refurb':''}">${esc(p.badge)}</span>
          <span class="qty"><button type="button" data-qkind="package" data-key="${sel.index}" data-delta="-1">−</button><span>${sel.qty}</span><button type="button" data-qkind="package" data-key="${sel.index}" data-delta="1">+</button></span></div>
        </div>
        <button class="remove-order" type="button" data-rkind="package" data-rkey="${sel.index}">×</button>
      </div>`);
    });
    state.items.forEach(sel=>{
      const it=getCatalogItem(sel.code); if(!it)return;
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

  const smartAliasRules=[
    {code:'54337282#ABH', patterns:['standaard laptop','m&r laptop','m en r laptop','m r laptop']},
    {code:'54337265#ABH', patterns:['monteur laptop','management laptop','managementlaptop','monteurlaptop']},
    {code:'54337313#ABH', patterns:['tekenlaptop','teken laptop','cad laptop','cad-laptop']},
    {code:'9X3V1UT#ABB', patterns:['standaard docking','standaard dock','standaard dockingstation']},
    {code:'AW5M5UT#ABB', patterns:['cad docking','cad dock','tekendocking','teken docking','teken dock','cad dockingstation']},
    {code:'671R3AA#ABB', patterns:['65w usb-c lader','65w usb c lader','usb-c 65w','usb c 65w','65w lader','usb-c lader 65w']},
    {code:'75615', patterns:['rj45','usb-c rj45','usb c rj45','netwerkadapter','netwerk adapter','ethernet adapter']},
    {code:'D31429-RPET', patterns:['rugtas','rugzak','backpack','laptop rugtas','laptoprugtas']}
  ];

  function normalizeSmartText(s){
    return String(s||'')
      .normalize('NFD').replace(/[\u0300-\u036f]/g,'')
      .toLowerCase()
      .replace(/usb\s*[-_/]?\s*c/g,'usbc')
      .replace(/rj\s*[-_]?\s*45/g,'rj45')
      .replace(/iphone\s*16\s*e/g,'iphone16e')
      .replace(/20\s*w/g,'20w')
      .replace(/\bcharger\b/g,'lader')
      .replace(/\bmouse\b/g,'muis')
      .replace(/\bbackpack\b/g,'rugtas')
      .replace(/\brugzak\b/g,'rugtas')
      .replace(/\bkeyboard\b/g,'toetsenbord')
      .replace(/\bheadset\b/g,'koptelefoon')
      .replace(/[^a-z0-9]+/g,' ')
      .replace(/\s+/g,' ')
      .trim();
  }

  function ticketMeaningRaw(s){
    let raw=String(s||'').trim();
    raw=raw.replace(/^\s*(serienummer|serialnummer|serial)\s*:\s*/i,'');
    // Alles vanaf een tweede dubbele punt met een serienummer/assetcode is metadata.
    raw=raw.replace(/\s*:\s*[A-Z0-9][A-Z0-9._-]{4,}.*$/i,'');
    raw=raw.replace(/[()]+\s*$/g,'').trim();
    return raw;
  }

  function ticketIntentText(s){
    return normalizeSmartText(ticketMeaningRaw(s))
      .replace(/\b(nieuw|refurb)\b/g,' ')
      .replace(/\s+/g,' ')
      .trim();
  }

  function ticketPackageText(s){
    return normalizeSmartText(ticketMeaningRaw(s)).trim();
  }

  function isNoiseTicketLine(line){
    const raw=String(line||'').trim();
    const n=normalizeSmartText(raw);
    if(!n) return true;

    // Administratieve ticketzinnen: nooit als artikel behandelen.
    if(n.includes('verwerken in dynamics')) return true;
    if(
      n.startsWith('meegegeven aan ') ||
      n.startsWith('afgegeven aan ') ||
      n.startsWith('overhandigd aan ') ||
      n.startsWith('uitgeleverd aan ') ||
      n.startsWith('geleverd aan ') ||
      n.startsWith('toegewezen aan ') ||
      n.startsWith('verstuurd op ') ||
      n.startsWith('verzonden op ') ||
      n.startsWith('verwerkt op ') ||
      n.startsWith('aangemaakt op ') ||
      n.startsWith('datum ') ||
      n.startsWith('datum van ') ||
      n.startsWith('verwerkt door ') ||
      n.startsWith('behandeld door ') ||
      n.startsWith('medewerker ')
    ) return true;

    // Pure datum-/tijdregels zijn metadata.
    if(/^\s*\d{1,2}[-\/.]\d{1,2}[-\/.]\d{2,4}(?:\s+\d{1,2}:\d{2})?\s*$/.test(raw)) return true;

    if(n==='esim geactiveerd' || n==='esim actief' || n==='geactiveerd') return true;

    // "serienummer:" is géén ruis als op dezelfde regel ook een product staat.
    if(/^(geen|zonder)\b/.test(n)) return true;
    if(n.includes('niet geleverd') || n.includes('niet meegeleverd') || n.includes('ontbreekt')) return true;
    return false;
  }

  function findIphone16ePackageIndex(){
    return data.packages.findIndex(p=>normalizeSmartText(p.name)==='iphone16e nieuw');
  }

  function detectTicketPackageIntents(text){
    const lines=String(text||'').split(/\r?\n|;/).map(x=>x.trim()).filter(Boolean);
    const found=[];

    for(const line of lines){
      const meaning=ticketPackageText(line);
      if(!meaning) continue;

      // Harde bedrijfsregel:
      // SM-G556BZKDEEB / Samsung XCover 7 wordt altijd als compleet pakket uitgegeven.
      if(
        meaning.includes('sm g556bzkdeeb') ||
        meaning.includes('smg556bzkdeeb') ||
        meaning.includes('samsung xcover 7') ||
        meaning.includes('xcover 7')
      ){
        const xcoverIndex=data.packages.findIndex(p=>normalizeSmartText(p.name)==='samsung xcover 7 nieuw');
        if(xcoverIndex>=0 && !found.some(x=>x.index===xcoverIndex)){
          found.push({
            index:xcoverIndex,
            qty:1,
            excludedCodes:[],
            label:'Samsung Xcover 7 nieuw'
          });
        }
        continue;
      }

      // Harde bedrijfsregel:
      // "iPad 11 nieuw" betekent ALTIJD Apple iPad 11 2025
      // en moet dus het pakket "iPad 11 nieuw" kiezen.
      if(meaning.includes('ipad 11') && meaning.includes('nieuw')){
        const ipad11Index=data.packages.findIndex(p=>normalizeSmartText(p.name)==='ipad 11 nieuw');
        if(ipad11Index>=0 && !found.some(x=>x.index===ipad11Index)){
          found.push({
            index:ipad11Index,
            qty:1,
            excludedCodes:[],
            label:'Apple iPad 11 2025'
          });
        }
        continue;
      }

      // Exacte pakketnamen uit onze catalogus winnen van losse artikelmatching.
      let bestIndex=-1;
      let bestLen=0;
      data.packages.forEach((p,index)=>{
        const pn=normalizeSmartText(p.name);
        if(pn && meaning.includes(pn) && pn.length>bestLen){
          bestIndex=index;
          bestLen=pn.length;
        }
      });

      // Veelgebruikte schrijfwijze: "iPhone 16 e" / "iphone16e".
      if(bestIndex<0 && meaning.includes('iphone16e')){
        bestIndex=findIphone16ePackageIndex();
      }

      if(bestIndex>=0 && !found.some(x=>x.index===bestIndex)){
        found.push({index:bestIndex,qty:1,excludedCodes:[],label:data.packages[bestIndex].name});
      }
    }

    // Uitsluitingen gelden op het herkende pakket in dezelfde tickettekst.
    const all=normalizeSmartText(text);
    const no20w=
      /\bgeen\s+20w\b/.test(all) ||
      /\bzonder\s+20w\b/.test(all) ||
      /\bgeen\s+(20w\s+)?(lader|blokje|adapter)\b/.test(all) ||
      /\bzonder\s+(20w\s+)?(lader|blokje|adapter)\b/.test(all) ||
      /\b(lader|blokje|adapter)\b.{0,25}\b(niet geleverd|niet meegeleverd|ontbreekt)\b/.test(all);

    if(no20w){
      found.forEach(x=>{
        if(data.packages[x.index]?.items?.some(it=>it.code==='MD3J4ZM/A')) x.excludedCodes.push('MD3J4ZM/A');
      });
    }

    return found;
  }

  function parseTicketLines(text){
    return String(text||'')
      .split(/\r?\n|;/)
      .map(x=>x.trim())
      .filter(Boolean)
      .filter(line=>!isNoiseTicketLine(line))
      .filter(line=>!isAdministrativeMeaning(line))
      .map((raw,index)=>{
        let line=raw.replace(/^[-•*]+\s*/,'').trim();
        line=ticketMeaningRaw(line);
        let qty=1;
        let m=line.match(/^(\d+)\s*[x×]\s*(.+)$/i);
        if(m){ qty=Math.max(1,Number(m[1])); line=m[2].trim(); }
        else{
          m=line.match(/^x\s*(\d+)\s+(.+)$/i);
          if(m){ qty=Math.max(1,Number(m[1])); line=m[2].trim(); }
          else{
            m=line.match(/^(.+?)\s+[x×]\s*(\d+)$/i);
            if(m){ line=m[1].trim(); qty=Math.max(1,Number(m[2])); }
          }
        }
        return {id:index,raw,query:line,qty};
      });
  }

  function tokenSet(s){
    const stop=new Set(['een','de','het','voor','van','met','en','nieuw','refurb','artikel','artikelen','stuks','stuk','x']);
    return new Set(normalizeSmartText(s).split(' ').filter(x=>x.length>1&&!stop.has(x)));
  }

  function scoreCandidate(query,item){
    const q=tokenSet(query);
    const candidateText=normalizeSmartText(item.name+' '+item.category);
    const ct=tokenSet(candidateText);
    if(!q.size) return 0;
    let overlap=0;
    q.forEach(t=>{ if(ct.has(t)) overlap+=1; });
    let score=overlap/q.size;

    const nq=normalizeSmartText(query);
    const nn=normalizeSmartText(item.name);
    const nc=normalizeSmartText(item.category);

    if(nn===nq) score+=0.7;
    else if(nn.includes(nq)||nq.includes(nn)) score+=0.38;

    if(nq.includes('lader') && (nn.includes('lader')||nn.includes('adapter'))) score+=0.22;
    if(nq.includes('rj45') && nn.includes('rj45')) score+=0.45;
    if(nq.includes('rugtas') && (nn.includes('rugtas')||nc.includes('tassen'))) score+=0.35;
    if(nq.includes('muis')){
      if(nn.includes('muis')||nn.includes('lift')) score+=0.65;
      else if(nc.includes('muizen')) score+=0.22;
      if(nn.includes('toetsenbord')||nn.includes('keyboard')||nn.includes('kbd')) score-=0.55;
    }
    if(nq.includes('toetsenbord')){
      if(nn.includes('toetsenbord')||nn.includes('keyboard')||nn.includes('kbd')) score+=0.6;
      else if(nc.includes('muizen')) score+=0.18;
      if(nn.includes('muis')||nn.includes('lift')) score-=0.5;
    }
    if(nq.includes('monitor') && nc.includes('monitor')) score+=0.3;
    if(nq.includes('dock') && nc.includes('docks')) score+=0.3;
    if((nq.includes('iphone')||nq.includes('telefoon')) && nc.includes('telefoon')) score+=0.25;
    if((nq.includes('ipad')||nq.includes('tablet')) && nc.includes('ipad')) score+=0.25;
    if(nq.includes('headset')||nq.includes('koptelefoon')){ if(nc.includes('headsets')) score+=0.3; }

    return score;
  }

  function resolveFixedBusinessRule(query){
    const nq=ticketIntentText(query);
    const directRules=[
      {code:'54337282#ABH', terms:['standaard laptop','m&r laptop','m en r laptop','m r laptop']},
      {code:'54337265#ABH', terms:['monteur laptop','management laptop','managementlaptop','monteurlaptop']},
      {code:'54337313#ABH', terms:['tekenlaptop','teken laptop','cad laptop','cad-laptop']},
      {code:'9X3V1UT#ABB', terms:['standaard docking','standaard dock','standaard dockingstation']},
      {code:'AW5M5UT#ABB', terms:['cad docking','cad dock','tekendocking','teken docking','teken dock','cad dockingstation']}
    ];
    for(const rule of directRules){
      if(rule.terms.some(term=>nq.includes(ticketIntentText(term)))){
        const item=getCatalogItem(rule.code) || data.items.find(x=>x.code===rule.code);
        if(item) return item;
      }
    }
    return null;
  }

  function rankSmartMatches(query){
    const nq=ticketIntentText(query);

    // Harde bedrijfsregels winnen altijd van fuzzy matching of eerder geleerde keuzes.
    for(const rule of smartAliasRules){
      if(rule.patterns.some(p=>{
        const np=ticketIntentText(p);
        // Voor nu telt alleen de betekenis van het artikel/pakket.
        // Extra tekst zoals serienummers, assetnummers, namen en opmerkingen negeren we.
        return np && nq.includes(np);
      })){
        const exact=getCatalogItem(rule.code);
        if(exact) return [{item:exact,confidence:3,reason:'vaste bedrijfsregel'}];
      }
    }

    const learnedCode=state.learnedAliases[nq];
    if(learnedCode){
      const learnedItem=getCatalogItem(learnedCode);
      if(learnedItem) return [{item:learnedItem,confidence:2,reason:'geleerde keuze'}];
    }

    // Generieke muisvraag: toon bewust alle echte muismodellen, inclusief
    // Logitech Lift links/rechts, maar filter toetsenborden uit dezelfde Excelcategorie weg.
    if(nq==='muis' || nq==='muizen' || nq==='mouse' || nq.includes('ergonomische muis')){
      const mouseItems=catalogItems().filter(item=>{
        const n=normalizeSmartText(item.name);
        const cat=normalizeSmartText(item.category);
        const looksMouse=
          n.includes('muis') ||
          n.includes('mouse') ||
          n.includes('logitech lift') ||
          n.includes('lift right') ||
          n.includes('lift left');
        const looksKeyboard=
          n.includes('toetsenbord') ||
          n.includes('keyboard') ||
          n.includes('kbd');
        return !looksKeyboard && (looksMouse || (cat.includes('muizen') && n.includes('lift')));
      });
      if(mouseItems.length){
        return mouseItems.map((item,index)=>({
          item,
          confidence:1.15-(index*.02),
          reason:'muismodellen'
        })).slice(0,6);
      }
    }

    return catalogItems()
      .map(item=>({item,confidence:scoreCandidate(query,item),reason:'catalogusmatch'}))
      .filter(x=>x.confidence>=0.25)
      .sort((a,b)=>b.confidence-a.confidence)
      .slice(0,5);
  }

  function isAdministrativeMeaning(text){
    const raw=String(text||'').trim();
    const n=normalizeSmartText(raw);
    if(!n) return true;
    if(
      n.includes('verwerken in dynamics') ||
      n.startsWith('verstuurd op ') ||
      n.startsWith('verzonden op ') ||
      n.startsWith('verwerkt op ') ||
      n.startsWith('aangemaakt op ') ||
      n.startsWith('datum ') ||
      n.startsWith('datum van ') ||
      n.startsWith('meegegeven aan ') ||
      n.startsWith('afgegeven aan ') ||
      n.startsWith('overhandigd aan ') ||
      n.startsWith('uitgeleverd aan ') ||
      n.startsWith('geleverd aan ') ||
      n.startsWith('toegewezen aan ') ||
      n.startsWith('verwerkt door ') ||
      n.startsWith('behandeld door ') ||
      n.startsWith('medewerker ')
    ) return true;
    if(/^\d{1,2}\s+\d{1,2}\s+\d{2,4}$/.test(n)) return true;
    return false;
  }

  function fragmentSearchText(text){
    return normalizeSmartText(text).replace(/\b(nieuw|refurb)\b/g,' ').replace(/\s+/g,' ').trim();
  }

  function fragmentQty(text, phrase){
    const hay=fragmentSearchText(text);
    const p=ticketIntentText(phrase).replace(/[.*+?^$()|[\]\\]/g,'\\$&');
    if(!p) return 1;
    let m=hay.match(new RegExp('(?:^|\\s)(\\d+)\\s*x?\\s+'+p+'(?:\\s|$)','i'));
    if(m) return Math.max(1,Number(m[1])||1);
    m=hay.match(new RegExp('(?:^|\\s)'+p+'\\s*x\\s*(\\d+)(?:\\s|$)','i'));
    return m?Math.max(1,Number(m[1])||1):1;
  }

  function scanWholeTicketFragments(text){
    const hay=fragmentSearchText(text);
    const out=[];
    const codes=new Set();
    const phrases=[];

    function addAuto(code, phrase, reason){
      if(codes.has(code)) return;
      const item=getCatalogItem(code)||data.items.find(x=>x.code===code);
      if(!item) return;
      codes.add(code);
      const p=ticketIntentText(phrase);
      if(p) phrases.push(p);
      out.push({
        id:'fragment-'+out.length, raw:phrase, query:phrase, qty:fragmentQty(text,phrase),
        suggestions:[{item:item,confidence:99,reason:reason||'fragmentherkenning'}],
        selectedCode:item.code, auto:true, fragment:true
      });
    }

    smartAliasRules.forEach(rule=>{
      const hits=rule.patterns.map(p=>({raw:p,n:ticketIntentText(p)})).filter(x=>x.n&&hay.includes(x.n)).sort((a,b)=>b.n.length-a.n.length);
      if(hits.length) addAuto(rule.code,hits[0].raw,'vaste bedrijfsregel');
    });

    Object.entries(state.learnedAliases||{}).forEach(([alias,code])=>{
      const n=ticketIntentText(alias);
      if(n&&n.length>=3&&hay.includes(n)) addAuto(code,alias,'geleerde keuze');
    });

    catalogItems().slice().sort((a,b)=>normalizeSmartText(b.name).length-normalizeSmartText(a.name).length).forEach(item=>{
      if(codes.has(item.code)) return;
      const n=ticketIntentText(item.name);
      if(n.length>=5&&hay.includes(n)) addAuto(item.code,item.name,'artikelnaam gevonden');
    });

    const mousePresent=/(?:^|\s)(?:\d+\s*x?\s+)?(?:muis|muizen|mouse)(?:\s|$)/i.test(hay);
    const mouseAlready=out.some(r=>{const it=getCatalogItem(r.selectedCode);return it&&normalizeSmartText(it.category).includes('muizen');});
    if(mousePresent&&!mouseAlready){
      const candidates=catalogItems().filter(item=>{
        const n=normalizeSmartText(item.name), cat=normalizeSmartText(item.category);
        const mouse=n.includes('muis')||n.includes('mouse')||n.includes('logitech lift')||n.includes('lift right')||n.includes('lift left');
        const keyboard=n.includes('toetsenbord')||n.includes('keyboard')||n.includes('kbd');
        return !keyboard&&(mouse||(cat.includes('muizen')&&n.includes('lift')));
      });
      if(candidates.length){
        const m=hay.match(/(?:^|\s)(\d+)\s*x?\s+(?:muis|muizen|mouse)(?:\s|$)/i);
        out.push({id:'fragment-'+out.length,raw:'muis',query:'muis',qty:m?Math.max(1,Number(m[1])||1):1,
          suggestions:candidates.map((item,i)=>({item:item,confidence:1.2-i*.02,reason:'muismodellen'})).slice(0,6),
          selectedCode:null,auto:false,fragment:true});
        phrases.push('muis','muizen','mouse');
      }
    }

    return {results:out,phrases:phrases};
  }

  function analyzeTicketText(text){
    const packageTexts=new Set(detectTicketPackageIntents(text).map(x=>normalizeSmartText(data.packages[x.index].name)));
    const scanned=scanWholeTicketFragments(text);
    const results=scanned.results.slice();

    parseTicketLines(text)
      .filter(line=>!Array.from(packageTexts).some(pn=>ticketPackageText(line.query).includes(pn)))
      .filter(line=>{
        const n=ticketIntentText(line.query);
        return !scanned.phrases.some(p=>p&&n.includes(p));
      })
      .forEach(line=>{
        const fixed=resolveFixedBusinessRule(line.query);
        const suggestions=fixed?[{item:fixed,confidence:99,reason:'vaste bedrijfsregel'}]:rankSmartMatches(line.query);
        const first=suggestions[0]||null, second=suggestions[1]||null;
        let selectedCode=fixed?fixed.code:null, auto=!!fixed;
        const nq=ticketIntentText(line.query);
        const genericTerms=new Set(['muis','toetsenbord','monitor','headset','koptelefoon','dock','lader','oplader','telefoon','iphone','ipad','tablet','rugtas','tas','screenprotector','hoes','case']);
        const genericAmbiguous=genericTerms.has(nq)&&suggestions.length>1;
        if(!fixed&&first&&!genericAmbiguous){
          const gap=second?first.confidence-second.confidence:first.confidence;
          if(first.confidence>=1.35||(first.confidence>=0.85&&gap>=0.28)){selectedCode=first.item.code;auto=true;}
        }
        if(!selectedCode&&suggestions.length===0&&isAdministrativeMeaning(line.query)) return;
        if(selectedCode&&results.some(r=>r.selectedCode===selectedCode)) return;
        results.push({...line,suggestions:suggestions,selectedCode:selectedCode,auto:auto});
      });
    return results;
  }
  function renderTicketPreview(results){
    const box=$('ticketMatchPreview'); if(!box)return;
    box.classList.remove('hidden');

    const packageIntents=window.__ticketPackageIntents||[];
    const resolvedItems=results.filter(x=>x.selectedCode).length;
    const unresolvedItems=results.filter(x=>!x.selectedCode).length;

    const packageRows=packageIntents.map(intent=>{
      const p=data.packages[intent.index];
      const exclusions=intent.excludedCodes||[];
      const extra=exclusions.includes('MD3J4ZM/A')?' · zonder 20W-lader':'';
      return `<div class="ticket-package-row">
        <div class="ticket-package-check">✓</div>
        <div class="ticket-package-name"><strong>${esc(p.name)}</strong>${esc(extra)}</div>
        <div class="ticket-confidence good">Pakket herkend</div>
      </div>`;
    }).join('');

    const headerText = packageIntents.length
      ? `${packageIntents.length} pakket${packageIntents.length===1?'':'ten'} herkend${results.length?' · '+resolvedItems+' van '+results.length+' losse regels gekozen':''}`
      : `${resolvedItems} van ${results.length} regels gekozen · klik een suggestie bij twijfel`;

    const itemRows=results.map(r=>{
      const chosen=r.selectedCode ? getCatalogItem(r.selectedCode) : null;
      const sugg=r.suggestions.slice(0,4);
      return `<div class="ticket-line-block" data-ticket-line="${r.id}">
        <div class="ticket-line-main">
          <div class="ticket-source">${esc(r.query)}</div>
          <div class="ticket-qty">${r.qty}×</div>
          <div class="ticket-result">${chosen?esc(chosen.name):(sugg.length?'Kies hieronder':'Geen suggesties gevonden')}</div>
          <div class="ticket-confidence ${chosen?'good':'warn'}">${chosen?(r.auto?'Automatisch':'Gekozen'):'Keuze nodig'}</div>
        </div>
        <div class="ticket-suggestions">
          ${sugg.map(s=>`<button type="button" class="ticket-suggestion ${r.selectedCode===s.item.code?'selected':''}" data-ticket-pick-line="${r.id}" data-ticket-pick-code="${esc(s.item.code)}">
            <span class="ticket-suggestion-name">${esc(s.item.name)}</span>
            <span class="ticket-suggestion-cat">${esc(s.item.category)}</span>
          </button>`).join('')}
        </div>
      </div>`;
    }).join('');

    box.innerHTML=`<div class="ticket-preview-head">${headerText}</div>`+packageRows+itemRows;

    document.querySelectorAll('[data-ticket-pick-line]').forEach(btn=>{
      btn.addEventListener('click',()=>{
        const id=Number(btn.dataset.ticketPickLine);
        const code=btn.dataset.ticketPickCode;
        const row=window.__ticketResults?.find(x=>x.id===id);
        if(!row)return;
        row.selectedCode=code;
        row.auto=false;
        state.learnedAliases[ticketIntentText(row.query)]=code;
        save();
        renderTicketPreview(window.__ticketResults);
      });
    });
  }

  function previewTicket(){
    const text=$('ticketPasteInput')?.value||'';
    if(!text.trim()){toast('Plak eerst de tickettekst');return;}
    window.__ticketResults=analyzeTicketText(text);
    window.__ticketPackageIntents=detectTicketPackageIntents(text);
    window.__ticketText=text;
    renderTicketPreview(window.__ticketResults);
  }

  function applyTicket(){
    const text=$('ticketPasteInput')?.value||'';
    if(!text.trim()){toast('Plak eerst de tickettekst');return;}

    const currentText=window.__ticketText||'';
    if(!window.__ticketResults || currentText!==text){
      window.__ticketResults=analyzeTicketText(text);
      window.__ticketPackageIntents=detectTicketPackageIntents(text);
      window.__ticketText=text;
    }
    const results=window.__ticketResults;
    renderTicketPreview(results);

    const packageIntents=window.__ticketPackageIntents||[];
    const unresolved=results.filter(r=>!r.selectedCode && (r.suggestions||[]).length>0);
    const ignored=results.filter(r=>!r.selectedCode && !(r.suggestions||[]).length);
    if(unresolved.length){
      toast(`${unresolved.length} regel(s) hebben nog een keuze nodig`);
      return;
    }

    // Regels zonder enige productmatch blokkeren een reeds herkend pakket niet.
    // Dit voorkomt dat datum/status/administratieve tekst de workflow stilzet.
    if(packageIntents.length && ignored.length){
      ignored.forEach(r=>{ r.ignored=true; });
    }

    let added=0;
    packageIntents.forEach(packageIntent=>{
      const existing=state.packages.find(x=>x.index===packageIntent.index);
      if(existing){
        existing.qty=Math.max(existing.qty,packageIntent.qty||1);
        existing.excludedCodes=[...new Set([...(existing.excludedCodes||[]),...(packageIntent.excludedCodes||[])])];
      }else{
        state.packages.push({
          index:packageIntent.index,
          qty:packageIntent.qty||1,
          excludedCodes:[...(packageIntent.excludedCodes||[])]
        });
      }
      added+=data.packages[packageIntent.index].items
        .filter(it=>!(packageIntent.excludedCodes||[]).includes(it.code))
        .reduce((n,it)=>n+(it.qty||1)*(packageIntent.qty||1),0);
    });
    results.filter(r=>r.selectedCode).forEach(r=>{
      const item=getCatalogItem(r.selectedCode); if(!item)return;
      let sel=itemSelected(item.code);
      const status=state.itemStatuses[item.code]||item.defaultStatus||'Nieuw';
      if(sel) sel.qty+=r.qty;
      else state.items.push({code:item.code,qty:r.qty,status});
      state.learnedAliases[ticketIntentText(r.query)]=item.code;
      added+=r.qty;
    });

    save();
    render();
    toast(`${added} stuks toegevoegd aan de order`);
    closeTicketModal();
  }

  function openTicketModal(){
    if(!$('ticketPasteModal')) return;
    $('ticketPasteModal').classList.remove('hidden');
    $('ticketPasteInput').value='';
    $('ticketMatchPreview').classList.add('hidden');
    $('ticketMatchPreview').innerHTML='';
    window.__ticketResults=null;
    window.__ticketPackageIntents=[];
    window.__ticketText='';
    setTimeout(()=>$('ticketPasteInput').focus(),0);
  }
  function closeTicketModal(){ $('ticketPasteModal')?.classList.add('hidden'); }

  let packageDraftRows=[];

  function openPackageModal(){
    if(!$('packageModal')) return;
    $('packageModal').classList.remove('hidden');
    $('newPackageName').value='';
    $('newPackageBadge').value='Nieuw';
    packageDraftRows=[];
    addPackageBuilderRow();
    setTimeout(()=>$('newPackageName').focus(),0);
  }

  function closePackageModal(){ $('packageModal')?.classList.add('hidden'); }

  function addPackageBuilderRow(){
    const list=catalogItems();
    if(!list.length){ toast('Geen artikelen beschikbaar'); return; }
    const first=list[0];
    packageDraftRows.push({
      code:first.code,
      status:$('newPackageBadge')?.value||'Nieuw',
      qty:1
    });
    renderPackageBuilderRows();
  }

  function removePackageBuilderRow(index){
    packageDraftRows.splice(index,1);
    renderPackageBuilderRows();
  }

  function renderPackageBuilderRows(){
    const box=$('packageBuilderRows'); if(!box)return;
    const list=catalogItems().slice().sort((a,b)=>a.name.localeCompare(b.name,'nl'));
    if(!packageDraftRows.length){
      box.innerHTML='<div class="package-builder-empty">Nog geen artikelen toegevoegd.</div>';
      return;
    }
    box.innerHTML=packageDraftRows.map((row,index)=>`
      <div class="package-row">
        <select data-package-row-code="${index}">
          ${list.map(item=>`<option value="${esc(item.code)}" ${item.code===row.code?'selected':''}>${esc(item.name)} — ${esc(item.code)}</option>`).join('')}
        </select>
        <select data-package-row-status="${index}">
          <option ${row.status==='Nieuw'?'selected':''}>Nieuw</option>
          <option ${row.status==='Refurb'?'selected':''}>Refurb</option>
        </select>
        <input data-package-row-qty="${index}" type="number" min="1" max="99" value="${row.qty}">
        <button class="remove-package-row" data-remove-package-row="${index}" type="button">×</button>
      </div>
    `).join('');

    document.querySelectorAll('[data-package-row-code]').forEach(el=>el.addEventListener('change',()=>{
      packageDraftRows[+el.dataset.packageRowCode].code=el.value;
    }));
    document.querySelectorAll('[data-package-row-status]').forEach(el=>el.addEventListener('change',()=>{
      packageDraftRows[+el.dataset.packageRowStatus].status=el.value;
    }));
    document.querySelectorAll('[data-package-row-qty]').forEach(el=>el.addEventListener('change',()=>{
      packageDraftRows[+el.dataset.packageRowQty].qty=Math.max(1,Number(el.value)||1);
      el.value=packageDraftRows[+el.dataset.packageRowQty].qty;
    }));
    document.querySelectorAll('[data-remove-package-row]').forEach(el=>el.addEventListener('click',()=>removePackageBuilderRow(+el.dataset.removePackageRow)));
  }

  function saveCustomPackage(){
    const name=$('newPackageName')?.value.trim();
    const badge=$('newPackageBadge')?.value||'Nieuw';
    if(!name){ toast('Vul een pakketnaam in'); $('newPackageName')?.focus(); return; }
    if(!packageDraftRows.length){ toast('Voeg minimaal één artikel toe'); return; }

    if(data.packages.some(p=>normalizeSmartText(p.name)===normalizeSmartText(name))){
      toast('Er bestaat al een pakket met deze naam');
      return;
    }

    const catalog=catalogItems();
    const items=[];
    packageDraftRows.forEach(row=>{
      const item=catalog.find(x=>x.code===row.code);
      if(!item) return;
      const qty=Math.max(1,Number(row.qty)||1);
      items.push({
        code:item.code,
        status:row.status||badge,
        qty,
        label:item.name
      });
    });
    if(!items.length){ toast('Geen geldige artikelen in pakket'); return; }

    const preview=[];
    items.forEach(it=>{ for(let q=0;q<it.qty;q++) preview.push(it.label); });
    const firstItem=catalog.find(x=>x.code===items[0].code);
    const pkg={
      custom:true,
      customId:'pkg-'+Date.now()+'-'+Math.random().toString(36).slice(2,7),
      name,
      badge,
      items,
      count:items.reduce((n,it)=>n+it.qty,0),
      preview,
      iconCategory:firstItem?.category||'Accessoires'
    };

    state.customPackages.push(pkg);
    data.packages.push(pkg);
    save();
    closePackageModal();
    render();
    toast('Pakket toegevoegd');
  }

  function populateCategorySelect(){
    $('newArticleCategory').innerHTML=categoryOrder.map(cat=>`<option>${esc(cat)}</option>`).join('');
  }
  function openArticleModal(mode){
    const manage=mode==='manage';
    $('articleModal').classList.remove('hidden');
    $('addArticleSection').classList.toggle('hidden',manage);
    $('manageArticleSection').classList.toggle('hidden',!manage);
    $('articleModalTitle').textContent=manage?'Artikelen beheren':'Artikel toevoegen';
    if(manage){
      $('manageArticleSearch').value='';
      renderManageArticles();
      setTimeout(()=>$('manageArticleSearch').focus(),0);
    }else{
      populateCategorySelect();
      $('newArticleCode').value='';
      $('newArticleName').value='';
      $('newArticleStatus').value='Nieuw';
      setTimeout(()=>$('newArticleCode').focus(),0);
    }
  }
  function closeArticleModal(){ $('articleModal').classList.add('hidden'); }

  function addCatalogArticle(){
    const code=$('newArticleCode').value.trim();
    const name=$('newArticleName').value.trim();
    const category=$('newArticleCategory').value;
    const status=$('newArticleStatus').value;
    if(!code){ toast('Vul een artikelcode in'); $('newArticleCode').focus(); return; }
    if(!name){ toast('Vul een artikelnaam in'); $('newArticleName').focus(); return; }
    const existing=catalogItems().find(x=>lower(x.code)===lower(code));
    if(existing){ toast('Deze artikelcode bestaat al'); return; }

    const baseExisting=data.items.find(x=>lower(x.code)===lower(code));
    if(baseExisting && state.deletedItemCodes.includes(baseExisting.code)){
      state.deletedItemCodes=state.deletedItemCodes.filter(x=>x!==baseExisting.code);
      state.itemStatuses[baseExisting.code]=status;
      save();
      closeArticleModal();
      render();
      toast('Bestaand artikel hersteld');
      return;
    }

    state.catalogAdditions.push({code,name,category,defaultStatus:status,custom:true});
    state.itemStatuses[code]=status;
    save();
    closeArticleModal();
    render();
    toast('Artikel toegevoegd');
  }

  function deleteCatalogArticle(code){
    const it=getCatalogItem(code); if(!it)return;
    if(!confirm(`Artikel "${it.name}" verwijderen uit de catalogus?`)) return;

    state.catalogAdditions=state.catalogAdditions.filter(x=>x.code!==code);
    if(data.items.some(x=>x.code===code) && !state.deletedItemCodes.includes(code)) state.deletedItemCodes.push(code);
    state.items=state.items.filter(x=>x.code!==code);
    delete state.itemStatuses[code];
    save();
    render();
    renderManageArticles();
    toast('Artikel verwijderd');
  }

  function renderManageArticles(){
    const q=lower($('manageArticleSearch').value.trim());
    let list=catalogItems().filter(x=>!q||lower(x.name+' '+x.code+' '+x.category).includes(q));
    list.sort((a,b)=>a.name.localeCompare(b.name,'nl'));
    $('manageArticleCount').textContent=`${list.length} artikelen`;
    $('manageArticleList').innerHTML=list.length?list.map(it=>`
      <div class="manage-article-row">
        <div class="manage-article-main">
          <div class="manage-article-name">${esc(it.name)}</div>
          <div class="manage-article-code">${esc(it.code)}</div>
        </div>
        <div class="manage-article-category">${esc(it.category)}</div>
        <div class="manage-article-status">${esc(state.itemStatuses[it.code]||it.defaultStatus||'Nieuw')}</div>
        <button class="delete-article-button" type="button" data-delete-code="${esc(it.code)}">Verwijderen</button>
      </div>`).join(''):`<div class="manage-empty">Geen artikelen gevonden.</div>`;
    document.querySelectorAll('[data-delete-code]').forEach(el=>el.addEventListener('click',()=>deleteCatalogArticle(el.dataset.deleteCode)));
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
  $('createPackageButton')?.addEventListener('click',openPackageModal);
  $('addPackageRowButton')?.addEventListener('click',addPackageBuilderRow);
  $('savePackageButton')?.addEventListener('click',saveCustomPackage);
  document.querySelectorAll('[data-close-package-modal]').forEach(el=>el.addEventListener('click',closePackageModal));
  $('ticketPasteButton')?.addEventListener('click',openTicketModal);
  $('previewTicketButton')?.addEventListener('click',previewTicket);
  $('applyTicketButton')?.addEventListener('click',applyTicket);
  document.querySelectorAll('[data-close-ticket-modal]').forEach(el=>el.addEventListener('click',closeTicketModal));
  $('addArticleButton')?.addEventListener('click',()=>openArticleModal('add'));
  $('manageArticlesButton')?.addEventListener('click',()=>openArticleModal('manage'));
  $('saveNewArticle')?.addEventListener('click',addCatalogArticle);
  $('manageArticleSearch')?.addEventListener('input',renderManageArticles);
  document.querySelectorAll('[data-close-article-modal]').forEach(el=>el.addEventListener('click',closeArticleModal));
  document.addEventListener('keydown',e=>{
    if(e.key!=='Escape') return;
    if($('ticketPasteModal')&&!$('ticketPasteModal').classList.contains('hidden')) closeTicketModal();
    if($('packageModal')&&!$('packageModal').classList.contains('hidden')) closePackageModal();
    if($('articleModal')&&!$('articleModal').classList.contains('hidden')) closeArticleModal();
  });
  const initial = new URLSearchParams(location.search).get('view')==='items' ? 'items' : 'packages';
  restore();
  setView(initial);

  // Beheerworkflow: start iedere nieuwe pagina-open direct in "Plak uit ticket".
  // Handmatig werken blijft bereikbaar door het venster met X/Escape te sluiten.
  setTimeout(()=>openTicketModal(),0);
})();