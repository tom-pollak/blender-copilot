import os
from fasthtml.common import *
from dotenv import load_dotenv

from .auth import init_auth

__all__ = ["app", "rt", "oauth", "static_path"]

load_dotenv()

hdrs = (
    Meta(charset="UTF-8"),
    Meta(
        name="viewport",
        content="width=device-width, initial-scale=1.0, maximum-scale=1.0",
    ),
    Script(src="https://cdn.tailwindcss.com/3.4.16"),
)

static_path = os.path.dirname(os.path.abspath(__file__)) # then /static

app, rt = fast_app(
    debug=True,
    hdrs=hdrs, # tailwind
    default_hdrs=True, # htmx
    static_path=static_path,
    pico=False,
)

oauth = init_auth(app)

serve()
