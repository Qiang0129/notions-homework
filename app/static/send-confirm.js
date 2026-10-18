'use strict';
(() => {
  const PAGE_SIZE=20;
  const drawerEl=$('#send-confirm-drawer');
  const drawer=new bootstrap.Offcanvas(drawerEl,{backdrop:true,keyboard:true,scroll:false});
  const C={snapshot:null,query:'',page:1,opening:0,busy:false,uncertain:false,jobId:'',trigger:null,allowHide:false};
  let drawerReady=Promise.resolve();

  function renderPolicy(){
    $('#send-confirm-policy-slot').innerHTML=sendPolicyMarkup('send-confirm',C.snapshot.notice);
    bindSendPolicy($('#send-confirm-policy'),policy=>{if(C.busy||C.snapshot.request)return;Object.assign(C.snapshot.notice,policy);$('#send-confirm-ack').checked=false;updatePolicyOrigin();updateSubmit();});
    updatePolicyOrigin();
  }
  function updatePolicyOrigin(){
    const defaults=C.snapshot.profile,policy=readSendPolicy($('#send-confirm-policy'));
    const changed=policy.concurrency!==defaults.default_concurrency||policy.interval!==defaults.default_interval;
    $('#send-policy-origin').textContent=changed?'仅本次修改':'沿用邮箱默认';$('#send-policy-origin').classList.toggle('is-custom',changed);
    $('#send-policy-reset').hidden=!changed;
  }

  function fingerprint(value){return JSON.stringify(value);}
  function currentIdentity(){
    const current=notice(),{interval,...content}=current;
    return fingerprint({notice:content,profile:$('#compose-profile').value,classId:$('#compose-class').value,ids:Array.from(S.selected)});
  }
  function setError(message=''){$('#send-confirm-error').hidden=!message;$('#send-confirm-error').textContent=message;}
  function setOutcome(title='',description='',note=''){
    const box=$('#send-confirm-outcome');box.hidden=!title;
    $('#send-confirm-outcome-title').textContent=title;$('#send-confirm-outcome-description').textContent=description;$('#send-confirm-outcome-note').textContent=note;
  }
  function selectedPeople(){
    const byId=new Map(S.students.map(person=>[person.id,person]));
    return Array.from(S.selected,id=>byId.get(id)).filter(Boolean).map(person=>({id:person.id,name:person.name,email:person.email}));
  }
  function pageWindow(page,pages){
    const keep=new Set([1,pages]);for(let n=Math.max(1,page-1);n<=Math.min(pages,page+1);n++)keep.add(n);
    const result=[];for(const n of [...keep].sort((a,b)=>a-b)){const last=result[result.length-1];if(last&&n-last===2)result.push(last+1);else if(last&&n-last>2)result.push('gap');result.push(n);}return result;
  }
  function filteredPeople(){
    const q=C.query.trim().toLowerCase();return q?C.snapshot.people.filter(person=>(person.name+' '+person.email).toLowerCase().includes(q)):C.snapshot.people;
  }
  function renderList(){
    if(!C.snapshot)return;
    const filtered=filteredPeople(),pages=Math.max(1,Math.ceil(filtered.length/PAGE_SIZE));C.page=Math.min(Math.max(1,C.page),pages);
    const start=(C.page-1)*PAGE_SIZE,rows=filtered.slice(start,start+PAGE_SIZE),total=C.snapshot.people.length;
    $('#send-confirm-list-total').textContent=`本次发送 ${total} 人`;
    $('#send-confirm-match').textContent=C.query?`本次发送 ${total} 人 · 匹配 ${filtered.length} 人`:`本次发送 ${total} 人`;
    $('#send-confirm-search-clear').hidden=!C.query;
    $('#send-confirm-list').innerHTML=rows.length?`<ol class="send-confirm-roster">${rows.map((person,index)=>`<li><span class="send-confirm-index">${start+index+1}</span><span class="send-confirm-person"><strong>${esc(person.name)}</strong><span>${esc(person.email)}</span></span></li>`).join('')}</ol>`:`<div class="send-confirm-empty"><strong>没有找到匹配的同学</strong><p>仅筛选显示，不改变发送名单。</p><button type="button" class="text-action" data-clear-confirm-search>清空搜索</button></div>`;
    $('#send-confirm-range').textContent=filtered.length?`显示 ${start+1}–${Math.min(start+PAGE_SIZE,filtered.length)} / ${filtered.length} 人`:`匹配 0 人`;
    $('#send-confirm-pages').innerHTML=filtered.length>PAGE_SIZE?`<button type="button" class="icon-btn" data-confirm-page="${C.page-1}" ${C.page===1?'disabled':''} aria-label="上一页"><i class="bi bi-chevron-left"></i></button>${pageWindow(C.page,pages).map(item=>item==='gap'?'<span aria-hidden="true">…</span>':`<button type="button" class="send-confirm-page ${item===C.page?'active':''}" data-confirm-page="${item}" ${item===C.page?'aria-current="page"':''}>${item}</button>`).join('')}<button type="button" class="icon-btn" data-confirm-page="${C.page+1}" ${C.page===pages?'disabled':''} aria-label="下一页"><i class="bi bi-chevron-right"></i></button>`:'';
  }
  function intervalValue(){const value=Number($('#send-confirm-interval').value);return Number.isInteger(value)&&value>=1&&value<=60?value:null;}
  function updateSubmit(){
    const interval=intervalValue(),ack=$('#send-confirm-ack').checked;
    $('#send-confirm-interval').setAttribute('aria-invalid',String(interval===null));
    const submit=$('#send-confirm-submit');
    if(C.jobId){submit.textContent='重试读取发送记录';submit.disabled=C.busy;return;}
    submit.textContent=C.uncertain?'使用同一请求重试':'开始发送'+(C.snapshot?`（${C.snapshot.people.length} 人）`:'');
    submit.disabled=C.busy||!C.snapshot||!validSendPolicy(readSendPolicy($('#send-confirm-policy')))||interval===null||!ack;
    $('#send-confirm-footer-hint').textContent=interval===null?'发送间隔需为 1–60 秒的整数。':C.uncertain?'上次回包不确定；只可使用相同请求和幂等键手动重试。':ack?'已确认，可以创建发送任务。':'勾选确认后，再创建发送任务。';
  }
  function setBusy(busy){
    C.busy=busy;drawerEl.setAttribute('aria-busy',String(busy));
    for(const selector of ['#send-confirm-close','#send-confirm-back','#send-confirm-search','#send-confirm-search-clear','#send-confirm-interval','#send-confirm-ack'])$(selector).disabled=busy;
    $('#send-confirm-policy').disabled=busy||Boolean(C.snapshot?.request);
    $('#send-policy-reset').disabled=busy||Boolean(C.snapshot?.request);
    drawerEl.querySelectorAll('#send-confirm-pages button,[data-clear-confirm-search]').forEach(button=>{if(busy){button.dataset.wasDisabled=String(button.disabled);button.disabled=true;}else{button.disabled=button.dataset.wasDisabled==='true';delete button.dataset.wasDisabled;}});
    updateSubmit();if(busy)$('#send-confirm-submit').textContent=C.jobId?'正在读取…':'正在创建任务…';
  }
  function fillSnapshot(snapshot,preview){
    C.snapshot=snapshot;C.query='';C.page=1;C.uncertain=false;C.jobId='';
    $('#send-confirm-total').textContent=snapshot.people.length;
    $('#send-confirm-sender-name').textContent=snapshot.profile.sender_name;
    $('#send-confirm-sender-email').textContent=snapshot.profile.sender_email;
    $('#send-confirm-class').textContent=snapshot.classroom.name;
    $('#send-confirm-subject').textContent=preview.subject;
    const personalized=/{{\s*(name|class_name|course|assignment|deadline|submission_email)\s*}}/.test(snapshot.notice.subject);
    $('#send-confirm-subject-hint').hidden=!personalized;$('#send-confirm-subject-hint').textContent=personalized?'以上为首位收件人的主题示例。':'';
    $('#send-confirm-search').value='';renderPolicy();
    $('#send-confirm-ack').checked=false;$('#send-confirm-sample').open=false;
    $('#send-confirm-sample-person').textContent=`样例同学：${snapshot.people[0].name}（${snapshot.people[0].email}）`;
    $('#send-confirm-preview').srcdoc=preview.html;
    $('#send-confirm-body').scrollTop=0;
    setError();setOutcome();renderList();updateSubmit();
  }
  async function openReview(){
    if(C.busy||drawerEl.classList.contains('show')||drawerEl.classList.contains('showing'))return;
    const seq=++C.opening;C.trigger=document.activeElement;
    if(C.snapshot?.request&&(C.uncertain||C.jobId)){
      if(C.snapshot.identity!==currentIdentity())throw new Error(C.jobId?'任务已经创建，不能用修改后的内容再次创建。请重试读取发送记录。':'存在创建结果待确认的固定请求，不能换参数生成新请求。请恢复原内容后使用同一请求重试。');
      $('#send-confirm-ack').checked=false;setError();renderList();updateSubmit();drawer.show();return;
    }
    const n=validNotice();ensureSendSelection(n);
    const profile=S.profiles.find(item=>item.id===n.profile_id),classroom=S.classes.find(item=>item.id===n.class_id),people=selectedPeople();
    if(!profile)throw new Error('请先添加并选择发送邮箱');if(!classroom||people.length!==n.student_ids.length)throw new Error('收件名单已变化，请返回重新选择。');
    $('#review-send').disabled=true;
    try{
      const identity=currentIdentity();
      const preview=await api('/notices/preview',{method:'POST',body:{notice:n,student_id:people[0].id}});
      if(seq!==C.opening||identity!==currentIdentity())throw new Error('预览期间通知或收件名单发生变化，请重新核对。');
      const frozen=JSON.parse(JSON.stringify({...n,student_ids:people.map(person=>person.id)}));
      frozen.interval=Number.isInteger(frozen.interval)&&frozen.interval>=1&&frozen.interval<=60?frozen.interval:3;
      fillSnapshot({notice:frozen,profile:{id:profile.id,sender_name:profile.sender_name,sender_email:profile.sender_email,default_concurrency:profile.default_concurrency??1,default_interval:profile.default_interval??3},classroom:{id:classroom.id,name:classroom.name},people,identity,idempotencyKey:makeKey(),request:null},preview);
      bootstrap.Offcanvas.getInstance($('#import-drawer'))?.hide();bootstrap.Offcanvas.getInstance($('#navigation'))?.hide();
      drawer.show();
    }finally{$('#review-send').disabled=S.recipientState!=='ready'||!S.selected.size;}
  }
  async function verifySnapshot(){
    if(C.snapshot.identity!==currentIdentity())throw new Error('页面中的通知、发件配置或收件选择已变化，请返回重新核对。');
    const live=await api(`/classes/${C.snapshot.classroom.id}/students`),byId=new Map(live.map(person=>[person.id,person]));
    for(const frozen of C.snapshot.people){const now=byId.get(frozen.id);if(!now||now.name!==frozen.name||now.email!==frozen.email)throw new Error(`收件名单已变化：${frozen.name} 的记录已删除或修改。请返回核对，不会自动替换联系人。`);}
  }
  async function readCreatedJob(){
    await api(`/send-jobs/${C.jobId}`);S.jobId=C.jobId;
    await drawerReady;C.allowHide=true;drawer.hide();C.allowHide=false;location.hash='history';
    C.snapshot=null;C.jobId='';C.uncertain=false;
    try{await loadJobs();toast('任务已创建，正在发送记录中查看进度');}catch(error){toast(`任务已创建，但发送记录暂时加载失败：${error.message}`,true);}
  }
  async function submit(){
    if(C.busy)return;
    if(C.jobId){setBusy(true);try{await readCreatedJob();}catch(error){setOutcome('任务已创建','暂时无法读取发送记录。不会再次创建任务。',error.message);setError('');}finally{setBusy(false);}return;}
    if(!$('#send-confirm-ack').checked||!validSendPolicy(readSendPolicy($('#send-confirm-policy'))))return;
    setBusy(true);setError();setOutcome();
    try{
      if(!C.snapshot.request){await verifySnapshot();Object.assign(C.snapshot.notice,readSendPolicy($('#send-confirm-policy')));C.snapshot.request=JSON.parse(JSON.stringify({notice:C.snapshot.notice,idempotency_key:C.snapshot.idempotencyKey}));C.snapshot.requestJson=JSON.stringify(C.snapshot.request);}
      const result=await createFixedRequest();C.jobId=result.id;C.uncertain=false;
      setOutcome('任务已创建','服务器已创建发送任务；这不代表邮件已经送达。','接下来只读取发送记录，不会再次创建任务。');
      try{await readCreatedJob();}catch(error){setOutcome('任务已创建','暂时无法读取发送记录。不会再次创建任务。',error.message);}
    }catch(error){
      if(C.snapshot?.request&&error.uncertain){C.uncertain=true;setOutcome('创建结果待确认','请求可能已经到达服务，不能宣称失败，也不会自动重发。','确认服务恢复后，可用下方按钮以完全相同的请求和幂等键手动重试。');}
      else setError(error.message);
    }finally{setBusy(false);}
  }
  async function createFixedRequest(){
    let response,data;
    try{response=await fetch('/api/send-jobs',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':S.csrf},body:C.snapshot.requestJson});data=await response.json();}
    catch{throw Object.assign(new Error('服务回包不确定'),{uncertain:true});}
    if(!response.ok)throw Object.assign(new Error(typeof data.detail==='string'?data.detail:'任务未能创建，请核对设置'),{uncertain:response.status>=500});
    if(typeof data.id!=='string'||!data.id)throw Object.assign(new Error('任务回包缺少有效标识'),{uncertain:true});
    return data;
  }
  function clearSearch(){if(C.busy)return;$('#send-confirm-search').value='';C.query='';C.page=1;renderList();$('#send-confirm-search').focus();}
  function backToRecipients(){if(C.busy)return;drawer.hide();setTimeout(()=>$('#recipient-picker').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'}),0);}

  $('#review-send').addEventListener('click',guard(openReview));
  $('#send-confirm-close').addEventListener('click',()=>{if(!C.busy)drawer.hide();});
  $('#send-confirm-back').addEventListener('click',backToRecipients);
  $('#send-confirm-search').addEventListener('input',event=>{C.query=event.target.value;C.page=1;renderList();});
  $('#send-confirm-search-clear').addEventListener('click',clearSearch);
  $('#send-confirm-list').addEventListener('click',event=>{if(event.target.closest('[data-clear-confirm-search]'))clearSearch();});
  $('#send-confirm-pages').addEventListener('click',event=>{const button=event.target.closest('[data-confirm-page]');if(C.busy||!button||button.disabled)return;C.page=Number(button.dataset.confirmPage);renderList();$('#send-confirm-list-title').focus?.({preventScroll:true});});
  $('#send-policy-reset').addEventListener('click',()=>{if(C.busy||C.snapshot?.request)return;C.snapshot.notice.concurrency=C.snapshot.profile.default_concurrency;C.snapshot.notice.interval=C.snapshot.profile.default_interval;$('#send-confirm-ack').checked=false;renderPolicy();updateSubmit();});
  $('#send-confirm-ack').addEventListener('change',updateSubmit);$('#send-confirm-submit').addEventListener('click',submit);
  drawerEl.addEventListener('show.bs.offcanvas',()=>{document.body.classList.add('send-confirm-open');drawerReady=new Promise(resolve=>drawerEl.addEventListener('shown.bs.offcanvas',resolve,{once:true}));});
  drawerEl.addEventListener('shown.bs.offcanvas',()=>$('#send-confirm-search').focus({preventScroll:true}));
  drawerEl.addEventListener('hide.bs.offcanvas',event=>{if(C.busy&&!C.allowHide)event.preventDefault();});
  drawerEl.addEventListener('hidden.bs.offcanvas',()=>{document.body.classList.remove('send-confirm-open');if(C.trigger?.isConnected&&C.trigger.getClientRects().length)C.trigger.focus({preventScroll:true});});
  document.addEventListener('recipient-selection-updated',()=>{if(drawerEl.classList.contains('show')&&!C.busy&&C.snapshot?.identity!==currentIdentity()){setError('页面中的收件选择已变化，请关闭后重新打开确认抽屉。');$('#send-confirm-ack').checked=false;updateSubmit();}});
  window.sendConfirmController={openReview,renderList,state:C};
})();
