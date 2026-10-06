from chatexporter.providers.chatgpt.fetch.conversation_fetcher import ConversationFetcher

class Api:
    def __init__(self, raw): self.raw=raw
    def get_conversation(self,cid): return self.raw
    def get_textdocs(self,cid): raise RuntimeError('textdocs unavailable')

def test_textdocs_failure_does_not_discard_complete_graph(simple_raw):
    simple_raw['mapping']['a1']['message']['recipient']='canmore.create_textdoc'
    fetched=ConversationFetcher(Api(simple_raw),fetch_textdocs=True).fetch('c1')
    assert fetched.validation.complete
    assert fetched.textdocs == []
    assert fetched.supplemental_errors and fetched.supplemental_errors[0].startswith('textdocs:')
