# %%

import time
import os
from io import BytesIO
from pathlib import Path
import msgpack

from fastapi import Response, Body, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

import modal

cuda_version = "12.4.0"  # should be no greater than host CUDA version
flavor = "devel"  # includes full CUDA toolkit
operating_sys = "ubuntu22.04"
tag = f"{cuda_version}-{flavor}-{operating_sys}"

cuda_dev_image = modal.Image.from_registry(
    f"nvidia/cuda:{tag}", add_python="3.11"
).entrypoint([])

diffusers_commit_sha = "81cf3b2f155f1de322079af28f625349ee21ec6b"

flux_image = (
    cuda_dev_image.apt_install(
        "git",
        "libglib2.0-0",
        "libsm6",
        "libxrender1",
        "libxext6",
        "ffmpeg",
        "libgl1",
    )
    .pip_install(
        "invisible_watermark==0.2.0",
        "transformers==4.44.0",
        "huggingface_hub[hf_transfer]==0.26.2",
        "accelerate==0.33.0",
        "safetensors==0.4.4",
        "sentencepiece==0.2.0",
        "torch==2.5.0",
        f"git+https://github.com/huggingface/diffusers.git@{diffusers_commit_sha}",
        "numpy<2",
        "msgpack==1.1.0",
    )
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)

flux_image = flux_image.env({"TORCHINDUCTOR_CACHE_DIR": "/root/.inductor-cache"}).env(
    {"TORCHINDUCTOR_FX_GRAPH_CACHE": "1"}
)

auth_scheme = HTTPBearer()
app = modal.App("flux", image=flux_image)

with flux_image.imports():
    import torch
    from diffusers import FluxPipeline # type: ignore

MINUTES = 60  # seconds
VARIANT = "schnell"  # or "dev", but note [dev] requires you to accept terms and conditions on HF
NUM_INFERENCE_STEPS = 25  # use ~50 for [dev], smaller for [schnell]


@app.cls(
    gpu="H100",  # fastest GPU on Modal
    container_idle_timeout=20 * MINUTES,
    timeout=60 * MINUTES,  # leave plenty of time for compilation
    secrets=[
        modal.Secret.from_name("huggingface-token"),
        modal.Secret.from_name("blender-api-token")
    ],
    volumes={  # add Volumes to store serializable compilation artifacts, see section on torch.compile below
        "/root/.nv": modal.Volume.from_name("nv-cache", create_if_missing=True),
        "/root/.triton": modal.Volume.from_name("triton-cache", create_if_missing=True),
        "/root/.inductor-cache": modal.Volume.from_name(
            "inductor-cache", create_if_missing=True
        ),
    },
)
class Model:
    compile: int = (  # see section on torch.compile below for details
        modal.parameter(default=0)
    )

    def setup_model(self):
        import huggingface_hub # type: ignore
        from transformers.utils import move_cache # type: ignore

        huggingface_hub.login(token=os.environ["HUGGINGFACE_TOKEN"])
        huggingface_hub.snapshot_download(f"black-forest-labs/FLUX.1-{VARIANT}")

        move_cache()

        pipe = FluxPipeline.from_pretrained(
            f"black-forest-labs/FLUX.1-{VARIANT}", torch_dtype=torch.bfloat16
        )

        return pipe

    @modal.build()
    def build(self):
        self.setup_model()

    @modal.enter()
    def enter(self):
        pipe = self.setup_model()
        pipe.to("cuda")  # move model to GPU
        self.pipe = optimize(pipe, compile=bool(self.compile))

    @modal.method()
    def inference(self, prompt: str, batch_size: int = 1) -> list[bytes]:
        print("🎨 generating image...")
        outputs = self.pipe(
            [prompt] * batch_size,
            output_type="pil",
            num_inference_steps=NUM_INFERENCE_STEPS,
        ).images

        image_bytes = []
        for image in outputs:
            byte_stream = BytesIO()
            image.save(byte_stream, format="PNG")
            image_bytes.append(byte_stream.getvalue())
        return image_bytes

    @modal.web_endpoint(method="POST", docs=True)
    def web(
        self,
        request: Request,
        token: HTTPAuthorizationCredentials = Depends(auth_scheme),
        prompt: str = Body(...),
        batch_size: int = Body(...),
    ):
        if token.credentials != os.environ["API_TOKEN"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not prompt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Prompt is required",
            )
        if batch_size < 1:
            return HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Batch size must be at least 1",
            )

        image_bytes = self.inference.remote(prompt, batch_size=batch_size)
        return Response(
            content=msgpack.packb(image_bytes), media_type="application/x-msgpack"
        )


@app.local_entrypoint()
def main(
    prompt: str = "a computer screen showing ASCII terminal art of the"
    " word 'Modal' in neon green. two programmers are pointing excitedly"
    " at the screen.",
    twice: bool = True,
    compile: bool = False,
    batch_size: int = 4,
):
    t0 = time.time()
    image_bytes = Model(compile=compile).inference.remote(prompt, batch_size=batch_size)
    print(f"🎨 first inference latency: {time.time() - t0:.2f} seconds")

    if twice:
        t0 = time.time()
        image_bytes = Model(compile=compile).inference.remote(
            prompt, batch_size=batch_size
        )
        print(f"🎨 second inference latency: {time.time() - t0:.2f} seconds")

    output_dir = Path("/tmp") / "flux"
    output_dir.mkdir(exist_ok=True, parents=True)
    print(f"🎨 saving output to {output_dir}")
    for i, image_bytes in enumerate(image_bytes):
        output_path = output_dir / f"output_{i}.png"
        output_path.write_bytes(image_bytes)


def optimize(pipe, compile=True):
    # fuse QKV projections in Transformer and VAE
    pipe.transformer.fuse_qkv_projections()
    pipe.vae.fuse_qkv_projections()

    # switch memory layout to Torch's preferred, channels_last
    pipe.transformer.to(memory_format=torch.channels_last)
    pipe.vae.to(memory_format=torch.channels_last)

    if not compile:
        return pipe

    # set torch compile flags
    config = torch._inductor.config # type: ignore
    config.disable_progress = False  # show progress bar
    config.conv_1x1_as_mm = True  # treat 1x1 convolutions as matrix muls
    # adjust autotuning algorithm
    config.coordinate_descent_tuning = True
    config.coordinate_descent_check_all_directions = True
    config.epilogue_fusion = False  # do not fuse pointwise ops into matmuls

    # tag the compute-intensive modules, the Transformer and VAE decoder, for compilation
    pipe.transformer = torch.compile(
        pipe.transformer, mode="max-autotune", fullgraph=True
    )
    pipe.vae.decode = torch.compile(
        pipe.vae.decode, mode="max-autotune", fullgraph=True
    )

    # trigger torch compilation
    print("🔦 running torch compiliation (may take up to 20 minutes)...")

    pipe(
        "dummy prompt to trigger torch compilation",
        output_type="pil",
        num_inference_steps=NUM_INFERENCE_STEPS,  # use ~50 for [dev], smaller for [schnell]
    ).images[0]

    print("🔦 finished torch compilation")

    return pipe
