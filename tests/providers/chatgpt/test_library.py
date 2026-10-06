from chatexporter.providers.chatgpt.storage.library import LibraryStore


class FakeFileApi:
 def metadata(self,fid): return {"id":fid,"name":"demo.txt","mime_type":"text/plain","file_extension":"txt","size":3}
 def download_ticket(self,fid, *, gizmo_id=None): return {"download_url":"https://example.invalid/signed?sig=secret","file_name":"demo.txt","file_size_bytes":3}
 def download_bytes(self,url): return b'abc'


def test_materialization_and_derived_state(tmp_path):
 store=LibraryStore(tmp_path)
 ref={"id":"file_1","kind":"attachment","name":"demo.txt"}
 assert store.derived_state(ref)=='PENDING'
 result=store.materialize(ref,FakeFileApi())
 assert result['state']=='MATERIALIZED'
 assert store.derived_state(ref)=='MATERIALIZED'
 meta=(store.metadata_path('file_1')).read_text(encoding='utf-8')
 assert 'sig=secret' not in meta
 assert 'download_url_persisted' in meta


def test_unsupported_non_file_id(tmp_path):
 store=LibraryStore(tmp_path)
 assert store.derived_state({"id":"libfile_1"})=='UNSUPPORTED'
