from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy import String,JSON,ForeignKey,UniqueConstraint
from src.config.database import Base
class Utterance(Base):
 __tablename__='utterances'
 __table_args__=(UniqueConstraint('snapshot_id','reference'),)
 id:Mapped[int]=mapped_column(primary_key=True)
 snapshot_id:Mapped[int]=mapped_column(ForeignKey('corpus_snapshots.id'))
 reference:Mapped[str]=mapped_column(String(80))
 features:Mapped[dict]=mapped_column(JSON)
