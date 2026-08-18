"""WSGI entry point for production servers."""

from alt_web01 import create_app

app = create_app()

