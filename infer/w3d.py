import os
import msgpack
import io
import tempfile
import time
from PIL import Image
from pydantic_core import ValidationError
import torch
from typing import Literal
from pathlib import Path
from typing_extensions import Annotated
from io import BytesIO
import numpy as np
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
from pydantic import BaseModel

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
        "clang",
        "libgl1-mesa-glx",
        "libglib2.0-0",
        "libsm6",
        "libxext6",
        "libxrender-dev",
        "python3-opengl",
        "ninja-build",
        "libcudnn8",
    )
    .pip_install(
        "wheel",
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
        "onnxruntime-gpu==1.20.1",
        "pyrender",
        "jaxtyping",
        "pymeshlab",
        "cholespy",
        "open3d",
        "fire",
        "comet_ml",
        "peft",
        "fastapi[standard]",
        "msgpack==1.1.0",
        "huggingface_hub[hf_transfer]",
        "tensorrt",
    )
    .run_commands("git clone https://github.com/facebookresearch/pytorch3d.git")
    .workdir("/pytorch3d")
    .run_commands("git checkout V0.7.8")
    .env({
        "USE_CUDA": "1",
        "TORCH_CUDA_ARCH_LIST": "7.0;7.5;8.0;8.6",
        "FORCE_CUDA": "1",
    })
    .run_commands("pip install -e .")
    .workdir("/")
    .run_commands(
        "pip install torch-scatter -f https://data.pyg.org/whl/torch-2.1.0+cu121.html"
    )
    .run_commands("git clone https://github.com/xxlong0/Wonder3D.git /Wonder3D")
    .env(
        {
            "PYTHONPATH": "/Wonder3D",
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
        }
    )
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

auth_scheme = HTTPBearer()
app = modal.App("wonder3d-plus", image=image)


class GenerationConfig(BaseModel):
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
    def inference(self, image: Image.Image, config: GenerationConfig) -> bytes:
        temp_output_dir = tempfile.TemporaryDirectory()
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
            scence_name="scene",
            crop_size=config.crop_size,
        )

        # Run refinement stages
        mv_normals, mv_imgs = views_6to4(normals_pred), views_6to4(images_pred)
        for refine_idx in range(config.num_refine):
            normals_pred, images_pred = pred_enhancement_joint(
                mv_image=mv_imgs,
                mv_normlas=mv_normals,
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
                scence_name="scene",
                crop_size=config.crop_size,
                refine_idx=refine_idx,
                do_sr=(refine_idx == (config.num_refine - 1)),
                output_path=temp_output_dir.name,
            )
            obj_path = Path(temp_output_dir.name) / f"scene/iterative_refine-{refine_idx}/ortho/3d_model/model.glb"
            assert obj_path.exists()

        obj_bytes = obj_path.read_bytes()
        temp_output_dir.cleanup()
        return obj_bytes


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
            mesh_bytes = [self.inference.remote(image=pil_image, config=config) for pil_image in pil_images]
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
    t0 = time.time()
    image = Image.open(image_path)
    mesh_bytes = Model().inference.remote(image, config=GenerationConfig())
    print(f"🎨 Inference latency: {time.time() - t0:.2f} seconds")

    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)
    (output_dir / "output.glb").write_bytes(mesh_bytes)
