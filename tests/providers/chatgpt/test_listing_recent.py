"""Listing-Modi auto/recent/full, Aenderungsgrenze und Grenzpruefung."""

import pytest
from chatexporter.providers.chatgpt.api.conversations import ConversationApi
from chatexporter.providers.chatgpt.config.loader import load_config
from chatexporter.providers.chatgpt.storage.raw_repository import RawRepository
from chatexporter.providers.chatgpt.sync.listing import (
    CONTENT, META, NEW, SAME, classify, fetch_recent_listing,
)
from chatexporter.providers.chatgpt.sync.models import SyncAction
from chatexporter.providers.chatgpt.sync.orchestrator import SyncOrchestrator
from chatexporter.providers.chatgpt.sync.planner import build_plan


class FakeClient:
    def __init__(self, pages): self.pages=pages; self.calls=[]
    def get_json(self,path,params=None):
        self.calls.append((path,dict(params or {})))
        return self.pages[params["offset"]]


def _item(cid, update_time, **extra):
    return {"id":cid,"title":cid,"update_time":update_time,"is_archived":False,
            "is_starred":False,"pinned_time":None, **extra}


def _local(update_time, title, **extra):
    return {"remote_updated_at":update_time,"title":title,"is_archived":False,
            "is_starred":False,"pinned_time":None, **extra}


def _recent(pages, local, **kw):
    client=FakeClient(pages)
    remote,info=fetch_recent_listing(ConversationApi(client),local_index=local,**kw)
    return client,remote,info


# -- API --------------------------------------------------------------------

def test_list_page_sends_order_only_when_requested():
    client=FakeClient({0:{"items":[]}})
    api=ConversationApi(client)
    api.list_page(offset=0,limit=100)
    api.list_page(offset=0,limit=100,order="updated")
    assert "order" not in client.calls[0][1]
    assert client.calls[1][1]=={"offset":0,"limit":100,"order":"updated"}


def test_list_page_rejects_unproven_order():
    with pytest.raises(ValueError):
        ConversationApi(FakeClient({})).list_page(offset=0,limit=100,order="created")


# -- Klassifikation -----------------------------------------------------------

def test_classify_distinguishes_content_and_metadata_changes():
    assert classify(_item("a",5),None)==NEW
    assert classify(_item("a",6),_local(5,"a"))==CONTENT
    assert classify(_item("a",5,is_starred=True),_local(5,"a"))==META
    assert classify(_item("a",5),_local(5,"a"))==SAME


@pytest.mark.parametrize("remote,local", [
    ("2023-07-31T09:53:43Z", "2023-07-31T09:53:43.000000Z"),
    ("2023-07-31T09:53:43.000000Z", "2023-07-31T09:53:43Z"),
    ("2023-07-31T09:53:43+00:00", "2023-07-31T09:53:43Z"),
    ("2026-09-29T11:05:50.642226Z", "2026-09-29T11:05:50.642226+00:00"),
])
def test_time_format_differences_are_not_changes(remote, local):
    """Das Listing liefert update_time in wechselnder Schreibweise (lokal
    belegt: 198 Eintraege ohne, 2900 mit Nachkommastellen)."""
    assert classify(_item("a",remote),_local(local,"a"))==SAME
    plan=build_plan({"a":_item("a",remote)},{"a":_local(local,"a")})
    assert plan[0].action==SyncAction.SKIP


def test_excluded_chat_behind_boundary_does_not_break_it():
    """Regression 2026-09-30: der manuell ausgeschlossene Chat ist lokal nie
    vorhanden (-> 'new') und stand hinter der Grenze -> jedes Mal Voll-Abruf."""
    pages={0:{"items":[_item("n",9),_item("a",5),_item("ex",4.5),_item("b",4),_item("c",3)]}}
    local={k:_local(t,k) for k,t in (("a",5),("b",4),("c",3))}
    client,remote,info=_recent(pages,local,limit=5,confirm_unchanged=3,
                               ignore=lambda cid: cid=="ex")
    assert info["boundary_reached"] and info["reason"] is None
    assert info["ignored"]==["ex"] and info["counts"]["ignored"]==1
    assert info["changed"]==1, "nur 'n' ist eine echte Aenderung"
    assert "ex" in remote, "wird weiter gelistet (Planung: EXCLUDED)"
    ex=[e for e in info["entries"] if e["id"]=="ex"][0]
    assert ex["kind"]=="ignored" and ex["pos"]==3


