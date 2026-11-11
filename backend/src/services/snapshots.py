from sqlalchemy import select,func
from fastapi import HTTPException
from src.models import CorpusSnapshot,Utterance
from src.utils.serialize import row
from .audit import record
def list_snapshots(db):return [dict(row(s),count=db.scalar(select(func.count()).select_from(Utterance).where(Utterance.snapshot_id==s.id))) for s in db.scalars(select(CorpusSnapshot).order_by(CorpusSnapshot.id))]
def get_utterances(db,id,limit=None):
 if not db.get(CorpusSnapshot,id):raise HTTPException(404,'快照不存在')
 q=select(Utterance).where(Utterance.snapshot_id==id).order_by(Utterance.reference)
 if limit:q=q.limit(limit)
 return [row(x) for x in db.scalars(q)]
def create_snapshot(db,data,user):
 if db.scalar(select(CorpusSnapshot).where(CorpusSnapshot.name==data.name)):raise HTTPException(409,'快照名称已存在')
 refs=[x.reference for x in data.utterances]
 if len(refs)!=len(set(refs)):raise HTTPException(422,'reference重复')
 obj=CorpusSnapshot(**data.model_dump(exclude={'utterances'}));db.add(obj);db.flush();db.add_all([Utterance(snapshot_id=obj.id,**x.model_dump()) for x in data.utterances]);db.commit();record(db,user.email,'snapshot.import',{'snapshot_id':obj.id,'rows':len(refs)});return row(obj)
