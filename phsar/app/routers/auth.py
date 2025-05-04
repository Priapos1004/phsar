from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_roles
from app.core.security import create_access_token
from app.models.users import RoleType
from app.schemas import auth_schema
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=auth_schema.Token)
async def register(user: auth_schema.UserCreateWithToken, db: AsyncSession = Depends(get_db)):
    try:
        new_user = await AuthService.register(user, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    access_token = create_access_token(data={"sub": new_user.username, "role": new_user.role.value})
    return auth_schema.Token(access_token=access_token)

@router.post("/login", response_model=auth_schema.Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    user = await AuthService.authenticate(form_data.username, form_data.password, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    
    access_token = create_access_token(data={"sub": user.username, "role": user.role.value})
    return auth_schema.Token(access_token=access_token)

@router.post("/issue-token", response_model=auth_schema.RegistrationTokenResponse)
async def issue_registration_token(
    token_data: auth_schema.RegistrationTokenCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_roles(RoleType.Admin.value))
):
    try:
        new_token = await AuthService.create_registration_token(token_data.role, current_user, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return auth_schema.RegistrationTokenResponse(
        token=new_token.token,
        role=new_token.role,
        created_by=current_user.username,
        expires_on=new_token.expires_on,
    )
