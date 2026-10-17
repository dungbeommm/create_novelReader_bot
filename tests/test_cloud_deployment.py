"""Offline regression tests: no real Telegram, Google, or GitHub credentials."""
import asyncio
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tarfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.exceptions import InvalidTag
from integrations import cloud_output as cloud
from integrations import checkpoint as cp
from integrations.github import GitHubReleases

ROOT = Path(__file__).resolve().parents[1]
JID = 'a' * 16


@pytest.fixture(autouse=True)
def clean_cloud(monkeypatch):
    for name in ('GITHUB_REPOSITORY','GITHUB_TOKEN','GH_RELEASE_TOKEN','ALLOW_PUBLIC_RELEASES',
                 'CLOUD_UPLOAD','GDRIVE_CLIENT_ID','GDRIVE_CLIENT_SECRET','GDRIVE_REFRESH_TOKEN','GDRIVE_FOLDER_ID'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cloud, 'drive_config', lambda: {'enabled': False})


@pytest.fixture
def output(tmp_path):
    path = tmp_path/'output.txt'
    path.write_text('Xin chào', encoding='utf-8')
    return path


def test_unconfigured_local_mode(output):
    assert cloud.publish(output,JID,output.parent) is None


def test_disabled(output,monkeypatch):
    monkeypatch.setenv('CLOUD_UPLOAD','off')
    monkeypatch.setenv('GITHUB_TOKEN','fake')
    monkeypatch.setenv('GITHUB_REPOSITORY','owner/repo')
    assert cloud.publish(output,JID,output.parent) is None


def enable(monkeypatch):
    monkeypatch.setenv('GITHUB_TOKEN','fake')
    monkeypatch.setenv('GITHUB_REPOSITORY','owner/repo')


def test_drive_first_and_saved_receipt(output,monkeypatch):
    enable(monkeypatch)
    calls=[]
    def drive(*args):
        calls.append('drive')
        return {'provider':'drive','url':'https://drive.google.com/file/d/123/view'}
    monkeypatch.setattr(cloud,'upload_drive',drive)
    monkeypatch.setattr(cloud,'upload_release',lambda *_: pytest.fail('must not use fallback'))
    first=cloud.publish(output,JID,output.parent)
    assert first['provider']=='drive'
    assert cloud.publish(output,JID,output.parent)==first
    assert calls==['drive']
    output.write_bytes(b'new content')
    cloud.publish(output,JID,output.parent)
    assert len(calls)==2


@pytest.mark.parametrize('failure',[ValueError('missing config'),RuntimeError('expired token'),OSError('network')])
def test_drive_failure_falls_back(output,monkeypatch,failure):
    enable(monkeypatch)
    def fail(*_): raise failure
    monkeypatch.setattr(cloud,'upload_drive',fail)
    monkeypatch.setattr(cloud,'upload_release',lambda *_:{'provider':'github','url':'https://example.test/asset'})
    assert cloud.publish(output,JID,output.parent)['provider']=='github'


def test_both_fail_no_receipt(output,monkeypatch):
    enable(monkeypatch)
    def fail(*_): raise ValueError('offline')
    monkeypatch.setattr(cloud,'upload_drive',fail)
    monkeypatch.setattr(cloud,'upload_release',fail)
    with pytest.raises(ValueError):cloud.publish(output,JID,output.parent)
    assert not (output.parent/'cloud.json').exists()


@pytest.mark.parametrize('strict,optin,allowed',[(False,False,False),(False,True,True),(True,True,False)])
def test_public_repo_guard(monkeypatch,strict,optin,allowed):
    enable(monkeypatch)
    if optin:monkeypatch.setenv('ALLOW_PUBLIC_RELEASES','true')
    gh=GitHubReleases()
    gh.session=SimpleNamespace(get=lambda *a,**k:SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'private':False}))
    if allowed:gh.check_private(strict=strict)
    else:
        with pytest.raises(ValueError):gh.check_private(strict=strict)


