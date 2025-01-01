import os
import msgpack
import io
from PIL import Image
from typing import Annotated, Literal
import modal
from fastapi import (
    Response,
    Form,
    Depends,
    HTTPException,
    status,
    Request,
    File,
    UploadFile,
)
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, ValidationError

cuda_version = "12.1.0"  # no greater than host CUDA version
flavor = "devel"  # full CUDA toolkit
operating_sys = "ubuntu22.04"
tag = f"{cuda_version}-{flavor}-{operating_sys}"

cuda_dev_image = modal.Image.from_registry(
    f"nvidia/cuda:{tag}", add_python="3.11"
).entrypoint([])

image = (
    cuda_dev_image.pip_install(
        "wheel",
        "fastapi[standard]==0.115.6",
        "pydantic==2.10.4",
        "msgpack",
        "pillow",
    )
)

auth_scheme = HTTPBearer()
app = modal.App("mock", image=image)


class GenerationConfig(BaseModel):
    default_literal: Literal["ortho", "persp"] = "ortho"
    default_int: int = 2
    default_seed: int = 42
    default_float: float = 2.5
    default_list: list[int] = [1, 2, 3]

@app.cls(
    gpu="A10G",
    container_idle_timeout=10 * 60,
    timeout=10 * 60,
    secrets=[
        modal.Secret.from_name("blender-api-token"),
    ],
)
class Model:
    @modal.enter()
    def enter(self):
        pass

    @modal.method()
    def inference(self, image: Image.Image) -> bytes:
        return b"test"

    @modal.web_endpoint(method="POST", docs=True)
    async def web(
        self,
        request: Request,
        token: Annotated[HTTPAuthorizationCredentials, Depends(auth_scheme)],
        images: Annotated[list[UploadFile], File()],
        config: Annotated[str, Form()] # type: ignore

    ):
        """Generate 3D models from uploaded images"""
        if token.credentials != os.environ["API_TOKEN"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            config: GenerationConfig = GenerationConfig.model_validate_json(config)
        except ValidationError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid config: {str(e)}"
            )

        pil_images = []
        for img_file in images:
            try:
                img_data = await img_file.read()
                image = Image.open(io.BytesIO(img_data))
                pil_images.append(image)
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid image in upload: {str(e)}"
                )

        if not pil_images:
            raise HTTPException(
                status_code=400,
                detail="No valid images provided"
            )

        try:
            mesh_bytes = [self.inference.remote(image=pil_image) for pil_image in pil_images]
            return Response(
                content=msgpack.packb(mesh_bytes),
                media_type="application/x-msgpack"
            )

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Generation failed: {str(e)}"
            )



@app.local_entrypoint()
def main(image_path: str):
    image = Image.open(image_path)
    out = Model().inference.remote(image)
    print(out)
