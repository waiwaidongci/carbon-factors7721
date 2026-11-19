"""申报表工作流状态机测试（仅标准库，stub 掉 fastapi/sqlalchemy）。

覆盖：
- 中断恢复：computing 草案重试复用同一行，attempt 累加、不新增版本
- 冲突无解：指出冲突、保留旧生效表；重试成功后可核对产生新生效版本
- 并发保护：旧草案（version 不占优）不得覆盖现行表
- 定时交付快照在独立测试中验证
"""
import sys
import types
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ---------- 第三方依赖 stub ----------
fastapi = types.ModuleType('fastapi')


class HTTPException(Exception):
 def __init__(self, status_code, detail):
  self.status_code = status_code
  self.detail = detail
  super().__init__(detail)


fastapi.HTTPException = HTTPException
sys.modules['fastapi'] = fastapi

sa = types.ModuleType('sqlalchemy')


class _Expr:
 def __init__(self, name, op, value):
  self.name = name
  self.op = op
  self.value = value

 def __call__(self, row):
  actual = getattr(row, self.name, None)
  if self.op == '==': return actual == self.value
  if self.op == '!=': return actual != self.value
  if self.op == '<=': return actual <= self.value
  if self.op == '>=': return actual >= self.value
  if self.op == '<': return actual < self.value
  if self.op == '>': return actual > self.value
  raise ValueError(self.op)


class _Column:
 def __init__(self, *args, **kwargs):
  self.name = None
  self.kwargs = kwargs

 def desc(self):
  return self

 def __eq__(self, value): return _Expr(self.name, '==', value)
 def __ne__(self, value): return _Expr(self.name, '!=', value)
 def __le__(self, value): return _Expr(self.name, '<=', value)
 def __ge__(self, value): return _Expr(self.name, '>=', value)
 def __lt__(self, value): return _Expr(self.name, '<', value)
 def __gt__(self, value): return _Expr(self.name, '>', value)
 def __hash__(self): return hash(self.name)


def Column(*args, **kwargs):
 return _Column(*args, **kwargs)


class _Meta(type):
 def __new__(mcs, name, bases, ns):
  cls = super().__new__(mcs, name, bases, ns)
  cols = {}
  for base in bases:
   cols.update(getattr(base, '_columns', {}))
  for k, v in list(ns.items()):
   if isinstance(v, _Column):
    v.name = k
    cols[k] = v
  cls._columns = cols

  def init(self, **kw):
   for col_name in cols:
    setattr(self, col_name, kw.get(col_name, cols[col_name].kwargs.get('default')))
  cls.__init__ = init
  return cls


class Base(metaclass=_Meta):
 pass


class _Type:
 def __init__(self, *a, **k): pass
 def __call__(self, *a, **k): return self


sa.Column = Column
sa.Integer = sa.String = sa.JSON = sa.Text = sa.Float = sa.Boolean = _Type()
sa.UniqueConstraint = lambda *a, **k: None
sys.modules['sqlalchemy'] = sa

sa_text = types.ModuleType('sqlalchemy.text')
sa.text = lambda sql: sql
sys.modules['sqlalchemy.text'] = sa_text

# 配置层 stub
settings = types.ModuleType('src.config.settings')
settings.CONFIG = {'fields': ['period', 'department', 'activity', 'quantity', 'unit']}
settings.DATABASE_URL = 'sqlite://'
settings.REDIS_URL = 'x'
settings.SECRET = 't'
sys.modules['src.config.settings'] = settings

database_mod = types.ModuleType('src.config.database')


