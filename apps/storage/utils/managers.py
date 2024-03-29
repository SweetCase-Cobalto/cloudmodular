import shutil
from typing import Any, Dict, List, Optional
from fastapi import UploadFile
import os
import datetime

from apps.storage.models import DataInfo
from apps.storage.schemas import DataInfoCreate, DataInfoUpdate
from apps.storage.utils.queries.data_db_query import DataDBQuery
from apps.storage.utils.queries.data_storage_query import DataStorageQuery
from apps.user.models import User
from apps.user.utils.queries.user_db_query import UserDBQuery
from architecture.manager.backend_manager import CRUDManager
from core.exc import (
    DataAlreadyExists,
    DataNotFound,
    UsageLimited,
    UserNotFound
)
from core.token_generators import (
    LoginTokenGenerator,
    decode_token,
)
from core.permissions import (
    PermissionAdminChecker as AdminOnly,
    PermissionIssueLoginChecker as LoginedOnly,
)
from architecture.query.permission import (
    PermissionSameUserChecker as OnlyMine,
)
from architecture.manager.base_manager import FrontendManager
from settings.base import SERVER

class DataFileCRUDManager(CRUDManager):

    def create(
        self, root_id: int, user_id: int, file: UploadFile
    ) -> List[DataInfo]:
        """
        파일 생성
        동일한 이름의 파일이 존재하는 경우, 덮어쓴다.

        :param root_id: 파일이 올라갈 디렉토리 아이디
        :param user_id: 사용자 아이디
        :param files: 올라갈 파일 데이터들

        :return: 생성된 데이터 리스트
        """
        # user 존재 여부 확인
        user: User = UserDBQuery().read(user_id=user_id)
        if not user:
            raise UserNotFound()
        
        dir_root = '/'  # 최상위 루트
        if root_id != 0:
            # id가 0인 경우는 최상위 루트이다.
            # 0이상인 경우만 DB에서 검색한다.
            directory_info: DataInfo =  DataDBQuery().read(
                user_id=user_id, data_id=root_id, 
                is_dir=True)
            if not directory_info:
                raise DataNotFound()
            # 상위 디렉토리 절대경로 생성
            dir_root = f'{directory_info.root}{directory_info.name}/'
        
        # 파일 이름 및 절대경로 생성
        filename = file.filename.split('/')[-1]
        file_root = \
            f'{SERVER["storage"]}/storage/{user_id}/root{dir_root}{filename}'
        # 같은 이름의 데이터가 DB에 남아있는지 조사
        db_already_info: DataInfo = DataDBQuery().read(
            user_id=user_id, full_root=(dir_root, filename))
        db_already_id = db_already_info.id if db_already_info else 0
        if db_already_id and db_already_info.is_dir:
            # 데이터가 존재하는데 디렉토리면 업로드 불가능
            raise DataAlreadyExists()
        else:
            # 나머지는 업데이트 혹은 생성 가능
            if DataStorageQuery().read(root=file_root, is_dir=True) or \
                DataStorageQuery().read(root=file_root, is_dir=False):
                # 같은 이름의 데이터가 스토리지에 존재하면 삭제
                DataStorageQuery().destroy(root=file_root)
        # Validation 측정 틀리면 ValidationError 발생
        input_format: DataInfoCreate = DataInfoCreate(
            name=filename,
            user_id=user_id,
            root=dir_root,
            is_dir=False,
            size=0)
        # 데이터 생성
        data_size = \
            DataStorageQuery() \
                .create(
                    root=file_root,
                    is_dir=False, file=file,
                    user_id=user_id)
        # 파일 크기 추가
        input_format.size = data_size
        try:
            if db_already_id:
                data_info = \
                    DataDBQuery().update_file_automatic(
                        data_id=db_already_id,
                        data_format=input_format)
            else:
                data_info = \
                    DataDBQuery().create(
                        data_format=input_format)
        except Exception as e:
            # 실패시 스토리지 루트 삭제
            DataStorageQuery().destroy(root=file_root)
            raise e
        else:
            return data_info

    def read(self, raw_root: str) -> str:
        # 다운로드 할 때만 사용
        return raw_root

    def update(self, user_id: int, data_id: int, new_name: str):
        # User 확인
        user: User = UserDBQuery().read(user_id=user_id)
        if not user:
            raise UserNotFound()
        # 수정 대상 DataInfo 확인
        data: DataInfo = \
            DataDBQuery().read(user_id=user_id, data_id=data_id, is_dir=False)
        if not data:
            raise DataNotFound()
        # Validate 측정
        DataInfoUpdate(name=new_name, root=data.root, user_id=user_id)

        prev_name = data.name
        directory_root = f'{SERVER["storage"]}/storage/{user_id}/root{data.root}'
        raw_root = f'{directory_root}{prev_name}'
        try:
            # 파일 수정
            new_root = DataStorageQuery().update(raw_root, new_name)
        except Exception:
            """
            같은 이름의 파일 및 디렉토리가 있는 경우 발생
            업데이트 불가능
            """
            raise DataAlreadyExists()
        
        if not new_root:
            # 생성 실패: 타겟 데이터가 스토리지에 존재하지 않음
            DataDBQuery().destroy(data_id)
            raise DataNotFound()
        
        try:
            # DB 데이터 수정
            res = DataDBQuery().update(
                data_id=data.id, 
                new_name=new_name, user_id=user_id
            )
        except Exception as e:
            # DB 데이터 수정에 에러 발생
            # Storage rollback
            DataStorageQuery().update(f'{directory_root}{new_name}', data.name)
            raise e
        return res

    def destroy(self, user_id: int, data_id: int):
        root, name = DataDBQuery().destroy(data_id)
        raw_root = \
            f'{SERVER["storage"]}/storage/{user_id}/root{root}{name}'
        DataStorageQuery().destroy(root=raw_root)
        

    def search(self, *args, **kwargs):
        raise NotImplementedError()

