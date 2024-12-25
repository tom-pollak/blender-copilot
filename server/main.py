from fasthtml.common import *
from functools import wraps

app, rt = fast_app(pico=True)

def basic_auth(f):
    @wraps(f)
    async def wrapper(request: Request, *args, **kwargs):
        token = request.headers.get("Authorization")
        if token != "1234":
            return Response("Not Authorized", status_code=401)
        return await f(request, *args, **kwargs)
    return wrapper


@rt
@basic_auth
def image_to_3d(request: Request):
    pass

# @rt
# def index():
#     return Div(Button("Image to 3D", hx_get="/image_to_3d", hx_target="#dest"), id="dest")

serve()