def test_release_asset_pagination(monkeypatch):
    enable(monkeypatch)
    gh=GitHubReleases()
    gh.session=SimpleNamespace(get=lambda *a,**kw:SimpleNamespace(raise_for_status=lambda:None,
        json=lambda: list(range(100)) if kw['params']['page']==1 else [100]))
    assert len(gh.assets({'id':1}))==101


def test_release_reuses_existing_asset(output,monkeypatch):
    digest=cloud.fingerprint(output)
    class Fake:
        def release(self,*_):return {'id':1}
        def assets(self,*_):return [{'name':digest[:16]+'_'+output.name,'size':output.stat().st_size,'browser_download_url':'url'}]
        def upload(self,*_):pytest.fail('duplicate upload')
    monkeypatch.setattr(cloud,'GitHubReleases',Fake)
    assert cloud.upload_release(output,JID,digest)['url']=='url'


def test_checkpoint_encrypt_roundtrip_and_tamper(tmp_path,monkeypatch):
    monkeypatch.setenv('CHECKPOINT_KEY',base64.urlsafe_b64encode(os.urandom(32)).decode())
    source,encrypted,restored=[tmp_path/p for p in ('source','encrypted','restored')]
    source.write_bytes(os.urandom(2*1024**2+137))
    cp.encrypt(source,encrypted)
    assert encrypted.read_bytes()!=source.read_bytes()
    cp.decrypt(encrypted,restored)
    assert source.read_bytes()==restored.read_bytes()
    data=bytearray(encrypted.read_bytes());data[100]^=1;encrypted.write_bytes(data)
    with pytest.raises(InvalidTag):cp.decrypt(encrypted,restored)
    assert not restored.exists()


@pytest.mark.parametrize('value',['','wrong',base64.urlsafe_b64encode(b'short').decode()])
def test_checkpoint_invalid_key(monkeypatch,value):
    monkeypatch.setenv('CHECKPOINT_KEY',value)
    with pytest.raises(ValueError):cp.key()


def test_snapshot_wal_database_and_exclusions(tmp_path):
    root=tmp_path/'data';root.mkdir()
    db=sqlite3.connect(root/'queue.sqlite3')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE test(value TEXT)');db.execute("INSERT INTO test VALUES('durable')");db.commit()
    (root/'runner.log').write_text('secret log')
    (root/'chapter.mp3').write_bytes(b'incomplete')
    (root/'progress.tmp').write_text('incomplete')
    (root/'input.txt').write_text('source')
    target=tmp_path/'backup.tar.gz'
    cp.snapshot(root,target)
    db.close()
    restored=tmp_path/'restored';cp.extract(target,restored)
    assert sorted(p.name for p in restored.iterdir())==['input.txt','queue.sqlite3']
    with sqlite3.connect(restored/'queue.sqlite3') as db:
        assert db.execute('SELECT value FROM test').fetchone()[0]=='durable'


@pytest.mark.parametrize('name,symlink',[('../escape',False),('/absolute',False),('link',True)])
def test_reject_unsafe_tar(tmp_path,name,symlink):
    path=tmp_path/'bad.tar.gz'
    with tarfile.open(path,'w:gz') as tar:
        entry=tarfile.TarInfo(name)
        if symlink:entry.type=tarfile.SYMTYPE;entry.linkname='/etc/passwd'
        else:entry.size=1
        tar.addfile(entry,None if symlink else io.BytesIO(b'x'))
    with pytest.raises(ValueError):cp.extract(path,tmp_path/'target')


def test_restore_refuses_overwrite(tmp_path,monkeypatch):
    monkeypatch.setenv('CHECKPOINT_KEY',base64.urlsafe_b64encode(os.urandom(32)).decode())
    (tmp_path/'queue.sqlite3').write_bytes(b'existing')
    with pytest.raises(ValueError,match='trống'):cp.restore(tmp_path)


