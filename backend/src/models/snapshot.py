from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy import String,DateTime
from datetime import datetime,timezone
from src.config.database import Base
class CorpusSnapshot(Base):
 __tablename__='corpus_snapshots'
 id:Mapped[int]=mapped_column(primary_key=True)
 name:Mapped[str]=mapped_column(String(100),unique=True)
 kind:Mapped[str]=mapped_column(String(20))
 filename:Mapped[str]=mapped_column(String(160))
 description:Mapped[str]=mapped_column(String(500),default='')
 created_at:Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))
