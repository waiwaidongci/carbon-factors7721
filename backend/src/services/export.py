import csv,io,json,decimal
from fastapi import HTTPException
BOM='﻿'
def csv_text(result):
 rows=result.get('rows',[])
 if not rows: raise HTTPException(409,'尚无结果')
 stream=io.StringIO();keys=list(dict.fromkeys(k for row in rows for k in row));w=csv.DictWriter(stream,fieldnames=keys);w.writeheader()
 for row in rows: w.writerow({k:(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v) for k,v in row.items()})
 return BOM+stream.getvalue()
def _num(v):
 if isinstance(v,decimal.Decimal):
  return int(v) if v==v.to_integral_value() else float(v)
 return v
def declaration_rows(result):
 """把受控取整结果展开为 部门×活动 透视行，行列总量与取整前后并列。"""
 if not result or not result.get('feasible'): raise HTTPException(409,'申报表无可行取整方案')
 depts=result['departments'];acts=result['activities'];assign=result['assignment']
 cell_map={(c['department'],c['activity']):c for c in result['cells']}
 rows=[]
 for i,dept in enumerate(depts):
  row={'部门':dept}
  for j,act in enumerate(acts):
   c=cell_map[(dept,act)]
   row[f'{act} 原值kg']=_num(c['original_kg'])
   row[f'{act} 整数kg']=c['rounded_kg']
   row[f'{act} 偏差kg']=_num(c['difference_kg'])
   row[f'{act} 取整方向']=c['direction']
  row['部门规定总量kg']=result['row_target'][i]
  row['部门实际合计kg']=sum(assign[i])
  rows.append(row)
 col_total={'部门':'活动规定总量kg'}
 for j,act in enumerate(acts):
  col_total[f'{act} 整数kg']=result['col_target'][j]
  col_total[f'{act} 原值合计kg']=_num(result['col_original'][j])
 rows.append(col_total)
 rows.append({'部门':'总合计kg','部门规定总量kg':result['grand_total']})
 return rows
def declaration_csv(result):
 rows=declaration_rows(result)
 stream=io.StringIO()
 keys=list(dict.fromkeys(k for r in rows for k in r))
 w=csv.DictWriter(stream,fieldnames=keys,extrasaction='ignore');w.writeheader()
 for r in rows: w.writerow(r)
 return BOM+stream.getvalue()
