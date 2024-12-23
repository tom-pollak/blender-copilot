# ruff: noqa
# type: ignore
# fmt: off

import os
import io
import time
from typing import Literal
from pathlib import Path
from PIL import Image
from io import BytesIO

from pydantic import BaseModel, Field

from tqdm import tqdm
import torch
import modal

from fastapi import Body, Depends, HTTPException, status, Request, File, UploadFile
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import Response
import msgpack

cuda_version = "12.4.0" # no greater than host CUDA version
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
    .run_commands(f"git clone https://github.com/Stability-AI/stable-fast-3d.git stable-fast-3d")
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
    from sf3d.system import SF3D
    from sf3d.utils import remove_background, resize_foreground
    import rembg

MINUTES = 60  # seconds

auth_scheme = HTTPBearer()
app = modal.App("stable-fast-3d", image=image)


class GenerationConfig(BaseModel):
    model_config = {
        "extra": "forbid"
    }
    texture_resolution: Literal[1024, 2048, 4096] = 1024
    remesh_option: Literal["none", "triangle", "quad"] = "triangle"
    target_vertex_count: int = -1
    foreground_ratio: float = Field(default=0.85, ge=0, le=1)
    batch_size: int = 1


@app.cls(
    gpu="A10G",
    container_idle_timeout=20 * MINUTES,
    timeout=20 * MINUTES,
    secrets=[modal.Secret.from_name("huggingface-token"),
             modal.Secret.from_name("api-token")],
)
class Model:
    def setup_model(self):
        import os
        import huggingface_hub
        huggingface_hub.login(token=os.environ["HUGGINGFACE_TOKEN"])

        model = SF3D.from_pretrained(
            "stabilityai/stable-fast-3d",
            config_name="config.yaml",
            weight_name="model.safetensors",
        ).eval()
        rembg_session = rembg.new_session()
        return model, rembg_session

    @modal.build()
    def build(self):
        self.setup_model()

    @modal.enter()
    def enter(self):
        model, rembg_session = self.setup_model()
        self.model = model.to("cuda")
        self.rembg_session = rembg_session

    def preprocess_image(self, image: Image.Image, config: GenerationConfig) -> Image.Image:
        image = remove_background(image.convert("RGBA"), self.rembg_session)
        image = resize_foreground(image, config.foreground_ratio)
        return image

    @modal.method()
    def generate(self, images: list[Image.Image], config: GenerationConfig) -> list[bytes]:
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
            print("🔦 Peak Memory:", torch.cuda.max_memory_allocated() / 1024 / 1024, "MB")

            if type(meshes) != list:
                meshes = [meshes]

            for mesh in meshes:
                byte_stream = BytesIO()
                mesh.export(byte_stream, file_type='glb', include_normals=True)
                mesh_bytes.append(byte_stream.getvalue())

        return mesh_bytes


    @modal.web_endpoint(method="POST")
    async def generate_3d(
        self,
        request: Request,
        token: HTTPAuthorizationCredentials = Depends(auth_scheme),
        images: list[UploadFile] = File(...),
        config: dict = Body(default={}),
    ):
        """Generate 3D models from uploaded images"""
        if token.credentials != os.environ["API_TOKEN"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Convert dict to GenerationConfig
        try:
            generation_config = GenerationConfig(**config)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid generation config: {str(e)}"
            )

        pil_images = []
        if isinstance(images, UploadFile):
            images = [images]
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
            mesh_bytes = self.generate.remote(
                images=pil_images,
                config=generation_config
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

@app.function(secrets=[modal.Secret.from_name("api-token")])
@modal.web_endpoint(method="GET")
async def healthcheck(
    request: Request,
    token: HTTPAuthorizationCredentials = Depends(auth_scheme),
):
    """Simple healthcheck endpoint"""
    if token.credentials != os.environ["API_TOKEN"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"status": "healthy"}

@app.local_entrypoint()
def main(image_path: str):
    t0 = time.time()
    image = Image.open(image_path)
    meshes_bytes = Model().generate.remote([image], config=GenerationConfig())
    print(f"🎨 inference latency: {time.time() - t0:.2f} seconds")
    output_dir = Path("/tmp") / "stable-fast-3d"
    output_dir.mkdir(exist_ok=True, parents=True)
    print(f"🎨 saving output to {output_dir}")
    for i, mesh_bytes in enumerate(meshes_bytes):
        (output_dir / f"output_{i}.glb").write_bytes(mesh_bytes)


if __name__ == "__main__":
    app.run()
