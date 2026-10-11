"""Server layer — FastAPI app, advisory service and agent invoker.

The FastAPI app in :mod:`server.app` is a thin HTTP shell. Domain routes live in
:mod:`server.routes`; :mod:`server.advisory` runs the agents and has no web
dependency, so it is unit-testable without FastAPI. Submodules are imported
directly (``from server.app import app``) so that importing this package does
not pull in google-adk.
"""
