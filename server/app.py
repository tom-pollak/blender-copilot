import os
from fasthtml.common import *
from dotenv import load_dotenv

from .auth import init_auth

load_dotenv()

hdrs = (
    Meta(charset="UTF-8"),
    Meta(
        name="viewport",
        content="width=device-width, initial-scale=1.0, maximum-scale=1.0",
    ),
    Script(src="https://cdn.tailwindcss.com/3.4.16"),
)

static_path = os.path.join(os.path.dirname(__file__), "static")

app, rt = fast_app(debug=True, hdrs=hdrs, default_hdrs=False, static_path=static_path)
auth = init_auth(app)

serve()
