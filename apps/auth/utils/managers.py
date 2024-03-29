from apps.user.models import User
from apps.user.utils.managers import UserCRUDManager
from architecture.manager.backend_manager import AuthManager
from architecture.manager.base_manager import FrontendManager
from core.token_generators import LoginTokenGenerator

import bcrypt

class LoginAuthManager(AuthManager):
    token_generator = LoginTokenGenerator


class AppAuthManager(FrontendManager):

    def login(self, email: str, passwd: str, hashing: bool = True) -> str:
        """
        아이디 패스워드 검증 및 로그인 토큰 발행
        """
        # 사용자 검색
        user: User = UserCRUDManager().read(user_email=email)
        if not user:
            # 사용자 없음
            raise ValueError('해당 사용자는 존재하지 않습니다.')
        user_passwd = user.passwd

        # 문자열이면 utf-8로 인코딩한다.
        if isinstance(passwd, str):
            passwd = passwd.encode('utf-8')
        if isinstance(user_passwd, str):
            user_passwd = user_passwd.encode('utf-8')
        
        # 패스워드 검토
        passwd_valid: bool = \
            bcrypt.checkpw(passwd, user_passwd) if hashing \
            else passwd == user_passwd
        if not passwd_valid:
            # 패스워드 틀림
            raise ValueError('패스워드가 정확하지 않습니다.')
        
        # 발급
        return LoginAuthManager().generate_token(req={'email': email})
