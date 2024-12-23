import requests
import msgpack

# Make the request
response = requests.post(
    "https://tom-pollak--stable-fast-3d-model-generate-endpoint-dev.modal.run",
    headers={"Authorization": "Bearer gsOqcfflD-j50tX0OY7vemBkVUeY9k6V"},
    files={"images": open("/Users/tom/fun/stable-fast-3d/demo_files/examples/chair1.png", "rb")}
)

# Decode the msgpack response
if response.status_code == 200:
    glb_files = msgpack.unpackb(response.content)
    with open("output.glb", "wb") as f:
        f.write(glb_files[0])
else:
    print(f"Request failed with status code {response.status_code}")
    print(response.text)