class _Session:
 def __init__(self):
  self.next_id = 1
  self.runs = {}
  self.drafts = {}
  self.effectives = {}
  self.schedules = {}
  self.deliveries = {}
  self.audits = []

 def get(self, model, pk):
  store = self._store(model)
  return store.get(pk) if store is not None else None

 def _store(self, model):
  from src.models.run import Run, Schedule, Delivery
  from src.models.declaration import DeclarationDraft, EffectiveDeclaration
  return {Run: self.runs, DeclarationDraft: self.drafts,
          EffectiveDeclaration: self.effectives, Schedule: self.schedules,
          Delivery: self.deliveries}.get(model)

 def add(self, obj):
  model = type(obj)
  store = self._store(model)
  if getattr(obj, 'id', None) is None:
   obj.id = self.next_id
   self.next_id += 1
  store[obj.id] = obj

 def flush(self): pass
 def commit(self): pass
 def refresh(self, obj): pass
 def execute(self, sql, params=None):  # FOR UPDATE / 咨询锁在单线程测试中直通
  class _R:
   @staticmethod
   def first(): return ('locked',)
  return _R()

 class _Q:
  def __init__(self, outer, model):
   self.outer = outer
   self.model = model
   self._filters = {}
   self._predicates = []
   self._desc = False
   self._limit = None

  def filter_by(self, **kw):
   self._filters.update(kw)
   return self

  def filter(self, *expressions):
   for expr in expressions:
    self._predicates.append(expr)
   return self

  def order_by(self, *_a, **_k):
   self._desc = True
   return self

  def limit(self, _n):
   self._limit = _n
   return self

  def all(self):
   store = self.outer._store(self.model)
   rows = list(store.values())
   for k, v in self._filters.items():
    rows = [r for r in rows if getattr(r, k, None) == v]
   for pred in self._predicates:
    rows = [r for r in rows if pred(r)]
   if self._desc:
    rows = list(reversed(rows))
   return rows[:self._limit] if self._limit else rows

  def one_or_none(self):
   rows = self.all()
   return rows[0] if rows else None

  def first(self):
   rows = self.all()
   return rows[0] if rows else None

 def query(self, model):
  return _Session._Q(self, model)


database_mod.Base = Base
database_mod.engine = None
database_mod.Session = _Session
sys.modules['src.config.database'] = database_mod

# 审计 log 落到 session.audits
audit_mod = types.ModuleType('src.services.audit')


def log(db, actor, action, detail):
 db.audits.append((actor, action, str(detail)))


audit_mod.log = log
sys.modules['src.services.audit'] = audit_mod

from src.models.run import Run  # noqa: E402
from src.models.declaration import DeclarationDraft, EffectiveDeclaration  # noqa: E402
from src.services import declaration_workflow as wf  # noqa: E402

POLICY = {'version': 'v1', 'scope': '工作流测试口径范围不少于五个字',
          'factors': {'电力': {'unit': 'kWh', 'kg_per_unit': 0.5},
                      '柴油': {'unit': 'L', 'kg_per_unit': 2.0}}}


def approved_run(db, sources):
 run = Run(id=1, name='r1', status='completed', approved=True,
           snapshot={'policy': POLICY, 'sources': sources}, checksum='abc')
 db.runs[1] = run
 return run


def src(dept, act, qty, unit):
 return {'period': '2026-11', 'department': dept, 'activity': act, 'quantity': qty, 'unit': unit}


class User:
 def __init__(self, email): self.email = email


