from fastapi import APIRouter, HTTPException, Request, status

from apps.auth.utils.managers import AppAuthManager
from apps.user.utils.managers import UserCRUDManager

auth_router = APIRouter(
    prefix='/api/auth',
    tags=['auth'],
    responses={404: {'error': 'Not Found'}}
)

class TokenGenerateView:
    """
    (POST)  /api/auth/token     토큰 발행
    """
    @staticmethod
    @auth_router.post(
        path='/token',
        status_code=status.HTTP_201_CREATED)
    async def get_token(request: Request):
        try:
            req = await request.json()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="요청 데이터가 없습니다.")
        try:
            token_issue = req['issue']
            if token_issue == 'login':
                # 로그인 토큰 요청
                email = req['email']
                passwd = req['passwd']
                token = AppAuthManager().login(email, passwd)
                # 데이터 검색
                user = UserCRUDManager().read(user_email=email)
                return {
                    'token': token, 
                    'user_id': user.id,
                }
            else:
                # 알 수 없는 요청
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail='알 수 없는 요청입니다.')
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='요청 데이터가 부족합니다.')
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='입력한 정보가 맞지 않습니다.')
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="server errror")
