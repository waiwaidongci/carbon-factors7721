from sqlalchemy import Column, Integer, String, JSON, Text, Float, Boolean, UniqueConstraint
from src.config.database import Base


class DeclarationDraft(Base):
 """整数公斤申报表草案：一次制表对应一行，重试同一份草案不新增版本。"""
 __tablename__ = 'declaration_drafts'
 id = Column(Integer, primary_key=True)
 run_id = Column(Integer, nullable=False, unique=True)
 state = Column(String(20), nullable=False)  # computing/ready/conflict/effective/superseded
 result = Column(JSON)                       # 可行：完整取整结果；冲突：冲突说明与原矩阵
 attempt = Column(Integer, default=0)        # 制表/重试次数
 version = Column(Integer, default=1)        # 乐观锁，并发核算防旧草案覆盖现行表
 effective_id = Column(Integer)              # 核对通过后指向生效表
 error = Column(Text)
 created = Column(Float)
 updated = Column(Float)


class EffectiveDeclaration(Base):
 """核对通过后整表生效的申报表；同 run 仅一条 active 现行版本，历史版本保留留痕。"""
 __tablename__ = 'effective_declarations'
 id = Column(Integer, primary_key=True)
 run_id = Column(Integer, nullable=False, index=True)
 draft_id = Column(Integer, nullable=False)
 version = Column(Integer, nullable=False)   # 生效版本号，逐次核对递增
 result = Column(JSON, nullable=False)       # 完整生效表（原值/取整/行列总量/偏差）
 checksum = Column(String(64))               # 生效内容 SHA256，便于追溯
 active = Column(Boolean, default=True, index=True)
 created = Column(Float)
 updated = Column(Float)
 __table_args__ = (UniqueConstraint('run_id', 'version', name='uq_effective_run_version'),)