class WorkflowTests(unittest.TestCase):
 def setUp(self):
  self.db = _Session()
  self.user = User('admin@demo.local')
  # 2x2 可行矩阵：电力(kWh,×0.5) 与柴油(L,×2)
  self.sources = [src('材料室', '电力', 2.4, 'kWh'), src('材料室', '柴油', 1.0, 'L'),
                  src('光学室', '电力', 5.2, 'kWh'), src('光学室', '柴油', 1.5, 'L')]
  approved_run(self.db, self.sources)

 def test_tabulate_then_confirm_effective(self):
  draft = wf.create_or_retry_draft(self.db, self.user, 1)
  self.assertEqual(draft.state, 'ready')
  self.assertEqual(draft.attempt, 1)
  self.assertTrue(draft.result['feasible'])
  # 行列对平
  for i, total in enumerate(draft.result['row_target']):
   self.assertEqual(sum(draft.result['assignment'][i]), total)
  eff = wf.confirm_draft(self.db, self.user, draft.id)
  self.assertEqual(eff.version, 1)
  self.assertTrue(eff.active)
  self.assertEqual(len(eff.checksum), 64)
  self.db.refresh(draft)
  self.assertEqual(draft.state, 'effective')
  self.assertEqual(draft.effective_id, eff.id)

 def test_interrupted_retry_keeps_single_draft(self):
  first = wf.create_or_retry_draft(self.db, self.user, 1)
  first_id = first.id
  # 模拟中断：草案停留在 computing
  first.state = 'computing'
  again = wf.create_or_retry_draft(self.db, self.user, 1)
  self.assertEqual(again.id, first_id)  # 同一草案，不新增版本
  self.assertEqual(again.attempt, 2)
  self.assertEqual(len(self.db.drafts), 1)
  self.assertEqual(again.state, 'ready')

 def test_ready_cannot_retabulate(self):
  draft = wf.create_or_retry_draft(self.db, self.user, 1)
  with self.assertRaises(HTTPException) as ctx:
   wf.create_or_retry_draft(self.db, self.user, 1)
  self.assertEqual(ctx.exception.status_code, 409)
  self.assertEqual(draft.attempt, 1)

 def test_conflict_keeps_previous_effective(self):
  # 先产生 v1 生效表
  draft = wf.create_or_retry_draft(self.db, self.user, 1)
  eff1 = wf.confirm_draft(self.db, self.user, draft.id)
  # 改成无解矩阵：单列两行 [0.4,0.4]→行目标[0,0]，列目标[1]
  self.db.runs[1].snapshot = {'policy': POLICY, 'sources': [
   src('材料室', '电力', 0.8, 'kWh'), src('光学室', '电力', 0.8, 'kWh')]}
  retry = wf.create_or_retry_draft(self.db, self.user, 1)
  self.assertEqual(retry.state, 'conflict')
  self.assertTrue(retry.error)
  self.assertIsNone(retry.effective_id)
  # 旧生效表仍为现行
  current = wf.get_effective(self.db, 1)
  self.assertEqual(current.id, eff1.id)
  self.assertTrue(current.active)
  # 恢复可行数据后重试同一草案
  self.db.runs[1].snapshot = {'policy': POLICY, 'sources': self.sources}
  fixed = wf.create_or_retry_draft(self.db, self.user, 1)
  self.assertEqual(fixed.id, retry.id)
  self.assertEqual(fixed.state, 'ready')
  eff2 = wf.confirm_draft(self.db, self.user, fixed.id)
  self.assertEqual(eff2.version, 2)
  self.assertTrue(eff2.active)
  self.db.refresh(eff1)
  self.assertFalse(eff1.active)  # 旧版本留痕但失效

 def test_stale_draft_cannot_overwrite_effective(self):
  draft = wf.create_or_retry_draft(self.db, self.user, 1)
  eff1 = wf.confirm_draft(self.db, self.user, draft.id)
  # 修订重算产生新草案（version 已递增），人为把版本回拨成旧草案
  retry = wf.create_or_retry_draft(self.db, self.user, 1)
  self.assertEqual(retry.state, 'ready')
  retry.version = eff1.version  # 模拟并发下的旧草案
  with self.assertRaises(HTTPException) as ctx:
   wf.confirm_draft(self.db, self.user, retry.id)
  self.assertEqual(ctx.exception.status_code, 409)
  # 现行表未被覆盖
  self.assertEqual(wf.get_effective(self.db, 1).id, eff1.id)

 def test_unapproved_run_rejected(self):
  self.db.runs[1].approved = False
  with self.assertRaises(HTTPException) as ctx:
   wf.create_or_retry_draft(self.db, self.user, 1)
  self.assertEqual(ctx.exception.status_code, 409)

 def test_list_state_shape(self):
  wf.create_or_retry_draft(self.db, self.user, 1)
  state = wf.list_state(self.db)
  self.assertIn('drafts', state)
  self.assertIn('effectives', state)
  self.assertEqual(len(state['drafts']), 1)
  self.assertEqual(state['drafts'][0]['state'], 'ready')


if __name__ == '__main__':
 unittest.main(verbosity=2)
