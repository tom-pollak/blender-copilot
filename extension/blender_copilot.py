# type: ignore
bl_info = {
    "name": "Blender Copilot",
    "author": "Tom Pollak",
    "version": (1, 3),
    "blender": (3, 0, 0),
    "location": "3D View > Sidebar > Copilot",
    "description": "Prototype with concurrency, optional text/image, resampler, resolution, and scene-style render",
    "warning": "",
    "doc_url": "",
    "category": "3D View",
}

import bpy
import os
import threading
import time
from mathutils import Vector
from datetime import datetime

# ------------------------------------------------------------------------
# Globals
# ------------------------------------------------------------------------

MAX_JOBS = 3
jobs = []
job_counter = 0

# Example job structure:
# {
#   "id": 1,
#   "text_prompt": "...",
#   "use_image": True/False,
#   "image_path": "/path/to/image.png" or None,
#   "use_scene_style": True/False,
#   "style_image": "/path/to/rendered.png" or None,
#   "resampler": "TRIANGLE"/"QUAD"/"NONE",
#   "resolution": "512"/"1024"/"2048",
#   "status": "queued"/"running"/"done"/"error"/"cancelled",
#   "thread": <Thread>,
#   "result_file": "/path/to/generated.glb" or None,
# }

# ------------------------------------------------------------------------
# Generate a 3D model
# ------------------------------------------------------------------------
def generate(job):
    """
    In a real add-on, you'd replace this with your stable-fast-3d or other 3D generation code.
    This version makes an HTTP POST request to your Modal endpoint with msgpack response.
    """
    job["status"] = "running"

    # If you want to handle cancellation gracefully, you'll need more robust checks.
    # For simplicity, we'll just do a single request here.
    try:
        # Example: passing the image if user selected "use_image"
        files_param = {}
        if job["use_image"] and job["image_path"] and os.path.isfile(job["image_path"]):
            files_param = {
                "images": open(job["image_path"], "rb")
            }

        # You might also want to pass in other fields (text_prompt, style_image, etc.)
        response = requests.post(
            "https://tom-pollak--stable-fast-3d-model-generate-endpoint-dev.modal.run",
            headers={"Authorization": "Bearer gsOqcfflD-j50tX0OY7vemBkVUeY9k6V"},
            files=files_param
        )

        if response.status_code == 200:
            glb_files = msgpack.unpackb(response.content)

            # Create an output directory if you want to store the results
            out_dir = "/Users/tom/fun/stable-fast-3d/output"
            if not os.path.exists(out_dir):
                os.makedirs(out_dir)

            # Write out each glb in out_dir with a unique name
            out_paths = []
            for idx, glb_data in enumerate(glb_files):
                out_path = os.path.join(out_dir, f"mesh_{job['id']}_{idx}.glb")
                with open(out_path, "wb") as f:
                    f.write(glb_data)
                out_paths.append(out_path)

            # Let the job know which single glb file to import as the "result"
            if out_paths:
                job["result_file"] = out_paths[0]  # pick the first one as the main
            else:
                job["result_file"] = None

            job["status"] = "done"
        else:
            # If the response is not 200, treat as error
            print(f"[generate] Request failed: {response.status_code} {response.text}")
            job["status"] = "error"

    except Exception as e:
        print(f"[generate] Exception: {e}")
        job["status"] = "error"

# ------------------------------------------------------------------------
# Utility: Create a new job
# ------------------------------------------------------------------------
def create_new_job(
    text_prompt, use_image, image_path, use_scene_style, resampler, resolution
):
    global jobs, job_counter

    if number_of_active_jobs() >= MAX_JOBS:
        return None  # can't exceed MAX_JOBS

    job_counter += 1
    new_job = {
        "id": job_counter,
        "text_prompt": text_prompt,
        "use_image": use_image,
        "image_path": image_path if use_image else None,
        "use_scene_style": use_scene_style,
        "style_image": None,
        "resampler": resampler,
        "resolution": resolution,
        "status": "queued",
        "thread": None,
        "result_file": None,
    }

    # If user wants the scene style, do a quick render on the main thread
    if use_scene_style:
        temp_file = generate_temp_filepath(prefix="style_image_", ext=".png")
        try:
            original_file_path = bpy.context.scene.render.filepath
            bpy.context.scene.render.filepath = temp_file
            bpy.ops.render.render(write_still=True)  # blocks until done
            bpy.context.scene.render.filepath = original_file_path
            new_job["style_image"] = temp_file
        except Exception as e:
            print(f"[Create Job] Error rendering scene style: {e}")
            new_job["style_image"] = None

    jobs.append(new_job)

    # Spawn the thread to do the real generation
    thread = threading.Thread(target=generate, args=(new_job,))
    new_job["thread"] = thread
    thread.start()

    return new_job


