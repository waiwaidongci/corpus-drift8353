from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy import String,JSON,ForeignKey,UniqueConstraint
from src.config.database import Base
class DriftFinding(Base):
 __tablename__='drift_findings'
 __table_args__=(UniqueConstraint('run_id','feature'),)
 id:Mapped[int]=mapped_column(primary_key=True)
 run_id:Mapped[int]=mapped_column(ForeignKey('comparison_runs.id'))
 feature:Mapped[str]=mapped_column(String(50))
 status:Mapped[str]=mapped_column(String(20))
 metrics:Mapped[dict]=mapped_column(JSON)
