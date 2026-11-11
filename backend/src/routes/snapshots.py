from fastapi import APIRouter,Depends
from sqlalchemy.orm import Session
from src.config.database import get_db
from src.controllers.dependencies import current_user,writers
from src.schemas.snapshot import SnapshotInput
from src.services import snapshots
from src.constants.features import NUMERIC,CATEGORICAL
router=APIRouter()
@router.get('/features')
def features(user=Depends(current_user)):return {'numeric':NUMERIC,'categorical':CATEGORICAL}
@router.get('/snapshots')
def index(db:Session=Depends(get_db),user=Depends(current_user)):return snapshots.list_snapshots(db)
@router.post('/snapshots',status_code=201)
def create(data:SnapshotInput,db:Session=Depends(get_db),user=Depends(writers)):return snapshots.create_snapshot(db,data,user)
@router.get('/snapshots/{id}/utterances')
def utterances(id:int,db:Session=Depends(get_db),user=Depends(current_user)):return snapshots.get_utterances(db,id,100)