def test_entries_record_diagnostics_for_each_listed_chat():
    pages={0:{"items":[_item("n",9),_item("a",5)]}}
    _client,_remote,info=_recent(pages,{"a":_local(5,"a")},limit=5)
    assert info["entries"]==[
        {"pos":1,"id":"n","kind":"new","remote_update_time":9,"local_update_time":None,
         "local_detail_update_time":None},
        {"pos":2,"id":"a","kind":"same","remote_update_time":5,"local_update_time":5,
         "local_detail_update_time":None}]


def test_listing_catching_up_to_detail_time_is_not_a_change():
    """Regression 2026-10-01 (Lauf sync_20261001T010708Z): Das Listing fuehrte
    update_time verzoegert (lokal .791121, Detailantwort beim Abruf .833364).
    Als das Listing auf .833364 nachzog, galt der Chat faelschlich als
    geaendert -> out_of_order_change an Position 100 -> Voll-Abruf."""
    remote="2026-08-20T23:45:29.833364Z"
    local=_local("2026-08-20T23:45:29.791121Z","a",raw_update_time=1787269529.833364)
    assert classify(_item("a",remote),local)==SAME
    plan=build_plan({"a":_item("a",remote)},{"a":local})
    assert plan[0].action==SyncAction.SKIP
    # Neuer als BEIDE gespeicherten Zeiten -> echte Aenderung.
    assert classify(_item("a","2026-08-20T23:45:30Z"),local)==CONTENT
    # Ohne Detailzeit (alter Index) bleibt der bisherige Vergleich.
    assert classify(_item("a",remote),_local("2026-08-20T23:45:29.791121Z","a"))==CONTENT


def test_drift_behind_boundary_no_longer_breaks_it():
    pages={0:{"items":[_item("n",9),_item("a",5),_item("b",4),_item("drift",3.5)]}}
    local={"a":_local(5,"a"),"b":_local(4,"b"),"drift":_local(3.4,"drift",raw_update_time=3.5)}
    _client,_remote,info=_recent(pages,local,limit=4,confirm_unchanged=3)
    assert info["boundary_reached"] and info["reason"] is None
    assert info["counts"]["content"]==0 and info["changed"]==1


# -- Aenderungsgrenze ---------------------------------------------------------------

def test_boundary_confirmed_on_first_page():
    pages={0:{"items":[_item("n",9),_item("a",5),_item("b",4),_item("c",3)]}}
    local={k:_local(t,k) for k,t in (("a",5),("b",4),("c",3))}
    client,remote,info=_recent(pages,local,limit=4,confirm_unchanged=3)
    assert len(client.calls)==1
    assert info["boundary_reached"] and info["reason"] is None
    assert info["boundary"]["conversation_id"]=="a"
    assert info["boundary"]["confirmed_unchanged"]==3
    assert info["changed"]==1 and set(remote)=={"n","a","b","c"}
    assert client.calls[0][1]["order"]=="updated"


def test_boundary_near_page_end_fetches_next_page_to_confirm():
    pages={0:{"items":[_item("n1",9),_item("n2",8),_item("a",5)]},
           3:{"items":[_item("b",4),_item("c",3),_item("d",2)]}}
    local={k:_local(t,k) for k,t in (("a",5),("b",4),("c",3),("d",2))}
    client,_remote,info=_recent(pages,local,limit=3,confirm_unchanged=3)
    assert [c[1]["offset"] for c in client.calls]==[0,3]
    assert info["boundary_reached"] and info["boundary"]["confirmed_unchanged"]==4


def test_all_changed_page_fetches_next_page():
    pages={0:{"items":[_item("a",9),_item("b",8)]},
           2:{"items":[_item("c",7),_item("d",1)]}}
    local={"b":_local(5,"b"),"d":_local(1,"d")}
    client,remote,info=_recent(pages,local,limit=2,confirm_unchanged=1)
    assert [c[1]["offset"] for c in client.calls]==[0,2]
    assert set(remote)=={"a","b","c","d"}
    assert info["counts"]=={NEW:2,CONTENT:1,META:0,SAME:1,"ignored":0}
    assert info["boundary_reached"]


