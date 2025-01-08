from fasthtml.common import fast_app, serve
from server.auth import init_auth
from dotenv import load_dotenv

load_dotenv()

app, rt = fast_app(pico=True, debug=True)
auth = init_auth(app)


serve()
