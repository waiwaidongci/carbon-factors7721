from fastapi import APIRouter, Depends
from fastapi.responses import Response
from src.config.database import database
from src.controllers.auth import current, editor, admin
from src.schemas.requests import DeclarationInput, DeclarationConfirm
from src.services.declaration_workflow import (
 create_or_retry_draft, confirm_draft, list_state, get_draft, get_effective)
from src.services.export import declaration_csv
router = APIRouter()


@router.get('/declarations')
def state(db=Depends(database), u=Depends(current)):
 return list_state(db)


@router.post('/declarations/tabulate')
def tabulate(b: DeclarationInput, db=Depends(database), u=Depends(editor)):
 draft = create_or_retry_draft(db, u, b.run_id)
 from src.services.declaration_workflow import _draft_row
 return _draft_row(draft)


@router.post('/declarations/{draft_id}/confirm')
def confirm(draft_id: int, b: DeclarationConfirm, db=Depends(database), u=Depends(admin)):
 obj = confirm_draft(db, u, draft_id)
 from src.services.declaration_workflow import _effective_row
 return _effective_row(obj)


@router.get('/runs/{run_id}/declaration')
def run_declaration(run_id: int, db=Depends(database), u=Depends(current)):
 draft = get_draft(db, run_id)
 effective = get_effective(db, run_id)
 from src.services.declaration_workflow import _draft_row, _effective_row
 return {'draft': _draft_row(draft) if draft else None,
         'effective': _effective_row(effective) if effective else None}


@router.get('/effective-declarations/{effective_id}/csv')
def effective_csv(effective_id: int, db=Depends(database), u=Depends(current)):
 from src.models.declaration import EffectiveDeclaration
 obj = db.get(EffectiveDeclaration, effective_id)
 if not obj or not obj.active:
  from fastapi import HTTPException
  raise HTTPException(404, '生效申报表不存在或已失效')
 return Response(declaration_csv(obj.result), media_type='text/csv',
                 headers={'Content-Disposition': f'attachment; filename="declaration-{effective_id}.csv"'})
