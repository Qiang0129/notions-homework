'use strict';
const $=s=>document.querySelector(s), $$=s=>Array.from(document.querySelectorAll(s));
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const S={csrf:'',profiles:[],classes:[],templates:[],drafts:[],students:[],managedStudents:[],selected:new Set(),recipientQuery:'',recipientState:'idle',recipientError:'',recipientClass:'',recipientSeq:0,recipientRequest:null,recipientVisible:[],managedClass:'',rosterPage:1,rosterPageSize:20,rosterSeq:0,rosterState:'idle',rosterError:'',draftId:'',templateId:'',editingTemplate:'',dirty:false,jobId:'',page:'compose',previewSeq:0,previewReady:false};
const names={compose:'写通知',classes:'班级名单',templates:'邮件模板',history:'发送记录',settings:'邮箱设置'};
const statusNames={queued:'排队中',sending:'发送中',completed:'已完成',partial:'部分失败',paused:'已暂停',interrupted:'已中断',cancelled:'已取消',pending:'待发送',accepted:'已提交',failed:'明确失败',unknown:'结果待确认',valid:'可导入',duplicate:'重复，跳过',conflict:'姓名冲突',invalid:'格式错误'};
const makeKey=()=>Array.from(crypto.getRandomValues(new Uint8Array(20)),b=>b.toString(16).padStart(2,'0')).join('');
const badge=status=>`<span class="status-badge ${esc(status)}">${esc(statusNames[status]||status)}</span>`;
const empty=(icon,title,text,action='')=>`<div class="empty-state"><i class="bi bi-${icon}" aria-hidden="true"></i><h3>${esc(title)}</h3><p>${esc(text)}</p>${action}</div>`;
function toast(message,error=false){const box=document.createElement('div');box.className='app-toast'+(error?' error':'');box.innerHTML=`<i class="bi bi-${error?'exclamation-circle':'check2-circle'}" aria-hidden="true"></i><span>${esc(message)}</span>`;$('#toast-region').append(box);while($('#toast-region').children.length>3)$('#toast-region').firstElementChild.remove();setTimeout(()=>box.remove(),error?7500:4000);}
function guard(fn){return async(...args)=>{try{await fn(...args);}catch(error){toast(error.message||'操作失败，请重试',true);}};}
async function api(path,{method='GET',body,form}={}){const options={method,headers:{}};if(method!=='GET')options.headers['X-CSRF-Token']=S.csrf;if(form)options.body=form;else if(body!==undefined){options.headers['Content-Type']='application/json';options.body=JSON.stringify(body);}let response;try{response=await fetch('/api'+path,options);}catch{throw new Error('无法连接本地服务，请确认电脑上的应用仍在运行');}const data=await response.json().catch(()=>({detail:'服务响应异常'}));if(response.status===401){location.replace('/login');throw new Error('登录已过期，请重新登录');}if(!response.ok)throw new Error(data.detail||'操作失败');return data;}
const modal=new bootstrap.Modal($('#dialog'));
let dialogTrigger=null,dialogReady=Promise.resolve();
// Bootstrap ignores hide() during its opening transition. Roster saves can finish sooner.
$('#dialog').addEventListener('show.bs.modal',()=>{dialogReady=new Promise(resolve=>$('#dialog').addEventListener('shown.bs.modal',resolve,{once:true}));});
function dialog(title,body,label,action){dialogTrigger=document.activeElement;$('#dialog-title').textContent=title;$('#dialog-body').innerHTML=body;$('#dialog-error').textContent='';const confirm=$('#dialog-confirm');confirm.textContent=label;confirm.disabled=false;confirm.onclick=async()=>{const form=$('#dialog-body form');if(form&&!form.reportValidity())return;confirm.disabled=true;confirm.textContent='处理中…';$('#dialog-error').textContent='';try{const result=await action();if(result!==false){if(S.page==='classes')await dialogReady;modal.hide();}}catch(error){$('#dialog-error').textContent=error.message;}finally{confirm.disabled=false;confirm.textContent=label;}};modal.show();return $('#dialog-body');}
$('#dialog').addEventListener('shown.bs.modal',()=>{$('#dialog-body input:not([type=checkbox]),#dialog-body textarea,#dialog-body select')?.focus();});
function confirmAction(title,text,action,label='确认'){dialog(title,`<p class="muted mb-0">${esc(text)}</p>`,label,action);}
function field(id,label,value='',{type='text',hint='',required=true,max=200}={}){return `<div class="mb-3"><label class="form-label" for="${id}">${label}</label><input id="${id}" class="form-control" type="${type}" value="${esc(value)}" maxlength="${max}" ${required?'required':''}>${hint?`<div class="field-hint">${hint}</div>`:''}</div>`;}
const quill=new Quill('#editor',{theme:'snow',modules:{toolbar:'#editor-toolbar'},formats:['bold','italic','underline','header','list','link','color'],placeholder:'在这里写下要告诉同学的事…'});
$('.ql-editor').setAttribute('aria-label','邮件正文');$('.ql-editor').setAttribute('role','textbox');$('.ql-editor').setAttribute('aria-multiline','true');
$$('.ql-picker-label').forEach(el=>{el.setAttribute('aria-label',el.closest('.ql-header')?'标题级别':'文字颜色');});
let previewTimer;
function changed(){S.dirty=true;S.previewReady=false;clearTimeout(previewTimer);previewTimer=setTimeout(()=>updatePreview(),500);}
quill.on('text-change',changed);
$('#notice-form').addEventListener('input',changed);
$$('[data-variable]').forEach(button=>button.addEventListener('click',()=>{const range=quill.getSelection(true);quill.insertText(range?range.index:quill.getLength()-1,'{{'+button.dataset.variable+'}}','user');}));
function applyComposePolicy(saved={}){const p=S.profiles.find(p=>p.id===$('#compose-profile').value);S.policyProfile=$('#compose-profile').value;S.sendPolicy={concurrency:saved.concurrency??p?.default_concurrency??1,interval:saved.interval??p?.default_interval??3};}
function notice(){if(S.policyProfile!==$('#compose-profile').value)applyComposePolicy();return {subject:$('#subject').value,title:$('#mail-title').value,course:$('#course').value,assignment:$('#assignment').value,deadline:$('#deadline').value,submission_email:$('#submission-email').value,delta:quill.getContents(),profile_id:$('#compose-profile').value,class_id:$('#compose-class').value,student_ids:Array.from(S.selected),...S.sendPolicy};}
function validNotice(){if(!$('#notice-form').reportValidity())throw new Error('请先完善通知内容的必填项');if(!quill.getText().trim())throw new Error('请填写邮件正文');return notice();}
function fillNotice(n){for(const [id,key] of Object.entries({subject:'subject','mail-title':'title',course:'course',assignment:'assignment',deadline:'deadline','submission-email':'submission_email'}))$("#"+id).value=n[key]||'';quill.setContents(n.delta||{ops:[{insert:'\n'}]});$('#compose-profile').value=S.profiles.some(p=>p.id===n.profile_id)?n.profile_id:(S.profiles[0]?.id||'');$('#compose-class').value=S.classes.some(c=>c.id===n.class_id)?n.class_id:'';applyComposePolicy(n);return loadRecipients(n.student_ids||[],{resetSearch:true});}
async function updatePreview(){const seq=++S.previewSeq;if(['loading','error'].includes(S.recipientState)){S.previewReady=false;$('#preview-placeholder').hidden=false;$('#preview-status').textContent=S.recipientState==='loading'?'正在读取收件名单…':'收件名单加载失败，请重试后预览';return;}const n=notice();updateSender();if(![n.subject,n.title,n.course,n.assignment,n.deadline,n.submission_email].every(v=>v.trim())||!quill.getText().trim()){$('#preview-status').textContent='';$('#preview-placeholder').hidden=false;S.previewReady=false;return;}$('#preview-status').classList.remove('danger');$('#preview-status').textContent='正在更新预览…';try{const content=await api('/notices/preview',{method:'POST',body:{notice:n,student_id:$('#preview-student').value||null}});if(seq!==S.previewSeq)return;$('#mail-preview').srcdoc=content.html;$('#preview-subject').textContent=content.subject;$('#preview-placeholder').hidden=true;$('#preview-status').textContent='预览已更新 · 姓名变量会按收件人替换';S.previewReady=true;}catch(error){if(seq!==S.previewSeq)return;$('#preview-status').classList.add('danger');$('#preview-status').textContent=error.message;S.previewReady=false;}}
function updateSender(){const p=S.profiles.find(p=>p.id===$('#compose-profile').value);$('#preview-sender').textContent=p?.sender_name||'课程助教';$('#preview-from').textContent=p?.sender_email||'请先选择发送邮箱';$('#send-summary').textContent=p?`发件人：${p.sender_email}`:'选好邮箱与收件人，再确认发送';}
// Full selection is authoritative. Search is a display-only view, never a send list.
let recipientComposing=false;
function recipientMatches(){
  const query=S.recipientQuery.trim().toLowerCase();
  return query?S.students.filter(student=>(student.name+' '+student.email).toLowerCase().includes(query)):S.students;
}
function ensureRecipientsLoaded(){
  if(['loading','error'].includes(S.recipientState)||($('#compose-class').value&&(S.recipientState!=='ready'||S.recipientClass!==$('#compose-class').value))){
    throw new Error(S.recipientState==='error'?'收件名单尚未加载成功，请先重试。':'正在读取收件名单，请稍后再操作。');
  }
}
function ensureSendSelection(notice){
  ensureRecipientsLoaded();
  if(!notice.class_id||!notice.student_ids.length)throw new Error('请先选择班级和至少一位同学');
  if(notice.class_id!==S.recipientClass||notice.student_ids.length!==S.selected.size||notice.student_ids.some(id=>!S.selected.has(id))){
    throw new Error('收件名单已变化，请重新确认发送。');
  }
}
function updateSelected(){
  const ready=S.recipientState==='ready',query=S.recipientQuery.trim();
  const matches=ready?S.recipientVisible:[],matchedSelected=matches.reduce((n,student)=>n+Number(S.selected.has(student.id)),0);
  const total=ready?S.students.length:0,count=ready?S.selected.size:0;
  $('#recipient-count').textContent=ready?count:0;$('#recipient-total').textContent=ready?total:'…';
  $('#send-count').textContent=count;
  $('#recipient-select-label').textContent=query?`选择搜索结果（${matches.length} 人）`:'选择全班同学';
  const selectAll=$('#select-all-recipients');
  selectAll.checked=matches.length>0&&matchedSelected===matches.length;
  selectAll.indeterminate=matchedSelected>0&&matchedSelected<matches.length;
  selectAll.disabled=!ready||!matches.length;
  $('#recipient-match-summary').textContent=!ready?(S.recipientState==='loading'?'正在读取…':S.recipientState==='error'?'加载失败':''):query?`匹配 ${matches.length} 人，其中已选 ${matchedSelected} 人`:`共 ${total} 人`;
  const hidden=count-matchedSelected,hint=$('#recipient-hidden-selection');
  hint.hidden=!(ready&&query&&hidden>0);
  hint.textContent=hint.hidden?'':`另有 ${hidden} 位已选同学不在搜索结果中`;
  $('#recipient-search').disabled=!ready||!total;
  $('#recipient-search-clear').hidden=!S.recipientQuery;
  $('#recipient-search-clear').disabled=!ready;
  const pending=['loading','error'].includes(S.recipientState);
  $('#review-send').disabled=pending||!ready||!count;
  document.dispatchEvent(new Event('recipient-selection-updated'));
  // Do not overwrite a saved recipient intent with the transient empty loading view.
  $('#save-draft').disabled=pending;
  $('#preview-student').disabled=pending;
  $('#recipient-area').querySelectorAll('[data-recipient]').forEach(box=>{
    box.checked=S.selected.has(box.dataset.recipient);
    box.closest('.recipient-row').classList.toggle('is-selected',box.checked);
  });
}
function renderRecipients(){
  const area=$('#recipient-area');
  $('#recipient-controls').hidden=!S.recipientClass;
  area.setAttribute('aria-busy',String(S.recipientState==='loading'));
  S.recipientVisible=S.recipientState==='ready'?recipientMatches():[];
  if(S.recipientState==='loading'){
    area.innerHTML='<div class="recipient-loading" role="status"><span class="visually-hidden">正在读取班级名单</span>'+Array.from({length:4},()=>'<div class="recipient-skeleton"><span></span><span></span></div>').join('')+'</div>';
  }else if(S.recipientState==='error'){
    area.innerHTML=`<div class="recipient-empty recipient-error"><i class="bi bi-exclamation-circle" aria-hidden="true"></i><div><strong>收件名单加载失败</strong><p>${esc(S.recipientError)}</p><button type="button" class="text-action" data-retry-recipients>重新加载名单</button></div></div>`;
  }else if(!S.recipientClass){
    area.innerHTML='<div class="recipient-empty"><i class="bi bi-people" aria-hidden="true"></i><div><strong>先选择一个班级</strong><p>选择后可以搜索姓名或邮箱，勾选本次收件同学。</p><a href="#classes" class="text-action">创建班级并导入同学</a></div></div>';
  }else if(!S.students.length){
    area.innerHTML='<div class="recipient-empty"><i class="bi bi-person-plus" aria-hidden="true"></i><div><strong>班级还没有同学</strong><p>添加或导入名单后，就可以在这里选择收件人。</p><a href="#classes" class="text-action">前往导入名单</a></div></div>';
  }else if(!S.recipientVisible.length){
    area.innerHTML='<div class="recipient-empty"><i class="bi bi-search" aria-hidden="true"></i><div><strong>没有找到匹配的同学</strong><p>换个姓名或邮箱关键词试试。已选名单不会因此改变。</p><button type="button" class="text-action" data-clear-recipient-search>清空搜索</button></div></div>';
  }else{
    area.innerHTML=S.recipientVisible.map(student=>`<label class="recipient-row ${S.selected.has(student.id)?'is-selected':''}"><input type="checkbox" data-recipient="${student.id}" ${S.selected.has(student.id)?'checked':''} aria-label="选择${esc(student.name)}，${esc(student.email)}"><span class="recipient-details"><span class="recipient-name">${esc(student.name)}</span><span class="recipient-email">${esc(student.email)}</span></span></label>`).join('');
  }
  updateSelected();
}
async function loadRecipients(ids=null,{resetSearch=false}={}){
  const classId=$('#compose-class').value;
  const intent=ids===null?null:[...new Set(ids)];
  const sampleId=classId===S.recipientClass?$('#preview-student').value:'';
  if(resetSearch||classId!==S.recipientClass){S.recipientQuery='';$('#recipient-search').value='';recipientComposing=false;}
  const seq=++S.recipientSeq;
  S.recipientClass=classId;S.recipientRequest={classId,ids:intent};
  S.recipientState=classId?'loading':'idle';S.recipientError='';S.students=[];S.selected=new Set();
  ++S.previewSeq;S.previewReady=false;
  $('#preview-student').innerHTML='<option value="">李同学（示例）</option>';
  renderRecipients();$('#recipient-area').scrollTop=0;
  if(!classId){await updatePreview();return true;}
  try{
    const students=await api(`/classes/${classId}/students`);
    if(seq!==S.recipientSeq||classId!==$('#compose-class').value)return false;
    const present=new Set(students.map(student=>student.id));
    S.students=students;S.selected=new Set(intent===null?present:intent.filter(id=>present.has(id)));
    S.recipientState='ready';S.recipientError='';
    const classroom=S.classes.find(item=>item.id===classId);
    if(classroom){
      classroom.count=students.length;
      const option=Array.from($('#compose-class').options).find(item=>item.value===classId);
      if(option)option.textContent=`${classroom.name} · ${students.length} 人`;
    }
    $('#preview-student').innerHTML='<option value="">李同学（示例）</option>'+students.map(student=>`<option value="${student.id}">${esc(student.name)}</option>`).join('');
    if(present.has(sampleId))$('#preview-student').value=sampleId;
    renderRecipients();await updatePreview();return true;
  }catch(error){
    if(seq!==S.recipientSeq||classId!==$('#compose-class').value)return false;
    S.recipientState='error';S.recipientError=error.message;renderRecipients();await updatePreview();return false;
  }
}
async function refreshRecipients(){
  const classId=$('#compose-class').value;
  const intent=S.recipientState==='ready'?[...S.selected]:S.recipientRequest?.classId===classId?S.recipientRequest.ids:[];
  const success=await loadRecipients(intent);
  if(!success&&S.recipientState==='error'&&S.recipientClass===classId)throw new Error(S.recipientError);
}
function applyRecipientSearch(){
  const value=$('#recipient-search').value;
  if(value===S.recipientQuery)return;
  S.recipientQuery=value;renderRecipients();$('#recipient-area').scrollTop=0;
}
function clearRecipientSearch(){
  recipientComposing=false;$('#recipient-search').value='';applyRecipientSearch();$('#recipient-search').focus();
}
$('#recipient-search').addEventListener('compositionstart',()=>{recipientComposing=true;});
$('#recipient-search').addEventListener('compositionend',()=>{recipientComposing=false;applyRecipientSearch();});
$('#recipient-search').addEventListener('input',event=>{if(!recipientComposing&&!event.isComposing)applyRecipientSearch();});
$('#recipient-search-clear').addEventListener('click',clearRecipientSearch);
$('#recipient-picker').addEventListener('change',event=>{
  if(S.recipientState!=='ready')return;
  const box=event.target;let changed=false;
  if(box.id==='select-all-recipients'){
    for(const student of S.recipientVisible){
      if(S.selected.has(student.id)!==box.checked){changed=true;if(box.checked)S.selected.add(student.id);else S.selected.delete(student.id);}
    }
  }else if(box.dataset.recipient){
    if(!S.students.some(student=>student.id===box.dataset.recipient))return;
    changed=S.selected.has(box.dataset.recipient)!==box.checked;
    if(box.checked)S.selected.add(box.dataset.recipient);else S.selected.delete(box.dataset.recipient);
  }else return;
  if(changed)S.dirty=true;
  updateSelected();
});
$('#recipient-area').addEventListener('click',async event=>{
  if(event.target.closest('[data-clear-recipient-search]'))clearRecipientSearch();
  if(event.target.closest('[data-retry-recipients]')){
    const request=S.recipientRequest;
    if(!request||request.classId!==$('#compose-class').value)return;
    const success=await loadRecipients(request.ids);
    if(success)(S.students.length?$('#recipient-search'):$('#recipient-area')).focus({preventScroll:true});
  }
});
$('#compose-class').addEventListener('change',guard(async()=>{S.dirty=true;await loadRecipients(null,{resetSearch:true});}));
$('#compose-profile').addEventListener('change',()=>{S.dirty=true;applyComposePolicy();updateSender();});$('#preview-student').addEventListener('change',()=>updatePreview());
$('#mode-edit').addEventListener('click',()=>setMode(false));$('#mode-preview').addEventListener('click',()=>{setMode(true);updatePreview();});
function setMode(preview){$('#compose-layout').classList.toggle('show-preview',preview);$('#mode-edit').classList.toggle('active',!preview);$('#mode-preview').classList.toggle('active',preview);$('#mode-edit').setAttribute('aria-pressed',String(!preview));$('#mode-preview').setAttribute('aria-pressed',String(preview));}
$('#preview-desktop').addEventListener('click',()=>device(false));$('#preview-mobile').addEventListener('click',()=>device(true));function device(mobile){$('#preview-frame-wrap').classList.toggle('mobile-preview',mobile);$('#preview-desktop').classList.toggle('active',!mobile);$('#preview-mobile').classList.toggle('active',mobile);$('#preview-desktop').setAttribute('aria-pressed',String(!mobile));$('#preview-mobile').setAttribute('aria-pressed',String(mobile));}
function applyTemplate(id,editing=false){const t=S.templates.find(t=>t.id===id);if(!t)return;S.templateId=id;S.editingTemplate=editing?id:'';$('#subject').value=t.subject;$('#mail-title').value=t.title;quill.setContents(t.delta);$$('[data-template]').forEach(b=>b.classList.toggle('active',b.dataset.template===id));$('#save-as-template').innerHTML=editing?'<i class="bi bi-bookmark-check"></i> 保存模板更改':'<i class="bi bi-bookmark-plus"></i> 存为模板';changed();}
function renderTemplates(){const order=['作业发布','截止提醒','补交通知'];S.templates.sort((a,b)=>(order.indexOf(a.name)<0?99:order.indexOf(a.name))-(order.indexOf(b.name)<0?99:order.indexOf(b.name)));$('#template-pills').innerHTML=S.templates.map(t=>`<button class="template-pill ${S.templateId===t.id?'active':''}" type="button" data-template="${t.id}"><i class="bi bi-${t.name==='截止提醒'?'clock':t.name==='补交通知'?'arrow-return-right':'file-earmark-text'}"></i> ${esc(t.name)}</button>`).join('');$('#template-list').innerHTML=S.templates.length?S.templates.map(t=>`<article class="template-card"><div class="template-art"><div class="template-paper"><i class="bi bi-envelope"></i><span></span><span></span><span></span><span></span></div></div><h2>${esc(t.name)}${t.builtin?'<span class="badge-soft">内置</span>':''}</h2><p>${esc(t.subject)}</p><div class="card-actions"><button class="btn btn-primary btn-sm" data-use-template="${t.id}">使用模板 <i class="bi bi-arrow-right"></i></button><button class="btn btn-soft btn-sm" data-edit-template="${t.id}">编辑</button><button class="icon-btn ms-auto danger" data-delete-template="${t.id}" aria-label="删除${esc(t.name)}模板"><i class="bi bi-trash3"></i></button></div></article>`).join(''):empty('layout-text-window','还没有模板','在写通知页面编辑正文，即可保存为自己的模板。');}
$('#template-pills').addEventListener('click',event=>{const b=event.target.closest('[data-template]');if(b){if(S.dirty&&quill.getText().trim())confirmAction('替换当前正文？','课程等信息会保留；未保存的主题、标题和正文将被选中的模板替换。',()=>applyTemplate(b.dataset.template),'使用此模板');else applyTemplate(b.dataset.template);}});
$('#template-list').addEventListener('click',guard(async event=>{const use=event.target.closest('[data-use-template]'),edit=event.target.closest('[data-edit-template]'),del=event.target.closest('[data-delete-template]');if(use||edit){const b=use||edit;const proceed=()=>{location.hash='compose';applyTemplate(b.dataset.useTemplate||b.dataset.editTemplate,!!edit);setMode(false);};if(S.dirty)confirmAction('使用此模板？','当前未保存的主题、标题和正文会被替换，其他课程信息保留。',proceed,'继续');else proceed();}if(del)confirmAction('删除邮件模板？','只删除模板，不会影响保存的草稿或已经提交的发送任务。',async()=>{await api(`/templates/${del.dataset.deleteTemplate}`,{method:'DELETE'});S.templates=await api('/templates');renderTemplates();toast('模板已删除');},'删除模板');}));
function saveTemplate(){const n=notice();if(!n.subject.trim()||!n.title.trim()||!quill.getText().trim())throw new Error('请先填写主题、邮件标题和正文');const current=S.templates.find(t=>t.id===S.editingTemplate);dialog(current?'保存模板更改':'保存为邮件模板',`<form>${field('template-name','模板名称',current?.name||'我的作业提醒',{max:100})}${current?'<label class="form-check"><input id="overwrite-template" class="form-check-input" type="checkbox" checked><span class="form-check-label">覆盖此模板（取消勾选则另存一份）</span></label>':''}</form>`,'保存模板',async()=>{const overwrite=current&&$('#overwrite-template').checked;const result=await api('/templates'+(overwrite?'/'+current.id:''),{method:overwrite?'PUT':'POST',body:{name:$('#template-name').value,subject:n.subject,title:n.title,delta:n.delta}});S.templates=await api('/templates');S.templateId=result.id;S.editingTemplate='';renderTemplates();toast('邮件模板已保存');});}
$('#save-as-template').addEventListener('click',guard(saveTemplate));$('#new-template').addEventListener('click',guard(saveTemplate));
async function refreshBasics(){const profileId=$('#compose-profile').value,classId=$('#compose-class').value;[S.profiles,S.classes,S.templates,S.drafts]=await Promise.all([api('/smtp-profiles'),api('/classes'),api('/templates'),api('/notices')]);$('#compose-profile').innerHTML=S.profiles.length?S.profiles.map(p=>`<option value="${p.id}">${esc(p.sender_name)} · ${esc(p.sender_email)}${p.is_default?'（默认）':''}</option>`).join(''):'<option value="">请先添加一个发送邮箱</option>';if(S.profiles.some(p=>p.id===profileId))$('#compose-profile').value=profileId;$('#compose-class').innerHTML='<option value="">请选择一个班级</option>'+S.classes.map(c=>`<option value="${c.id}">${esc(c.name)} · ${c.count} 人</option>`).join('');if(S.classes.some(c=>c.id===classId))$('#compose-class').value=classId;renderProfiles();renderClassList();renderTemplates();updateSender();}
$('#save-draft').addEventListener('click',guard(async()=>{ensureRecipientsLoaded();const n=notice();const result=await api('/notices'+(S.draftId?'/'+S.draftId:''),{method:S.draftId?'PUT':'POST',body:{content:n}});S.draftId=result.id;S.dirty=false;S.drafts=await api('/notices');toast('草稿已保存在本机');}));
$('#open-drafts').addEventListener('click',guard(async()=>{S.drafts=await api('/notices');dialog('打开已保存的草稿',S.drafts.length?`<div class="list-group">${S.drafts.map(d=>`<div class="list-group-item d-flex align-items-center gap-2"><div class="flex-grow-1 overflow-hidden"><strong class="small">${esc(d.name||'未命名草稿')}</strong><small class="d-block muted">${esc(new Date(d.updated_at).toLocaleString('zh-CN'))}</small></div><button class="btn btn-soft btn-sm" data-load-draft="${d.id}">打开</button><button class="icon-btn danger" data-delete-draft="${d.id}" aria-label="删除草稿"><i class="bi bi-trash3"></i></button></div>`).join('')}</div>`:empty('file-earmark','还没有草稿','写通知时点击“保存草稿”，下次可以接着编辑。'),'关闭',()=>{});$('#dialog-body').onclick=guard(async event=>{const load=event.target.closest('[data-load-draft]'),del=event.target.closest('[data-delete-draft]');if(load){const d=S.drafts.find(x=>x.id===load.dataset.loadDraft);if(S.dirty){$('#dialog-error').textContent='当前内容尚未保存；请先关闭并保存草稿，再打开其他草稿。';return;}await fillNotice(d.content);S.draftId=d.id;S.dirty=false;modal.hide();toast(d.needs_submission_email?'旧草稿使用提交链接，请补填提交邮箱后再预览或发送':'草稿已打开');}if(del){const id=del.dataset.deleteDraft;await api(`/notices/${id}`,{method:'DELETE'});del.closest('.list-group-item').remove();if(S.draftId===id)S.draftId='';toast('草稿已删除');}});}));
$('#dialog').addEventListener('hidden.bs.modal',()=>{$('#dialog-body').onclick=null;$$('#dialog-body input[type=password]').forEach(input=>input.value='');if(dialogTrigger?.isConnected&&dialogTrigger.getClientRects().length)dialogTrigger.focus({preventScroll:true});else $('#main').focus({preventScroll:true});});
$('#test-mail').addEventListener('click',guard(()=>{const n=validNotice();if(!n.profile_id)throw new Error('请先添加并选择发送邮箱');dialog('先给自己发一封',`<form>${field('test-address','测试收件邮箱','',{type:'email',hint:'只向此地址发送一封测试邮件，不会发送给班级同学。'})}<div class="info-note mb-0"><i class="bi bi-info-circle"></i><span>使用当前预览的样例姓名；主题、正文与正式发送使用同一套邮件渲染。</span></div></form>`,'发送测试邮件',async()=>{await api('/notices/test',{method:'POST',body:{notice:n,student_id:$('#preview-student').value||null,to:$('#test-address').value}});toast('测试邮件已提交，请前往测试邮箱确认显示');});}));

