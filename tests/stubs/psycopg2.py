"""Stub psycopg2: no Postgres in tests, so callers fall through to the SQLite path."""


class Error(Exception):
    pass


def connect(**kwargs):
    raise Error("stub psycopg2: no postgres in tests")
