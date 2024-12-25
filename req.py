# # %%
import os
import requests
import io
import msgpack
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

# %%
url = "https://tom-pollak--stable-fast-3d-model-generate-endpoint-dev.modal.run"
response = requests.post(
    url,
    headers={"Authorization": f"Token {os.getenv('MODAL_API_KEY')}"},
    files={
        "images": open(
            "/Users/tom/fun/stable-fast-3d/demo_files/examples/chair1.png", "rb"
        )
    },
)

if response.status_code == 200:
    glb_files = msgpack.unpackb(response.content)
    with open("output.glb", "wb") as f:
        f.write(glb_files[0])
else:
    print(f"Request failed with status code {response.status_code}")
    print(response.text)

# %%
url = "https://tom-pollak--example-flux-model-web-dev.modal.run/web"

params = {
    "prompt": "a computer screen showing ASCII terminal art of the word 'Modal' in neon green",
    "batch_size": 1,
}

# Make the request
response = requests.get(
    url,
    headers={"Authorization": "Bearer gsOqcfflD-j50tX0OY7vemBkVUeY9k6V"},
    params=params,
)

if response.status_code == 200:
    image_files = msgpack.unpackb(response.content)
    for i, image_file in enumerate(image_files):
        image = Image.open(io.BytesIO(image_file))
        image.save(f"generated_image_{i}.png")
else:
    print(f"Error: {response.status_code}")
    print(response.text)
