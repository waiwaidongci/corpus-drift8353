from fastapi import APIRouter,Depends
from sqlalchemy.orm import Session
from src.config.database import get_db
from src.controllers.dependencies import current_user,writers,admins
from src.controllers.export import export_plan
from src.schemas.plan import PlanInput,ApprovalInput
from src.services import plans
router=APIRouter()
@router.get('/plans')
def index(db:Session=Depends(get_db),user=Depends(current_user)):return plans.list_plans(db)
@router.post('/plans',status_code=201)
def create(data:PlanInput,db:Session=Depends(get_db),user=Depends(writers)):return plans.create_plan(db,data,user)
@router.patch('/plans/{id}/approval')
def approve(id:int,data:ApprovalInput,db:Session=Depends(get_db),user=Depends(admins)):return plans.approve_plan(db,id,data,user)
@router.get('/plans/{id}/export')
def export(id:int,db:Session=Depends(get_db),user=Depends(current_user)):return export_plan(db,id)