class DataDirectoryCRUDManager(CRUDManager):

    def create(self, root_id: int, user_id: int, dirname: str) -> DataInfo:
        # User 존재 여부 확인
        user: User = UserDBQuery().read(user_id=user_id)
        if not user:
            raise UserNotFound()

        # 루트 디렉토리 확인
        dir_root = '/'  # 최상위 루트
        if root_id != 0:
            # 최상위 루트가 아닌 경우
            # 직접 검색
            directory_info: DataInfo =  DataDBQuery().read(
                user_id=user_id, data_id=root_id, 
                is_dir=True
            )
            if not directory_info:
                raise DataNotFound()
            dir_root = f'{directory_info.root}{directory_info.name}/'
        
        # 새로 생성될 디렉토리 루트 생성
        root = f'{SERVER["storage"]}/storage/{user_id}/root{dir_root}{dirname}'
        # DB에 같은 데이터가 들어있는 지 확인
        db_already_info: DataInfo = DataDBQuery().read(
            user_id=user_id, full_root=(dir_root, dirname))
        db_already_id = db_already_info.id if db_already_info else 0

        if db_already_id:
            # 있는것 자체만으로도 생성 불가능
            raise DataAlreadyExists()
        # DB에 없고 스토리지에 같은 이름의 데이터가 존재하는 경우 강제삭제
        if DataStorageQuery().read(root=root, is_dir=True) or \
            DataStorageQuery().read(root=root, is_dir=False):
            DataStorageQuery().destroy(root=root)
        # Validation Check 실패 시 ValidationError
        input_format: DataInfoCreate = DataInfoCreate(
            name=dirname,
            root=dir_root,
            user_id=user_id,
            is_dir=True,
            size=0)
        # 스토리지에 디렉토리 생성
        DataStorageQuery().create(root=root, is_dir=True)
        # DB 추가
        try:
            info: DataInfo = DataDBQuery().create(input_format)
        except Exception as e:
            # 실패 시 스토리지에 있는 디렉토리 삭제
            DataStorageQuery().destroy(root=root)
            raise e
        return info

    def update(self, user_id: int, data_id: int, new_name: str):
        # User 확인
        user: User = UserDBQuery().read(user_id=user_id)
        if not user:
            raise UserNotFound()
        # DataInfo 확인
        data: DataInfo = \
            DataDBQuery().read(user_id=user_id, data_id=data_id)
        if not data:
            raise DataNotFound()
        # Validate 측정
        DataInfoUpdate(name=new_name, root=data.root, user_id=user_id)

        prev_name = data.name
        directory_root = f'{SERVER["storage"]}/storage/{user_id}/root{data.root}'
        raw_root = f'{directory_root}{prev_name}'
        try:
            # 디렉토리 수정
            new_root = DataStorageQuery().update(raw_root, new_name)
        except Exception:
            """
            같은 이름의 파일 및 디렉토리가 있는 경우 발생
            업데이트 불가능
            """
            raise DataAlreadyExists()
        
        if not new_root:
            # 생성 실패: 타겟 데이터가 스토리지에 존재하지 않음
            DataDBQuery().destroy(data_id)
            raise DataNotFound()
        
        try:
            # DB 데이터 수정
            res = DataDBQuery().update(
                data_id=data.id, new_name=new_name, user_id=user_id
            )
        except Exception as e:
            # DB 데이터 수정에 에러 발생
            # Storage 원상태 복구
            DataStorageQuery().update(f'{directory_root}{new_name}', prev_name)
            raise e
        return res

    def read(self, raw_root: str) -> str:
        # 다운로드 할 때만 사용

        # Zip File 생성
        tmp_name = f'download-{datetime.datetime.now().strftime("%Y%m%d-%H%M%S%f")}'
        tmp_zip = shutil.make_archive(tmp_name, 'zip', raw_root)
        return tmp_zip
    
    def destroy(self, user_id: int, data_id: int):
        root, name = DataDBQuery().destroy(data_id)
        raw_root = \
            f'{SERVER["storage"]}/storage/{user_id}/root{root}{name}'
        DataStorageQuery().destroy(root=raw_root)

    def search(self, *args, **kwargs):

        raise NotImplementedError()