def test_changed_item_after_boundary_is_detected():
    """Aenderungen muessen einen zusammenhaengenden Anfang bilden."""
    pages={0:{"items":[_item("n",9),_item("a",5),_item("late",4),_item("b",3)]}}
    local={"a":_local(5,"a"),"late":_local(2,"late"),"b":_local(3,"b")}
    client,remote,info=_recent(pages,local,limit=4,confirm_unchanged=1)
    assert len(client.calls)==1
    assert info["boundary_reached"] is False
    assert info["reason"]=="out_of_order_change"
    assert info["anomalies"]["out_of_order_change"]==["late"]
    assert "late" in remote, "der verspaetete Eintrag wird trotzdem geplant"


def test_metadata_change_after_boundary_does_not_break_boundary():
    pages={0:{"items":[_item("a",5),_item("b",4,is_starred=True),_item("c",3)]}}
    local={k:_local(t,k) for k,t in (("a",5),("b",4),("c",3))}
    _client,_remote,info=_recent(pages,local,limit=3,confirm_unchanged=3)
    assert info["boundary_reached"]
    assert info["counts"][META]==1 and info["changed"]==1


def test_sort_order_violation_is_detected():
    pages={0:{"items":[_item("a",5),_item("b",7),_item("c",3)]}}
    local={k:_local(t,k) for k,t in (("a",5),("b",7),("c",3))}
    _client,_remote,info=_recent(pages,local,limit=3,confirm_unchanged=1)
    assert info["reason"]=="order_violation"
    assert info["anomalies"]["order_violation"]==["b"]


def test_local_recent_conversation_missing_from_listing_is_detected():
    """Lokal aktiv und neuer als die Grenze, aber nicht im Listing:
    archiviert oder geloescht -- das sieht nur ein Voll-Abruf."""
    pages={0:{"items":[_item("a",5),_item("b",4),_item("c",3)]}}
    local={k:_local(t,k) for k,t in (("a",5),("b",4),("c",3))}
    local["weg"]=_local(6,"weg")
    local["alt_archiviert"]=_local(7,"alt",is_archived=True)
    _client,_remote,info=_recent(pages,local,limit=3,confirm_unchanged=1)
    assert info["reason"]=="recent_local_missing"
    assert info["anomalies"]["recent_local_missing"]==["weg"]


def test_cap_reached_warns_and_flags():
    pages={0:{"items":[_item("a",9),_item("b",8)]},
           2:{"items":[_item("c",7),_item("d",6)]}}
    messages=[]
    client,_remote,info=_recent(pages,{},limit=2,max_pages=2,progress=messages.append)
    assert len(client.calls)==2
    assert info["boundary_reached"] is False and info["reason"]=="cap_reached"
    assert any("WARNUNG" in m for m in messages)


def test_short_list_is_complete_even_without_confirmations():
    pages={0:{"items":[_item("a",9),_item("b",8)]}}
    local={"b":_local(8,"b")}
    client,_remote,info=_recent(pages,local,limit=5,confirm_unchanged=3)
    assert len(client.calls)==1 and info["boundary_reached"]


def test_duplicate_across_pages_keeps_first():
    pages={0:{"items":[_item("a",9),_item("b",8)]},
           2:{"items":[_item("b",8),_item("c",1)]}}
    local={"c":_local(1,"c")}
    _client,remote,info=_recent(pages,local,limit=2,confirm_unchanged=1)
    assert list(remote)==["a","b","c"]
    assert info["changed"]==2


def test_partial_listing_never_marks_missing_remote():
    local={"x":_local(1,"x")}
    remote={"y":{"update_time":2,"title":"y","is_archived":False,"is_starred":False,"pinned_time":None}}
    full=build_plan(remote,local)
    partial=build_plan(remote,local,partial_listing=True)
    assert any(i.action==SyncAction.MISSING_REMOTE for i in full)
    assert not any(i.action==SyncAction.MISSING_REMOTE for i in partial)
    assert [i.conversation_id for i in partial]==["y"]


# -- Orchestrator: Modi und Grenzpruefung ------------------------------------------------

