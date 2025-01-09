import os
from dotenv import load_dotenv

from fasthtml.common import *

from .auth import init_auth

__all__ = ["app", "rt", "oauth", "ROOT_PATH"]

load_dotenv()

hdrs = (
    Meta(charset="UTF-8"),
    Meta(
        name="viewport",
        content="width=device-width, initial-scale=1.0, maximum-scale=1.0",
    ),
    Script(src="https://cdn.tailwindcss.com/3.4.16"),
)

def _not_found(req, exc):
    return Container(
        H1("404", style="margin:30px 0; font-size:4em; line-height:1; letter-spacing:-1px; font-family: Times; font-weight: bold"),
        P(Strong("Page not found :(", style="font-family: Times; font-weight: bold")),
        style="margin:10px auto; max-width:600px; text-align:center"
    )


ROOT_PATH = os.path.dirname(os.path.abspath(__file__))

app, rt = fast_app(
    debug=True,
    hdrs=hdrs, # tailwind
    default_hdrs=True, # htmx
    static_path=os.path.join(ROOT_PATH, "static"),
    exception_handlers={404: _not_found},
    pico=False,
)

oauth = init_auth(app)

serve()
