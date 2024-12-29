# from huggingface_hub import snapshot_download, hf_hub_download

# file_path = hf_hub_download(
#     repo_id="abhishek/StableSAM",
#     filename="sam_vit_h_4b8939.pth",
#     repo_type="model",
#     local_dir="sam_pt"
# )
# snapshot_download(repo_id='flamehaze1115/Wonder3D_plus', local_dir="./ckpts")

import os
import io
import time
from PIL import Image
import torch
from typing import Literal
from pathlib import Path
from typing_extensions import Annotated
from io import BytesIO
import numpy as np
import modal
from fastapi import (
    Response,
    Body,
    Depends,
    HTTPException,
    status,
    Request,
    File,
    UploadFile,
)
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

cuda_version = "12.1.0"  # no greater than host CUDA version
flavor = "devel"  # full CUDA toolkit
operating_sys = "ubuntu22.04"
tag = f"{cuda_version}-{flavor}-{operating_sys}"

cuda_dev_image = modal.Image.from_registry(
    f"nvidia/cuda:{tag}", add_python="3.11"
).entrypoint([])

image = (
    cuda_dev_image.apt_install(
        "git",
        "build-essential",
        "libgl1-mesa-glx",
        "libglib2.0-0",
        "libsm6",
        "libxext6",
        "libxrender-dev",
        "python3-opengl",
    )
    .pip_install(
        [
            "torch==2.1.0",
            "torchvision",
            "iopath",
            "nvdiffrast @ git+https://github.com/NVlabs/nvdiffrast.git",
            "pillow",
            "diffusers[torch]==0.30.0",
            "transformers>=4.25.1",
            "bitsandbytes==0.35.4",
            "decord==0.6.0",
            "pytorch-lightning<2",
            "omegaconf==2.2.3",
            "nerfacc==0.3.3",
            "trimesh==3.9.8",
            "pyhocon==0.3.57",
            "icecream==2.1.0",
            "accelerate",
            "modelcards",
            "einops",
            "ftfy",
            "piq",
            "matplotlib",
            "opencv-python",
            "imageio",
            "imageio-ffmpeg",
            "scipy",
            "pyransac3d",
            "torch_efficient_distloss",
            "tensorboard",
            "rembg",
            "segment_anything",
            "gradio==3.50.2",
            "mosaicml-streaming",
            "onnxruntime-gpu==1.17.0",
            "pyrender",
            "jaxtyping",
            "pymeshlab",
            "cholespy",
            "open3d",
            "fire",
            "comet_ml",
        ]
    )
    .run_commands("git clone https://github.com/facebookresearch/pytorch3d.git")
    .workdir("/pytorch3d")
    .run_commands("git checkout V0.7.8")
    .pip_install("wheel")
    .apt_install("clang")
    .run_commands("pip install --no-build-isolation .")
    .workdir("/")
    .run_commands(
        "pip install torch-scatter -f https://data.pyg.org/whl/torch-2.1.0+cu121.html"
    )
    .run_commands("git clone https://github.com/xxlong0/Wonder3D.git Wonder3D")
    .workdir("/Wonder3D")
    .workdir("/")
    .env(
        {
            "PYTHONPATH": "/Wonder3D",
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
        }
    )
    .pip_install("pydantic==2.10.4")
    .pip_install("fastapi[standard]")
    .pip_install("msgpack==1.1.0")
    .pip_install("huggingface_hub[hf_transfer]")
    .workdir("/Wonder3D")
)

with image.imports():
    from omegaconf import OmegaConf  # type: ignore
    from run_mv_prediction import pred_multiview_joint  # type: ignore
    from run_mv_enhancement import pred_enhancement_joint  # type: ignore

    from MVMeshRecon.Coarse_recon import coarse_recon  # type: ignore
    from MVMeshRecon.Iterative_refine import iterative_refine  # type: ignore
    from MVMeshRecon.utils.refine_lr_to_sr import sr_front  # type: ignore
    from rembg import remove  # type: ignore
    from remeshing.util.func import save_obj  # type: ignore

auth_scheme = HTTPBearer()
app = modal.App("wonder3d-plus", image=image)


class GenerationConfig(BaseModel):
    model_config = {
        "extra": "forbid",
    }
    crop_size: int = 192
    camera_type: Literal["ortho", "persp"] = "ortho"
    num_refine: int = 2
    seed: int = 42


def views_6to4(imgs):
    outs = []
    for i in range(6):
        if i == 1 or i == 5:
            continue
        outs.append(imgs[i])
    return outs


