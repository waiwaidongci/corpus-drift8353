from sqlalchemy import select
from fastapi import HTTPException
from src.models import ComparisonRun,CorpusSnapshot
from src.utils.serialize import row
from src.constants.enums import RunStatus
from .audit import record
def list_runs(db):return [row(x) for x in db.scalars(select(ComparisonRun).order_by(ComparisonRun.id.desc()))]
def get_run(db,id):
 obj=db.get(ComparisonRun,id)
 if not obj:raise HTTPException(404,'比较运行不存在')
 return obj
def create_run(db,data,user):
 ref=db.get(CorpusSnapshot,data.reference_id);cand=db.get(CorpusSnapshot,data.candidate_id)
 if not ref or not cand:raise HTTPException(404,'快照不存在')
 if ref.kind!='reference' or cand.kind!='candidate':raise HTTPException(422,'请按参考/候选快照类型选择')
 obj=ComparisonRun(name=data.name,reference_id=ref.id,candidate_id=cand.id,config=data.model_dump(exclude={'name','reference_id','candidate_id'}),creator_id=user.id);db.add(obj);db.commit()
 from src.worker import compare_run
 try:compare_run.delay(obj.id)
 except Exception:obj.status=RunStatus.FAILED;obj.error='队列不可用';db.commit();raise HTTPException(503,obj.error)
 record(db,user.email,'comparison.queued',{'run_id':obj.id});return row(obj)