class DualApi:
    """Liefert iter_scope (full) und list_page (recent) aus derselben Liste."""
    def __init__(self, items):
        self.items=items; self.list_page_calls=[]; self.iter_scope_calls=0; self.fetched=[]
        self.extra_nodes={}

    def iter_scope(self, *, archived, limit=100):
        self.iter_scope_calls+=1
        if not archived:
            yield from self.items

    def list_page(self, *, offset, limit, archived=False, order=None):
        self.list_page_calls.append({"offset":offset,"limit":limit,"archived":archived,"order":order})
        ordered=sorted(self.items,key=lambda x:x["update_time"],reverse=True)
        return {"items":ordered[offset:offset+limit]}

    def get_conversation(self, cid):
        item=next(x for x in self.items if x["id"]==cid)
        self.fetched.append(cid)
        mapping={
            "root":{"id":"root","message":None,"parent":None,"children":["u"]},
            "u":{"id":"u","parent":"root","children":[],"message":{"id":"u","author":{"role":"user"},
                 "content":{"content_type":"text","parts":["x"]},"metadata":{},"recipient":"all"}}}
        current="u"
        if cid in self.extra_nodes:
            mapping["u"]["children"]=["v"]
            mapping["v"]={"id":"v","parent":"u","children":[],"message":{"id":"v","author":{"role":"assistant"},
                          "content":{"content_type":"text","parts":["neu"]},"metadata":{},"recipient":"all"}}
            current="v"
        return {"conversation_id":cid,"title":item["title"],"create_time":1789700000.0,
                "update_time":item["update_time"],"current_node":current,"mapping":mapping}

    def get_textdocs(self, cid):
        return []


def _orch(repo, api, **kw):
    kw.setdefault("verify_boundary", False)
    return SyncOrchestrator(conversation_api=api,file_api=None,repository=repo,fetch_files=False,**kw)


def _seeded(tmp_path, n=5):
    repo=RawRepository(tmp_path/'raw')
    api=DualApi([_item(f"c{i}",i) for i in range(1,n+1)])
    _orch(repo,api,listing_mode="full").run()
    api.fetched=[]; api.iter_scope_calls=0; api.list_page_calls=[]
    return repo,api


def test_recent_mode_fetches_only_changed(tmp_path):
    repo,api=_seeded(tmp_path)
    api.items=[_item(f"c{i}",i) for i in range(1,5)]+[_item("c5",50),_item("c6",60)]
    result=_orch(repo,api,listing_mode="recent",listing_limit=3,recent_confirm_unchanged=2).run()
    assert api.iter_scope_calls==0
    assert [c["offset"] for c in api.list_page_calls]==[0,3]
    assert sorted(api.fetched)==["c5","c6"]
    assert result["stats"]["missing_remote"]==0
    assert result["listing"]["effective"]=="recent" and result["listing"]["boundary_reached"]


def test_auto_without_local_data_does_initial_full(tmp_path):
    repo=RawRepository(tmp_path/'raw')
    api=DualApi([_item(f"c{i}",i) for i in range(1,4)])
    result=_orch(repo,api).run()
    assert api.iter_scope_calls>0 and api.list_page_calls==[]
    assert result["listing"]=={"mode":"auto","effective":"full","escalation":"initial","items":3}
    assert sorted(api.fetched)==["c1","c2","c3"]


def test_auto_with_local_data_uses_recent(tmp_path):
    repo,api=_seeded(tmp_path)
    api.items=api.items+[_item("c9",90)]
    result=_orch(repo,api,listing_limit=10).run()
    assert api.iter_scope_calls==0 and len(api.list_page_calls)==1
    assert result["listing"]["mode"]=="auto" and result["listing"]["effective"]=="recent"
    assert api.fetched==["c9"]


def test_auto_escalates_to_full_when_boundary_not_confirmed(tmp_path):
    """Simuliert einen unterbrochenen Erstabruf: lokal nur ein Teil."""
    repo,api=_seeded(tmp_path,n=2)
    api.items=api.items+[_item(f"n{i}",100+i) for i in range(6)]
    result=_orch(repo,api,listing_limit=2,recent_max_pages=2).run()
    listing=result["listing"]
    assert listing["effective"]=="full" and listing["escalation"]=="cap_reached"
    assert listing["recent"]["pages"]==2
    assert api.iter_scope_calls>0
    assert sorted(api.fetched)==[f"n{i}" for i in range(6)]


