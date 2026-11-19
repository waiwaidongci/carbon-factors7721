# 初始结构

SQLAlchemy启动创建以下业务表：activity_periods, activities, emission_factors, carbon_runs, delivery_schedules, deliveries、users、audits。Source专属JSON字段由对应validation严格校验；Policy为不可覆盖的版本记录；Run保存source/policy冻结快照；Period仅用于已有期间选择器，不计入核心复杂度。已有数据库升级需先备份，后续字段演进应以独立迁移执行。

# 002 整数公斤申报表

新增两表，由 SQLAlchemy `create_all` 在启动时自动建立（仅对新库生效；已存在的旧库需手动执行下列 DDL，或在空库重建）：

- `declaration_drafts`：申报表草案，`run_id` 唯一（一份报告一份草案，重试复用同一行）。字段含 `state`（computing/ready/conflict/effective/superseded）、`result`(JSON)、`attempt`、`version`（乐观锁）、`effective_id`、`error`、时间戳。
- `effective_declarations`：核对通过的生效表。`(run_id, version)` 唯一，同 run 仅一条 `active=true` 现行版本，历史版本保留留痕。`result` 保存完整取整结果，`checksum` 为内容 SHA256。

PostgreSQL DDL 参考：

```sql
CREATE TABLE IF NOT EXISTS declaration_drafts (
 id SERIAL PRIMARY KEY, run_id INTEGER NOT NULL UNIQUE,
 state VARCHAR(20) NOT NULL, result JSON, attempt INTEGER DEFAULT 0,
 version INTEGER DEFAULT 1, effective_id INTEGER, error TEXT,
 created DOUBLE PRECISION, updated DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS effective_declarations (
 id SERIAL PRIMARY KEY, run_id INTEGER NOT NULL, draft_id INTEGER NOT NULL,
 version INTEGER NOT NULL, result JSON NOT NULL, checksum VARCHAR(64),
 active BOOLEAN DEFAULT TRUE, created DOUBLE PRECISION, updated DOUBLE PRECISION,
 CONSTRAINT uq_effective_run_version UNIQUE (run_id, version));
CREATE INDEX IF NOT EXISTS ix_effective_run_active ON effective_declarations(run_id, active);
```

语义：取整原值仅来自已复核报告 `carbon_runs.snapshot` 的冻结来源与口径，不回读可被修改的 activities 表；草案重试累加 `attempt` 不新增行；核对时乐观版本号拒绝旧草案覆盖现行表；无解（行列规定总量对不平或超出 floor/ceil 区间）时草案置 conflict 并保留上一版生效表。定时交付 `deliveries.payload` 新增 `declaration` 字段冻结当时完整生效表，旧交付行只增不改。
