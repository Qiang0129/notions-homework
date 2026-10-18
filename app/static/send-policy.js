'use strict';
// Shared native controls for mailbox defaults and one-off send policies.
function sendPolicyMarkup(prefix,policy={concurrency:1,interval:3}){
  return `<fieldset class="send-policy" id="${prefix}-policy"><legend class="visually-hidden">发送策略</legend><div class="send-policy-controls"><div class="send-policy-concurrency"><span class="send-policy-label" id="${prefix}-concurrency-label">并发数</span><div class="send-policy-segments" role="radiogroup" aria-labelledby="${prefix}-concurrency-label">${[1,2,3,4,5].map(n=>`<label><input type="radio" name="${prefix}-concurrency" value="${n}" ${n===policy.concurrency?'checked':''}><span>${n}<small>路</small></span></label>`).join('')}</div></div><div class="send-policy-interval"><label class="send-policy-label" for="${prefix}-interval">每路发送间隔</label><div><input id="${prefix}-interval" class="form-control" type="number" min="1" max="60" step="1" required value="${policy.interval}" aria-describedby="${prefix}-policy-summary"><span>秒</span></div></div></div><p class="send-policy-summary" id="${prefix}-policy-summary" role="status" aria-live="polite"></p><p class="send-policy-warning" hidden><i class="bi bi-info-circle" aria-hidden="true"></i><span></span></p></fieldset>`;
}
function readSendPolicy(root){return {concurrency:Number(root.querySelector('input[type=radio]:checked')?.value),interval:Number(root.querySelector('input[type=number]').value)};}
function validSendPolicy(policy){return Number.isInteger(policy.concurrency)&&policy.concurrency>=1&&policy.concurrency<=5&&Number.isInteger(policy.interval)&&policy.interval>=1&&policy.interval<=60;}
function renderSendPolicy(root){
  const policy=readSendPolicy(root),valid=validSendPolicy(policy);
  root.querySelector('input[type=number]').setAttribute('aria-invalid',String(!valid));
  root.querySelector('.send-policy-summary').textContent=valid?`最多同时处理 ${policy.concurrency} 封；每路完成后等待 ${policy.interval} 秒。`:'发送间隔需为 1–60 秒的整数。';
  const warning=root.querySelector('.send-policy-warning');warning.hidden=policy.concurrency<=1;
  warning.querySelector('span').textContent=`开始时最多同时提交 ${policy.concurrency} 封，提高并发会增加发信频率，请确认邮箱允许。`;
}
function bindSendPolicy(root,onChange=()=>{}){
  root.addEventListener('input',()=>{renderSendPolicy(root);onChange(readSendPolicy(root));});renderSendPolicy(root);
}
