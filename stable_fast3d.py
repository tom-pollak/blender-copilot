# ruff: noqa
# type: ignore
# fmt: off

from typing import Literal
from dataclasses import dataclass
from pathlib import Path
from PIL import Image
from io import BytesIO

from tqdm import tqdm
import modal


cuda_version = "12.4.0"  # should be no greater than host CUDA version
flavor = "devel"  # includes full CUDA toolkit
operating_sys = "ubuntu22.04"
tag = f"{cuda_version}-{flavor}-{operating_sys}"

cuda_dev_image = modal.Image.from_registry(
    f"nvidia/cuda:{tag}", add_python="3.11"
).entrypoint([])

image = (
    cuda_dev_image.apt_install(
        "git",
        "libglib2.0-0",
        "libsm6",
        "libxrender1",
        "libxext6",
        "ffmpeg",
        "libgl1",
        "build-essential",
        "g++",
        "ninja-build",
    )
    .pip_install(
        "huggingface_hub[hf_transfer]==0.26.2",
        "setuptools==69.5.1",
        "wheel",
        "torch==2.5.1",
    )
    .run_commands("git clone https://github.com/Stability-AI/stable-fast-3d.git stable-fast-3d")
    .workdir("/stable-fast-3d")
    .run_commands("pip install -r requirements.txt")
    .run_commands("pip install .")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)

app = modal.App("stable-fast-3d", image=image)

with image.imports():
    import torch
    from sf3d.system import SF3D
    from sf3d.utils import remove_background, resize_foreground


MINUTES = 60  # seconds

@dataclass
class Config:
    texture_resolution: int = 1024
    remesh_option: Literal["none", "triangle", "quad"] = "triangle"
    target_vertex_count: int = -1
    foreground_ratio: float = 0.85
    batch_size: int = 1

@app.cls(
    gpu="H100",  # fastest GPU on Modal
    container_idle_timeout=20 * MINUTES,
    timeout=60 * MINUTES,  # leave plenty of time for compilation
)
class Model:
    def setup_model(self):
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

    def preprocess_image(self, image: Image.Image, config: Config) -> Image.Image:
        image = remove_background(image.convert("RGBA"), self.rembg_session)
        image = resize_foreground(image, config.foreground_ratio)
        return image

    @modal.method()
    def inference(self, images: list[Image.Image], **cfg_kwargs):
        config = Config(**cfg_kwargs)
        images = [self.preprocess_image(image, config) for image in images]

        mesh_bytes = []
        for i in tqdm(range(0, len(images), config.batch_size)):
            image_batch = images[i : i + config.batch_size]
            torch.cuda.reset_peak_memory_stats()
            with torch.no_grad():
                with torch.autocast(
                    device_type="cuda", dtype=torch.float16
                ):
                    meshes, _ = self.model.run_image(
                        image_batch,
                        bake_resolution=config.texture_resolution,
                        remesh=config.remesh_option,
                        vertex_count=config.target_vertex_count,
                    )
            print("🔦 Peak Memory:", torch.cuda.max_memory_allocated() / 1024 / 1024, "MB")

            if len(meshes) == 1:
                meshes = [meshes]

            for mesh in meshes:
                byte_stream = BytesIO()
                mesh.export(byte_stream, file_type='glb', include_normals=True)
                mesh_bytes.append(byte_stream.getvalue())

        return mesh_bytes

@app.local_entrypoint()
def main(image_path: str):
    t0 = time.time()
    image = Image.open(image_path)
    image_bytes = Model().inference.remote(image)
    print(f"🎨 inference latency: {time.time() - t0:.2f} seconds")
    output_path = Path("/tmp") / "stable-fast-3d" / "output.glb"
    output_path.parent.mkdir(exist_ok=True, parents=True)
    print(f"🎨 saving output to {output_path}")
    output_path.write_bytes(image_bytes)