function renderProfiles(){$('#profile-list').innerHTML=S.profiles.length?S.profiles.map(p=>`<article class="profile-card"><div class="profile-top"><i class="bi bi-envelope-at"></i><div class="overflow-hidden"><h2>${esc(p.name)}${p.is_default?'<span class="badge-soft">默认邮箱</span>':''}</h2><div class="profile-address">${esc(p.sender_email)}</div></div></div><div class="profile-server">${esc(p.host)}:${p.port} <span class="float-end">${p.security==='ssl'?'隐式 TLS':'STARTTLS'}</span><div class="mt-1">显示名称 · ${esc(p.sender_name)}</div></div><div class="profile-policy-summary"><i class="bi bi-sliders2" aria-hidden="true"></i>${p.default_concurrency||1} 路并发<span>·</span>每路间隔 ${p.default_interval??3} 秒</div><div class="card-actions"><button class="btn btn-outline-secondary btn-sm" data-test-profile="${p.id}"><i class="bi bi-plug"></i> 测试连接</button><button class="btn btn-soft btn-sm" data-edit-profile="${p.id}">编辑</button>${!p.is_default?`<button class="text-action" data-default-profile="${p.id}">设为默认</button>`:''}<button class="icon-btn danger ms-auto" data-delete-profile="${p.id}" aria-label="删除${esc(p.name)}邮箱"><i class="bi bi-trash3"></i></button></div></article>`).join(''):empty('envelope-plus','先连接一个发送邮箱','添加 QQ、Gmail 或学校邮箱的 SMTP 配置，授权码将由 Windows 凭据库保管。','<button class="btn btn-primary" data-add-profile><i class="bi bi-plus-lg"></i> 添加发送邮箱</button>');}
function profileDialog(p=null){dialog(p?'编辑发送邮箱':'添加发送邮箱',`<form id="profile-form"><div class="mb-3"><label class="form-label" for="profile-preset">快速配置</label><select class="form-select" id="profile-preset"><option value="custom">自定义 SMTP</option><option value="qq">QQ 邮箱</option><option value="gmail">Gmail</option></select></div><div class="row"><div class="col-sm-6">${field('profile-name','配置名称',p?.name||'',{max:100})}</div><div class="col-sm-6">${field('profile-sender-name','发件人显示名称',p?.sender_name||'',{max:100})}</div></div><div class="row"><div class="col-sm-7">${field('profile-host','SMTP 服务器',p?.host||'',{max:255})}</div><div class="col-sm-5">${field('profile-port','端口',p?.port||465,{type:'number',max:5})}</div></div><div class="mb-3"><label class="form-label" for="profile-security">连接加密方式</label><select class="form-select" id="profile-security"><option value="ssl" ${p?.security==='ssl'?'selected':''}>隐式 TLS / SSL（通常 465）</option><option value="starttls" ${p?.security==='starttls'?'selected':''}>STARTTLS（通常 587）</option></select></div><div class="row"><div class="col-sm-6">${field('profile-user','SMTP 认证用户名',p?.username||'',{max:254})}</div><div class="col-sm-6">${field('profile-email','发件邮箱',p?.sender_email||'',{type:'email',max:254})}</div></div>${field('profile-password',p?'更换授权码（留空则保持原值）':'授权码 / 应用专用密码','',{type:'password',required:!p,max:1024,hint:'不使用日常登录密码；不会回显已保存的授权码。'})}${field('profile-reply','Reply-To 回复邮箱（可选）',p?.reply_to||'',{type:'email',required:false,max:254})}<label class="form-check"><input class="form-check-input" type="checkbox" id="profile-default" ${p?.is_default||!S.profiles.length?'checked':''}><span class="form-check-label">作为默认发送邮箱</span></label><p class="field-hint mt-3 mb-0">HTTP 下填写的授权码会经过未加密网络，建议在运行服务的电脑本机配置。</p><section class="profile-send-policy" aria-labelledby="profile-policy-title"><div class="profile-policy-heading"><h3 id="profile-policy-title">默认发送策略</h3><span>每次发送前仍可调整</span></div>${sendPolicyMarkup('profile',{concurrency:p?.default_concurrency??1,interval:p?.default_interval??3})}</section></form>`,'保存邮箱',async()=>{const password=$('#profile-password').value;const port=Number($('#profile-port').value);if(!Number.isInteger(port)||port<1||port>65535)throw new Error('端口需为 1–65535');await api('/smtp-profiles'+(p?'/'+p.id:''),{method:p?'PUT':'POST',body:{name:$('#profile-name').value,host:$('#profile-host').value,port,security:$('#profile-security').value,username:$('#profile-user').value,sender_name:$('#profile-sender-name').value,sender_email:$('#profile-email').value,reply_to:$('#profile-reply').value,password:password||null,is_default:$('#profile-default').checked,default_concurrency:readSendPolicy($('#profile-policy')).concurrency,default_interval:readSendPolicy($('#profile-policy')).interval}});await refreshBasics();toast('邮箱配置已保存，授权码由 Windows 凭据库保管');});bindSendPolicy($('#profile-policy'));$('#profile-password').autocomplete='new-password';$('#profile-port').min=1;$('#profile-port').max=65535;$('#profile-preset').addEventListener('change',event=>{const v=event.target.value;if(v==='custom')return;$('#profile-host').value=v==='qq'?'smtp.qq.com':'smtp.gmail.com';$('#profile-port').value=v==='qq'?465:587;$('#profile-security').value=v==='qq'?'ssl':'starttls';if(!$('#profile-name').value)$('#profile-name').value=v==='qq'?'QQ 课程邮箱':'Gmail 课程邮箱';});}
$('#add-profile').addEventListener('click',()=>profileDialog());$('#profile-list').addEventListener('click',guard(async event=>{const add=event.target.closest('[data-add-profile]'),edit=event.target.closest('[data-edit-profile]'),del=event.target.closest('[data-delete-profile]'),test=event.target.closest('[data-test-profile]'),defaultButton=event.target.closest('[data-default-profile]');if(add)profileDialog();if(edit)profileDialog(S.profiles.find(p=>p.id===edit.dataset.editProfile));if(del)confirmAction('删除发送邮箱？','此配置及系统凭据将被删除，历史发送结果保留。正在发送的邮箱无法删除。',async()=>{await api(`/smtp-profiles/${del.dataset.deleteProfile}`,{method:'DELETE'});await refreshBasics();toast('发送邮箱已删除');},'删除邮箱');if(test){test.disabled=true;const old=test.innerHTML;test.textContent='正在连接…';try{const result=await api(`/smtp-profiles/${test.dataset.testProfile}/test`,{method:'POST'});toast(result.detail);}finally{test.disabled=false;test.innerHTML=old;}}if(defaultButton){const p=S.profiles.find(p=>p.id===defaultButton.dataset.defaultProfile),{id,...body}=p;await api(`/smtp-profiles/${id}`,{method:'PUT',body:{...body,is_default:true}});await refreshBasics();toast('默认邮箱已更新');}}));
// Roster pagination is a view of managedStudents, never the compose recipient source.
function rosterView(students,query,page,size){
  const q=query.trim().toLowerCase();
  const filtered=q?students.filter(s=>(s.name+' '+s.email).toLowerCase().includes(q)):students;
  const pageSize=[20,50,100].includes(size)?size:20;
  const total=filtered.length, pages=Math.max(1,Math.ceil(total/pageSize));
  const current=Math.min(pages,Math.max(1,Number.isFinite(page)?Math.floor(page):1));
  const offset=(current-1)*pageSize;
  return {rows:filtered.slice(offset,offset+pageSize),total,pages,page:current,start:total?offset+1:0,end:Math.min(offset+pageSize,total),query:q};
}
function rosterPageWindow(page,pages){
  const keep=new Set([1,pages]);
  for(let n=Math.max(1,page-1);n<=Math.min(pages,page+1);n++)keep.add(n);
  const result=[];
  for(const n of [...keep].sort((a,b)=>a-b)){
    const last=result[result.length-1];
    if(last&&n-last===2)result.push(last+1);
    else if(last&&n-last>2)result.push('gap');
    result.push(n);
  }
  return result;
}
function renderClassList(){
  // Resolve selection before painting its active state (including after deleting a class).
  if(!S.classes.some(c=>c.id===S.managedClass))S.managedClass=S.classes[0]?.id||'';
  $('#class-list-count').textContent=S.classes.length;
  $('#class-list').innerHTML=S.classes.length?S.classes.map(c=>`<button class="class-item ${S.managedClass===c.id?'active':''}" data-manage-class="${c.id}" ${S.managedClass===c.id?'aria-current="true"':''}><i class="bi bi-journal-bookmark" aria-hidden="true"></i><strong>${esc(c.name)}</strong><span class="class-item-count" aria-label="${c.count} 位同学">${c.count}</span></button>`).join(''):empty('journal-plus','还没有班级','新建班级后，就可以整理名单。');
  const picker=$('#managed-class-select');
  picker.innerHTML=S.classes.length?S.classes.map(c=>`<option value="${c.id}">${esc(c.name)} · ${c.count} 人</option>`).join(''):'<option value="">请先新建班级</option>';
  picker.value=S.managedClass;picker.disabled=!S.classes.length;
  for(const id of ['rename-class','import-students','add-student','delete-class'])$('#'+id).disabled=!S.managedClass;
}
function resetRosterView(){S.rosterPage=1;$('#student-search').value='';}
function updateRosterHeading(){
  const c=S.classes.find(c=>c.id===S.managedClass);
  $('#class-title').textContent=c?.name||'创建你的第一个班级';
  $('#class-subtitle').textContent=c?'名单仅保存在本机':'先新建班级，再粘贴名单或导入 CSV / XLSX';
  $('#class-member-count').hidden=!c;
  $('#class-member-count').textContent=c?`${c.count} 人`:'';
  $('#student-search').disabled=!c;
}
async function showClass(id,{reset=false}={}){
  const next=S.classes.some(c=>c.id===id)?id:S.classes[0]?.id||'';
  if(next!==S.managedClass||reset)resetRosterView();
  S.managedClass=next;
  const seq=++S.rosterSeq;
  S.managedStudents=[];S.rosterError='';S.rosterState=next?'loading':'idle';
  renderClassList();updateRosterHeading();renderStudents();
  if(!next)return;
  try{
    const students=await api(`/classes/${next}/students`);
    if(seq!==S.rosterSeq||S.managedClass!==next)return;
    S.managedStudents=students;S.rosterState='ready';
    const c=S.classes.find(c=>c.id===next);if(c)c.count=students.length;
    renderClassList();updateRosterHeading();renderStudents();
  }catch(error){
    if(seq!==S.rosterSeq||S.managedClass!==next)return;
    S.rosterState='error';S.rosterError=error.message;renderStudents();
  }
}
function renderRosterPagination(view){
  const ready=S.rosterState==='ready',enabled=ready&&view.total>0;
  const range=S.rosterState==='loading'?'正在读取名单…':S.rosterState==='error'?'名单暂未加载':`第 ${view.start}–${view.end} 位，共 ${view.total} 位`;
  $('#roster-range').textContent=range;$('#roster-top-range').textContent=range;
  $('#roster-page-size').disabled=!ready;$('#roster-page-size').value=S.rosterPageSize;
  const prev=`<button type="button" class="roster-page-button" data-roster-step="prev" aria-label="上一页" ${!enabled||view.page===1?'disabled':''}><i class="bi bi-chevron-left" aria-hidden="true"></i></button>`;
  const next=`<button type="button" class="roster-page-button" data-roster-step="next" aria-label="下一页" ${!enabled||view.page===view.pages?'disabled':''}><i class="bi bi-chevron-right" aria-hidden="true"></i></button>`;
  const compact=`<span class="roster-page-position" aria-label="第 ${view.page} 页，共 ${view.pages} 页">${view.page} / ${view.pages}</span>`;
  const pages=rosterPageWindow(view.page,view.pages).map(n=>n==='gap'?'<span class="roster-page-gap" aria-hidden="true">…</span>':`<button type="button" class="roster-page-button" data-roster-page="${n}" aria-label="第 ${n} 页" ${n===view.page?'aria-current="page"':''} ${!enabled?'disabled':''}>${n}</button>`).join('');
  $('#roster-pages').innerHTML=prev+`<span class="roster-page-numbers">${pages}</span>`+compact+next;
  $('#roster-top-pages').innerHTML=prev+compact+next;
}
function renderStudents(){
  const query=$('#student-search').value,view=rosterView(S.managedStudents,query,S.rosterPage,S.rosterPageSize);
  // Loading must not clamp a preserved page using a temporarily empty array.
  if(S.rosterState==='ready')S.rosterPage=view.page;
  const list=$('#student-list');list.setAttribute('aria-busy',String(S.rosterState==='loading'));
  $('#clear-student-search').hidden=!query;
  $('#student-search-status').textContent=S.rosterState==='ready'?(view.query?`找到 ${view.total} / ${S.managedStudents.length} 人`:`全部 ${S.managedStudents.length} 人`):'';
  renderRosterPagination(view);
  if(S.rosterState==='loading'){
    list.innerHTML='<div class="roster-loading" role="status"><span class="visually-hidden">正在读取名单</span>'+Array.from({length:5},()=>'<div class="roster-skeleton"><span></span><span></span></div>').join('')+'</div>';return;
  }
  if(S.rosterState==='error'){
    list.innerHTML=empty('exclamation-circle','名单加载失败','请重试。不会显示其他班级的旧名单。')+`<div class="roster-retry"><p>${esc(S.rosterError)}</p><button class="btn btn-outline-secondary btn-sm" data-roster-retry>重新加载</button></div>`;return;
  }
  if(!S.managedClass){list.innerHTML=empty('journal-plus','先建立一个班级','点击“新建班级”，再添加同学或批量导入名单。');return;}
  list.innerHTML=view.rows.length?`<table class="data-table roster-table"><caption class="visually-hidden">${esc($('#class-title').textContent)}的学生名单，第 ${view.start} 至 ${view.end} 位</caption><thead><tr><th scope="col" class="roster-number">序号</th><th scope="col" class="roster-name-column">姓名<span class="roster-mobile-label"> / 邮箱</span></th><th scope="col" class="roster-email-desktop">邮箱地址</th><th scope="col" class="roster-row-actions">操作</th></tr></thead><tbody>${view.rows.map((s,i)=>`<tr data-student-id="${s.id}"><td class="roster-number">${view.start+i}</td><td class="roster-name"><strong>${esc(s.name)}</strong><span class="roster-email-mobile">${esc(s.email)}</span></td><td class="email-cell roster-email-desktop">${esc(s.email)}</td><td class="roster-row-actions"><button class="icon-btn" data-edit-student="${s.id}" aria-label="编辑${esc(s.name)}" title="编辑同学"><i class="bi bi-pencil" aria-hidden="true"></i></button><button class="icon-btn danger" data-delete-student="${s.id}" aria-label="删除${esc(s.name)}" title="删除同学"><i class="bi bi-trash3" aria-hidden="true"></i></button></td></tr>`).join('')}</tbody></table>`:empty(view.query?'search':'people',view.query?'没有找到匹配的同学':'把你的同学加入名单',view.query?'试试其他姓名或邮箱关键词，或清空搜索。':'使用“批量导入”粘贴名单，也可以逐个添加同学。');
}
function scrollRosterStart({pageChange=false}={}){
  $('#student-list').scrollTop=0;
  if(pageChange&&!matchMedia('(min-width: 992px) and (min-height: 640px)').matches)$('#roster-toolbar').scrollIntoView({block:'start',behavior:'instant'});
}
$('#student-search').addEventListener('input',()=>{S.rosterPage=1;renderStudents();scrollRosterStart();});
$('#clear-student-search').addEventListener('click',()=>{resetRosterView();renderStudents();scrollRosterStart();$('#student-search').focus();});
$('#roster-page-size').addEventListener('change',event=>{S.rosterPageSize=Number(event.target.value);S.rosterPage=1;renderStudents();scrollRosterStart({pageChange:true});});
$('.roster-page').addEventListener('click',event=>{
  const button=event.target.closest('[data-roster-page],[data-roster-step]');
  if(!button||button.disabled||S.rosterState!=='ready')return;
  const navId=button.closest('nav').id,step=button.dataset.rosterStep;
  S.rosterPage=step?S.rosterPage+(step==='next'?1:-1):Number(button.dataset.rosterPage);
  renderStudents();scrollRosterStart({pageChange:true});
  // Repainted buttons need explicit focus restoration for keyboard users.
  const bounded=matchMedia('(min-width: 992px) and (min-height: 640px)').matches;
  const nav=$('#'+(bounded?navId:'roster-top-pages'));
  const target=step?nav.querySelector(`[data-roster-step="${step}"]:not(:disabled)`):nav.querySelector('[aria-current="page"]');
  (target||nav.querySelector('[aria-current="page"]')||nav.querySelector('button:not(:disabled)')||$('#student-list')).focus({preventScroll:true});
});
$('#student-list').addEventListener('click',event=>{if(event.target.closest('[data-roster-retry]'))showClass(S.managedClass);});
$('#class-list').addEventListener('click',event=>{const button=event.target.closest('[data-manage-class]');if(button)showClass(button.dataset.manageClass,{reset:true});});
$('#managed-class-select').addEventListener('change',event=>showClass(event.target.value,{reset:true}));
async function afterRoster({reset=false}={}){
  const focusId=dialogTrigger?.dataset.editStudent||dialogTrigger?.dataset.deleteStudent;
  await refreshBasics();await showClass(S.managedClass,{reset});
  if(focusId)dialogTrigger=$(`[data-edit-student="${focusId}"]`)||$('#student-list');
  if($('#compose-class').value)await refreshRecipients();
}
$('#add-class').addEventListener('click',()=>dialog('新建班级',`<form>${field('class-name','班级名称','',{max:100,hint:'例如：高等数学 A · 2026 级 1 班'})}</form>`,'创建班级',async()=>{const c=await api('/classes',{method:'POST',body:{name:$('#class-name').value}});S.managedClass=c.id;await refreshBasics();await showClass(c.id,{reset:true});toast('班级已创建，可以导入名单了');}));
$('#rename-class').addEventListener('click',()=>{const c=S.classes.find(c=>c.id===S.managedClass);if(!c)return;dialog('重命名班级',`<form>${field('class-name','班级名称',c.name,{max:100})}</form>`,'保存',async()=>{await api(`/classes/${c.id}`,{method:'PUT',body:{name:$('#class-name').value}});await afterRoster();toast('班级名称已更新');});});
$('#delete-class').addEventListener('click',()=>{const c=S.classes.find(c=>c.id===S.managedClass);if(c)confirmAction('删除整个班级？',`将删除“${c.name}”及其中 ${c.count} 位同学的名单。历史任务快照不受影响，此操作不可撤销。`,async()=>{await api(`/classes/${c.id}`,{method:'DELETE'});S.managedClass='';await refreshBasics();await showClass(S.managedClass,{reset:true});await loadRecipients([]);toast('班级及其名单已删除');},'删除班级');});
function studentDialog(s=null){if(!S.managedClass)return;dialog(s?'编辑同学信息':'添加一位同学',`<form>${field('student-name','姓名',s?.name||'',{max:100})}${field('student-email','邮箱',s?.email||'',{type:'email',max:254})}</form>`,'保存',async()=>{await api(`/classes/${S.managedClass}/students`+(s?'/'+s.id:''),{method:s?'PUT':'POST',body:{name:$('#student-name').value,email:$('#student-email').value}});await afterRoster({reset:!s});toast('同学信息已保存');});}
$('#add-student').addEventListener('click',()=>studentDialog());$('#student-list').addEventListener('click',event=>{const edit=event.target.closest('[data-edit-student]'),del=event.target.closest('[data-delete-student]');if(edit)studentDialog(S.managedStudents.find(s=>s.id===edit.dataset.editStudent));if(del){const s=S.managedStudents.find(s=>s.id===del.dataset.deleteStudent);confirmAction('从班级删除这位同学？',`${s.name}（${s.email}）将不再出现在当前班级名单，历史任务不变。`,async()=>{await api(`/classes/${S.managedClass}/students/${s.id}`,{method:'DELETE'});await afterRoster();toast('已从班级中移除');},'删除同学');}});

