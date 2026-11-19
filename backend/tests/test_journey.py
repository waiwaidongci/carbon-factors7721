"""端到端业务旅程集成测试：完整串联取重算→制表→核对→冲突沿用→再生效→定时交付。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests import test_declaration_workflow as stub  # noqa: E402,F401
from src.models.run import Run  # noqa: E402
from src.services import declaration_workflow as wf  # noqa: E402
from src.services import delivery as ds  # noqa: E402
from src.services.export import declaration_csv, declaration_rows  # noqa: E402


def src(dept, act, qty, unit):
 return {'period': '2026-11', 'department': dept, 'activity': act, 'quantity': qty, 'unit': unit}


POLICY = {'version': 'v1', 'scope': '端到端测试口径范围不少于五个字',
          'factors': {'电力': {'unit': 'kWh', 'kg_per_unit': 0.57},
                      '柴油': {'unit': 'L', 'kg_per_unit': 2.68},
                      '通勤': {'unit': 'km', 'kg_per_unit': 0.12}}}


class JourneyTests(unittest.TestCase):
 def setUp(self):
  self.db = stub._Session()
  self.admin = stub.User('admin@demo.local')
  self.analyst = stub.User('analyst@demo.local')
  # 3 部门 × 3 活动，含因子换算；用量按因子取整设计，使每格原始排放均为整数 kg，
  # 行列规定总量天然可对平（取整偏差为 0）。
  sources = []
  data = [('材料室', '电力', 1000.0, 'kWh'), ('材料室', '柴油', 25.0, 'L'), ('材料室', '通勤', 25.0, 'km'),
          ('工艺室', '电力', 2000.0, 'kWh'), ('工艺室', '柴油', 50.0, 'L'), ('工艺室', '通勤', 50.0, 'km'),
          ('光学室', '电力', 1000.0, 'kWh'), ('光学室', '柴油', 25.0, 'L'), ('光学室', '通勤', 25.0, 'km')]
  for d, a, q, u in data:
   sources.append(src(d, a, q, u))
  self.sources = sources
  run = Run(id=1, name='十一月核算', status='completed', approved=True,
            snapshot={'policy': POLICY, 'sources': sources}, checksum='sha')
  self.db.runs[1] = run

 def test_full_journey(self):
  # 1) 分析师制表
  draft = wf.create_or_retry_draft(self.db, self.analyst, 1)
  self.assertEqual(draft.state, 'ready')
  res = draft.result
  # 2) 行列对平
  for i, total in enumerate(res['row_target']):
   self.assertEqual(sum(res['assignment'][i]), total)
  for j, total in enumerate(res['col_target']):
   self.assertEqual(sum(res['assignment'][i][j] for i in range(len(res['departments']))), total)
  self.assertEqual(sum(res['row_target']), sum(res['col_target']), res['grand_total'])
  # 3) 每格都是 floor/ceil 之一（整数格等于原值）
  from src.services.declaration import frac_scaled
  from decimal import Decimal
  for cell in res['cells']:
   v = Decimal(str(cell['original_kg']))
   z = cell['rounded_kg']
   self.assertIn(z, (int(v), int(v) + (0 if frac_scaled(v) == 0 else 1)))
  # 4) 管理员核对生效
  eff1 = wf.confirm_draft(self.db, self.admin, draft.id)
  self.assertEqual(eff1.version, 1)
  # 5) 定时交付携带完整生效表
  from src.models.run import Schedule
  sch = Schedule(id=1, name='计划', run_id=1, interval_seconds=60, next_at=0.0, enabled=True)
  self.db.add(sch)
  ds.tick(self.db)
  from src.models.run import Delivery
  d1 = self.db.query(Delivery).all()[0]
  self.assertEqual(d1.payload['declaration']['version'], 1)
  # 交付 CSV 可生成且含取整前后列
  csv1 = declaration_csv(d1.payload['declaration']['result'])
  self.assertIn('原值kg', csv1)
  self.assertIn('整数kg', csv1)
  # 6) 修订重算（数据不变，结果一致但版本递增）
  redraft = wf.create_or_retry_draft(self.db, self.analyst, 1)
  self.assertEqual(redraft.id, draft.id)  # 同草案
  self.assertEqual(redraft.attempt, 2)
  eff2 = wf.confirm_draft(self.db, self.admin, redraft.id)
  self.assertEqual(eff2.version, 2)
  self.db.refresh(eff1)
  self.assertFalse(eff1.active)
  self.assertTrue(eff2.active)
  # 7) 下一次交付带 v2；旧交付原件仍是 v1（用不同到期点，due_key 唯一）
  self.db.get(Schedule, 1).next_at = -100.0
  ds.tick(self.db)
  deliveries = {d.id: d for d in self.db.query(Delivery).all()}
  old = next(d for d in deliveries.values() if d.payload['declaration']['version'] == 1)
  new = [d for d in deliveries.values() if d.payload['declaration']['version'] == 2][0]
  self.assertEqual(len(deliveries), 2)
  self.assertEqual(old.payload['declaration']['id'], eff1.id)
  self.assertEqual(new.payload['declaration']['id'], eff2.id)
  # 8) 透视行结构完整
  rows = declaration_rows(eff2.result)
  self.assertEqual(rows[-1]['部门规定总量kg'], eff2.result['grand_total'])

 def test_conflict_then_restore_keeps_current_effective(self):
  # 先生效一版
  draft = wf.create_or_retry_draft(self.db, self.analyst, 1)
  eff1 = wf.confirm_draft(self.db, self.admin, draft.id)
  # 换成行列总量对不平的数据：单活动两行各 0.4kg（0.8kWh×0.5），
  # 行目标各 0、列目标 1，合计不一致 → 无解冲突
  tiny_policy = {'version': 'v1', 'scope': '冲突场景口径范围不少于五个字',
                 'factors': {'电力': {'unit': 'kWh', 'kg_per_unit': 0.5}}}
  self.db.runs[1].snapshot = {'policy': tiny_policy, 'sources': [
   src('材料室', '电力', 0.8, 'kWh'),
   src('工艺室', '电力', 0.8, 'kWh')]}
  conflict = wf.create_or_retry_draft(self.db, self.analyst, 1)
  self.assertEqual(conflict.state, 'conflict')
  self.assertTrue(conflict.error)
  # 现行表沿用，未被覆盖
  self.assertEqual(wf.get_effective(self.db, 1).id, eff1.id)
  self.assertTrue(wf.get_effective(self.db, 1).active)
  # 恢复数据后同一草案重试成功并产生新版本
  self.db.runs[1].snapshot = {'policy': POLICY, 'sources': self.sources}
  restored = wf.create_or_retry_draft(self.db, self.analyst, 1)
  self.assertEqual(restored.id, conflict.id)
  self.assertEqual(restored.state, 'ready')
  eff2 = wf.confirm_draft(self.db, self.admin, restored.id)
  self.assertEqual(eff2.version, 2)


if __name__ == '__main__':
 unittest.main(verbosity=2)
