from chatexporter.providers.chatgpt.sync.planner import build_plan
from chatexporter.providers.chatgpt.sync.models import SyncAction


def entry(title='T',update=1,arch=False,star=False,pin=None):
 return {"title":title,"remote_updated_at":update,"is_archived":arch,"is_starred":star,"pinned_time":pin}
def summary(title='T',update=1,arch=False,star=False,pin=None):
 return {"id":"c","title":title,"update_time":update,"is_archived":arch,"is_starred":star,"pinned_time":pin}


def test_new():
 p=build_plan({"c":summary()}, {})[0]
 assert p.action == SyncAction.FETCH_FULL and p.reason == 'new'


def test_unchanged():
 p=build_plan({"c":summary()}, {"c":entry()})[0]
 assert p.action == SyncAction.SKIP


def test_title_change_fetches_full():
 assert build_plan({"c":summary(title='X')},{"c":entry()})[0].action == SyncAction.FETCH_FULL


def test_archive_change_fetches_full():
 assert build_plan({"c":summary(arch=True)},{"c":entry()})[0].action == SyncAction.FETCH_FULL


def test_star_change_fetches_full():
 assert build_plan({"c":summary(star=True,pin=9)},{"c":entry()})[0].action == SyncAction.FETCH_FULL


def test_missing_remote_never_deleted():
 p=build_plan({}, {"c":entry()})[0]
 assert p.action == SyncAction.MISSING_REMOTE


def test_corrupt_local_fetches_full():
    local=entry(); local['raw_integrity_ok']=False
    p=build_plan({'c':summary()},{'c':local})[0]
    assert p.action == SyncAction.FETCH_FULL
    assert p.reason == 'local_incomplete_or_integrity_failed'