async function loadJobs(){const jobs=await api('/send-jobs');const fingerprint=JSON.stringify(jobs);if(fingerprint===S.jobsFingerprint){if(S.jobId)await showJob(S.jobId);return;}S.jobsFingerprint=fingerprint;$('#job-list').innerHTML=jobs.length?jobs.map(j=>`<div class="job-row"><span class="job-icon"><i class="bi bi-send-check"></i></span><div class="job-main"><h3>${esc(j.subject)}</h3><p>${esc(new Date(j.created_at).toLocaleString('zh-CN'))} · ${j.total} 位同学 · ${esc(j.sender_email)} · ${j.concurrency||1} 路并发 · 每路间隔 ${j.interval??3} 秒</p></div>${badge(j.status)}<button class="btn btn-soft btn-sm" data-view-job="${j.id}">查看详情 <i class="bi bi-arrow-right"></i></button></div>`).join(''):empty('send','还没有发送记录','先编辑一封通知，预览并试发后，再确认发送给同学。','<a class="btn btn-primary" href="#compose">去写通知 <i class="bi bi-arrow-right"></i></a>');if(!S.jobId&&jobs.length)S.jobId=jobs[0].id;if(S.jobId)await showJob(S.jobId);}
async function showJob(id){const j=await api(`/send-jobs/${id}`);S.jobId=id;const fingerprint=JSON.stringify(j);if(fingerprint===S.jobFingerprint)return;S.jobFingerprint=fingerprint;const c=j.counts,active=['queued','sending'].includes(j.status);const finished=(c.accepted||0)+(c.failed||0)+(c.unknown||0)+(c.cancelled||0);$('#job-detail').hidden=false;$('#job-detail').innerHTML=`<div class="list-heading"><div><h2>${esc(j.subject)}</h2><p class="muted mb-0">${esc(j.sender_name)} · ${esc(j.sender_email)}<span class="job-policy-summary">${j.concurrency||1} 路并发 · 每路间隔 ${j.interval??3} 秒</span></p></div><div class="d-flex flex-wrap gap-2">${badge(j.status)}${active||['paused','interrupted'].includes(j.status)?`<button class="btn btn-outline-secondary btn-sm" data-cancel-job="${j.id}" ${j.cancel_requested?'disabled':''}>${j.cancel_requested?'正在取消…':'取消剩余发送'}</button>`:''}${!active&&(c.failed||0)>0?`<button class="btn btn-soft btn-sm" data-retry-job="${j.id}">重试明确失败项（${c.failed}）</button>`:''}</div></div>${j.error?`<div class="info-note"><i class="bi bi-exclamation-circle"></i><span>${esc(j.error)}</span></div>`:''}<div class="job-stats">${[['待发送',(c.pending||0)+(c.sending||0)],['已提交',c.accepted||0],['明确失败',c.failed||0],['结果待确认',c.unknown||0],['已取消',c.cancelled||0]].map(([label,count])=>`<div class="job-stat"><strong>${count}</strong><span>${label}</span></div>`).join('')}</div><div class="progress" role="progressbar" aria-label="处理进度" aria-valuenow="${finished}" aria-valuemin="0" aria-valuemax="${j.total}"><div class="progress-bar" style="width:${j.total?finished/j.total*100:0}%"></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>同学</th><th>邮箱</th><th>状态</th><th>说明</th></tr></thead><tbody>${j.deliveries.map(d=>`<tr><td>${esc(d.name)}</td><td class="email-cell">${esc(d.email)}</td><td>${badge(d.status)}</td><td class="muted">${esc(d.detail||'尚未发送')}</td></tr>`).join('')}</tbody></table></div>`;}
$('#refresh-jobs').addEventListener('click',guard(loadJobs));$('#job-list').addEventListener('click',guard(event=>{const b=event.target.closest('[data-view-job]');if(b)return showJob(b.dataset.viewJob);}));$('#job-detail').addEventListener('click',event=>{const cancel=event.target.closest('[data-cancel-job]'),retry=event.target.closest('[data-retry-job]');if(cancel)confirmAction('取消剩余发送？','已经提交的邮件无法撤回。当前正在提交的一封会先完成，其余待发送项目将取消。',async()=>{await api(`/send-jobs/${cancel.dataset.cancelJob}/cancel`,{method:'POST'});await loadJobs();toast('已请求取消剩余发送');},'取消剩余发送');if(retry){const key=makeKey();confirmAction('只重试明确失败的邮件？','将创建新任务，只包含服务器明确拒绝或确认未提交的失败项；不会包含已提交、待确认和未发送的邮件。',async()=>{const result=await api(`/send-jobs/${retry.dataset.retryJob}/retry`,{method:'POST',body:{idempotency_key:key}});S.jobId=result.id;await loadJobs();toast('已创建失败项重试任务');},'创建重试任务');}});
async function route(){const page=location.hash.slice(1);S.page=names[page]?page:'compose';document.body.classList.toggle('roster-active',S.page==='classes');$$('[data-page]').forEach(el=>el.hidden=el.dataset.page!==S.page);$$('[data-route]').forEach(el=>{el.classList.toggle('active',el.dataset.route===S.page);if(el.dataset.route===S.page)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});$('#breadcrumb-current').textContent=names[S.page];document.title=`${names[S.page]} · 课信`;bootstrap.Offcanvas.getInstance($('#navigation'))?.hide();if(S.page==='classes')await showClass(S.managedClass);if(S.page==='history')await loadJobs();}
window.addEventListener('hashchange',guard(route));$('#logout').addEventListener('click',()=>confirmAction('退出当前工作空间？','发送任务在服务仍运行时会继续。未保存的编辑不会保留。',async()=>{await api('/auth/logout',{method:'POST'});S.dirty=false;location.replace('/login');},'退出登录'));
window.addEventListener('beforeunload',event=>{if(S.dirty){event.preventDefault();event.returnValue='';}});
setInterval(()=>{if(S.page==='history'&&!document.hidden)loadJobs().catch(error=>{$('#job-list').dataset.error=error.message;});},2000);
(async()=>{try{const auth=await api('/auth/status');if(!auth.authenticated){location.replace('/login');return;}S.csrf=auth.csrf;await refreshBasics();const initial=S.templates.find(t=>t.name==='截止提醒')||S.templates[0];if(initial)applyTemplate(initial.id);S.dirty=false;updateSelected();await route();}catch(error){toast(error.message,true);}})();
