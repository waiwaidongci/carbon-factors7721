import hashlib
import json
import time

from fastapi import HTTPException
from sqlalchemy import text

from src.models.run import Run
from src.models.declaration import DeclarationDraft, EffectiveDeclaration
from src.services.declaration import build_original_matrix, round_declaration
from src.services.audit import log


def _now():
 return time.time()


def _load_run(db, run_id):
 run = db.get(Run, run_id)
 if not run:
  raise HTTPException(404, '报告不存在')
 if run.status != 'completed' or not run.approved:
  raise HTTPException(409, '仅已复核报告可重算制表')
 if not run.snapshot or not run.snapshot.get('sources'):
  raise HTTPException(409, '报告冻结底稿缺失，无法重算')
 return run


def _result_checksum(payload):
 return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                  default=str).encode()).hexdigest()


def get_draft(db, run_id):
 return db.query(DeclarationDraft).filter_by(run_id=run_id).one_or_none()


def get_effective(db, run_id):
 return db.query(EffectiveDeclaration).filter_by(run_id=run_id, active=True).one_or_none()


def _advisory_lock(db, run_id):
 """以 run_id 为键的事务级咨询锁：串行化同一报告的制表与核对，
 即使草案行尚不存在也能互斥；事务提交/回滚后自动释放。"""
 db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:k))'),
            {'k': 'declaration-run-%d' % run_id})


def create_or_retry_draft(db, user, run_id):
 """制表（可中断恢复）：同 run 仅一份草案；重试累加 attempt 不新增版本。
 咨询锁 + run_id 唯一约束 + 乐观版本号，保证并发核算下旧草案不得覆盖现行表。"""
 run = _load_run(db, run_id)
 _advisory_lock(db, run_id)
 draft = get_draft(db, run_id)
 if draft is None:
  draft = DeclarationDraft(run_id=run_id, state='computing', attempt=0, version=1,
                           created=_now(), updated=_now())
  db.add(draft)
  db.flush()
 else:
  if draft.state == 'ready':
   raise HTTPException(409, '草案已生成且待核对，请勿重复制表；可在核对页查看')
  # computing（中断恢复）、conflict（冲突后重试）、effective（修订重算）
  # 均复用同一草案行：attempt 累加、version 递增，不新增草案版本。
  # 重算冲突时现行生效表保持 active 不变，即沿用上一版。
 # 乐观版本号：进入计算前自占一版，过期写入将在核对时拒绝
 draft.attempt += 1
 draft.state = 'computing'
 draft.error = None
 draft.effective_id = None  # 新一轮制表尚未核对，解除旧生效指针
 draft.version += 1
 draft.updated = _now()
 db.flush()
 log(db, user.email, 'declaration.tabulate',
     {'run_id': run_id, 'draft_id': draft.id, 'attempt': draft.attempt})
 try:
  matrix = build_original_matrix(run.snapshot)
  result = round_declaration(matrix)
 except Exception as exc:  # 重算本身失败：保留草案为 computing，可再次重试恢复
  draft.state = 'computing'
  draft.error = '重算失败：%s' % exc
  draft.updated = _now()
  db.commit()
  raise HTTPException(500, draft.error)
 if result['feasible']:
  draft.state = 'ready'
  draft.result = _jsonable(result)
  draft.error = None
 else:
  # 无解：指出冲突并沿用上一版生效表
  draft.state = 'conflict'
  draft.result = _jsonable(result)
  draft.error = '；'.join(result['conflicts'])
  log(db, user.email, 'declaration.conflict',
      {'run_id': run_id, 'draft_id': draft.id, 'conflicts': result['conflicts']})
 draft.updated = _now()
 db.commit()
 db.refresh(draft)
 return draft


def confirm_draft(db, user, draft_id):
 """核对通过：整表生效。乐观锁拒绝并发核算产生的旧草案覆盖现行表。"""
 draft = db.get(DeclarationDraft, draft_id)
 if not draft:
  raise HTTPException(404, '草案不存在')
 _advisory_lock(db, draft.run_id)  # 与同报告的制表互斥
 db.refresh(draft)
 if draft.state != 'ready':
  raise HTTPException(409, '仅待核对且取整可行的草案可以核对生效（当前状态：%s）' % draft.state)
 if not draft.result or not draft.result.get('feasible'):
  raise HTTPException(409, '草案无可行取整方案，不能生效')
 effective = get_effective(db, draft.run_id)
 if effective is not None:
  # 现行表存在：仅当草案基于更新版本时才允许覆盖，防止旧草案回写
  if draft.version <= effective.version:
   raise HTTPException(409, '现行表版本不低于该草案，已拒绝旧草案覆盖')
  effective.active = False
  new_version = effective.version + 1
 else:
  new_version = 1
 payload = _jsonable(draft.result)
 checksum = _result_checksum(payload)
 obj = EffectiveDeclaration(run_id=draft.run_id, draft_id=draft.id,
                            version=new_version, result=payload, checksum=checksum,
                            active=True, created=_now(), updated=_now())
 db.add(obj)
 db.flush()
 draft.state = 'effective'
 draft.effective_id = obj.id
 draft.updated = _now()
 log(db, user.email, 'declaration.effective',
     {'run_id': draft.run_id, 'effective_id': obj.id, 'version': new_version})
 db.commit()
 db.refresh(obj)
 return obj


def list_state(db):
 drafts = db.query(DeclarationDraft).order_by(DeclarationDraft.id.desc()).all()
 effectives = db.query(EffectiveDeclaration).filter_by(active=True).all()
 return {'drafts': [_draft_row(x) for x in drafts],
         'effectives': [_effective_row(x) for x in effectives]}


def _draft_row(obj):
 return {'id': obj.id, 'run_id': obj.run_id, 'state': obj.state, 'attempt': obj.attempt,
         'version': obj.version, 'effective_id': obj.effective_id, 'error': obj.error,
         'created': obj.created, 'updated': obj.updated,
         'result': _jsonable(obj.result) if obj.result else None}


def _effective_row(obj):
 return {'id': obj.id, 'run_id': obj.run_id, 'draft_id': obj.draft_id,
         'version': obj.version, 'checksum': obj.checksum, 'active': obj.active,
         'created': obj.created, 'updated': obj.updated, 'result': _jsonable(obj.result)}


def _jsonable(value):
 """Decimal 等不可直接 JSON 序列化的值转为字符串/数字安全结构。"""
 if isinstance(value, dict):
  return {k: _jsonable(v) for k, v in value.items()}
 if isinstance(value, (list, tuple)):
  return [_jsonable(v) for v in value]
 from decimal import Decimal
 if isinstance(value, Decimal):
  # 整数形态保持 int，便于前端按整数公斤展示
  if value == value.to_integral_value():
   return int(value)
  return float(value)
 return value
