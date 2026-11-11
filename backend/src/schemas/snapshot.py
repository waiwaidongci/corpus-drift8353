import math
from pydantic import BaseModel,Field,model_validator
from typing import Literal
from src.constants.features import FEATURES,NUMERIC,CATEGORICAL,MISSING,NEW
class UtteranceInput(BaseModel):
 reference:str=Field(min_length=1,max_length=80)
 features:dict
 @model_validator(mode='after')
 def validate_features(self):
  if set(self.features)!=set(FEATURES):raise ValueError('片段必须包含且仅包含五个特征')
  for k,v in self.features.items():
   if v is None:continue
   if k in NUMERIC and (not isinstance(v,(int,float)) or not math.isfinite(v)):raise ValueError('数值特征必须为有限数字或null')
   if k in CATEGORICAL and (not isinstance(v,str) or not 1<=len(v)<=40 or v in (MISSING,NEW)):raise ValueError('类别须非空且不可使用保留桶名')
  return self
class SnapshotInput(BaseModel):
 name:str=Field(min_length=1,max_length=100)
 kind:Literal['reference','candidate']
 filename:str=Field(min_length=1,max_length=160)
 description:str=Field(default='',max_length=500)
 utterances:list[UtteranceInput]=Field(min_length=20,max_length=5000)
