# fmt: off
import math
import os
from PIL import Image
from pydantic import BaseModel, Field
import numpy as np
import torch
import torch.nn.functional as F

import modal

from fastapi.security import HTTPBearer

from infer.utils import remove_background, resize_foreground

cuda_version = "12.4.0"  # no greater than host CUDA version
flavor = "devel"  # full CUDA toolkit
operating_sys = "ubuntu22.04"
tag = f"{cuda_version}-{flavor}-{operating_sys}"

cuda_image = modal.Image.from_registry(
    f"nvidia/cuda:{tag}", add_python="3.11"
).entrypoint([])

threestudio_commit = "28d9d80d9d00f308244adfcf3be8b17ca0cb6465"

image = (
    cuda_image.apt_install(
        "git",
        "build-essential",
        "clang",
        "ninja-build",
        "libomp-dev",
        "libgl1",
    )
    .pip_install("pip==23.0.1")  # Downgrade pip
    .pip_install(
        "wheel",
        "torch==2.5.1",
        "omegaconf==2.3.0",
        "pytorch-lightning==2.5.0",
        "numpy<2",
        "pydantic==2.10.4",
        "fastapi[standard]",
    )
    .env({
            "TCNN_CUDA_ARCHITECTURES": "70;75;80;86",
            "TORCH_CUDA_ARCH_LIST": "7.0;7.5;8.0;8.6",
    })
    .run_commands(
        "git clone https://github.com/threestudio-project/threestudio.git",
        f"cd threestudio && git checkout {threestudio_commit}",
        "cd threestudio && pip install -r requirements.txt",
    )
    .env({
            "PYTHONPATH": "/threestudio",
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
    })
    .apt_install(
        "libglib2.0-0",
        "libsm6",
        "libxext6",
    )
    .pip_install("fastapi==0.115.6", "rembg[gpu]==2.0.57", "msgpack==1.1.0")
    .pip_install(
        "accelerate==0.19.0",
        "diffusers==0.19.3",
        "huggingface_hub[hf_transfer]==0.19.4",
        "hf_transfer"
    )
    .pip_install("mediapipe==0.10.20")
)

class CameraConfig(BaseModel):
    elevation_deg: float = 5
    azimuth_deg: float = -180
    camera_distance: float = 3.8
    fovy_deg: float = 20
    height_width_ratio: int = 1

class GenerationConfig(CameraConfig):
    width: int = 256
    height: int = 256
    foreground_ratio: float = 0.85 # rembg



MINUTES = 60  # seconds

auth_scheme = HTTPBearer()
app = modal.App("stable-zero123", image=image)

with image.imports():
    import rembg  # type: ignore
    from threestudio.systems.zero123 import Zero123  # type: ignore
    from threestudio.utils.ops import ( # type: ignore
        get_mvp_matrix,
        get_projection_matrix,
        get_ray_directions,
        get_rays,
    )



