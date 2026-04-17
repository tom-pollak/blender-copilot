# fmt: off
import os
import io
import time
from typing import Literal
from pathlib import Path
from pydantic_core import ValidationError
from typing_extensions import Annotated
from PIL import Image
from io import BytesIO

from pydantic import BaseModel, Field

from tqdm import tqdm
import torch
import modal

from fastapi import Response, Body, Depends, HTTPException, status, Request, File, UploadFile, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import msgpack

# from infer.utils import remove_background, resize_foreground

from PIL import Image
from PIL.Image import Image as ImageT
import numpy as np
from typing import Any


def remove_background(
    image: ImageT,
    rembg_session: Any = None,
    force: bool = False,
    **rembg_kwargs,
) -> ImageT:
    import rembg # type: ignore
    do_remove = True
    if image.mode == "RGBA" and image.getextrema()[3][0] < 255: # type: ignore
        do_remove = False
    do_remove = do_remove or force
    if do_remove:
        image = rembg.remove(image, session=rembg_session, **rembg_kwargs) # type: ignore
    return image


def resize_foreground(
    image: ImageT,
    ratio: float,
) -> ImageT:
    image_np = np.array(image)
    assert image_np.shape[-1] == 4
    alpha = np.where(image_np[..., 3] > 0.5)
    y1, y2, x1, x2 = (
        alpha[0].min(),
        alpha[0].max(),
        alpha[1].min(),
        alpha[1].max(),
    )
    # crop the foreground
    fg = image_np[y1:y2, x1:x2]
    # pad to square
    size = max(fg.shape[0], fg.shape[1])
    ph0, pw0 = (size - fg.shape[0]) // 2, (size - fg.shape[1]) // 2
    ph1, pw1 = size - fg.shape[0] - ph0, size - fg.shape[1] - pw0
    new_image = np.pad(
        fg,
        ((ph0, ph1), (pw0, pw1), (0, 0)),
        mode="constant",
        constant_values=((0, 0), (0, 0), (0, 0)),
    )

    # compute padding according to the ratio
    new_size = int(new_image.shape[0] / ratio)
    # pad to size, double side
    ph0, pw0 = (new_size - size) // 2, (new_size - size) // 2
    ph1, pw1 = new_size - size - ph0, new_size - size - pw0
    new_image = np.pad(
        new_image,
        ((ph0, ph1), (pw0, pw1), (0, 0)),
        mode="constant",
        constant_values=((0, 0), (0, 0), (0, 0)),
    )
    new_image = Image.fromarray(new_image, mode="RGBA")
    return new_image


cuda_version = "12.4.0" # more stable version
flavor = "devel" # full CUDA toolkit
operating_sys = "ubuntu22.04"
tag = f"{cuda_version}-{flavor}-{operating_sys}"

cuda_dev_image = modal.Image.from_registry(
    f"nvidia/cuda:{tag}", add_python="3.11"
).entrypoint([])

stable_fast3d_commit_sha = "2b35658e6fa41df4171f15d8696102c62845f16a"

image = (
    cuda_dev_image.apt_install(
        "git",
        "build-essential",
        "ninja-build",
        "libgl1",
        "ffmpeg",
        "clang",
        "g++",
    )
    .pip_install(
        "setuptools==69.5.1",
        "wheel",
        "huggingface_hub[hf_transfer]==0.26.2",
        "torch==2.5.1",
        "numpy<2",
        "pydantic==2.10.4",
        "fastapi[standard]",
        "msgpack==1.1.0",
    )
    .env({
        # For texture baker
        "USE_CUDA": "1",
        "TORCH_CUDA_ARCH_LIST": "7.0;7.5;8.0;8.6",
    })
    .run_commands("git clone https://github.com/Stability-AI/stable-fast-3d.git stable-fast-3d")
    .workdir("/stable-fast-3d")
    .run_commands(f"git checkout {stable_fast3d_commit_sha}")
    .run_commands("pip install -r requirements.txt")
    .workdir("/")
    .env({
        "PYTHONPATH": "/stable-fast-3d",
        "HF_HUB_ENABLE_HF_TRANSFER": "1",
    })
)

with image.imports():
    from sf3d.system import SF3D # type: ignore
    import rembg # type: ignore

MINUTES = 60  # seconds

auth_scheme = HTTPBearer()
model_cache = modal.Volume.from_name("stable-fast-3d-model-cache", create_if_missing=True)
app = modal.App("stable-fast-3d", image=image)


class GenerationConfig(BaseModel):
    # model_config = {
    #     "extra": "forbid"
    # }
    texture_resolution: Literal[1024, 2048, 4096] = 1024
    remesh_option: Literal["none", "triangle", "quad"] = "triangle"
    target_vertex_count: int = -1
    foreground_ratio: float = Field(default=0.85, ge=0, le=1)
    batch_size: int = 1


