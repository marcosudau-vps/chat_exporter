import json
from pathlib import Path
from chatexporter.providers.chatgpt.storage.raw_repository import RawRepository, _month_bucket
from chatexporter.providers.chatgpt.storage.index import StorageIndex
from chatexporter.providers.chatgpt.storage.envelope import build_envelope
from chatexporter.providers.chatgpt.fetch.conversation_fetcher import FetchedConversation
from chatexporter.providers.chatgpt.fetch.validator import validate_conversation_graph
from chatexporter.providers.chatgpt.common.hashing import sha256_file


def envelope(simple_raw, summary):
 return build_envelope(summary,FetchedConversation(simple_raw,[],[],[],validate_conversation_graph(simple_raw),[]))


def test_month_bucket_epoch():
 assert _month_bucket(1789700000.0).startswith('2026-')


def test_empty_root_builds_empty_index(tmp_path):
 repo=RawRepository(tmp_path/'raw')
 assert repo.index.conversations == {}
 assert (tmp_path/'raw'/'storage_index.json').exists()


def test_commit_and_rebuild_without_index(tmp_path,simple_raw,summary):
 root=tmp_path/'raw'; repo=RawRepository(root); env=envelope(simple_raw,summary)
 path=repo.commit(env)
 assert path.exists()
 (root/'storage_index.json').unlink()
 idx=StorageIndex(root).load_or_rebuild()
 assert 'c1' in idx.conversations
 assert idx.conversations['c1']['relative_path'].endswith('/c1.json')


def test_corrupt_index_recovers(tmp_path,simple_raw,summary):
 root=tmp_path/'raw'; repo=RawRepository(root); repo.commit(envelope(simple_raw,summary))
 (root/'storage_index.json').write_text('{bad',encoding='utf-8')
 idx=StorageIndex(root).load_or_rebuild()
 assert set(idx.conversations)=={'c1'}


def test_schema_mismatch_recovers(tmp_path,simple_raw,summary):
 root=tmp_path/'raw'; repo=RawRepository(root); repo.commit(envelope(simple_raw,summary))
 (root/'storage_index.json').write_text(json.dumps({"schema_version":999,"conversations":{}}),encoding='utf-8')
 assert 'c1' in StorageIndex(root).load_or_rebuild().conversations


def test_atomic_replace_keeps_valid_json(tmp_path,simple_raw,summary):
 root=tmp_path/'raw'; repo=RawRepository(root); env=envelope(simple_raw,summary); path=repo.commit(env)
 env['remote_summary']['title']='Changed'; repo.commit(env)
 assert json.loads(path.read_text(encoding='utf-8'))['remote_summary']['title']=='Changed'
 assert not list((root/'.staging'/'conversations').glob('*.tmp'))


def test_file_hash_rebuilt(tmp_path,simple_raw,summary):
 root=tmp_path/'raw'; repo=RawRepository(root); path=repo.commit(envelope(simple_raw,summary))
 assert repo.index.conversations['c1']['file_sha256'] == sha256_file(path)


def test_dirty_marker_forces_rebuild_of_stale_index(tmp_path,simple_raw,summary):
    root=tmp_path/'raw'; repo=RawRepository(root); env=envelope(simple_raw,summary); path=repo.commit(env)
    # Simulate raw replace succeeded but index save did not.
    raw=json.loads(path.read_text(encoding='utf-8')); raw['remote_summary']['title']='Newer on disk'
    path.write_text(json.dumps(raw),encoding='utf-8')
    repo.index.dirty_marker.parent.mkdir(parents=True,exist_ok=True); repo.index.dirty_marker.write_text('c1')
    idx=StorageIndex(root).load_or_rebuild()
    assert idx.conversations['c1']['title']=='Newer on disk'
    assert not idx.dirty_marker.exists()

def test_rebuild_detects_raw_payload_integrity_failure(tmp_path,simple_raw,summary):
    root=tmp_path/'raw'; repo=RawRepository(root); env=envelope(simple_raw,summary); path=repo.commit(env)
    raw=json.loads(path.read_text(encoding='utf-8')); raw['raw']['title']='tampered'; path.write_text(json.dumps(raw),encoding='utf-8')
    idx=StorageIndex(root).rebuild()
    assert idx.conversations['c1']['raw_integrity_ok'] is False
