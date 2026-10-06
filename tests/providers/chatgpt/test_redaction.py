from chatexporter.providers.chatgpt.common.redaction import sanitize_reasoning_payload, REDACTED_REASONING, redact_text


def test_hidden_thoughts_text_redacted_but_shape_preserved():
    raw = {"content_type":"thoughts", "parts":["secret thought"], "meta": {"x": 1}}
    out = sanitize_reasoning_payload(raw)
    assert out["content_type"] == "thoughts"
    assert out["parts"] == [REDACTED_REASONING]
    assert out["meta"]["x"] == 1


def test_raw_cot_summary_redacted():
    raw = {"metadata":{"summary_type":"raw_cot"}, "content":{"parts":["hidden"]}}
    out = sanitize_reasoning_payload(raw)
    assert REDACTED_REASONING in str(out)
    assert "hidden" not in str(out)


def test_reasoning_recap_retained():
    raw={"content_type":"reasoning_recap","parts":["visible recap"]}
    out=sanitize_reasoning_payload(raw)
    assert out["parts"] == ["visible recap"]


def test_bearer_redaction():
    text='Authorization: Bearer ' + ('A'*40)
    assert 'A'*40 not in redact_text(text)


def test_signed_url_query_redacted_in_logs():
    from chatexporter.providers.chatgpt.common.redaction import redact_log_text
    text='failed https://chatgpt.com/backend-api/estuary/content?id=x&sig=SECRET&ts=123'
    out=redact_log_text(text)
    assert 'SECRET' not in out
    assert '<REDACTED_QUERY>' in out


def test_recursive_redaction_strips_signed_url_values():
    from chatexporter.providers.chatgpt.common.redaction import redact_secrets
    out=redact_secrets({'url':'https://x.invalid/file?id=1&sig=TOPSECRET&ts=2'})
    assert 'TOPSECRET' not in out['url']
    assert '<REDACTED_QUERY>' in out['url']


def test_playwright_call_log_cookie_header_is_fully_redacted():
    from chatexporter.providers.chatgpt.common.redaction import redact_log_text
    text = (
        "TargetClosedError: APIRequestContext.get: Request context disposed.\n"
        "  - -> GET https://chatgpt.com/backend-api/x?id=1&sig=SECRET\n"
        "    - cookie: a=alpha; __Secure-next-auth.session-token.0=SUPERSECRET; b=beta\n"
        "    - authorization: Bearer " + ("Z" * 80) + "\n"
        "    - user-agent: harmless\n"
        "    - x-user: person@example.com\n"
    )
    out = redact_log_text(text)
    assert "SUPERSECRET" not in out
    assert "a=alpha" not in out
    assert "Z" * 40 not in out
    assert "person@example.com" not in out
    assert "cookie: <REDACTED>" in out
    assert "authorization: <REDACTED>" in out
    assert "<REDACTED_QUERY>" in out


def test_compact_error_text_is_bounded():
    from chatexporter.providers.chatgpt.common.redaction import compact_error_text
    exc = RuntimeError("x" * 5000)
    out = compact_error_text(exc, max_chars=200)
    assert len(out) < 240
    assert "<TRUNCATED>" in out


def test_account_email_is_masked_in_console_output():
    """Gesamttest 2026-10-05: ``update`` zeigte "ChatGPT-Sitzung validiert: <volle E-Mail>"."""
    from types import SimpleNamespace
    from chatexporter.providers.chatgpt.common.redaction import mask_email
    from chatexporter.providers.chatgpt.contract import session_hint
    assert mask_email("nutzer@example.org") == "n***@example.org"
    hint = session_hint(SimpleNamespace(email="nutzer@example.org", user_id="user-1", name="Vor Nachname"))
    assert hint == "n***@example.org" and "nutzer@" not in hint
    assert session_hint(SimpleNamespace(email=None, user_id="user-1", name="Vor Nachname")) == "validierte Sitzung"
