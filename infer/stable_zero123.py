import os
from PIL import Image

from pydantic import BaseModel, Field
import torch
import modal
import numpy as np

from fastapi.security import HTTPBearer

from infer.utils import remove_background, resize_foreground

cuda_version = "12.4.0" # no greater than host CUDA version
flavor = "devel" # full CUDA toolkit
operating_sys = "ubuntu22.04"
tag = f"{cuda_version}-{flavor}-{operating_sys}"

cuda_image = modal.Image.from_registry(
    f"nvidia/cuda:{tag}", add_python="3.11"
).entrypoint([])

threestudio_commit = "28d9d80d9d00f308244adfcf3be8b17ca0cb6465"

image = (
    cuda_image.apt_install("git", "build-essential", "clang", "ninja-build")
    .pip_install("pip==23.0.1")  # Downgrade pip
    .pip_install(
        "torch==2.5.1",
        "torchvision==0.15.2",
        "omegaconf==2.3.0",
        "pytorch-lightning==2.5.0",
        "numpy<2",
        "pydantic==2.10.4",
        "fastapi[standard]",
    )
    .env({
        "TCNN_CUDA_ARCHITECTURES": "70;75;80;86"
    })
    .run_commands(
        "git clone https://github.com/threestudio-project/threestudio.git",
        f"cd threestudio && git checkout {threestudio_commit}",
        "cd threestudio && pip install -r requirements.txt"
    )
    .env({
        "PYTHONPATH": "/threestudio",
        "HF_HUB_ENABLE_HF_TRANSFER": "1",
    })
)

class GenerationConfig(BaseModel):
    "Can change this however you want..."
    model_config = {
        "extra": "forbid"
    }
    height: int = 256
    width: int = 256
    num_inference_steps: int = 50
    guidance_scale: float = 3.0
    elevation_deg: float = Field(default=5.0, ge=-90, le=90)
    azimuth_deg: float = Field(default=0.0, ge=-180, le=180)
    camera_distance: float = 3.8
    foreground_ratio: float = Field(default=0.85, ge=0, le=1)

MINUTES = 60  # seconds

auth_scheme = HTTPBearer()
app = modal.App("stable-zero123", image=image)

with image.imports():
    from omegaconf import OmegaConf # type: ignore
    import rembg # type: ignore
    import torchvision.transforms.functional as TF # type: ignore
    import pytorch_lightning as pl # type: ignore
    import huggingface_hub # type: ignore
    from threestudio.systems.zero123 import Zero123System # type: ignore


@app.cls(
    gpu="A10G",
    container_idle_timeout=20 * MINUTES,
    timeout=20 * MINUTES,
    secrets=[modal.Secret.from_name("huggingface-token"),
             modal.Secret.from_name("blender-api-token")],
)
class Model:
    def __init__(self):
        self.device = "cuda"

    def setup_model(self):
        huggingface_hub.login(token=os.environ["HUGGINGFACE_TOKEN"])
        huggingface_hub.hf_hub_download(
            repo_id="stabilityai/stable-zero123",
            filename="stable_zero123.ckpt",
            local_dir="/threestudio/load/zero123/stable_zero123.ckpt",
            local_dir_use_symlinks=False
        )
        config = OmegaConf.load("/threestudio/configs/stable-zero123.yaml")
        rembg_session = rembg.new_session()

        # return stuff...


    @modal.enter()
    def enter(self):
        self.setup_model() # set stuff...

    def preprocess_image(self, image: Image.Image, config: GenerationConfig) -> torch.Tensor:
        image = image.convert("RGBA")
        image = remove_background(image, self.rembg_session)
        image = resize_foreground(image, config.foreground_ratio)
        image = image.resize((config.width, config.height))
        image_np = np.array(image).astype(np.float32) / 255.0
        rgb = image_np[..., :3] * image_np[..., 3:] + (1 - image_np[..., 3:])
        return torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).to(self.device)

    @modal.method()
    def inference(
        self,
        image: list[Image.Image],
        config: GenerationConfig
    ) -> list[bytes]:
        raise NotImplementedError

@app.local_entrypoint()
def main(image_path: str):
    image = Image.open(image_path)
    model = Model()
    output_bytes = model.inference.remote([image], GenerationConfig())
