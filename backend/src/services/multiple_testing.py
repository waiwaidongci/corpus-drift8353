import numpy as np
def benjamini_hochberg(pvalues):
 p=np.asarray(pvalues,dtype=float)
 if not np.isfinite(p).all() or (p<0).any() or (p>1).any():raise ValueError('p值必须在[0,1]')
 if not len(p):return []
 order=np.argsort(p,kind='stable');ordered=p[order];m=len(p)
 adjusted=np.minimum.accumulate((ordered*m/np.arange(1,m+1))[::-1])[::-1]
 out=np.empty(m);out[order]=np.minimum(adjusted,1.);return out.tolist()
