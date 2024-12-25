# %%
import msgpack
import requests
from pathlib import Path

example_images = Path(__file__).parents[1] / "example_images"

response = requests.get(
    "http://localhost:5001/image_to_3d",
    headers={"Authorization": "Bearer 1234"},
    # files={'images': open(example_images / "chair1.png", "rb")},
    files=[
        ('images', open(example_images / "chair1.png", "rb")),
        ('images', open(example_images / "chair1.png", "rb")),
        ('images', open(example_images / "chair1.png", "rb"))
    ],
    data={
        "remesh_option": "TRIANGLE",
        "texture_resolution": "512",
    },
)

if response.status_code == 200:
    glb_files = msgpack.unpackb(response.content)
    print(f"Succeeded! Returned {len(glb_files)} files in {response.elapsed.total_seconds()} seconds")
else:
    print(response.status_code)
    print(response.text)
# %%

response = requests.get(
    "http://localhost:5001/text_to_3d",
    headers={"Authorization": "Bearer 1234"},
    data={
        "prompt": "a computer screen showing ASCII terminal art of the word 'Modal' in neon green.",
        "remesh_option": "TRIANGLE",
        "texture_resolution": "512",
        "batch_size": -3,
    },
)

if response.status_code == 200:
    glb_files = msgpack.unpackb(response.content)
    print(f"Succeeded! Returned {len(glb_files)} files in {response.elapsed.total_seconds()} seconds")
else:
    print(response.status_code)
    print(response.text)
