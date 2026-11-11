import hashlib,json
from src.constants.features import FEATURES
def fingerprint(reference,candidate,config):
 def rows(items):return [{'id':r['id'],'reference':r['reference'],'features':{k:r['features'][k] for k in sorted(FEATURES)}} for r in sorted(items,key=lambda r:r['reference'])]
 data={'reference':rows(reference),'candidate':rows(candidate),'config':config,'algorithm':'frozen-quantile-psi-js-ks-bh-v1'}
 return hashlib.sha256(json.dumps(data,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()
