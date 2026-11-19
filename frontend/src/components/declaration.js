import {esc,fmt} from '../utils/format.js';
import {DECLARATION_STATES} from '../constants/enums.js';

// 把受控取整结果渲染为 部门×活动 对照表：每格显示 原值→整数（偏差/方向），附行列总量
export function declarationMatrix(result,{compact=false}={}){
 if(!result)return '<p class="empty">尚无取整结果。</p>';
 if(!result.feasible){
  return `<div class="conflict-box"><h3>取整冲突，无可行方案</h3><ul>${(result.conflicts||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul><p>已保留上一版生效申报表，未覆盖现行表。</p></div>`;
 }
 const depts=result.departments,acts=result.activities;
 const cell={};
 for(const c of result.cells)cell[c.department+'||'+c.activity]=c;
 const head=`<tr><th>部门 / 活动</th>${acts.map(a=>`<th>${esc(a)}</th>`).join('')}<th>部门规定总量</th><th>实际合计</th></tr>`;
 const body=depts.map((d,i)=>`<tr><th>${esc(d)}</th>${acts.map((a,j)=>{
   const c=cell[d+'||'+a];
   return `<td><div class="cell-round"><strong>${c.rounded_kg}</strong><span class="orig">原值 ${fmt(c.original_kg)}</span><span class="diff ${c.direction.includes('上')?'up':c.direction.includes('下')?'down':''}">${esc(c.direction)} ${fmt(c.difference_kg)}</span></div></td>`;
  }).join('')}<td><strong>${result.row_target[i]}</strong></td><td>${result.assignment[i].reduce((a,b)=>a+b,0)}</td></tr>`).join('');
 const colRow=`<tr><th>活动规定总量</th>${result.col_target.map(t=>`<td><strong>${t}</strong></td>`).join('')}<td colspan="2">总合计 <strong>${result.grand_total}</strong> kg</td></tr>`;
 const origRow=`<tr><th>活动原值合计</th>${result.col_original.map(t=>`<td>${fmt(t)}</td>`).join('')}<td colspan="2"></td></tr>`;
 return `<div class="table-wrap declaration-matrix"><table><thead>${head}</thead><tbody>${body}${colRow}${origRow}</tbody></table></div>
  <p class="method">${esc(result.tie_break||'总绝对偏差最小的受控取整方案')}；总绝对偏差 ${fmt(result.total_abs_deviation)} kg</p>`;
}

export function declarationStateBadge(state){
 return `<span class="status ${esc(state)}">${esc(DECLARATION_STATES[state]||state)}</span>`;
}

// 某报告对应的草案卡片（含制表/重试/核对操作）
export function draftPanel(c,d,runId,role){
 const drafts=(d.declarations?.drafts||[]).filter(x=>x.run_id===runId);
 const draft=drafts[0];
 const effectives=(d.declarations?.effectives||[]).filter(x=>x.run_id===runId);
 const eff=effectives[0];
 const canWrite=role==='admin'||role==='analyst';
 const canConfirm=role==='admin';
 return `<section class="declaration-panel">
  <div class="report-top"><h3>整数公斤申报表</h3>${draft?declarationStateBadge(draft.state):'<span class="status">未制表</span>'}</div>
  ${draft?`<p class="checksum">草案 #${draft.id} · 重试 ${draft.attempt} 次 · 版本 ${draft.version}${draft.effective_id?` · 已生效 #${draft.effective_id}`:''}</p>`:''}
  ${eff?`<p>现行生效表 <strong>#${eff.id} v${eff.version}</strong> · SHA256 <span class="checksum">${esc(eff.checksum.slice(0,24))}…</span></p>
   <p><button type="button" class="effective-export" data-effective="${eff.id}">下载生效申报表 CSV</button></p>`:'<p class="empty">尚无生效申报表。</p>'}
  ${draft&&draft.state==='conflict'?declarationMatrix(draft.result):''}
  ${draft&&(draft.state==='ready'||draft.state==='effective')&&draft.result?.feasible?declarationMatrix(draft.result,{compact:true}):''}
  <div class="report-actions">
   ${canWrite?`<button class="tabulate" data-run="${runId}">${draft&&draft.state==='conflict'?'重试制表（沿用现行表）':draft&&draft.state==='effective'?'修订重算':'制表 / 中断恢复'}</button>`:''}
   ${canConfirm&&draft&&draft.state==='ready'?`<form class="confirm-form" data-draft="${draft.id}"><label>核对说明（可选）<input name="note" placeholder="确认行列对平与取整口径" maxlength="2000"></label><button>核对通过，整表生效</button></form>`:''}
  </div>
  ${draft&&draft.error?`<p class="error">${esc(draft.error)}</p>`:''}
 </section>`;
}
