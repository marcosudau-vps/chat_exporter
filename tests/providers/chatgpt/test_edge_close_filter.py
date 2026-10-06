"""Nach Strg+C: nur die harmlose TargetClosedError-Meldung von asyncio unterdruecken."""

import logging

from chatexporter.providers.chatgpt.auth.edge_cdp import _ClosedFutureFilter


class TargetClosedError(Exception):
    pass


def _record(msg, exc=None):
    return logging.LogRecord("asyncio", logging.ERROR, __file__, 1, msg, None,
                             (type(exc), exc, None) if exc else None)


def test_filter_drops_only_closed_target_future_message():
    f = _ClosedFutureFilter()
    closed = TargetClosedError("Target page, context or browser has been closed")
    assert f.filter(_record("Future exception was never retrieved", closed)) is False
    assert f.filter(_record("Future exception was never retrieved", ValueError("anders"))) is True
    assert f.filter(_record("Etwas ganz anderes", closed)) is True
    pending = ("Task was destroyed but it is pending!\ntask: <Task cancelling coro=<APIRequestContext.get() "
               "running at ...\\site-packages\\playwright\\_impl\\_fetch.py:211>>")
    assert f.filter(_record(pending)) is False
    assert f.filter(_record("Task was destroyed but it is pending!\ntask: <Task fremd>")) is True
