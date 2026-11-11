from sqlalchemy import select
from fastapi import HTTPException
from src.models import ResamplingPlan,ComparisonRun,DriftFinding
from src.utils.serialize import row
from src.constants.enums import PlanStatus,RunStatus
from .audit import record
def list_plans(db):return [row(x) for x in db.scalars(select(ResamplingPlan).order_by(ResamplingPlan.id.desc()))]
def create_plan(db,data,user):
 run=db.get(ComparisonRun,data.run_id)
 if not run or run.status!=RunStatus.SUCCEEDED:raise HTTPException(422,'请选择成功运行')
 if len(set(data.finding_ids))!=len(data.finding_ids):raise HTTPException(422,'发现不得重复')
 valid=set(db.scalars(select(DriftFinding.id).where(DriftFinding.run_id==run.id)))
 if not set(data.finding_ids)<=valid:raise HTTPException(422,'发现必须属于本运行')
 obj=ResamplingPlan(**data.model_dump(),creator_id=user.id);db.add(obj);db.commit();record(db,user.email,'resampling.created',{'plan_id':obj.id,'finding_ids':data.finding_ids});return row(obj)
def approve_plan(db,id,data,user):
 obj=db.get(ResamplingPlan,id)
 if not obj:raise HTTPException(404,'补采计划不存在')
 if obj.status!=PlanStatus.DRAFT:raise HTTPException(409,'仅草案可审核')
 obj.status=data.status;obj.review_note=data.review_note;db.commit();record(db,user.email,'resampling.reviewed',{'plan_id':id,'status':obj.status});return row(obj)