def test_checkpoint_rotation_upload_before_delete(tmp_path,monkeypatch):
    monkeypatch.setenv('CHECKPOINT_KEY',base64.urlsafe_b64encode(os.urandom(32)).decode())
    events=[]
    class Fake:
        def check_private(self,strict=False):assert strict
        def release(self,*a,**k):return {'id':1}
        def assets(self,*a):return [{'name':'checkpoint-1.enc','id':1},{'name':'checkpoint-2.enc','id':2}]
        def upload(self,*a):events.append('upload')
        def delete_asset(self,a):events.append(('delete',a['id']))
    monkeypatch.setattr(cp,'GitHubReleases',Fake)
    cp.save(tmp_path)
    assert events==['upload',('delete',1)]


def test_checkpoint_failed_upload_keeps_previous(tmp_path,monkeypatch):
    monkeypatch.setenv('CHECKPOINT_KEY',base64.urlsafe_b64encode(os.urandom(32)).decode())
    class Fake:
        def check_private(self,**k):pass
        def release(self,*a):return {'id':1}
        def assets(self,*a):return [{'name':'checkpoint-1.enc','id':1}]
        def upload(self,*a):raise OSError('offline')
        def delete_asset(self,*a):pytest.fail('deleted a good checkpoint')
    monkeypatch.setattr(cp,'GitHubReleases',Fake)
    with pytest.raises(OSError):cp.save(tmp_path)


def load_state():
    spec=importlib.util.spec_from_file_location('novel_state_tests',ROOT/'telegram/state.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.State


def test_document_idempotency_and_recover(tmp_path):
    state=load_state()(tmp_path)
    jid=state.create(1,1,'translate','.txt',b'text',message_id=42)
    assert state.create(1,1,'translate','.txt',b'text',message_id=42)==jid
    assert len(state.list(1))==1
    state.next();assert state.get(jid)['status']=='running'
    state.recover();assert state.get(jid)['status']=='queued'
    assert state.get(jid,owner=2) is None


@pytest.fixture
def bot_module(tmp_path,monkeypatch):
    monkeypatch.setenv('BOT_DATA',str(tmp_path/'botdata'))
    monkeypatch.syspath_prepend(str(ROOT/'telegram'))
    spec=importlib.util.spec_from_file_location('novel_bot_tests',ROOT/'telegram/bot.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_bot_cloud_delivery_then_resume(bot_module,monkeypatch):
    b=bot_module
    jid=b.state.create(1,1,'translate','.txt',b'input')
    folder=b.DATA/jid;output=folder/'output';output.mkdir();(output/'result.txt').write_text('result')
    b.state.set(jid,'delivering')
    calls=[]
    monkeypatch.setattr(b,'publish',lambda *a:calls.append(a[0].name) or {'provider':'github','url':'https://example.test/result'})
    app=SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock(),send_document=AsyncMock(),send_audio=AsyncMock()))
    row=b.state.get(jid)
    asyncio.run(b.deliver(app,row))
    assert b.state.get(jid)['status']=='done'
    asyncio.run(b.deliver(app,row))
    assert calls==['result.txt']
    assert app.bot.send_document.await_count==1


def test_bot_large_file_link_only(bot_module,monkeypatch):
    b=bot_module
    jid=b.state.create(1,1,'translate','.txt',b'input')
    folder=b.DATA/jid;out=folder/'output';out.mkdir()
    with (out/'large.epub').open('wb') as f:f.truncate(49*1024**2)
    b.state.set(jid,'delivering')
    monkeypatch.setattr(b,'publish',lambda *a:{'provider':'drive','url':'https://example.test/large'})
    app=SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock(),send_document=AsyncMock(),send_audio=AsyncMock()))
    asyncio.run(b.deliver(app,b.state.get(jid)))
    assert b.state.get(jid)['status']=='done'
    app.bot.send_document.assert_not_awaited()


