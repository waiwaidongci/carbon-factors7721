import {heading} from '../components/common/header.js';
import {esc,time} from '../utils/format.js';
import {declarationMatrix,declarationStateBadge} from '../components/declaration.js';

export function declarations(c,d,role){
 const runs=d.runs||[];
 const drafts=d.declarations?.drafts||[];
 const effectives=d.declarations?.effectives||[];
 const runName=id=>runs.find(r=>r.id===id)?.name||('#'+id);
 const canWrite=role==='admin'||role==='analyst';
 const canConfirm=role==='admin';
 const list=drafts.length?drafts.map(x=>{
  const eff=effectives.find(e=>e.run_id===x.run_id);
  return `<article class="decl-card ${esc(x.state)}">
   <header><h3>${esc(runName(x.run_id))}</h3>${declarationStateBadge(x.state)}</header>
   <p class="checksum">草案 #${x.id} · 重试 ${x.attempt} 次 · 版本 ${x.version} · 更新 ${time(x.updated)}</p>
   ${x.error?`<p class="error">${esc(x.error)}</p>`:''}
   ${eff?`<p>现行生效 <strong>#${eff.id} v${eff.version}</strong>（${time(eff.updated)}）</p>`:''}
   <div class="report-actions">
    ${canWrite?`<button class="tabulate" data-run="${x.run_id}">${x.state==='conflict'?'重试制表':x.state==='effective'?'修订重算':'中断恢复 / 重试'}</button>`:''}
    ${canConfirm&&x.state==='ready'?`<form class="confirm-form" data-draft="${x.id}"><label>核对说明（可选）<input name="note" maxlength="2000" placeholder="确认行列对平、偏差可接受"></label><button>核对通过，整表生效</button></form>`:''}
    ${eff?`<button type="button" class="effective-export" data-effective="${eff.id}">下载生效 CSV</button>`:''}
   </div>
  </article>`;
 }).join(''):'<p class="empty">暂无申报表草案。在下方选择已复核报告开始制表。</p>';
 const approved=runs.filter(r=>r.approved&&r.status==='completed');
 const options=approved.map(r=>`<option value="${r.id}">${esc(r.name)}</option>`).join('');
 return heading('INTEGER DECLARATION / 05','整数公斤申报与核对','以已复核报告的冻结底稿重算原值，按部门×活动受控取整：每格向上或向下、行列对平、总绝对偏差最小，同分取字典序最小。')
 + (canWrite?`<form id="declaration-form" class="inline-form"><label>选择已复核报告<select name="run_id">${options}</select></label><button>制表（可中断恢复）</button></form>`:'')
 + `<div class="decl-grid">${list}</div>`
 + `<h2>生效申报表核对（取整前后数值）</h2>`
 + (effectives.length?effectives.map(e=>`<details ${e.active?'open':''}><summary>${esc(runName(e.run_id))} · 生效 #${e.id} v${e.version} ${e.active?'（现行）':'（历史版本）'}</summary>${declarationMatrix(e.result)}</details>`).join(''):'<p class="empty">尚无生效表。草案核对通过后整表生效。</p>');
}
