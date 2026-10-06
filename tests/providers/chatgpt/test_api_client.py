import json
from chatexporter.providers.chatgpt.api.client import ApiClient

class Resp:
 status=200; headers={"content-type":"application/json"}
 def body(self): return b'{"ok":true}'
class Req:
 def __init__(self): self.calls=[]
 def get(self,url,**kwargs): self.calls.append((url,kwargs)); return Resp()
class Context:
 def __init__(self): self.request=Req()


def test_thin_client_adds_bearer_in_memory():
 c=Context(); api=ApiClient(c,'secret-token',base_url='https://chatgpt.com')
 r=api.request('GET','/x',params={'a':1})
 assert r.json()=={'ok':True}
 url,kw=c.request.calls[0]
 assert url.endswith('/x?a=1')
 assert kw['headers']['Authorization']=='Bearer secret-token'


def test_closed_browser_transport_is_wrapped_as_fatal_transport_error():
    from chatexporter.providers.chatgpt.api.client import ApiTransportClosedError

    class TargetClosedError(Exception):
        pass

    class ClosedReq:
        def get(self, url, **kwargs):
            raise TargetClosedError("APIRequestContext.get: Target page, context or browser has been closed")

    class ClosedContext:
        def __init__(self):
            self.request = ClosedReq()

    api = ApiClient(ClosedContext(), "secret-token", base_url="https://chatgpt.com")
    try:
        api.request("GET", "/x")
    except ApiTransportClosedError as exc:
        assert "cannot continue safely" in str(exc)
    else:
        raise AssertionError("expected ApiTransportClosedError")