def test_bot_cloud_failure_does_not_mark_sent(bot_module,monkeypatch):
    b=bot_module
    jid=b.state.create(1,1,'translate','.txt',b'input')
    folder=b.DATA/jid;out=folder/'output';out.mkdir();(out/'result.txt').write_text('result')
    b.state.set(jid,'delivering')
    def fail(*a):raise OSError('upload failed')
    monkeypatch.setattr(b,'publish',fail)
    app=SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock(),send_document=AsyncMock(),send_audio=AsyncMock()))
    with pytest.raises(OSError):asyncio.run(b.deliver(app,b.state.get(jid)))
    assert not (folder/'sent.json').exists()
    app.bot.send_document.assert_not_awaited()


def test_workflows_parse_and_no_pr_triggers():
    import yaml
    for path in (ROOT/'.github/workflows').glob('*.yml'):
        # BaseLoader retains the literal 'on' key (YAML 1.2 GitHub semantics).
        data=yaml.load(path.read_text(),Loader=yaml.BaseLoader)
        assert 'pull_request' not in data['on']
        assert data['concurrency']['cancel-in-progress']=='false'
        assert data['jobs']


def response(data=None, status=200, headers=None):
    return SimpleNamespace(status_code=status, headers=headers or {},
        json=lambda: data or {}, raise_for_status=lambda:None)


def test_drive_oauth_upload_streaming(output,monkeypatch):
    monkeypatch.setattr(cloud,'drive_config',lambda:{'enabled':True,'mode':'api',
        'client_id':'client','client_secret':'secret','refresh_token':'refresh','folder_id':'folder123'})
    events=[]
    def post(url,**kw):
        if 'oauth2.googleapis.com/token' in url:
            assert kw['data']['grant_type']=='refresh_token'
            events.append('refresh')
            return response({'access_token':'access'})
        assert kw['headers']['Authorization']=='Bearer access'
        assert kw['json']['parents']==['folder123']
        assert kw['json']['appProperties']['novel_job']==JID
        events.append('init')
        return response(headers={'Location':'https://www.googleapis.com/upload/session123'})
    def put(url,**kw):
        assert hasattr(kw['data'],'read')  # file object, not a full in-memory buffer
        assert kw['data'].read()==output.read_bytes()
        events.append('upload')
        return response({'id':'file123'})
    monkeypatch.setattr(cloud.requests,'post',post)
    monkeypatch.setattr(cloud.requests,'get',lambda *a,**k:response({'files':[]}))
    monkeypatch.setattr(cloud.requests,'put',put)
    result=cloud.upload_drive(output,JID,cloud.fingerprint(output))
    assert result['url']=='https://drive.google.com/file/d/file123/view'
    assert events==['refresh','init','upload']


def test_drive_reuses_completed_upload(output,monkeypatch):
    monkeypatch.setattr(cloud,'drive_config',lambda:{'enabled':True,'mode':'api',
        'access_token':'access','folder_id':'folder123'})
    monkeypatch.setattr(cloud.requests,'get',lambda *a,**k:response({'files':[{'id':'existing'}]}))
    monkeypatch.setattr(cloud.requests,'post',lambda *a,**k:pytest.fail('duplicate upload'))
    assert cloud.upload_drive(output,JID,cloud.fingerprint(output))['url'].endswith('/existing/view')


def test_drive_rejects_hostile_upload_location(output,monkeypatch):
    monkeypatch.setattr(cloud,'drive_config',lambda:{'enabled':True,'mode':'api',
        'access_token':'access','folder_id':'folder123'})
    monkeypatch.setattr(cloud.requests,'get',lambda *a,**k:response({'files':[]}))
    monkeypatch.setattr(cloud.requests,'post',lambda *a,**k:response(headers={'Location':'https://evil.example/upload'}))
    monkeypatch.setattr(cloud.requests,'put',lambda *a,**k:pytest.fail('credential leak'))
    with pytest.raises(ValueError,match='không hợp lệ'):
        cloud.upload_drive(output,JID,cloud.fingerprint(output))


