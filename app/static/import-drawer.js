/* Isolated two-step import flow. Never persists input or credentials in browser storage. */
(() => {
  'use strict';
  const root = document.querySelector('#import-drawer');
  const el = id => root.querySelector('#' + id);
  const panel = new bootstrap.Offcanvas(root, {backdrop: true, keyboard: true, scroll: false});
  let generation = 0, state = null, shown = Promise.resolve();
  const isCurrent = (session, seq) => state?.open && state.session === session && state.seq === seq;
  const locked = () => state && (state.committing || state.refreshing);
  const hasInput = () => !!el('import-text').value.trim() || !!el('import-file').files[0];
  const fileError = file => !file ? '请选择一份名单文件。' : !/\.(csv|xlsx)$/i.test(file.name) ? '只支持 CSV 或 XLSX 文件。' : file.size > 5 * 1024 * 1024 ? '文件不能超过 5 MB，请精简后重新选择。' : file.size === 0 ? '所选文件为空，请更换文件。' : '';
  function inputError() {
    if (state.mode === 'file') return fileError(el('import-file').files[0]);
    const text = el('import-text').value;
    if (!text.trim()) return '请先粘贴姓名与邮箱。';
    if (text.split(/\r?\n/).filter(line => line.trim()).length > 5001) return '一次最多导入 5000 行学生，请拆分名单。';
    if (new Blob([text]).size > 5 * 1024 * 1024) return '粘贴内容过大，请拆分名单。';
    return '';
  }
  function errorMessage(message = '') {
    el('import-error').textContent = message;
    el('import-error').hidden = !message;
  }
  function invalidate({source = false} = {}) {
    state.seq++;
    state.controller?.abort(); state.controller = null;
    state.checking = false; state.previewId = ''; state.stale = true;
    el('valid-only').checked = false; el('overwrite-conflicts').checked = false;
    if (source) { state.result = null; state.mappingTouched = false; state.step = 1; el('import-mapping').open = false; }
    errorMessage();
    render();
  }
  async function request(path, {form, json, signal} = {}) {
    let response;
    try {
      response = await fetch('/api' + path, {
        method: 'POST', signal, headers: {'X-CSRF-Token': S.csrf, ...(json ? {'Content-Type': 'application/json'} : {})},
        body: form || JSON.stringify(json),
      });
    } catch (error) {
      if (error.name === 'AbortError') throw error;
      throw Object.assign(new Error('无法连接本地服务，请确认应用仍在运行。'), {status: 0});
    }
    let data;
    try { data = await response.json(); }
    catch { throw Object.assign(new Error('服务响应无法识别。'), {status: response.ok ? 0 : response.status}); }
    if (!response.ok) throw Object.assign(new Error(data.detail || '操作失败，请稍后重试。'), {status: response.status});
    return data;
  }
  function counts() {
    const result = {valid: 0, duplicate: 0, invalid: 0, conflict: 0};
    for (const row of state.result?.rows || []) result[row.status]++;
    return result;
  }
  function unresolved() {
    return (state.result?.rows || []).filter(row => row.status === 'invalid' || (row.status === 'conflict' && (!el('overwrite-conflicts').checked || row.message.startsWith('文件内')))).length;
  }
  function actionable() {
    return (state.result?.rows || []).filter(row => row.status === 'valid' || (row.status === 'conflict' && el('overwrite-conflicts').checked && !row.message.startsWith('文件内'))).length;
  }
  function renderPreview() {
    if (!state.result) return;
    const c = counts(), total = state.result.rows.length;
    el('import-summary').innerHTML = `<strong>共 ${total} 行</strong><span>有效 <b>${c.valid}</b></span><span>重复 <b>${c.duplicate}</b></span><span ${c.invalid + c.conflict ? 'class="danger"' : ''}>错误／冲突 <b>${c.invalid + c.conflict}</b></span>`;
    const result = state.result;
    el('import-mapping-summary').textContent = `${result.auto_detected ? '已识别' : '当前设置'}：姓名第 ${Number(el('import-name-column').value) + 1} 列 · 邮箱第 ${Number(el('import-email-column').value) + 1} 列 · ${el('import-header').checked ? '含表头' : '无表头'}`;
    el('import-mapping-stale').hidden = !state.stale;
    const rows = result.rows.filter(row => state.filter === 'all' || (state.filter === 'problem' ? ['invalid', 'conflict'].includes(row.status) : row.status === 'duplicate'));
    const pages = Math.max(1, Math.ceil(rows.length / 50));
    state.page = Math.min(pages, Math.max(1, state.page));
    const offset = (state.page - 1) * 50;
    root.querySelectorAll('[data-import-filter]').forEach(button => {
      const filter = button.dataset.importFilter;
      button.setAttribute('aria-pressed', String(state.filter === filter));
      button.textContent = `${{all: '全部', problem: '问题', duplicate: '重复'}[filter]} ${filter === 'all' ? total : filter === 'problem' ? c.invalid + c.conflict : c.duplicate}`;
    });
    const labels = {valid: '可导入', invalid: '错误', conflict: '姓名冲突', duplicate: '重复'};
    el('import-results').innerHTML = rows.length ? `<table class="import-preview-table"><caption class="visually-hidden">${esc(state.className)}的导入预览</caption><thead><tr><th scope="col" class="import-line-column">行号</th><th scope="col">姓名 / 邮箱</th><th scope="col" class="import-result-column">检查结果</th></tr></thead><tbody>${rows.slice(offset, offset + 50).map(row => `<tr data-import-line="${row.line}"><td class="import-line-column">${row.line}</td><td class="import-person"><strong>${esc(row.name) || '未填写姓名'}</strong><span>${esc(row.email) || '未填写邮箱'}</span></td><td><span class="import-row-status import-status-${row.status}">${labels[row.status]}</span>${row.message === labels[row.status] ? '' : `<small>${esc(row.message)}</small>`}</td></tr>`).join('')}</tbody></table>` : '<div class="import-preview-empty">没有符合此筛选条件的行。</div>';
    el('import-preview-range').textContent = `显示 ${rows.length ? offset + 1 : 0}–${Math.min(offset + 50, rows.length)} 行，共 ${rows.length} 行`;
    el('import-preview-page').textContent = `${state.page} / ${pages}`;
    el('import-preview-prev').disabled = state.page <= 1 || locked() || state.discard;
    el('import-preview-next').disabled = state.page >= pages || locked() || state.discard;
    el('import-problem-options').hidden = c.invalid + c.conflict === 0;
    el('import-overwrite-option').hidden = c.conflict === 0;
  }
  function render() {
    if (!state) return;
    const done = !!state.completed || state.uncertain;
    const busy = locked(), disable = busy || state.discard;
    root.dataset.step = String(state.step);
    root.dataset.state = state.committing ? 'committing' : state.refreshing ? 'refreshing' : done ? 'completed' : state.checking ? 'checking' : state.previewId ? 'ready' : 'editing';
    el('import-input-step').hidden = state.step !== 1 || done;
    el('import-review-step').hidden = state.step !== 2 || done;
    el('import-input-step').disabled = disable; el('import-review-step').disabled = disable;
    el('import-completed').hidden = !done;
    el('import-step-one').toggleAttribute('aria-current', state.step === 1);
    el('import-step-two').toggleAttribute('aria-current', state.step === 2);
    (state.step === 1 ? el('import-step-one') : el('import-step-two')).setAttribute('aria-current', 'step');
    el('import-step-one').classList.toggle('is-complete', state.step === 2);
    el('import-paste-panel').hidden = state.mode !== 'paste'; el('import-file-panel').hidden = state.mode !== 'file';
    root.querySelectorAll('[data-import-mode]').forEach(button => {
      const selected = button.dataset.importMode === state.mode;
      button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1;
    });
    const file = el('import-file').files[0];
    el('import-file-area').hidden = !!file; el('import-file-selected').hidden = !file;
    el('import-file-name').textContent = file?.name || '';
    el('import-file-size').textContent = file ? (file.size < 1024 ? `${file.size} B` : file.size < 1048576 ? `${(file.size / 1024).toFixed(1)} KB` : `${(file.size / 1048576).toFixed(1)} MB`) : '';
    const lineCount = el('import-text').value.split(/\r?\n/).filter(line => line.trim()).length;
    el('import-line-count').textContent = lineCount ? `${lineCount} 行待检查` : '尚未录入';
    el('import-discard').hidden = !state.discard;
    el('import-close').disabled = busy; el('import-cancel').disabled = busy;
    el('import-cancel').textContent = done ? '关闭' : '取消';
    el('import-back').hidden = state.step === 1 || done; el('import-back').disabled = disable || state.checking;
    renderPreview();
    const primary = el('import-primary');
    let hint, label, disabled = disable || state.checking || state.classMissing;
    if (state.completed || state.uncertain) {
      const result = state.completed;
      el('import-completed-icon').className = `bi bi-${result ? 'check2-circle' : 'exclamation-circle'}`;
      el('import-completed-title').textContent = result ? '名单已导入' : '导入结果需要核对';
      el('import-completed-description').textContent = result ? `已添加 ${result.added} 人，更新 ${result.updated} 人，跳过 ${result.skipped} 行。` : '请求已提交，但未能确认服务器的处理结果。为避免重复操作，本次不会再次提交。';
      el('import-completed-note').textContent = state.refreshing ? '正在刷新班级名单…' : '请重新刷新名单；这里只会读取数据，不会再次导入。';
      label = state.refreshing ? '正在刷新…' : '重新刷新名单';
      hint = result ? '导入已完成，无需再次提交。' : '请刷新后核查名单，再决定后续操作。';
    } else if (state.committing) { label = '正在导入…'; hint = '正在保存，请勿关闭页面。'; }
    else if (state.checking) { label = '正在检查…'; hint = '正在识别列与检查每一行…'; }
    else if (state.step === 1) {
      label = '下一步：检查名单'; hint = inputError() || '先检查，再导入。名单只保存在本机。'; disabled ||= !!inputError();
    } else if (!state.previewId || state.stale) {
      label = '重新检查'; hint = '内容或列设置已变化，请重新检查后再导入。'; disabled ||= !!inputError();
    } else {
      label = '确认导入';
      const problems = unresolved(), useful = actionable();
      disabled ||= problems > 0 && !el('valid-only').checked || useful === 0;
      hint = problems && !el('valid-only').checked ? `有 ${problems} 行需要处理，请修改名单或明确选择处理方式。` : useful === 0 ? '没有可新增或更新的记录，无需导入。' : '确认后写入当前班级，不会发送邮件。';
    }
    primary.textContent = label; primary.disabled = !!disabled;
    el('import-footer-hint').textContent = hint;
  }
  function top() { el('import-drawer-body').scrollTo({top: 0, behavior: 'instant'}); }
  function setMode(mode, focus = false) {
    if (locked() || state.discard || state.mode === mode) return;
    state.mode = mode; invalidate({source: true});
    if (focus) el(mode === 'paste' ? 'import-tab-paste' : 'import-tab-file').focus();
  }
  async function check() {
    if (!state?.open || locked() || state.checking || state.discard) return;
    if (inputError()) { errorMessage(inputError()); render(); return; }
    if (state.previewId && !state.stale) { state.step = 2; render(); top(); return; }
    const session = state.session, seq = ++state.seq;
    state.controller?.abort(); state.controller = new AbortController();
    state.checking = true; errorMessage(); render();
    const form = new FormData();
    if (state.mode === 'file') form.append('file', el('import-file').files[0]); else form.append('text', el('import-text').value);
    if (state.mappingTouched) {
      form.append('name_column', el('import-name-column').value);
      form.append('email_column', el('import-email-column').value);
      form.append('has_header', String(el('import-header').checked));
    }
    try {
      const result = await request(`/classes/${state.classId}/import/preview`, {form, signal: state.controller.signal});
      if (!isCurrent(session, seq)) return;
      state.result = result; state.previewId = result.preview_id; state.stale = false; state.step = 2; state.filter = 'all'; state.page = 1;
      for (const [id, key] of [['import-name-column', 'name_column'], ['import-email-column', 'email_column']]) {
        el(id).innerHTML = result.columns.map((name, i) => `<option value="${i}">第 ${i + 1} 列 · ${esc(String(name).slice(0, 30) || '空白列')}</option>`).join('');
        el(id).value = result[key];
      }
      el('import-header').checked = result.has_header;
      el('valid-only').checked = false; el('overwrite-conflicts').checked = false;
      const c = counts();
      el('import-mapping').open = c.valid === 0 && c.invalid > 0;
      top();
    } catch (error) {
      if (!isCurrent(session, seq) || error.name === 'AbortError') return;
      errorMessage(error.message); if (error.status === 404) state.classMissing = true;
    } finally {
      if (isCurrent(session, seq)) { state.checking = false; state.controller = null; render(); }
    }
  }
  async function refreshAfterImport() {
    if (!state?.open || state.refreshing) return;
    const session = state.session, target = state.classId;
    state.refreshing = true; errorMessage(); render();
    try {
      await refreshBasics();
      if (!S.classes.some(c => c.id === target)) throw new Error('目标班级已不存在，请关闭面板后核查。');
      await showClass(target, {reset: true});
      if (S.managedClass !== target || S.rosterState !== 'ready') throw new Error('未能刷新目标班级的名单。');
      if ($('#compose-class').value) await refreshRecipients();
      if (!state.open || state.session !== session) return;
      const result = state.completed;
      toast(result ? `已添加 ${result.added} 人，更新 ${result.updated} 人，跳过 ${result.skipped} 行` : '名单已刷新，请核查本次导入结果。', !result);
      state.refreshing = false; await close(true);
    } catch (error) {
      if (state?.open && state.session === session) {
        state.refreshing = false;
        errorMessage((state.completed ? '导入已完成，但刷新失败。' : '暂时无法刷新名单。') + error.message);
        render(); top();
      }
    }
  }
  async function commit() {
    if (!state?.open || locked() || state.checking || !state.previewId || state.stale || state.completed || state.uncertain || state.discard) return;
    if (unresolved() && !el('valid-only').checked || !actionable()) return;
    state.committing = true; errorMessage(); render();
    try {
      const result = await request(`/classes/${state.classId}/import/confirm`, {json: {
        preview_id: state.previewId, valid_only: el('valid-only').checked, overwrite_conflicts: el('overwrite-conflicts').checked,
      }});
      state.completed = result; state.previewId = ''; state.committing = false;
      render(); top(); await refreshAfterImport();
    } catch (error) {
      state.committing = false;
      if (error.status === 410) {
        state.previewId = ''; state.stale = true;
        errorMessage('预览已过期，输入仍保留。请点击“重新检查”后再导入。');
      } else if (error.status === 0 || error.status >= 500) {
        // A dropped response might follow a committed transaction. Never blindly resubmit.
        state.previewId = ''; state.uncertain = true; errorMessage(error.message);
      } else {
        if (error.status === 404) state.classMissing = true;
        errorMessage(error.message);
      }
      render(); top();
    }
  }
  async function close(force = false) {
    if (!state?.open || locked() || state.closing) return;
    if (!force && !state.completed && !state.uncertain && hasInput()) {
      state.discardFocus = root.contains(document.activeElement) ? document.activeElement : el('import-close');
      state.discard = true; render();
      // Backdrop dismissal begins on mousedown; focus after its native focus action.
      requestAnimationFrame(() => { if (state?.open && state.discard) el('import-keep').focus(); });
      return;
    }
    state.closing = true;
    const session = state.session;
    await shown;
    if (!state?.open || state.session !== session) return;
    state.allowClose = true; panel.hide();
  }
  function open() {
    if (!S.managedClass || state?.open || root.classList.contains('hiding') || $('#dialog').classList.contains('show')) return;
    state = {session: ++generation, open: true, seq: 0, classId: S.managedClass, className: S.classes.find(c => c.id === S.managedClass)?.name || '当前班级',
      mode: 'paste', step: 1, page: 1, filter: 'all', result: null, previewId: '', stale: true, checking: false, committing: false, refreshing: false,
      completed: null, uncertain: false, mappingTouched: false, discard: false, allowClose: false, closing: false, classMissing: false, controller: null};
    el('import-text').value = ''; el('import-file').value = ''; el('valid-only').checked = false; el('overwrite-conflicts').checked = false;
    el('import-mapping').open = false; el('import-name-column').innerHTML = ''; el('import-email-column').innerHTML = ''; el('import-results').innerHTML = '';
    el('import-target-class').textContent = state.className;
    shown = new Promise(resolve => root.addEventListener('shown.bs.offcanvas', resolve, {once: true}));
    errorMessage(); render(); top();
    // Navigation is normally already closed; serialize overlays if its hide animation is pending.
    const navigation = $('#navigation');
    if (navigation.classList.contains('show') || navigation.classList.contains('hiding')) {
      navigation.addEventListener('hidden.bs.offcanvas', () => panel.show($('#import-students')), {once: true});
      bootstrap.Offcanvas.getInstance(navigation)?.hide();
    } else panel.show($('#import-students'));
  }
  root.addEventListener('keydown', event => {
    if (event.key !== 'Tab' || !state?.open) return;
    // Also wrap at the document boundary, where native Tab may enter browser chrome
    // without emitting the focusin event Bootstrap normally uses to contain focus.
    const nodes = [...root.querySelectorAll('a[href],button,input,textarea,select,summary,[tabindex]')]
      .filter(node => node.tabIndex >= 0 && !node.matches(':disabled') && node.getClientRects().length);
    const first = nodes[0], last = nodes[nodes.length - 1];
    if (first && ((!event.shiftKey && document.activeElement === last) || (event.shiftKey && document.activeElement === first))) {
      event.preventDefault(); (event.shiftKey ? last : first).focus();
    }
  });
  root.addEventListener('show.bs.offcanvas', () => document.body.classList.add('import-drawer-open'));
  root.addEventListener('shown.bs.offcanvas', () => { if (state?.open && !state.discard) (state.step === 1 ? el('import-text') : el('import-primary')).focus(); });
  root.addEventListener('hide.bs.offcanvas', event => {
    if (!state?.allowClose || locked()) { event.preventDefault(); if (!locked()) close(); return; }
    state.open = false; state.seq++; state.controller?.abort();
  });
  root.addEventListener('hidden.bs.offcanvas', () => {
    document.body.classList.remove('import-drawer-open');
    el('import-text').value = ''; el('import-file').value = ''; el('import-results').replaceChildren();
    if (state) { state.result = null; state.completed = null; state.controller = null; }
    const trigger = $('#import-students');
    (trigger.getClientRects().length && !trigger.disabled ? trigger : $('#main')).focus({preventScroll: true});
  });
  $('#import-students').addEventListener('click', open);
  el('import-close').addEventListener('click', () => close());
  el('import-cancel').addEventListener('click', () => close());
  el('import-keep').addEventListener('click', () => {
    state.discard = false; render(); (state.discardFocus?.isConnected ? state.discardFocus : el('import-text')).focus({preventScroll: true});
  });
  el('import-discard-confirm').addEventListener('click', () => close(true));
  el('import-text').addEventListener('input', () => invalidate({source: true}));
  el('import-file').addEventListener('change', () => { invalidate({source: true}); if (fileError(el('import-file').files[0])) errorMessage(fileError(el('import-file').files[0])); });
  el('import-file-replace').addEventListener('click', () => el('import-file').click());
  el('import-file-remove').addEventListener('click', () => { el('import-file').value = ''; invalidate({source: true}); el('import-file').focus(); });
  root.querySelectorAll('[data-import-mode]').forEach(button => {
    button.addEventListener('click', () => setMode(button.dataset.importMode));
    button.addEventListener('keydown', event => {
      if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
        event.preventDefault(); setMode(event.key === 'Home' ? 'paste' : event.key === 'End' ? 'file' : state.mode === 'paste' ? 'file' : 'paste', true);
      }
    });
  });
  for (const id of ['import-name-column', 'import-email-column', 'import-header']) el(id).addEventListener('change', () => { state.mappingTouched = true; invalidate(); });
  for (const id of ['valid-only', 'overwrite-conflicts']) el(id).addEventListener('change', render);
  root.querySelectorAll('[data-import-filter]').forEach(button => button.addEventListener('click', () => {
    state.filter = button.dataset.importFilter; state.page = 1; renderPreview();
  }));
  for (const [id, change] of [['import-preview-prev', -1], ['import-preview-next', 1]]) el(id).addEventListener('click', () => {
    state.page += change; renderPreview(); el('import-results').scrollIntoView({block: 'start', behavior: 'instant'});
    if (el(id).disabled) el(change > 0 ? 'import-preview-prev' : 'import-preview-next').focus({preventScroll: true});
  });
  el('import-back').addEventListener('click', () => { state.step = 1; errorMessage(); render(); top(); });
  el('import-primary').addEventListener('click', () => {
    if (el('import-primary').disabled) return;
    if (state.completed || state.uncertain) refreshAfterImport();
    else if (state.step === 1 || !state.previewId || state.stale) check();
    else commit();
  });
  // Browsers supply their own non-sensitive message; no input is stored for recovery.
  window.addEventListener('beforeunload', event => {
    if (state?.open && (locked() || (!state.completed && !state.uncertain && hasInput()))) { event.preventDefault(); event.returnValue = ''; }
  });
})();
