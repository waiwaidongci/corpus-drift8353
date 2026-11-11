from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy import String,JSON,ForeignKey,DateTime
from datetime import datetime,timezone
from src.config.database import Base
class ComparisonRun(Base):
 __tablename__='comparison_runs'
 id:Mapped[int]=mapped_column(primary_key=True)
 reference_id:Mapped[int]=mapped_column(ForeignKey('corpus_snapshots.id'))
 candidate_id:Mapped[int]=mapped_column(ForeignKey('corpus_snapshots.id'))
 name:Mapped[str]=mapped_column(String(100))
 config:Mapped[dict]=mapped_column(JSON)
 status:Mapped[str]=mapped_column(String(20),default='queued')
 result:Mapped[dict]=mapped_column(JSON,default=dict)
 error:Mapped[str|None]=mapped_column(String(1000),nullable=True)
 creator_id:Mapped[int]=mapped_column(ForeignKey('users.id'))
 created_at:Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))