def test_real_environment_drive_config_partial_fails(monkeypatch):
    # Call the unpatched function by loading a separate module instance.
    spec=importlib.util.spec_from_file_location('cloud_config_test',ROOT/'integrations/cloud_output.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setenv('GDRIVE_CLIENT_ID','client')
    with pytest.raises(ValueError,match='bốn'):module.drive_config()


def test_remote_checkpoint_restore_roundtrip(tmp_path,monkeypatch):
    monkeypatch.setenv('CHECKPOINT_KEY',base64.urlsafe_b64encode(os.urandom(32)).decode())
    original=tmp_path/'original';original.mkdir()
    state=load_state()(original)
    jid=state.create(1,1,'translate','.txt','你好'.encode())
    state.next()
    archive,encrypted=tmp_path/'state.tar.gz',tmp_path/'state.enc'
    cp.snapshot(original,archive);cp.encrypt(archive,encrypted)
    class Fake:
        def check_private(self,strict=False):assert strict
        def release(self,*a,**k):return {'id':1}
        def assets(self,*a):return [{'name':'checkpoint-2.enc','size':encrypted.stat().st_size}]
        def download(self,asset,path):path.write_bytes(encrypted.read_bytes())
    monkeypatch.setattr(cp,'GitHubReleases',Fake)
    restored=tmp_path/'restored'
    assert cp.restore(restored)
    recovered=load_state()(restored);recovered.recover()
    assert recovered.get(jid)['status']=='queued'
    assert (restored/jid/'input.txt').read_bytes()=='你好'.encode()


def test_new_hosted_repository_has_no_checkpoint(tmp_path,monkeypatch):
    monkeypatch.setenv('CHECKPOINT_KEY',base64.urlsafe_b64encode(os.urandom(32)).decode())
    class Fake:
        def check_private(self,strict=False):assert strict
        def release(self,*a,**k):assert not k['create'];return None
    monkeypatch.setattr(cp,'GitHubReleases',Fake)
    assert cp.restore(tmp_path/'empty') is False


def test_bad_remote_checkpoint_never_restores_old_silently(tmp_path,monkeypatch):
    monkeypatch.setenv('CHECKPOINT_KEY',base64.urlsafe_b64encode(os.urandom(32)).decode())
    requested=[]
    class Fake:
        def check_private(self,**k):pass
        def release(self,*a,**k):return {'id':1}
        def assets(self,*a):return [{'name':'checkpoint-1.enc','size':64},{'name':'checkpoint-2.enc','size':64}]
        def download(self,asset,path):requested.append(asset['name']);path.write_bytes(b'corrupt data')
    monkeypatch.setattr(cp,'GitHubReleases',Fake)
    with pytest.raises(ValueError):cp.restore(tmp_path/'restored')
    assert requested==['checkpoint-2.enc']
    assert not (tmp_path/'restored').exists()


def test_bot_refuses_other_telegram_users(bot_module):
    b=bot_module
    b.ALLOWED={123}
    message=SimpleNamespace(reply_text=AsyncMock())
    update=SimpleNamespace(effective_user=SimpleNamespace(id=999),
        effective_chat=SimpleNamespace(type='private'),effective_message=message)
    assert asyncio.run(b.permitted(update)) is False
    message.reply_text.assert_awaited_once()


def test_bot_cancelled_delivery_does_not_upload(bot_module,monkeypatch):
    b=bot_module
    jid=b.state.create(1,1,'translate','.txt',b'input')
    folder=b.DATA/jid;out=folder/'output';out.mkdir();(out/'file.txt').write_text('content')
    b.state.set(jid,'cancelled')
    monkeypatch.setattr(b,'publish',lambda *a:pytest.fail('upload after cancellation'))
    app=SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock(),send_document=AsyncMock(),send_audio=AsyncMock()))
    asyncio.run(b.deliver(app,b.state.get(jid)))
    assert b.state.get(jid)['status']=='cancelled'
