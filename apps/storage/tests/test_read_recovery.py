import pytest
import os
import shutil
from fastapi.testclient import TestClient
from fastapi import UploadFile, status

from main import app
from apps.storage.models import DataInfo
from apps.auth.utils.managers import AppAuthManager
from apps.user.utils.managers import UserCRUDManager
from apps.storage.utils.managers import (
    DataFileCRUDManager,
    DataDirectoryCRUDManager,
)
from system.bootloader import Bootloader
from system.connection.generators import DatabaseGenerator
from settings.base import SERVER


admin_info = None
hi, hi2 = None, None
treedir = {
    'mydir': {
        'id': None,
        'hi.txt': {'id': None},
        'hi2.txt': {'id': None},
        'subdir': {
            'id': None,
            'hi.txt': {'id': None},
        }
    }
}
TEST_EXAMLE_ROOT = 'apps/storage/tests/example'

@pytest.fixture(scope='function')
def api():
    global admin_info
    global treedir
    global hi, hi2
    # Load Application
    Bootloader.migrate_database()
    Bootloader.init_storage()
    # Add Admin
    admin_info = {
        'email': 'seokbong60@gmail.com',
        'name': 'jeonhyun',
        'passwd': 'password0123',
        'storage_size': 5,
        'is_admin': True,
    }
    user = UserCRUDManager().create(**admin_info)
    admin_info['id'] = user.id
    # Make Directory and files
    """
    mydir
        `-hi.txt
        `-hi2.txt
        `-subdir
            `-hi.txt
    """
    hi = open(f'{TEST_EXAMLE_ROOT}/hi.txt', 'rb')
    hi2 = open(f'{TEST_EXAMLE_ROOT}/hi2.txt', 'rb')
    
    # add directory mydir on root
    mydir = DataDirectoryCRUDManager().create(
        root_id=0,
        user_id=user.id,
        dirname='mydir'
    )
    treedir['mydir']['id'] = mydir.id
    # add hi.txt, hi2.txt on mydir
    files = DataFileCRUDManager().create(
        root_id=mydir.id,
        user_id=user.id,
        files=[
            UploadFile(filename=hi.name, file=hi),
            UploadFile(filename=hi2.name, file=hi2)
        ]
    )
    treedir['mydir']['hi.txt']['id'] = files[0].id
    treedir['mydir']['hi2.txt']['id'] = files[1].id
    # add subdir on mydir
    subdir = DataDirectoryCRUDManager().create(
        root_id=mydir.id,
        user_id=user.id,
        dirname='subdir'
    )
    treedir['mydir']['subdir']['id'] = subdir.id
    # add hi.txt on subdir
    files = DataFileCRUDManager().create(
        root_id=subdir.id,
        user_id=user.id,
        files=[
            UploadFile(filename=hi.name, file=hi),
        ]
    )
    treedir['mydir']['subdir']['hi.txt']['id'] = files[0].id
    # Return test api
    yield TestClient(app)
    # Close all files and remove all data
    hi.close()
    hi2.close()
    Bootloader.remove_storage()
    Bootloader.remove_database()

def test_when_file_removed_illeagal_method(api: TestClient):
    """
    DB??? ????????? ????????? ?????? ????????? ?????????????????? ?????????
    ?????? ??? DB??? ????????? ???????????? ???????????? ???????????? 404????????? ????????????.
    """
    # mydir/hi.txt ??????
    root = f'{SERVER["storage"]}/storage/{admin_info["id"]}/root/mydir/hi.txt'
    os.remove(root)
    assert not os.path.isfile(root)

    email, passwd = admin_info['email'], admin_info['passwd']
    token = AppAuthManager().login(email, passwd)
    res = api.get(
        f'/api/users/{admin_info["id"]}/datas/{treedir["mydir"]["hi.txt"]["id"]}',
        headers={'token': token},
        params={'method': 'info'},
    )
    assert res.status_code == status.HTTP_404_NOT_FOUND

    # DB ????????? ??????????????? ??? ??????
    session = DatabaseGenerator.get_session()
    assert not session.query(DataInfo) \
        .filter(DataInfo.id == treedir["mydir"]["hi.txt"]["id"]) \
            .scalar()

def test_when_directory_removed_illeagal_method(api: TestClient):
    """
    ??????????????? ???????????? ???????????? ???????????? ?????? DB???????????? ???????????? ??????
    ?????? ??????????????? ?????? ??????????????? DB????????? ????????? ????????????.
    """
    # mydir ??????
    root = f'{SERVER["storage"]}/storage/{admin_info["id"]}/root/mydir'
    shutil.rmtree(root)
    assert not os.path.isdir(root)

    email, passwd = admin_info['email'], admin_info['passwd']
    token = AppAuthManager().login(email, passwd)
    res = api.get(
        f'/api/users/{admin_info["id"]}/datas/{treedir["mydir"]["id"]}',
        headers={'token': token},
        params={'method': 'info'}
    )
    assert res.status_code == status.HTTP_404_NOT_FOUND

    # ????????? ?????? ???????????? ??? ??????
    session = DatabaseGenerator.get_session()
    assert session.query(DataInfo) \
            .filter(
                DataInfo.root.startswith('/mydir/')
            ).count() == 0
