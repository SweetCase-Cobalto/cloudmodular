from sqlalchemy import and_, Sequence, func
from typing import Optional
import os

from apps.storage.models import DataInfo
from apps.data_tag.models import DataTag
from apps.tag.models import Tag
from apps.storage.schemas import DataInfoCreate
from architecture.query.crud import (
    QueryCRUD,
    QueryCreator,
    QueryDestroyer,
    QueryReader,
    QueryUpdator,
)
from core.exc import DataAlreadyExists, DataNotFound
from system.connection.generators import DatabaseGenerator

class DataDBQueryCreator(QueryCreator):
    def __call__(self, data_format: DataInfoCreate) -> DataInfo:

        session = DatabaseGenerator.get_session()
        q = session.query(DataInfo)

        data: DataInfo = DataInfo(
            name=data_format.name,
            root=data_format.root,
            user_id=data_format.user_id,
            is_dir=data_format.is_dir,
            size=data_format.size,
        )
        # user_id & name & root & is_dir일 경우 생성 불가능
        if q.filter(and_(
            DataInfo.name == data.name,
            DataInfo.root == data.root,
            DataInfo.user_id == data.user_id,
            DataInfo.is_dir == data.is_dir
        )).scalar():
            raise DataAlreadyExists()
        
        try:
            # DB 업로드
            session.add(data)
            session.commit()
            session.refresh(data)
        except Exception as e:
            session.rollback()
            raise e
        else:
            return data
        finally:
            session.close()

class DataDBQueryDestroyer(QueryDestroyer):
    def __call__(self, data_id: int) -> Optional[DataInfo]:
        session = DatabaseGenerator.get_session()
        q = session.query(DataInfo)
        
        data: DataInfo = q.filter(DataInfo.id == data_id).scalar()
        root, name = data.root, data.name
        try:
            if data.is_dir:
                # 디렉토리
                # 하위 디렉토리 태그 전부 삭제
                infos = session.query(DataInfo, DataTag, Tag) \
                    .filter(and_(
                        DataInfo.user_id == data.user_id,
                        DataInfo.root.startswith(f'{data.root}{data.name}/')
                    )) \
                    .filter(and_(
                        DataTag.datainfo_id == DataInfo.id,
                        Tag.id == DataTag.id,
                    )).all()
                for _, _, tag in infos:
                    session.delete(tag)

                # 하위 데이터 전부 삭제
                q.filter(and_(
                    DataInfo.user_id == data.user_id,
                    DataInfo.root.startswith(f'{data.root}{data.name}/')
                )).delete(synchronize_session='fetch')
            
            # 디렉토리/파일 전부 해당되는 내용 -> 자기 자신과 태그 삭제
            infos = session.query(DataTag, Tag).filter(and_(
                    DataTag.datainfo_id == data_id,
                    Tag.id == DataTag.tag_id,
            )).all()
            for _, tag in infos:
                session.delete(tag)
            # 파일
            q.filter(DataInfo.id == data_id).delete()
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        else:
            return root, name
        finally:
            session.close()

class DataDBQueryReader(QueryReader):
    def __call__(
        self, 
        user_id: Optional[int] = None,
        is_dir: Optional[bool] = None,
        data_id: Optional[int] = None,
        full_root: Optional[Sequence[str]] = None
    ) -> DataInfo:
        """
        is_dir이 설정된 경우 is_dir에 따른 데이터 검색
        None이면 is_dir 여부 관계없이 검색
        """
        session = DatabaseGenerator.get_session()
        q = session.query(DataInfo)
        data = None
        try:
            if data_id:
                # search by data_id
                query = q.filter(DataInfo.id == data_id)
                if user_id:
                    query.filter(DataInfo.user_id == user_id)
                data: DataInfo = query.scalar()

            elif full_root:
                # search by full_root
                query = q.filter(and_(
                    DataInfo.root == full_root[0],
                    DataInfo.name == full_root[1],
                ))
                if user_id:
                    query.filter(DataInfo.user_id == user_id)
                data = query.scalar()
        except Exception as e:
            session.rollback()
            raise e
        else:
            if is_dir:
                """
                is_dir이 설정된 경우
                is_dir까지 체크한다.
                """
                if data and data.is_dir != is_dir:
                    return None
            return data
        finally:
            session.close()

class DataDBQueryUpdator(QueryUpdator):
    def __call__(
        self, new_name: str,
        user_id: int,
        data_id: int,
    ) -> DataInfo:
        session = DatabaseGenerator.get_session()
        q = session.query(DataInfo)
        # 아이디로 찾는 경우
        data_info = q.filter(and_(
            DataInfo.user_id == user_id,
            DataInfo.id == data_id,
        )).scalar()
        if not data_info:
            # 그래도 못찾음
            raise DataNotFound()
        try:
            # 파일의 이름 수정
            prev_name = data_info.name
            data_info.name = new_name
            if data_info.is_dir:
                # 디렉토리인 경우 하위 디렉토리의 루트 수정
                dst_root = data_info.root + prev_name + '/'
                src_root = data_info.root + new_name + '/'
                q.filter(and_(
                    DataInfo.user_id == user_id,
                    DataInfo.root.startswith(dst_root),
                )).update({
                    DataInfo.root: func.replace(
                        DataInfo.root, dst_root, src_root)
                }, synchronize_session=False)
            session.commit()
            session.refresh(data_info)
        except Exception as e:
            session.rollback()
            raise e
        else:
            return data_info
        finally:
            session.close()

class DataDBQuery(QueryCRUD):
    creator = DataDBQueryCreator
    destroyer = DataDBQueryDestroyer
    reader = DataDBQueryReader
    updator = DataDBQueryUpdator

    def update_file_automatic(
        self, 
        data_id: int, 
        data_format: DataInfoCreate
    ) -> DataInfo:
        # 데이터를 생성할 때, 같은 이름의 파일을 자동 갱신할 때 사용한다.
        session = DatabaseGenerator.get_session()
        q = session.query(DataInfo)
        # 같은 유저 + 같은 이름 + 같은 루트
        data_info: DataInfo = q.filter(DataInfo.id == data_id).scalar()
        if not data_info:
            raise DataNotFound()
        try:
            # 데이터 수정
            # 싸이즈만 변경하면 된다.
            data_info.size = data_format.size
            session.commit()
            session.refresh(data_info)
        except Exception as e:
            session.rollback()
            raise e
        else:
            return data_info
        finally:
            session.close()

    def sync_file_size(self, data_id: int, full_root: str) -> DataInfo:
        # 해당 데이터와 실제 데이터의 크기를 동기화
        session = DatabaseGenerator.get_session()
        q = session.query(DataInfo)
        data_info: DataInfo = q.filter(DataInfo.id == data_id).scalar()
        if not data_info:
            raise DataNotFound()
        try:
            # 비교 후 수정
            real_size, db_size = os.path.getsize(full_root), data_info.size
            if real_size != db_size:
                data_info.size = real_size
                session.commit()
                session.refresh(data_info)
        except Exception as e:
            session.rollback()
            raise e
        else:
            return data_info
        finally:
            session.close()

