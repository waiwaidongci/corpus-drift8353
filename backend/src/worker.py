import json
from pathlib import Path
from sqlalchemy import select
from celery import Celery
from src.config.database import SessionLocal
from src.config.settings import REDIS_URL,ARTIFACT_DIR
from src.models import ComparisonRun,DriftFinding
from src.services.snapshots import get_utterances
from src.services.comparison import compare_snapshots
from src.services.audit import record
app=Celery('corpus_drift',broker=REDIS_URL,backend=REDIS_URL)
app.conf.update(task_track_started=True,worker_prefetch_multiplier=1,task_acks_late=True)
@app.task(name='corpus.compare',soft_time_limit=120,time_limit=150)
def compare_run(id):
 with SessionLocal() as db:
  run=db.get(ComparisonRun,id)
  if not run or run.status=='succeeded':return
  run.status='running';db.commit()
  try:
   result=compare_snapshots(get_utterances(db,run.reference_id),get_utterances(db,run.candidate_id),run.config)
   for f in result['findings']:
    if not db.scalar(select(DriftFinding).where(DriftFinding.run_id==id,DriftFinding.feature==f['feature'])):db.add(DriftFinding(run_id=id,**f))
   db.flush();Path(ARTIFACT_DIR).mkdir(parents=True,exist_ok=True);Path(ARTIFACT_DIR,f'comparison-{id}.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False));run.result={k:v for k,v in result.items() if k!='findings'};run.status='succeeded';run.error=None;db.commit();record(db,'worker','comparison.succeeded',{'run_id':id,'findings':len(result['findings'])})
  except Exception as e:
   db.rollback();run=db.get(ComparisonRun,id);run.status='failed';run.error=str(e)[:1000];db.commit();record(db,'worker','comparison.failed',{'run_id':id,'error':run.error})
