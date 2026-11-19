"""受控取整算法单元测试（仅标准库，可在无第三方依赖环境运行）。

运行：cd backend && python -m tests.test_declaration
暴力枚举独立校验：枚举每格 floor/ceil 全部组合，核对最小费用流解的
最优性与字典序同分规则。
"""
import sys
import types
import unittest
from decimal import Decimal
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 桩掉依赖环境变量与 /app/project.json 的配置层
settings = types.ModuleType('src.config.settings')
settings.CONFIG = {'fields': ['period', 'department', 'activity', 'quantity', 'unit']}
settings.DATABASE_URL = 'sqlite://'
settings.REDIS_URL = 'redis://localhost:6379/0'
settings.SECRET = 'test'
sys.modules['src.config.settings'] = settings

from src.services.declaration import (  # noqa: E402
 build_original_matrix, round_declaration, solve_rounding, half_up_int, frac_scaled, SCALE)

POLICY = {'version': 'v-test', 'scope': '单元测试口径范围不少于五个字',
          'factors': {'电力': {'unit': 'kWh', 'kg_per_unit': 0.5},
                      '柴油': {'unit': 'L', 'kg_per_unit': 2.0}}}


def snapshot_from_grid(values):
 """values: {(dept,act): (quantity, unit)}，period 统一。"""
 sources = []
 for (dept, act), (qty, unit) in values.items():
  sources.append({'period': '2026-11', 'department': dept, 'activity': act,
                  'quantity': qty, 'unit': unit})
 return {'period': '2026-11', 'policy': POLICY, 'sources': sources}


def brute_force(matrix):
 """枚举所有 floor/ceil 组合，返回 (最优总绝对偏差, 字典序最小赋值展平元组)。
 规定总量与实现一致：行/列原值合计半进位取整；无解返回 None。"""
 depts, acts = matrix['departments'], matrix['activities']
 grid = matrix['grid']
 options = []
 for i in range(len(depts)):
  row_opts = []
  for j in range(len(acts)):
   v = grid[i][j]['original']
   fl = int(v)
   row_opts.append([fl] if frac_scaled(v) == 0 else [fl, fl + 1])
  options.append(row_opts)
 row_target = [half_up_int(sum((grid[i][j]['original'] for j in range(len(acts))), Decimal(0)))
               for i in range(len(depts))]
 col_target = [half_up_int(sum((grid[i][j]['original'] for i in range(len(depts))), Decimal(0)))
               for j in range(len(acts))]
 if sum(row_target) != sum(col_target):
  return None
 best = None
 cell_choices = [options[i][j] for i in range(len(depts)) for j in range(len(acts))]
 for combo in product(*cell_choices):
  assign = [list(combo[i * len(acts):(i + 1) * len(acts)]) for i in range(len(depts))]
  if [sum(r) for r in assign] != row_target:
   continue
  if [sum(assign[i][j] for i in range(len(depts))) for j in range(len(acts))] != col_target:
   continue
  obj = sum(abs(Decimal(assign[i][j]) - grid[i][j]['original'])
            for i in range(len(depts)) for j in range(len(acts)))
  if best is None or (obj, combo) < (best[0], best[1]):
   best = (obj, combo)
 return best


