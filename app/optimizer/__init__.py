"""CP-SAT optimizer module.

Per ADR-0002 and ADR-0003 this module is HTTP-unaware. It must not import
from FastAPI, app.routes, or anything that pulls the web stack in. Pure
functions over plain data structures only.
"""
