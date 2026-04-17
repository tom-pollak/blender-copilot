import os
from dotenv import load_dotenv

from loguru import logger
from fasthtml.common import *

from .auth import init_auth

__all__ = ["app", "rt", "oauth", "ROOT_PATH"]

load_dotenv()

DOMAIN = os.getenv("DOMAIN")

hdrs = (
    Meta(charset="UTF-8"),
    Meta(
        name="viewport",
        content="width=device-width, initial-scale=1.0, maximum-scale=1.0",
    ),
    Script(src="https://cdn.tailwindcss.com/3.4.16"), # TODO: change to npm
)

def _not_found(req, exc):
    logger.debug("Hit 404")
    return HTMLResponse(to_xml(Main(
        H1("404", style="margin:30px 0; font-size:4em; line-height:1; letter-spacing:-1px; font-family: Times; font-weight: bold"),
        P(Strong("Page not found :(", style="font-family: Times; font-weight: bold")),
        style="margin:10px auto; max-width:600px; text-align:center"
    )), status_code=404)

def _unauthorized(req, exc):
    logger.debug("Hit 401")
    req.session.clear()
    return HTMLResponse(to_xml(Main(
        H1("401", style="margin:30px 0; font-size:4em; line-height:1; letter-spacing:-1px; font-family: Times; font-weight: bold"),
        P(Strong("Unauthorized :(", style="font-family: Times; font-weight: bold")),
        style="margin:10px auto; max-width:600px; text-align:center"
    )), status_code=401)


ROOT_PATH = os.path.dirname(os.path.abspath(__file__))

app, rt = fast_app(
    debug=os.getenv("DEBUG") == "true",
    hdrs=hdrs, # tailwind
    default_hdrs=True, # htmx
    static_path=os.path.join(ROOT_PATH, "static"),
    exception_handlers={404: _not_found, 401: _unauthorized},
    pico=False,
)

oauth = init_auth(app)

serve()