def generate_temp_filepath(prefix="", ext=".png"):
    """
    Generate a unique file path in Blender's temp dir or system temp dir.
    """
    temp_dir = bpy.app.tempdir if bpy.app.tempdir else "/tmp"
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{prefix}{now_str}{ext}"
    return os.path.join(temp_dir, filename)


def number_of_active_jobs():
    global jobs
    return len([j for j in jobs if j["status"] == "running"])


# ------------------------------------------------------------------------
# Property Group
# ------------------------------------------------------------------------
class BCOPILOT_Properties(bpy.types.PropertyGroup):
    text_prompt: bpy.props.StringProperty(
        name="Text Prompt", description="Your text prompt for generation", default=""
    )

    use_image: bpy.props.BoolProperty(
        name="Use Image",
        description="Include an additional image file in the generation",
        default=False,
    )
    image_path: bpy.props.StringProperty(
        name="Image File",
        description="Path to an image for generation",
        default="",
        subtype="FILE_PATH",
    )

    use_scene_style: bpy.props.BoolProperty(
        name="Use Scene Style",
        description="Render the current scene/camera as a style image to pass in",
        default=False,
    )

    # Resampler dropdown
    resampler: bpy.props.EnumProperty(
        name="Resampler",
        description="Choose how to resample the mesh or textures",
        items=[
            ("TRIANGLE", "Triangle", "Use triangle resampling (default)"),
            ("QUAD", "Quad", "Use quad-based resampling"),
            ("NONE", "None", "No resampling"),
        ],
        default="TRIANGLE",
    )

    # Resolution dropdown
    resolution: bpy.props.EnumProperty(
        name="Resolution",
        description="Output resolution for generated textures/meshes",
        items=[
            ("512", "512", ""),
            ("1024", "1024", "(default)"),
            ("2048", "2048", ""),
            ("4096", "4096", ""),
        ],
        default="1024",
    )


# ------------------------------------------------------------------------
# Operator: Create Job
# ------------------------------------------------------------------------
class BCOPILOT_OT_CreateJob(bpy.types.Operator):
    """Creates a new generation job (up to 3)."""

    bl_idname = "bcopilot.create_job"
    bl_label = "Start Generation"

    def execute(self, context):
        props = context.scene.bcopilot_props

        # Validate if an image is needed
        if props.use_image:
            if (not props.image_path) or (not os.path.isfile(props.image_path)):
                self.report(
                    {"ERROR"},
                    "Please select a valid image file or uncheck 'Use Image'.",
                )
                return {"CANCELLED"}

        new_job = create_new_job(
            text_prompt=props.text_prompt,
            use_image=props.use_image,
            image_path=props.image_path,
            use_scene_style=props.use_scene_style,
            resampler=props.resampler,
            resolution=props.resolution,
        )

        if not new_job:
            self.report({"WARNING"}, f"Maximum of {MAX_JOBS} jobs reached.")
        else:
            self.report({"INFO"}, f"Created job {new_job['id']}.")

        return {"FINISHED"}


# ------------------------------------------------------------------------
# Operator: Apply Job Result
# ------------------------------------------------------------------------
class BCOPILOT_OT_ApplyJobResult(bpy.types.Operator):
    """Imports the .glb from the finished job, placing all in a row near (0, 0, 2)."""

    bl_idname = "bcopilot.apply_job_result"
    bl_label = "Apply Job Result"

    job_id: bpy.props.IntProperty()

    def execute(self, context):
        global jobs
        job = next((j for j in jobs if j["id"] == self.job_id), None)
        if not job:
            self.report({"ERROR"}, "Job not found.")
            return {"CANCELLED"}

        if job["status"] != "done":
            self.report({"WARNING"}, "Job is not finished yet.")
            return {"CANCELLED"}

        result_file = job["result_file"]
        if not result_file or not os.path.isfile(result_file):
            # Possibly it's a dummy or missing path
            self.report({"ERROR"}, f"No valid result file found for job {job['id']}.")
            return {"CANCELLED"}

        # Import the GLB
        try:
            bpy.ops.import_scene.gltf(filepath=result_file)
            imported_objs = bpy.context.selected_objects
        except Exception as e:
            self.report({"ERROR"}, f"Failed to import: {e}")
            return {"CANCELLED"}

        # Place them in a row around (0, 0, 2)
        base_location = (0, 0, 2)
        for i, obj in enumerate(imported_objs):
            # e.g. put each object 2 Blender units offset in X
            obj.location = (base_location[0] + i*2, base_location[1], base_location[2])

        # Remove the job from the list now that it's applied
        jobs.remove(job)

        self.report({"INFO"}, f"Applied job {job['id']}.")
        return {"FINISHED"}