def test_recent_mode_never_escalates(tmp_path):
    repo,api=_seeded(tmp_path,n=2)
    api.items=api.items+[_item(f"n{i}",100+i) for i in range(6)]
    result=_orch(repo,api,listing_mode="recent",listing_limit=2,recent_max_pages=2).run()
    assert result["listing"]["boundary_reached"] is False
    assert api.iter_scope_calls==0


def test_boundary_check_verifies_the_confirming_chats(tmp_path):
    """Normalfall: update_time stimmt -> genau recent_confirm_unchanged Abrufe."""
    repo,api=_seeded(tmp_path)
    api.items=api.items+[_item("c9",90)]
    result=_orch(repo,api,listing_limit=10,verify_boundary=True).run()
    assert api.fetched==["c9","c5","c4","c3"], "die drei Chats an der Grenze"
    v=result["verification"]
    assert v["confirmed"] and v["consecutive_ok"]==3 and v["requests"]==3
    assert v["mismatches"]==0 and v["stopped"] is None
    assert result["stats"]["verified_unchanged"]==3 and result["stats"]["verify_requests"]==3


def test_boundary_check_mismatch_is_stored_and_extends_check(tmp_path):
    repo,api=_seeded(tmp_path)
    api.extra_nodes={"c5"}   # neuer Turn, update_time aber unveraendert
    result=_orch(repo,api,listing_limit=10,verify_boundary=True).run()
    v=result["verification"]; stats=result["stats"]
    assert api.fetched==["c5","c4","c3","c2"], "Abweichung -> ein Chat mehr; c5 nur EINMAL abgerufen"
    assert v["confirmed"] and v["mismatches"]==1 and v["requests"]==4
    assert stats["verify_mismatches"]==1 and stats["verified_unchanged"]==3
    assert stats["verify_events"][0]["remote_current_node"]=="v"
    assert repo.load("c5")["raw"]["current_node"]=="v", "neuer Stand wurde gespeichert"
    assert stats["unchanged"]==4 and stats["fetched"]==1


def test_boundary_check_needs_consecutive_matches(tmp_path):
    repo,api=_seeded(tmp_path)
    api.extra_nodes={"c5","c3"}
    result=_orch(repo,api,listing_limit=10,verify_boundary=True).run()
    v=result["verification"]
    assert api.fetched==["c5","c4","c3","c2","c1"]
    assert v["mismatches"]==2 and v["consecutive_ok"]==2
    assert v["confirmed"] is False and v["stopped"]=="candidates_exhausted"


def test_boundary_check_respects_max_requests(tmp_path):
    repo,api=_seeded(tmp_path)
    api.extra_nodes={"c5"}
    result=_orch(repo,api,listing_limit=10,verify_boundary=True,verify_max_requests=2).run()
    v=result["verification"]
    assert v["requests"]==2 and v["stopped"]=="max_requests" and v["confirmed"] is False


def test_boundary_check_can_be_disabled(tmp_path):
    repo,api=_seeded(tmp_path)
    result=_orch(repo,api,listing_limit=10,verify_boundary=False).run()
    assert api.fetched==[] and result["verification"]["enabled"] is False


def test_auto_stays_recent_with_excluded_chat_behind_boundary(tmp_path):
    from chatexporter.providers.chatgpt.sync.exclusions import ManualExclusions
    repo,api=_seeded(tmp_path)
    api.items=api.items+[_item("c9",90),_item("ex",4.5)]   # ex: lokal nie vorhanden
    result=_orch(repo,api,listing_limit=10,
                 exclusions=ManualExclusions({"ex":"HTTP 500 dauerhaft"},{})).run()
    assert result["listing"]["effective"]=="recent", "kein Voll-Abruf wegen Ausschluss"
    assert result["listing"]["ignored"]==["ex"]
    assert api.iter_scope_calls==0 and api.fetched==["c9"]
    assert result["plan_counts"]["EXCLUDED"]==1


def test_interrupted_escalation_keeps_recent_diagnostics(tmp_path):
    repo,api=_seeded(tmp_path,n=2)
    api.items=api.items+[_item(f"n{i}",100+i) for i in range(6)]

    def interrupted(*, archived, limit=100):
        raise KeyboardInterrupt
        yield  # pragma: no cover

    api.iter_scope=interrupted
    result=_orch(repo,api,listing_limit=2,recent_max_pages=2).run()
    listing=result["listing"]
    assert result["aborted"] is True and result["abort_stage"]=="interrupted"
    assert listing["escalation"]=="cap_reached" and listing["full_completed"] is False
    assert listing["recent"]["pages"]==2 and len(listing["recent"]["entries"])==4


