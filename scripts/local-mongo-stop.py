"""Request MongoDB shutdown only on the managed loopback ports."""

import sys

from pymongo import MongoClient
from pymongo.errors import AutoReconnect

port = int(sys.argv[1])
if port not in {27118, 27119}:
    raise SystemExit("Unexpected local MongoDB port")

with MongoClient("127.0.0.1", port, directConnection=True, serverSelectionTimeoutMS=2000) as client:
    client.admin.command("ping")
    try:
        client.admin.command("shutdown", timeoutSecs=10)
    except AutoReconnect:
        pass  # MongoDB closes the connection while shutting down.
