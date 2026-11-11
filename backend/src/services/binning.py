import numpy as np
from src.constants.features import MISSING,NEW

def freeze_numeric(values,bins):
 valid=np.asarray([float(v) for v in values if v is not None])
 if len(valid)<2 or not np.isfinite(valid).all() or len(np.unique(valid))<2:raise ValueError('参考数值特征缺失过多或为常量，无法冻结分位箱')
 edges=np.unique(np.quantile(valid,np.linspace(0,1,bins+1)[1:-1])).tolist()
 bounds=[None]+edges+[None];labels=[]
 for i in range(len(bounds)-1):labels.append(f"[{bounds[i] if bounds[i] is not None else '-inf'}, {bounds[i+1] if bounds[i+1] is not None else '+inf'})")
 return {'kind':'numeric','internal_edges':edges,'labels':labels+[MISSING],'fitted_from':'reference_only','interval':'left_closed_right_open; last includes +inf'}
def freeze_categorical(values):
 categories=sorted(set(v for v in values if v is not None))
 if not categories:raise ValueError('参考类别没有有效值')
 return {'kind':'categorical','categories':categories,'labels':categories+[NEW,MISSING],'fitted_from':'reference_only'}
def count_bins(values,spec):
 counts=[0]*len(spec['labels'])
 for v in values:
  if v is None:index=len(counts)-1
  elif spec['kind']=='numeric':
   if not np.isfinite(float(v)):raise ValueError('数值含非有限值')
   index=int(np.searchsorted(spec['internal_edges'],float(v),side='right'))
  else:index=spec['categories'].index(v) if v in spec['categories'] else len(counts)-2
  counts[index]+=1
 return counts
