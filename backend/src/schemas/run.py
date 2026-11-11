from pydantic import BaseModel,Field,model_validator
from src.constants.features import FEATURES
class ComparisonInput(BaseModel):
 name:str=Field(min_length=1,max_length=100)
 reference_id:int=Field(gt=0)
 candidate_id:int=Field(gt=0)
 features:list[str]=Field(min_length=1,max_length=5)
 bins:int=Field(ge=2,le=10)
 smoothing:float=Field(gt=0,le=10,allow_inf_nan=False)
 fdr_alpha:float=Field(gt=0,le=.2,allow_inf_nan=False)
 slice_language:str|None=Field(default=None,max_length=40)
 slice_device:str|None=Field(default=None,max_length=40)
 @model_validator(mode='after')
 def validate_config(self):
  if self.reference_id==self.candidate_id:raise ValueError('参考/候选不能是同一快照')
  if len(set(self.features))!=len(self.features) or not set(self.features)<=set(FEATURES):raise ValueError('特征不得重复或未知')
  return self
