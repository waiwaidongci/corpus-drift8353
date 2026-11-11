import numpy as np
def divergence(reference_counts,candidate_counts,smoothing):
 a=np.asarray(reference_counts,dtype=float);b=np.asarray(candidate_counts,dtype=float)
 if len(a)!=len(b) or not len(a) or (a<0).any() or (b<0).any() or not np.isfinite(a).all() or not np.isfinite(b).all() or a.sum()<=0 or b.sum()<=0:raise ValueError('计数必须同长、非负且两边非空')
 if not np.isfinite(smoothing) or smoothing<=0:raise ValueError('平滑伪计数必须为有限正数')
 p=(a+smoothing)/(a.sum()+smoothing*len(a));q=(b+smoothing)/(b.sum()+smoothing*len(b));m=(p+q)/2
 psi=float(np.sum((q-p)*np.log(q/p)))
 js=float(.5*np.sum(p*np.log2(p/m))+.5*np.sum(q*np.log2(q/m)))
 return {'psi':psi,'js':max(0.,js),'reference_proportions':p.tolist(),'candidate_proportions':q.tolist(),'smoothing_pseudocount':float(smoothing),'psi_log_base':'e','js_log_base':2}