def test_run_report_lists_fetched_conversations(tmp_path):
    repo,api=_seeded(tmp_path)
    api.items=api.items+[_item("c9",90)]
    api.items[0]=_item("c1",45)   # c1 geaendert
    result=_orch(repo,api,listing_limit=10).run()
    fetched={(i["id"],i["action"]) for i in result["items"]["fetched"]}
    assert fetched=={("c9","new"),("c1","signature_changed")}
    assert result["items"]["failed"]==[]


def test_orchestrator_rejects_unknown_listing_mode(tmp_path):
    with pytest.raises(ValueError):
        SyncOrchestrator(conversation_api=None,file_api=None,repository=RawRepository(tmp_path/'raw'),
                         listing_mode="bogus")


def test_config_listing_defaults_yaml_and_env(tmp_path, monkeypatch):
    p=tmp_path/'c.yaml'; p.write_text('sync:\n  listing_limit: 100\n',encoding='utf-8')
    cfg=load_config(p)
    assert cfg.sync.listing_mode=="auto" and cfg.sync.recent_max_pages==3
    assert cfg.sync.recent_confirm_unchanged==3
    assert cfg.sync.verify_boundary is True and cfg.sync.verify_max_requests==0
    p.write_text('sync:\n  listing_mode: recent\n  recent_max_pages: 0\n'
                 '  recent_confirm_unchanged: 0\n  verify_boundary: false\n'
                 '  verify_max_requests: -1\n',encoding='utf-8')
    cfg=load_config(p)
    assert cfg.sync.listing_mode=="recent" and cfg.sync.recent_max_pages==1
    assert cfg.sync.recent_confirm_unchanged==1
    assert cfg.sync.verify_boundary is False and cfg.sync.verify_max_requests==0
    monkeypatch.setenv("CHATEXPORTER_LISTING_MODE","full")
    assert load_config(p).sync.listing_mode=="full"
    monkeypatch.setenv("CHATEXPORTER_LISTING_MODE","bogus")
    with pytest.raises(ValueError):
        load_config(p)


def test_auto_reloads_conversations_deleted_locally_even_if_old(tmp_path):
    """Testablauf 2026-10-05: Chats nur lokal (im Storage) geloescht, nicht auf der Webseite.
    Ein alter Chat liegt hinter der Aenderungsgrenze; recent allein wuerde ihn nie wieder sehen."""
    repo,api=_seeded(tmp_path,n=10)
    entry=repo.index.conversations["c1"]
    (repo.index.root/entry["relative_path"]).unlink()      # aeltester Chat lokal geloescht
    repo=RawRepository(tmp_path/'raw')                     # naechster Lauf: Index merkt das Fehlen
    assert repo.index.lost_entries==["c1"]
    result=_orch(repo,api,listing_limit=3).run()
    listing=result["listing"]
    assert listing["effective"]=="full" and listing["escalation"]=="local_files_missing"
    assert listing["local_missing"]==["c1"]
    assert api.fetched==["c1"], "nur der fehlende Chat wird neu geladen"
    assert repo.index.lost_entries==[] and "c1" in repo.index.conversations
    api.fetched=[]; api.iter_scope_calls=0
    result=_orch(RawRepository(tmp_path/'raw'),api,listing_limit=3).run()
    assert result["listing"]["effective"]=="recent" and api.iter_scope_calls==0, "danach wieder sparsam"


def test_local_loss_is_remembered_until_the_conversation_is_back(tmp_path):
    """Bricht der Lauf vor dem Neuladen ab, bleibt der Verlust bekannt (eigene Datei, nicht im Index)."""
    repo,api=_seeded(tmp_path,n=4)
    entry=repo.index.conversations["c2"]
    (repo.index.root/entry["relative_path"]).unlink()
    assert RawRepository(tmp_path/'raw').index.lost_entries==["c2"]
    again=RawRepository(tmp_path/'raw')                    # Index inzwischen neu gebaut, ohne c2
    assert "c2" not in again.index.conversations and again.index.lost_entries==["c2"]
