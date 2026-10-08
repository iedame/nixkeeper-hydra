"""The tests never use the network: a request that no test answers itself
(mock.patch of urlopen, or a server of its own on 127.0.0.1) fails at once,
as Hydra being down would."""

import urllib.request

_urlopen = urllib.request.urlopen


def _offline(req, *args, **kwargs):
    url = req.full_url if isinstance(req, urllib.request.Request) else req
    if url.startswith("http://127.0.0.1:"):
        return _urlopen(req, *args, **kwargs)
    raise OSError("the tests don't use the network")


urllib.request.urlopen = _offline
