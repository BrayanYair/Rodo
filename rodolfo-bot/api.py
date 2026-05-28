"""Compatibility entrypoint for the Rodo HTTP API.

The implementation lives in api_runtime/* so the server can grow by feature
area instead of accumulating every route in this file.
"""

from api_runtime.server import start_http

