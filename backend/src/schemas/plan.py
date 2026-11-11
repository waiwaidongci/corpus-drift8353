from pydantic import BaseModel,Field
from typing import Literal
class PlanInput(BaseModel):
 run_id:int=Field(gt=0)
 name:str=Field(min_length=1,max_length=100)
 finding_ids:list[int]=Field(min_length=1,max_length=5)
 target_slice:str=Field(min_length=1,max_length=160)
 sample_target:int=Field(ge=20,le=10000)
 rationale:str=Field(min_length=1,max_length=500)
class ApprovalInput(BaseModel):
 status:Literal['approved','rejected']
 review_note:str=Field(min_length=1,max_length=500)
