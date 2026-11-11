from sqlalchemy import select
from src.models import DriftFinding
from src.utils.serialize import row
def list_findings(db,run_id=None):
 q=select(DriftFinding).order_by(DriftFinding.id)
 if run_id is not None:q=q.where(DriftFinding.run_id==run_id)
 return [row(x) for x in db.scalars(q)]
