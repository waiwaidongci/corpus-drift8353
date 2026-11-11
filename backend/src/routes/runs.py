from fastapi import APIRouter,Depends
from sqlalchemy.orm import Session
from src.config.database import get_db
from src.controllers.dependencies import current_user,writers
from src.schemas.run import ComparisonInput
from src.services import runs,findings
from src.utils.serialize import row
router=APIRouter()
@router.get('/runs')
def index(db:Session=Depends(get_db),user=Depends(current_user)):return runs.list_runs(db)
@router.get('/runs/{id}')
def detail(id:int,db:Session=Depends(get_db),user=Depends(current_user)):return row(runs.get_run(db,id))
@router.post('/runs',status_code=201)
def create(data:ComparisonInput,db:Session=Depends(get_db),user=Depends(writers)):return runs.create_run(db,data,user)
@router.get('/findings')
def all_findings(db:Session=Depends(get_db),user=Depends(current_user)):return findings.list_findings(db)
@router.get('/runs/{id}/findings')
def run_findings(id:int,db:Session=Depends(get_db),user=Depends(current_user)):
 runs.get_run(db,id);return findings.list_findings(db,id)