def add_margin(pil_img, color=0, size=256):
    width, height = pil_img.size
    result = Image.new(pil_img.mode, (size, size), color)
    result.paste(pil_img, ((size - width) // 2, (size - height) // 2))
    return result


def process_image(image_input, image_size=2048, crop_size=2048 * 0.75):
    if np.asarray(image_input).shape[-1] == 3:
        image_input = remove(image_input)

    if crop_size != -1:
        alpha_np = np.asarray(image_input)[:, :, 3]
        coords = np.stack(np.nonzero(alpha_np), 1)[:, (1, 0)]
        min_x, min_y = np.min(coords, 0)
        max_x, max_y = np.max(coords, 0)
        ref_img_ = image_input.crop((min_x, min_y, max_x, max_y))

        width, height = ref_img_.size

        # upsamle the input image if the quality of input image is quite low
        if width < 400 or height < 400:
            ref_img_ = sr_front(ref_img_)

        h, w = ref_img_.height, ref_img_.width
        scale = crop_size / max(h, w)
        h_, w_ = int(scale * h), int(scale * w)
        ref_img_ = ref_img_.resize((w_, h_))
        image_input = add_margin(ref_img_, size=image_size)
    else:
        image_input = add_margin(
            image_input, size=max(image_input.height, image_input.width)
        )
        image_input = image_input.resize((image_size, image_size))

    return image_input


@app.cls(
    gpu="A10G",
    container_idle_timeout=10 * 60,
    timeout=10 * 60,
    secrets=[
        modal.Secret.from_name("huggingface-token"),
        modal.Secret.from_name("blender-api-token"),
    ],
)
class Model:
    def setup_model(self):
        # Load configs
        self.config_mv = OmegaConf.load("./configs/mvdiffusion-joint.yaml")
        self.config_controlnet = OmegaConf.load("./configs/controlnet.yaml")

        # Download models
        import huggingface_hub  # type: ignore

        huggingface_hub.login(token=os.environ["HUGGINGFACE_TOKEN"])
        huggingface_hub.snapshot_download(
            repo_id="flamehaze1115/Wonder3D_plus", local_dir="./ckpts"
        )
        huggingface_hub.hf_hub_download(
            repo_id="abhishek/StableSAM",
            filename="sam_vit_h_4b8939.pth",
            repo_type="space",
            local_dir="./ckpts/sam_pt",
        )

        # Debug: Print the downloaded files
        print("Downloaded files:")
        for root, dirs, files in os.walk("./ckpts"):
            print(f"\nDirectory: {root}")
            for file in files:
                print(f"  - {file}")


        # Load pipelines
        from run_mv_prediction import load_wonder3d_pipeline  # type: ignore
        from run_mv_enhancement import load_controlnet_pipeline  # type: ignore

        self.device = torch.device("cuda:0")
        self.mv_pipeline = load_wonder3d_pipeline(self.config_mv).to(self.device)
        self.enhancement_pipeline = load_controlnet_pipeline(self.config_controlnet).to(
            self.device
        )

    @modal.enter()
    def enter(self):
        self.setup_model()

    @modal.method()
    def inference(self, image, config: GenerationConfig) -> bytes:
        processed_img = process_image(
            image_input=image, crop_size=config.crop_size * 8, image_size=2048
        )

        # Run Wonder3D pipeline stages
        normals_pred, images_pred = pred_multiview_joint(
            processed_img,
            self.mv_pipeline,
            seed=config.seed,
            crop_size=config.crop_size,
            camera_type=config.camera_type,
            cfg=self.config_mv,
        )

        # Run coarse reconstruction
        rendered_rgbs, rendered_normal, vertices, faces = coarse_recon(
            front_image=processed_img,
            rgbs=images_pred,
            normals=normals_pred,
            camera_type=config.camera_type,
            crop_size=config.crop_size,
        )

        # Run refinement stages
        for refine_idx in range(config.num_refine):
            normals_pred, images_pred = pred_enhancement_joint(
                mv_image=images_pred,
                mv_normlas=normals_pred,
                renderd_mv_image=rendered_rgbs,
                renderd_mv_normal=rendered_normal,
                front_image=processed_img,
                pipeline=self.enhancement_pipeline,
                seed=config.seed,
                crop_size=config.crop_size,
                camera_type=config.camera_type,
                cfg=self.config_controlnet,
                refine_idx=refine_idx,
            )

            rendered_rgbs, rendered_normal, vertices, faces = iterative_refine(
                vertex_init=vertices,
                face_init=faces,
                front_image=processed_img,
                rgbs=images_pred,
                normals=normals_pred,
                camera_type=config.camera_type,
                crop_size=config.crop_size,
                refine_idx=refine_idx,
                do_sr=(refine_idx == (config.num_refine - 1)),
            )

        # Export final mesh
        mesh_bytes = BytesIO()
        save_obj(vertices, faces, mesh_bytes)
        return mesh_bytes.getvalue()

    @modal.web_endpoint(method="POST")
    async def web(
        self,
        request: Request,
        token: Annotated[HTTPAuthorizationCredentials, Depends(auth_scheme)],
        image: UploadFile,
        config: GenerationConfig,
    ):
        if token.credentials != os.environ["HUGGINGFACE_TOKEN"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            img_data = await image.read()
            pil_image = Image.open(io.BytesIO(img_data))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid image: {str(e)}")

        try:
            mesh_bytes = self.inference.remote(pil_image, config)
            return Response(
                content=mesh_bytes,
                media_type="application/octet-stream",
                headers={"Content-Disposition": "attachment; filename=model.obj"},
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")


@app.local_entrypoint()
def main(image_path: str):
    t0 = time.time()
    image = Image.open(image_path)
    mesh_bytes = Model().inference.remote(image, GenerationConfig())
    print(f"🎨 Inference latency: {time.time() - t0:.2f} seconds")

    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)
    (output_dir / "output.obj").write_bytes(mesh_bytes)
