"""Application factory for alt_web01."""

from flask import Flask


def create_app() -> Flask:
    """Create and configure the Flask application.

    Returns:
        Flask: A configured Flask application instance.
    """
    app = Flask(__name__)

    from alt_web01.views import pages

    app.register_blueprint(pages)
    return app

