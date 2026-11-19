"""定时交付携带完整生效表、旧交付保留原件的测试（标准库 + stub）。"""
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 复用工作流测试的 stub 环境
from tests import test_declaration_workflow as stub  # noqa: E402,F401
from src.models.run import Run, Schedule, Delivery  # noqa: E402
from src.models.declaration import EffectiveDeclaration  # noqa: E402
from src.services import delivery as delivery_svc  # noqa: E402


class DeliveryTests(unittest.TestCase):
 def setUp(self):
  self.db = stub._Session()
  self.user = stub.User('admin@demo.local')
  self.result = {'feasible': True, 'departments': ['D'], 'activities': ['A'],
                 'assignment': [[3]], 'row_target': [3], 'col_target': [3],
                 'row_original': [2.6], 'col_original': [2.6], 'grand_total': 3,
                 'cells': [{'department': 'D', 'activity': 'A', 'original_kg': 2.6,
                            'rounded_kg': 3, 'difference_kg': 0.4, 'direction': '向上取整'}]}
  run = Run(id=1, name='r1', status='completed', approved=True,
            snapshot={'policy': {'version': 'v'}, 'sources': []}, checksum='sum',
            result={'rows': [{'x': 1}]}, review='ok')
  self.db.runs[1] = run

 def _schedule(self, next_at=0.0):
  sch = Schedule(id=1, name='s', run_id=1, interval_seconds=60, next_at=next_at, enabled=True)
  self.db.add(sch)
  return sch

 def test_tick_embeds_effective_snapshot(self):
  eff = EffectiveDeclaration(run_id=1, draft_id=9, version=1, result=self.result,
                              checksum='c' * 64, active=True)
  self.db.add(eff)
  self._schedule(next_at=1.0)
  delivery_svc.tick(self.db)
  deliveries = self.db.query(Delivery).all()
  self.assertEqual(len(deliveries), 1)
  payload = deliveries[0].payload
  self.assertIn('declaration', payload)
  self.assertEqual(payload['declaration']['version'], 1)
  self.assertEqual(payload['declaration']['result']['grand_total'], 3)
  # 计划时间被推进
  sch = self.db.get(Schedule, 1)
  self.assertGreater(sch.next_at, 1.0)

 def test_tick_without_effective_keeps_null_declaration(self):
  self._schedule(next_at=1.0)
  delivery_svc.tick(self.db)
  payload = self.db.query(Delivery).one_or_none().payload
  self.assertIsNone(payload['declaration'])

 def test_due_key_idempotent_no_duplicate(self):
  self._schedule(next_at=1.0)
  delivery_svc.tick(self.db)
  first = self.db.query(Delivery).one_or_none()
  # 不推进 next_at 的情况下再次 tick，due_key 相同，不产生第二条
  self.db.get(Schedule, 1).next_at = 1.0
  delivery_svc.tick(self.db)
  self.assertEqual(len(self.db.query(Delivery).all()), 1)
  # 旧交付 payload 不可变：再次 tick 后内容仍为首次快照
  self.assertEqual(self.db.query(Delivery).one_or_none().id, first.id)

 def test_old_delivery_unchanged_after_new_effective(self):
  # 第一次交付：无生效表
  self._schedule(next_at=1.0)
  delivery_svc.tick(self.db)
  old = self.db.query(Delivery).all()[0]
  self.assertIsNone(old.payload['declaration'])
  # 之后生效申报表，下一次交付携带新生效表；旧交付原件不变
  eff = EffectiveDeclaration(run_id=1, draft_id=9, version=1, result=self.result,
                             checksum='c' * 64, active=True)
  self.db.add(eff)
  self.db.get(Schedule, 1).next_at = -100.0  # 不同到期点，due_key 唯一
  delivery_svc.tick(self.db)
  by_key = {d.due_key: d for d in self.db.query(Delivery).all()}
  self.assertEqual(len(by_key), 2)
  old, new = by_key['1:1.0'], by_key['1:-100.0']
  self.assertIsNone(old.payload['declaration'])  # 旧件原件不变
  self.assertIsNotNone(new.payload['declaration'])  # 新件含完整生效表
  self.assertEqual(new.payload['declaration']['result']['grand_total'], 3)


if __name__ == '__main__':
 unittest.main(verbosity=2)
