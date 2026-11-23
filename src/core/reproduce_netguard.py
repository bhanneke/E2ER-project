"""Network guard for the steps of ``e2er reproduce`` (copied into the rerun's environment).

``e2er reproduce`` copies this file into the new virtual environment's
site-packages, with a ``.pth`` line that imports it at interpreter start. It
does nothing unless ``E2ER_REPRODUCE_NETWORK`` is set:

- ``block``: a connection to another machine fails with a plain OSError that
  says why (the study's code may read its inputs, not the web);
- ``record``: the connection is made, and recorded.
- ``public`` (a step that loads the study's data again): connections to public
  hosts are made and not recorded; a connection to this computer (loopback,
  the names Docker Desktop gives the host), the local network (private,
  link-local, shared and unique-local addresses) or a cloud metadata address
  fails with a plain OSError, and is recorded. A data source is on the
  internet; e2er's dashboard, a router or a cloud's metadata service is not.

Every attempt in ``block`` and ``record``, and every refused one in ``public``,
is appended to ``E2ER_REPRODUCE_NETWORK_LOG``, one JSON line ``{"host", "port",
"blocked"}``, which the report reads. In ``block`` and ``record`` loopback
addresses are left alone; local (Unix) sockets always are, and so is DNS (port 53).

Standard library only, and no syntax newer than Python 3.8: it runs in the
study's Python, whatever version the study asks for. It sees connections made
by Python; a program the script starts (``curl`` in a subprocess) is not
covered, which is why the estimation contract also reads the scripts.
"""

import ipaddress
import json
import os
import socket

_MODE = os.environ.get("E2ER_REPRODUCE_NETWORK", "").strip().lower()
_LOG = os.environ.get("E2ER_REPRODUCE_NETWORK_LOG", "").strip()

MESSAGE = (
    "e2er reproduce: this step may not use the network (it tried to reach {host}). "
    "The estimation must read its data from data.db or files in data/; web data is loaded in the data step "
    "(get_data.py). To let the step reach the web anyway, run `e2er reproduce --allow-network`."
)

_LOCAL = ("localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback")


def _is_local(host):
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    host = str(host).strip("[]").lower()
    if host in _LOCAL or host == "":
        return True
    if host.startswith("127.") or host == "::1" or host == "0.0.0.0":
        return True
    return False


PUBLIC_MESSAGE = (
    "e2er reproduce: a step that loads data again may reach hosts on the internet only (it tried to reach "
    "{host}, which is this computer, the local network or a cloud metadata address)."
)

#: Names that lead to this computer or a cloud's metadata service from inside a container.
_HOST_NAMES = ("host.docker.internal", "gateway.docker.internal", "metadata.google.internal", "metadata")


def _not_public(host):
    """Is ``host`` this computer, the local network or a metadata address (a name or an address literal)?"""
    if host is None:
        return False
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    name = str(host).strip("[]").lower().rstrip(".")
    if name in _LOCAL or name in _HOST_NAMES or name.endswith(".localhost") or name.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(name.split("%", 1)[0])
    except ValueError:
        return False  # a public name; its addresses are checked when the socket connects
    if getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_multicast


def _note(host, port, blocked):
    if not _LOG:
        return
    try:
        with open(_LOG, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"host": str(host), "port": port, "blocked": blocked}) + "\n")
    except OSError:
        pass


def _guard(host, port):
    if _MODE == "public":
        if port == 53 or not _not_public(host):
            return
        _note(host, port, True)
        raise OSError(PUBLIC_MESSAGE.format(host=host))
    if _is_local(host):
        return
    blocked = _MODE == "block"
    _note(host, port, blocked)
    if blocked:
        raise OSError(MESSAGE.format(host=host))


def install():
    if _MODE not in ("block", "record", "public"):
        return
    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    resolved = set()

    def getaddrinfo(host, port, *args, **kwargs):
        _guard(host, port)
        result = real_getaddrinfo(host, port, *args, **kwargs)
        for entry in result:
            try:
                resolved.add(entry[4][0])
            except (IndexError, TypeError):
                pass
        return result

    def _check_address(sock, address):
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            return
        host = address[0] if isinstance(address, tuple) and address else None
        port = address[1] if isinstance(address, tuple) and len(address) > 1 else None
        if host in resolved and _MODE == "record":
            return  # already recorded under its name
        _guard(host, port)

    def connect(self, address):
        _check_address(self, address)
        return real_connect(self, address)

    def connect_ex(self, address):
        _check_address(self, address)
        return real_connect_ex(self, address)

    socket.getaddrinfo = getaddrinfo
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex


install()
