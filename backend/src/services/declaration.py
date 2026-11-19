from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
from src.services.calculation import emissions

SCALE = 10 ** 9


# ---------- 由已复核报告的冻结底稿重算原值 ----------

def build_original_matrix(snapshot):
 """用冻结来源与冻结口径重算 部门×活动 的原始排放矩阵（kgCO2e，Decimal）。"""
 policy = snapshot['policy']
 factors = policy['factors']
 agg = defaultdict(Decimal)
 units = {}
 counts = defaultdict(int)
 for s in snapshot['sources']:
  _, kg = emissions(s['activity'], s['quantity'], s['unit'], factors)
  key = (s['department'], s['activity'])
  agg[key] += kg
  units[s['activity']] = factors[s['activity']]['unit']
  counts[key] += 1
 departments = sorted({d for d, _ in agg})
 activities = sorted({a for _, a in agg})
 grid = []
 for dept in departments:
  row = []
  for act in activities:
   value = agg.get((dept, act), Decimal(0))
   row.append({'department': dept, 'activity': act, 'original': value,
               'unit': units.get(act, ''), 'records': counts.get((dept, act), 0)})
  grid.append(row)
 return {'departments': departments, 'activities': activities, 'grid': grid}


def half_up_int(value):
 return int(value.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def frac_scaled(value):
 """小数部分放大 SCALE 取整，全程不经过 float。整数返回 0。"""
 frac = value - Decimal(int(value))
 return int((frac * SCALE).to_integral_value(rounding=ROUND_HALF_UP))


def _bounds(value):
 """单元格可取整区间 [floor, ceil]；整数格上下界相同。"""
 fl = int(value)
 return fl, fl if frac_scaled(value) == 0 else fl + 1


# ---------- 最小费用流（整数费用，SPFA 最短路，处理反向边） ----------

class _Net:
 def __init__(self, n):
  self.n = n
  self.g = [[] for _ in range(n)]

 def edge(self, u, v, cap, cost):
  # [对端, 残余容量, 单位费用, 反向边下标]，返回正向边对象引用
  forward = [v, cap, cost, len(self.g[v])]
  backward = [u, 0, -cost, len(self.g[u])]
  self.g[u].append(forward)
  self.g[v].append(backward)
  return forward

 def _spfa(self, s, t):
  inf = 10 ** 30
  dist = [inf] * self.n
  inq = [False] * self.n
  pv = [-1] * self.n
  pe = [-1] * self.n
  dist[s] = 0
  queue = [s]
  inq[s] = True
  head = 0
  while head < len(queue):
   u = queue[head]
   head += 1
   inq[u] = False
   for i, (v, cap, cost, _) in enumerate(self.g[u]):
    if cap > 0 and dist[u] + cost < dist[v]:
     dist[v] = dist[u] + cost
     pv[v], pe[v] = u, i
     if not inq[v]:
      queue.append(v)
      inq[v] = True
  return (pv, pe) if dist[t] < inf else None

 def min_cost_flow(self, s, t, need):
  """返回 (实际流量, 最小费用)。"""
  flow = cost = 0
  while flow < need:
   res = self._spfa(s, t)
   if res is None:
    break
   pv, pe = res
   add = need - flow
   v = t
   while v != s:
    u, i = pv[v], pe[v]
    add = min(add, self.g[u][i][1])
    v = u
   v = t
   while v != s:
    u, i = pv[v], pe[v]
    e = self.g[u][i]
    e[1] -= add
    self.g[v][e[3]][1] += add
    cost += add * e[2]
    v = u
   flow += add
  return flow, cost


def _add_cell_edges(net, ri, cj, value, fixed_value):
 """建单元格边，返回 (base边引用, base容量, up边引用或None)。"""
 fl, ce = _bounds(value)
 if fixed_value is not None:
  base = net.edge(ri, cj, int(fixed_value), 0)
  return base, int(fixed_value), None
 base = net.edge(ri, cj, fl, 0)  # 基量边：允许 0..floor
 if ce > fl:
  # 向上取整单位费用 = 1 - 小数部分；整数格无此边
  up = net.edge(ri, cj, 1, SCALE - frac_scaled(value))
  return base, fl, up
 return base, fl, None


def solve_rounding(matrix, fixed=None):
 """受控取整主求解。
 fixed: 可选 {(dept,act): int}，已被字典序贪心固定的格。
 返回 dict: feasible, conflicts, assignment, cells, objective_scaled 等。"""
 fixed = dict(fixed or {})
 depts = matrix['departments']
 acts = matrix['activities']
 grid = matrix['grid']
 m, n = len(depts), len(acts)
 # 规定总量：行/列原值合计后半进位取整
 row_original = [sum((grid[i][j]['original'] for j in range(n)), Decimal(0)) for i in range(m)]
 col_original = [sum((grid[i][j]['original'] for i in range(m)), Decimal(0)) for j in range(n)]
 row_target = [half_up_int(x) for x in row_original]
 col_target = [half_up_int(x) for x in col_original]
 row_sum, col_sum = sum(row_target), sum(col_target)
 head = {'feasible': False, 'row_target': row_target, 'col_target': col_target,
         'departments': depts, 'activities': acts,
         'row_original': row_original, 'col_original': col_original}
 conflicts = []
 if row_sum != col_sum:
  conflicts.append('部门规定总量合计 %d 与活动规定总量合计 %d 不一致，无法对平' % (row_sum, col_sum))
  return {**head, 'conflicts': conflicts}

 # 行/列可取整区间预检（固定格只计入固定值）
 for i, dept in enumerate(depts):
  lo = hi = 0
  for j in range(n):
   key = (dept, acts[j])
   if key in fixed:
    lo += fixed[key]; hi += fixed[key]
   else:
    a, b = _bounds(grid[i][j]['original'])
    lo += a; hi += b
  if not lo <= row_target[i] <= hi:
   conflicts.append('部门 %s 规定总量 %d 超出可取整区间 [%d, %d]' % (dept, row_target[i], lo, hi))
 for j, act in enumerate(acts):
  lo = hi = 0
  for i in range(m):
   key = (depts[i], act)
   if key in fixed:
    lo += fixed[key]; hi += fixed[key]
   else:
    a, b = _bounds(grid[i][j]['original'])
    lo += a; hi += b
  if not lo <= col_target[j] <= hi:
   conflicts.append('活动 %s 规定总量 %d 超出可取整区间 [%d, %d]' % (act, col_target[j], lo, hi))
 if conflicts:
  return {**head, 'conflicts': conflicts}

 # 节点：0 源；行 1..m；列 1+m..m+n；汇 sink
 S, T = 0, 1 + m + n
 net = _Net(T + 1)
 cell_edges = {}
 for i, dept in enumerate(depts):
  ri = 1 + i
  for j, act in enumerate(acts):
   cj = 1 + m + j
   key = (dept, act)
   base, base_cap, up = _add_cell_edges(net, ri, cj, grid[i][j]['original'], fixed.get(key))
   cell_edges[key] = (base, base_cap, up)
 for i in range(m):
  net.edge(S, 1 + i, row_target[i], 0)
 for j in range(n):
  net.edge(1 + m + j, T, col_target[j], 0)

 flow, cost = net.min_cost_flow(S, T, row_sum)
 if flow != row_sum:
  conflicts.append('行列总量虽各自满足单格区间，但联合约束无可行取整（流量仅 %d/%d）' % (flow, row_sum))
  return {**head, 'conflicts': conflicts}

 assignment = [[0] * n for _ in range(m)]
 cells = []
 total_abs = Decimal(0)
 for i, dept in enumerate(depts):
  for j, act in enumerate(acts):
   key = (dept, act)
   base, base_cap, up = cell_edges[key]
   z = (base_cap - base[1]) + ((1 - up[1]) if up is not None else 0)
   assignment[i][j] = z
   v = grid[i][j]['original']
   diff = Decimal(z) - v
   total_abs += diff.copy_abs()
   if frac_scaled(v) == 0:
    direction = '原值整数'
   elif key in fixed:
    direction = '草案固定值'
   elif diff > 0:
    direction = '向上取整'
   elif diff < 0:
    direction = '向下取整'
   else:
    direction = '恰好取整'
   cells.append({'department': dept, 'activity': act, 'original_kg': v,
                 'rounded_kg': z, 'difference_kg': diff, 'direction': direction})
 return {**head, 'feasible': True, 'conflicts': [],
         'assignment': assignment, 'cells': cells,
         'objective_scaled': cost, 'total_abs_deviation': total_abs,
         'grand_total': row_sum}


def round_declaration(matrix):
 """对外入口：最小偏差 + 同分字典序（部门、活动）最小。"""
 base = solve_rounding(matrix)
 if not base['feasible']:
  return base
 # 字典序贪心：按 (部门, 活动) 顺序逐格固定。每步先试 floor：
 #  - floor 在当前固定前缀下仍可达最优费用 → 取 floor（字典序更小）
 #  - 否则试 ceil；ceil 可行则取 ceil
 #  - 两者都不可行 → 当前前缀无解（理论上不应在基解可行时发生），返回冲突
 best = base['total_abs_deviation']
 fixed = {}
 for cell in base['cells']:
  key = (cell['department'], cell['activity'])
  fl = int(cell['original_kg'])
  if frac_scaled(cell['original_kg']) == 0:
   fixed[key] = fl  # 整数格无选择
   continue
  # 每步必须保证当前前缀仍包含一个全局最优解：
  # 优先试字典序更小的 floor，其总绝对偏差仍等于最优值则采用，否则试 ceil。
  floor_trial = solve_rounding(matrix, {**fixed, key: fl})
  if floor_trial['feasible'] and floor_trial['total_abs_deviation'] == best:
   fixed[key] = fl
   continue
  ceil_trial = solve_rounding(matrix, {**fixed, key: fl + 1})
  if ceil_trial['feasible'] and ceil_trial['total_abs_deviation'] == best:
   fixed[key] = fl + 1
   continue
  # 基解最优但前缀下两种取整均无法维持最优：明确报告冲突，不产出赋值
  return {'feasible': False,
          'row_target': base['row_target'], 'col_target': base['col_target'],
          'departments': base['departments'], 'activities': base['activities'],
          'row_original': base['row_original'], 'col_original': base['col_original'],
          'conflicts': ['字典序固定到 %s 时 floor/ceil 均无法维持最优解，取整冲突' % (key,)]}
 final = solve_rounding(matrix, fixed)
 if not final['feasible'] or final['total_abs_deviation'] != best:
  return base
 final['tie_break'] = '总绝对偏差最小方案中，按部门、活动排序取字典序最小值（同等偏差优先向下取整）'
 return final
