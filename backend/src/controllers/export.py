from fastapi import HTTPException
from src.models import ResamplingPlan,DriftFinding
from src.constants.enums import PlanStatus
from src.utils.csv_export import csv_response
def export_plan(db,id):
 obj=db.get(ResamplingPlan,id)
 if not obj:raise HTTPException(404,'计划不存在')
 if obj.status!=PlanStatus.APPROVED:raise HTTPException(403,'仅获批计划可导出')
 rows=[]
 for fid in obj.finding_ids:
  f=db.get(DriftFinding,fid);m=f.metrics
  rows.append([obj.name,obj.target_slice,obj.sample_target,obj.rationale,obj.review_note,f.feature,m['psi'],m['js'],m['p_value'],m['q_value'],m['fdr_reject']])
 return csv_response(f'resampling-{id}.csv',rows,['计划','补采切片','目标片段数','依据','审核说明','特征','PSI自然log','JS log2','原p','BH q','FDR拒绝'])