@app.cls(
    gpu="A10G",
    container_idle_timeout=20 * MINUTES,
    timeout=20 * MINUTES,
    secrets=[
        modal.Secret.from_name("huggingface-token"),
        modal.Secret.from_name("blender-api-token"),
    ],
)
class Model:
    def __init__(self):
        self.device = "cuda"

    def setup_model(self):
        import huggingface_hub  # type: ignore
        from omegaconf import OmegaConf  # type: ignore

        config = OmegaConf.load("/threestudio/configs/stable-zero123.yaml")
        config = OmegaConf.create(OmegaConf.to_container(config, resolve=True))

        system = Zero123(config.system)

        huggingface_hub.login(token=os.environ["HUGGINGFACE_TOKEN"])
        checkpoint_path = huggingface_hub.hf_hub_download(
            repo_id="stabilityai/stable-zero123",
            filename="stable_zero123.ckpt",
            local_dir="/threestudio/load/zero123/",
            local_dir_use_symlinks=False,
        )
        system.load_weights(checkpoint_path)
        system.to(self.device).eval()

        rembg_session = rembg.new_session()

        return system, rembg_session

    @modal.enter()
    def enter(self):
        self.config = CameraConfig()
        self.system, self.rembg_session = self.setup_model()

    def get_camera_params(self, config: GenerationConfig) -> dict:
        # Convert angles to radians - add batch dim [1]
        elevation = torch.tensor([config.elevation_deg * math.pi / 180])
        azimuth = torch.tensor([config.azimuth_deg * math.pi / 180])
        fovy = torch.tensor([config.fovy_deg * math.pi / 180])  # [1]

        # Calculate camera position from spherical coordinates - with batch dim [1,3]
        camera_position = torch.stack([
            config.camera_distance * torch.cos(elevation) * torch.cos(azimuth),
            config.camera_distance * torch.cos(elevation) * torch.sin(azimuth),
            config.camera_distance * torch.sin(elevation),
        ], dim=-1)  # [1, 3]

        # Setup coordinate frame
        center = torch.zeros_like(camera_position)  # [1, 3]
        up = torch.as_tensor([[0, 0, 1]], dtype=torch.float32)  # [1, 3]

        # Get lookat direction and construct coordinate frame
        lookat = F.normalize(center - camera_position, dim=-1)
        right = F.normalize(torch.cross(lookat, up), dim=-1)
        up = F.normalize(torch.cross(right, lookat), dim=-1)

        # Construct camera-to-world matrix like reference: [1, 3, 4]
        c2w = torch.cat([
            torch.stack([right, up, -lookat], dim=-1),
            camera_position[..., None]
        ], dim=-1)

        # Construct 4x4 matrix: [1, 4, 4]
        c2w4x4 = torch.zeros(1, 4, 4)
        c2w4x4[:, :3] = c2w
        c2w4x4[:, 3, 3] = 1.0

        # Get directions using reference approach
        directions_unit_focal = get_ray_directions(H=config.height, W=config.width, focal=1.0)
        focal_length = 0.5 * config.height / torch.tan(0.5 * fovy)

        # Scale directions
        directions = directions_unit_focal[None]  # [1, H, W, 3]
        directions[..., :2] = directions[..., :2] / focal_length

        # Get rays
        rays_o, rays_d = get_rays(
            directions,
            c2w,
            keepdim=True,
            noise_scale=2e-3,
            normalize=True
        )

        # Get MVP matrix - note fovy has batch dim now
        proj_mtx = get_projection_matrix(fovy, config.width/config.height, 0.1, 100.0)
        mvp_mtx = get_mvp_matrix(c2w4x4, proj_mtx)

        return {
            "rays_o": rays_o.to(self.device).clone(),  # [1, H, W, 3]
            "rays_d": rays_d.to(self.device).clone(),  # [1, H, W, 3]
            "mvp_mtx": mvp_mtx.to(self.device).clone(),  # [1, 4, 4]
            "camera_positions": camera_position.to(self.device),  # [1, 3]
            "light_positions": camera_position.to(self.device),  # [1, 3]
            "elevation": torch.tensor([config.elevation_deg]).to(self.device),  # [1]
            "azimuth": torch.tensor([config.azimuth_deg]).to(self.device),  # [1]
            "camera_distances": torch.tensor([config.camera_distance]).to(self.device),  # [1]
            "fovy": fovy.to(self.device),  # [1]
            "height": config.height,
            "width": config.width,
            "c2w": c2w4x4.to(self.device),  # [1, 4, 4]
        }

    def preprocess_image(
        self, image: Image.Image, config: GenerationConfig
    ) -> tuple[torch.Tensor, torch.Tensor]:
        image = image.convert("RGBA")
        image = remove_background(image, self.rembg_session)
        image = resize_foreground(image, config.foreground_ratio)
        image = image.resize((config.width, config.height))
        image_np = np.array(image).astype(np.float32) / 255.0
        rgb = image_np[..., :3]
        tensor = torch.from_numpy(rgb).contiguous()
        mask = torch.from_numpy(image_np[..., 3:] > 0.5)
        return tensor, mask

    @modal.method()
    @torch.no_grad()
    def inference(
        self, images: list[Image.Image], config: GenerationConfig
    ) -> list[bytes]:
        camera_params = self.get_camera_params(config)
        rgbs, masks = zip(*(self.preprocess_image(image, config) for image in images))
        batch = {
            "rgb": torch.stack(rgbs).to(self.device),  # [B, H, W, 3]
            "mask": torch.stack(masks).to(self.device),  # [B, H, W, 1]
            **camera_params
        }
        output = self.system(batch)
        # dict_keys(['comp_rgb', 'comp_rgb_fg', 'comp_rgb_bg', 'opacity', 'depth', 'z_variance', 'comp_normal'])
        print(output.keys())
        raise NotImplementedError()



@app.local_entrypoint()
def main(image_path: str):
    image = Image.open(image_path)
    model = Model()
    output_bytes = model.inference.remote([image], GenerationConfig())
