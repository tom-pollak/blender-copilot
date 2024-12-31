# fmt: off
import os
import msgpack
import httpx
from dotenv import load_dotenv
from loguru import logger
from PIL import Image
from fasthtml.common import *
from functools import wraps

load_dotenv()

MODAL_API_KEY = os.getenv("MODAL_API_KEY")
if not MODAL_API_KEY:
    raise EnvironmentError("MODAL_API_KEY environment variable is not set")

ENDPOINTS = {
    "sf3d": "https://tom-pollak--stable-fast-3d-model-web-dev.modal.run",
    "flux": "https://tom-pollak--flux-model-web-dev.modal.run",
    "wonder3d": "https://tom-pollak--wonder3d-plus-model-web-dev.modal.run",
}

app, rt = fast_app(pico=True, debug=True)

TEXT_PROMPT = """\
Front-facing 3D Blender render. Well-lit, smooth texture, soft shadows. Clean white background

Style: Show 3D shape of the object. Modern animated movie: {}

3D render, high quality, hyper detailed, rounded forms, video game assets, art station, sharp focus
"""
REQUEST_TIMEOUT = 3 * 60 # 3 minutes

_job_id = 0

def basic_auth(f):
    "Super basic auth for testing purposes"
    @wraps(f)
    async def wrapper(request: Request, *args, **kwargs):
        token = request.headers.get("Authorization")
        if token != "Bearer 1234":
            return Response("Not Authorized",
                            status_code=401,
                            headers={"WWW-Authenticate": "Bearer"})
        return await f(request, *args, **kwargs)

    return wrapper


async def req_modal_endpoint(endpoint: str, timeout: int = REQUEST_TIMEOUT, **post_args) -> Response:
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.post(
                ENDPOINTS[endpoint],
                headers={"Authorization": f"Bearer {MODAL_API_KEY}"},
                timeout=timeout,
                **post_args,
            )

        response.raise_for_status()
        logger.debug(f"Successful response from {endpoint}")
        return Response(response.content,
                        media_type="application/x-msgpack",
                        headers={
                            "X-Processing-Time": str(response.elapsed.total_seconds())
                        })

    except httpx.TimeoutException:
        logger.error(f"Timeout while calling {endpoint}")
        return Response("Request timed out", status_code=504, media_type="text/plain")

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error from {endpoint}: {e}")
        return Response("Bad Gateway", status_code=502, media_type="text/plain")

    except Exception as e:
        logger.error(f"Error calling {endpoint}: {str(e)}")
        return Response("Service temporarily unavailable",
                        status_code=503,
                        media_type="text/plain")

def _formitem(form, k):
    "Return single item `k` from `form` if len 1, otherwise return list"
    if isinstance(form, dict): return form[k]
    o = form.getlist(k)
    return o[0] if len(o) == 1 else o if o else None

def _listreq(k: str, lst: list):
    "Multi-request format: list of tuples"
    return [(k, o) for o in lst]

@rt
@basic_auth
async def image_to_3d(req: Request):
    "Generate 3D model from image"
    form = await parse_form(req)
    if not form.get("images"):
        return Response("No images provided", status_code=400, media_type="text/plain")
    images = _listreq("images", [await image.read() for image in form.getlist("images")])  # type: ignore
    logger.info(f"Length of images: {len(images)}")
    data = {k: _formitem(form, k) for k in form if k != "images"} # type: ignore
    model_name = "wonder3d" if data.pop("model_type", "faster") == "better" else "sf3d"
    logger.info(f"Model name: {model_name}")
    logger.info(f"Data: {data}")
    return await req_modal_endpoint(model_name, files=images, data=data)

@rt
@basic_auth
async def text_to_3d(req: Request):
    "Generate 3D model from text"
    form = await parse_form(req)
    data = form2dict(form)
    prompt = data.get("prompt")
    if not prompt:
        return Response("No prompt provided", status_code=400, media_type="text/plain")
    data["prompt"] = TEXT_PROMPT.format(prompt)
    if not data.get("batch_size"): data["batch_size"] = 1
    if int(data["batch_size"]) < 1:
        return Response("Batch size must be greater than 0", status_code=400, media_type="text/plain")
    logger.info(f"Data: {data}")
    response = await req_modal_endpoint("flux", json=data)
    if response.status_code != 200: return response
    if not response.body:
        return Response("No images returned", status_code=500, media_type="text/plain")
    images = msgpack.unpackb(response.body)

    global _job_id
    for i, image in enumerate(images):
        Image.open(io.BytesIO(image)).save(f"./output/image_{_job_id}_{i}.png")
    _job_id += 1

    logger.info(f"Length of images: {len(images)}")
    return await req_modal_endpoint("sf3d", files=_listreq("images", images), data=data)


serve()