class RoundingTests(unittest.TestCase):
 def assertBalanced(self, res):
  m, n = len(res['departments']), len(res['activities'])
  for i in range(m):
   self.assertEqual(sum(res['assignment'][i]), res['row_target'][i])
  for j in range(n):
   self.assertEqual(sum(res['assignment'][i][j] for i in range(m)), res['col_target'][j])

 def test_handcrafted_2x2(self):
  snap = snapshot_from_grid({
   ('材料室', '电力'): (1.2, 'kWh'), ('材料室', '柴油'): (1.0, 'L'),
   ('光学室', '电力'): (2.6, 'kWh'), ('光学室', '柴油'): (3.0, 'L')})
  matrix = build_original_matrix(snap)
  res = round_declaration(matrix)
  self.assertTrue(res['feasible'], res['conflicts'])
  self.assertBalanced(res)
  # 原值矩阵（kg），部门按字典序：光学室 [1.3, 6.0]、材料室 [0.6, 2.0]
  # 活动按字典序：柴油、电力；规定总量（半进位）：行 [7, 3]，列 [8, 2]，合计 10
  self.assertEqual(res['departments'], ['光学室', '材料室'])
  self.assertEqual(res['activities'], ['柴油', '电力'])
  self.assertEqual(res['row_target'], [7, 3])
  self.assertEqual(res['col_target'], [8, 2])
  self.assertEqual(res['assignment'], [[6, 1], [2, 1]])
  self.assertEqual(res['grand_total'], 10)
  # 总绝对偏差 = |6-6|+|1-1.3|+|2-2|+|1-0.6| = 0.7
  self.assertEqual(res['total_abs_deviation'], Decimal('0.7'))

 def test_integer_cells_fixed(self):
  snap = snapshot_from_grid({
   ('A', '电力'): (2.0, 'kWh'), ('A', '柴油'): (1.5, 'L'),
   ('B', '电力'): (4.0, 'kWh'), ('B', '柴油'): (2.5, 'L')})
  res = round_declaration(build_original_matrix(snap))
  self.assertTrue(res['feasible'])
  self.assertBalanced(res)
  for cell in res['cells']:
   if frac_scaled(cell['original_kg']) == 0:
    self.assertEqual(cell['rounded_kg'], int(cell['original_kg']))
    self.assertEqual(cell['direction'], '原值整数')

 def test_half_up_totals(self):
  self.assertEqual(half_up_int(Decimal('2.5')), 3)
  self.assertEqual(half_up_int(Decimal('2.4')), 2)
  self.assertEqual(half_up_int(Decimal('-0.0')), 0)

 def test_conflict_when_totals_disagree(self):
  # 构造行合计与列合计半进位后不一致：行 [0.4,0.4]→[0,0]，列 [0.8,0.0]→[1,0]
  matrix = {'departments': ['D1', 'D2'], 'activities': ['A1', 'A2'],
            'grid': [[{'department': 'D1', 'activity': 'A1', 'original': Decimal('0.4'), 'unit': '', 'records': 1},
                      {'department': 'D1', 'activity': 'A2', 'original': Decimal('0'), 'unit': '', 'records': 0}],
                     [{'department': 'D2', 'activity': 'A1', 'original': Decimal('0.4'), 'unit': '', 'records': 1},
                      {'department': 'D2', 'activity': 'A2', 'original': Decimal('0'), 'unit': '', 'records': 0}]]}
  res = round_declaration(matrix)
  self.assertFalse(res['feasible'])
  self.assertTrue(res['conflicts'])

 def test_brute_force_random_matrices(self):
  import random
  rng = random.Random(20261118)
  for trial in range(120):
   m = rng.randint(1, 3)
   n = rng.randint(1, 3)
   depts = ['部门%02d' % i for i in range(m)]
   acts = ['活动%02d' % j for j in range(n)]
   grid = []
   for i in range(m):
    row = []
    for j in range(n):
     # 含整数、零、较大值，覆盖边界
     whole = rng.randint(0, 30)
     tenth = rng.choice([0, 0, 1, 5, 9])
     v = Decimal(whole) + Decimal(tenth) / Decimal(10)
     row.append({'department': depts[i], 'activity': acts[j], 'original': v, 'unit': '', 'records': 1})
    grid.append(row)
   matrix = {'departments': depts, 'activities': acts, 'grid': grid}
   res = round_declaration(matrix)
   best = brute_force(matrix)
   if best is None:
    self.assertFalse(res['feasible'], 'trial %d 应无解' % trial)
    self.assertTrue(res['conflicts'])
    continue
   self.assertTrue(res['feasible'], 'trial %d 应有解: %s' % (trial, res['conflicts']))
   self.assertBalanced(res)
   self.assertEqual(res['total_abs_deviation'], best[0])
   flat = tuple(res['assignment'][i][j] for i in range(m) for j in range(n))
   self.assertEqual(flat, best[1], 'trial %d 字典序同分选择错误' % trial)

 def test_greedy_preserves_feasibility(self):
  # 固定阶段的每次尝试都必须保持可行或明确不可行，不抛异常
  import random
  rng = random.Random(7)
  for _ in range(20):
   m, n = rng.randint(2, 4), rng.randint(2, 4)
   grid = []
   for i in range(m):
    row = [{'department': 'D%d' % i, 'activity': 'A%d' % j,
            'original': Decimal(rng.randint(1, 9)) + Decimal(rng.randint(1, 9)) / Decimal(10),
            'unit': '', 'records': 1} for j in range(n)]
    grid.append(row)
   matrix = {'departments': ['D%d' % i for i in range(m)],
             'activities': ['A%d' % j for j in range(n)], 'grid': grid}
   res = round_declaration(matrix)
   if res['feasible']:
    self.assertBalanced(res)
   else:
    # 无解时必须给出明确冲突说明，且不能产出 assignment
    self.assertTrue(res['conflicts'])
    self.assertNotIn('assignment', res)

 def test_zero_matrix(self):
  matrix = {'departments': ['D'], 'activities': ['A'],
            'grid': [[{'department': 'D', 'activity': 'A', 'original': Decimal('0'), 'unit': '', 'records': 0}]]}
  res = round_declaration(matrix)
  self.assertTrue(res['feasible'])
  self.assertEqual(res['assignment'], [[0]])
  self.assertEqual(res['total_abs_deviation'], Decimal(0))

 def test_recompute_uses_frozen_snapshot(self):
  # 同一冻结快照两次重算结果完全一致
  snap = snapshot_from_grid({('材料室', '电力'): (3.3, 'kWh'), ('材料室', '柴油'): (1.2, 'L')})
  a = round_declaration(build_original_matrix(snap))
  b = round_declaration(build_original_matrix(snap))
  self.assertEqual(a['assignment'], b['assignment'])
  self.assertEqual(a['objective_scaled'], b['objective_scaled'])


if __name__ == '__main__':
 unittest.main(verbosity=2)