@app.cls(
    gpu="A100",
    scaledown_window=20 * MINUTES,
    timeout=20 * MINUTES,
    secrets=[modal.Secret.from_name("huggingface-token"),
             modal.Secret.from_name("blender-api-token")],
    volumes={"/models": model_cache},
    keep_warm=1,
)
class Model:
    def setup_model(self):
        import os
        import huggingface_hub # type: ignore
        from pathlib import Path

        # Check if model is already cached
        cache_dir = Path("/models/stable-fast-3d")
        if cache_dir.exists() and any(cache_dir.iterdir()):
            print("Loading model from cache...")
            model = SF3D.from_pretrained(
                str(cache_dir),
                config_name="config.yaml",
                weight_name="model.safetensors",
            ).eval()
        else:
            print("Downloading model to cache...")
            huggingface_hub.login(token=os.environ["HUGGINGFACE_TOKEN"])
            huggingface_hub.snapshot_download(
                "stabilityai/stable-fast-3d",
                local_dir=str(cache_dir),
                local_dir_use_symlinks=False,
                allow_patterns=["config.yaml", "model.safetensors"],
            )
            model_cache.commit()
            model = SF3D.from_pretrained(
                str(cache_dir),
                config_name="config.yaml",
                weight_name="model.safetensors",
            ).eval()

        rembg_session = rembg.new_session()
        return model, rembg_session

    @modal.enter()
    def enter(self):
        import platform, torch
        print("🐍", platform.platform())
        print("Torch:", torch.__version__, "CUDA:", torch.version.cuda)
        print("CUDA avail:", torch.cuda.is_available())
        model_cache.reload()  # Get latest cached model
        model, rembg_session = self.setup_model()
        self.model = model.to("cuda")
        self.rembg_session = rembg_session

    def preprocess_image(self, image: Image.Image, config: GenerationConfig) -> Image.Image:
        image = remove_background(image.convert("RGBA"), self.rembg_session)
        image = resize_foreground(image, config.foreground_ratio)
        return image

    # @modal.method()
    def inference(self, images: list[Image.Image], config: GenerationConfig) -> list[bytes]:
        images = [self.preprocess_image(image, config) for image in images]

        mesh_bytes = []
        for i in tqdm(range(0, len(images), config.batch_size)):
            image_batch = images[i : i + config.batch_size]
            torch.cuda.reset_peak_memory_stats()
            with torch.no_grad(), torch.autocast(device_type="cuda", dtype=torch.float16):
                meshes, _ = self.model.run_image(
                    image_batch,
                    bake_resolution=config.texture_resolution,
                    remesh=config.remesh_option,
                    vertex_count=config.target_vertex_count,
                )
            print("🔦 Peak Memory:", torch.cuda.max_memory_allocated() / 1024**2, "MB")

            if not isinstance(meshes, list):
                meshes = [meshes]

            for mesh in meshes:
                byte_stream = BytesIO()
                mesh.export(byte_stream, file_type='glb', include_normals=True)
                mesh_bytes.append(byte_stream.getvalue())

        return mesh_bytes


    @modal.fastapi_endpoint(method="POST", docs=True)
    async def web(
        self,
        request: Request,
        token: Annotated[HTTPAuthorizationCredentials, Depends(auth_scheme)],
        images: Annotated[list[UploadFile], File()],
        config: Annotated[str, Form()] # type: ignore
    ):
        """Generate 3D models from uploaded images"""
        # if token.credentials != os.environ["API_TOKEN"]:
        #     raise HTTPException(
        #         status_code=status.HTTP_401_UNAUTHORIZED,
        #         detail="Invalid authentication token",
        #         headers={"WWW-Authenticate": "Bearer"},
        #     )


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
            config: GenerationConfig = GenerationConfig.model_validate_json(config)
        except ValidationError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid config: {str(e)}"
            )

        try:
            mesh_bytes = self.inference(
                images=pil_images,
                config=config,
            )
            return Response(
                content=msgpack.packb(mesh_bytes),
                media_type="application/x-msgpack"
            )

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Generation failed: {str(e)}"
            )

@app.function(secrets=[modal.Secret.from_name("blender-api-token")])
@modal.fastapi_endpoint(method="GET")
async def healthcheck(
    request: Request,
    token: HTTPAuthorizationCredentials = Depends(auth_scheme),
):
    """Simple healthcheck endpoint"""
    # if token.credentials != os.environ["API_TOKEN"]:
    #     raise HTTPException(
    #         status_code=status.HTTP_401_UNAUTHORIZED,
    #         detail="Invalid authentication token",
    #         headers={"WWW-Authenticate": "Bearer"},
    #     )
    return {"status": "healthy"}

@app.local_entrypoint()
def main(image_path: str):
    t0 = time.time()
    image = Image.open(image_path)
    meshes_bytes = Model().inference.remote([image], config=GenerationConfig())
    print(f"🎨 inference latency: {time.time() - t0:.2f} seconds")
    output_dir = Path("/tmp") / "stable-fast-3d"
    output_dir.mkdir(exist_ok=True, parents=True)
    print(f"🎨 saving output to {output_dir}")
    for i, mesh_bytes in enumerate(meshes_bytes):
        (output_dir / f"output_{i}.glb").write_bytes(mesh_bytes)


if __name__ == "__main__":
    app.run()