class DataManager(FrontendManager):

    def create(
        self,
        token: str,
        user_id: int,
        data_id: int,
        req_file: Optional[UploadFile] = None,
        req_dirname: Optional[str] = None
    ) -> DataInfo:
        """
        파일/디렉토리 생성

        :param token: 인증용 토큰
        :param user_id: 사용자 아이디
        :param data_id: 데이터가 올라갈 상위 디렉토리 아이디
        :param request_files: 요청된 파일들
        :param req_dirname: 새로 생성할 디렉토리 이름

        :return: 새로 생성된 데이터의 리스트를 반환
        """
        op_email, issue = decode_token(token, LoginTokenGenerator)
        operator: User = UserDBQuery().read(user_email=op_email)
        # 해덩 User가 없으면 Permission Failed
        if not operator:
            raise PermissionError()
        # Admin이거나, client and 자기 자신이어야 한다.
        if not bool(
            LoginedOnly(issue) & (
                AdminOnly(operator.is_admin) | 
                ((~AdminOnly(operator.is_admin)) & OnlyMine(operator.id, user_id))
            )
        ):
            raise PermissionError()

        if req_file:
            # 파일 업로드
            return DataFileCRUDManager().create(
                root_id=data_id,
                user_id=user_id,
                file=req_file,
            )
        elif req_dirname:
            # 디렉토리 생성
            return DataDirectoryCRUDManager().create(
                root_id=data_id,
                user_id=user_id,
                dirname=req_dirname
            )

    def read(
        self, token: str, 
        user_id: int, 
        data_id: int, 
        mode: str = 'info'
    ) -> Dict[str, Any]:
        
        op_email, issue = decode_token(token, LoginTokenGenerator)
        operator: User = UserDBQuery().read(user_email=op_email)
        # 해당 User 없으면 PermissionError
        if not operator:
            raise PermissionError()
        # Admin이거나, client and 자기 자신이어야 한다
        if not bool(
            LoginedOnly(issue) & (
                AdminOnly(operator.is_admin) | 
                ((~AdminOnly(operator.is_admin)) & OnlyMine(operator.id, user_id)))):
            raise PermissionError()

        if not UserDBQuery().read(user_id=user_id):
            # user_id에 대한 정보가 존재하는 지 확인
            raise UserNotFound()
        try:
            # DB에 데이터 검색
            data_info: DataInfo = \
                DataDBQuery().read(user_id=user_id, data_id=data_id)
        except Exception as e:
            raise e
        if not data_info:
            # 데이터 없음
            raise DataNotFound()
        # 실제 루트
        raw_root = \
            f'{SERVER["storage"]}/storage/{user_id}/root{data_info.root}{data_info.name}'
        # 스토리지 데이터 확인
        storage_info = \
            DataStorageQuery().read(
                root=raw_root, is_dir=data_info.is_dir)
        if not storage_info:
            # 실제 스토리지에 존재하지 않음
            DataDBQuery().destroy(data_info.id)
            raise DataNotFound()
        
        if not data_info.is_dir:
            # 읽기 대상 데이터가 파일인 경우
            # 파일 크기에 대한 동기화를 진행한다.
            data_info = DataDBQuery().sync_file_size(
                data_id=data_id, full_root=raw_root)

        # 리턴 데이터
        res = {
            'info': {
                'created': data_info.created,
                'root': data_info.root,
                'is_dir': data_info.is_dir,
                'name': data_info.name,
                'size': len(os.listdir(raw_root)) if data_info.is_dir \
                    else data_info.size
            }
        }

        if mode == 'download':
            # 다운로드 모드
            # 다운로드 대상의 파일 주소만 리턴
            if not data_info.is_dir:
                res['file'] = DataFileCRUDManager().read(raw_root)
            else:
                res['file'] = DataDirectoryCRUDManager().read(raw_root)
        return res
    
    def update(
        self, token: str, user_id: int, data_id: int, new_name: str
    ) -> Dict[str, Any]:
        
        # email에 대한 요청 사용자 구하기
        op_email, issue = decode_token(token, LoginTokenGenerator)
        operator: Optional[User] = UserDBQuery().read(user_email=op_email)
        if not operator:
            raise PermissionError()

        # Admin이거나 client and 자기 자신이어야 한다
        if not bool(
            LoginedOnly(issue) & (
                AdminOnly(operator.is_admin) | 
                ((~AdminOnly(operator.is_admin)) & OnlyMine(operator.id, user_id))
            )
        ):
            raise PermissionError()
        
        try:
            # 데이터 검색
            target: Optional[DataInfo] = \
                DataDBQuery().read(user_id=user_id, data_id=data_id)
            if not target:
                # 데이터 없음
                raise DataNotFound()
            if target.is_dir:
                # 디렉토리
                res = DataDirectoryCRUDManager() \
                    .update(user_id, data_id, new_name)
            else:
                # 파일
                res = DataFileCRUDManager() \
                    .update(user_id, data_id, new_name)
        except Exception as e:
            raise e
        else:
            return {
                'created': res.created,
                'data_id': res.id,
                'root': res.root,
                'name': res.name,
                'is_dir': res.is_dir,
            }

    def destroy(self, token: str, user_id: int, data_id: int):
        # email에 대한 요청 사용자 구하기
        op_email, issue = decode_token(token, LoginTokenGenerator)
        operator: Optional[User] = \
            UserDBQuery().read(user_email=op_email)
        if not operator:
            raise PermissionError()

        # Admin이거나 client and 자기 자신이어야 한다
        if not bool(
            LoginedOnly(issue) & (
                AdminOnly(operator.is_admin) | 
                ((~AdminOnly(operator.is_admin)) & OnlyMine(operator.id, user_id))
            )
        ):
            raise PermissionError()

        try:
            # 검색
            target: Optional[DataInfo] = \
                DataDBQuery().read(user_id=user_id, data_id=data_id)
            if not target:
                raise DataNotFound()
            elif target.is_dir:
                DataDirectoryCRUDManager().destroy(user_id, data_id)
            else:
                DataFileCRUDManager().destroy(user_id, data_id)
        except Exception as e:
            raise e