# ------------------------------------------------------------------------
# Operator: Cancel Job
# ------------------------------------------------------------------------
class BCOPILOT_OT_CancelJob(bpy.types.Operator):
    """Cancels a running or finished job"""
    bl_idname = "bcopilot.cancel_job"
    bl_label = "Cancel Job"

    job_id: bpy.props.IntProperty()

    def execute(self, context):
        global jobs
        job = next((j for j in jobs if j["id"] == self.job_id), None)
        if not job:
            self.report({"ERROR"}, "Job not found.")
            return {"CANCELLED"}

        cancel_job(job)
        self.report({"INFO"}, f"Cancelled job {job['id']}.")
        return {"FINISHED"}


# ------------------------------------------------------------------------
# Panel
# ------------------------------------------------------------------------
class BCOPILOT_PT_MainPanel(bpy.types.Panel):
    """Main Panel for Blender Copilot"""

    bl_label = "Blender Copilot"
    bl_idname = "BCOPILOT_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Copilot"

    def draw(self, context):
        layout = self.layout
        props = context.scene.bcopilot_props

        box = layout.box()
        box.label(text="Generation Settings", icon="RENDER_STILL")
        box.label(text="Prompt:")
        box.prop(props, "text_prompt", text="")

        row = box.row()
        row.prop(props, "use_image", text="Use Image?")
        if props.use_image:
            row = box.row().split(factor=0.3)
            row.label(text="Image path:")
            row.prop(props, "image_path", text="")

        row = box.row()
        row.prop(props, "use_scene_style", text="Use Scene Style?")

        row = box.row().split(factor=0.28)
        row.label(text="Resampler:")
        row.prop(props, "resampler", text="")

        row = box.row().split(factor=0.28)
        row.label(text="Resolution:")
        row.prop(props, "resolution", text="")

        box.operator("bcopilot.create_job", text="Start Generation")

        layout.separator()
        layout.label(
            text=f"Active Jobs (max {MAX_JOBS}): {number_of_active_jobs()}", icon="INFO"
        )

        for job in jobs:
            row = layout.row(align=True)
            row.label(text=f"Job {job['id']}")
            row.label(text=f"Status: {job['status']}")

            # Cancel button
            op = row.operator("bcopilot.cancel_job", text="", icon='X')
            op.job_id = job["id"]

            if job["status"] == "done":
                op = row.operator("bcopilot.apply_job_result", text="Apply")
                op.job_id = job["id"]


# ------------------------------------------------------------------------
# Timer handler
# ------------------------------------------------------------------------
def cancel_job(job):
    """Mark the job as cancelled if it's running, or remove if done/error."""
    if job["status"] == "running" and job["thread"] and job["thread"].is_alive():
        job["status"] = "cancelled"
    else:
        global jobs
        if job in jobs:
            jobs.remove(job)


def check_jobs():
    """Check if any job threads have finished or errored."""
    global jobs
    for job in jobs:
        if job["thread"] is not None:
            if job["thread"].is_alive():
                # Optionally check if job["status"] == "cancelled"
                continue
            # If thread is dead but status is still "running", mark as "error"
            if job["status"] == "running":
                job["status"] = "error"
    return 0.5  # check again in half a second


# ------------------------------------------------------------------------
# Registration
# ------------------------------------------------------------------------
classes = (
    BCOPILOT_Properties,
    BCOPILOT_OT_CreateJob,
    BCOPILOT_OT_ApplyJobResult,
    BCOPILOT_OT_CancelJob,
    BCOPILOT_PT_MainPanel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.bcopilot_props = bpy.props.PointerProperty(type=BCOPILOT_Properties)

    # Register our job-check timer
    bpy.app.timers.register(check_jobs)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.bcopilot_props


if __name__ == "__main__":
    register()
