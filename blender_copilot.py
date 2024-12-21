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
#   "status": "queued"/"running"/"done"/"error",
#   "thread": <Thread>,
#   "result_file": "/path/to/generated.glb" or None,
# }


# ------------------------------------------------------------------------
# Simulation of a long-running generation
# ------------------------------------------------------------------------
def simulate_generation(job):
    """
    In a real add-on, you'd replace this with your stable-fast-3d or other 3D generation code,
    using job["text_prompt"], job["image_path"], job["style_image"], job["resampler"], etc.
    """
    job["status"] = "running"
    time.sleep(5)  # Fake 5-second generation time
    # When done:
    job["status"] = "done"
    # For demonstration, we just pretend it generated this one dummy file:
    job["result_file"] = "/Users/tom/fun/stable-fast-3d/output/0/mesh.glb"

    self.report({"INFO"}, f"Done job {new_job['id']}.")


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

    # If user wants the scene style, do a quick render to a temp file now (on the main thread!).
    if use_scene_style:
        # Attempt a basic render from the active camera
        # (If there's no camera, user might get an error or blank render)
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

    # Now spawn the thread to simulate generation
    thread = threading.Thread(target=simulate_generation, args=(new_job,))
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
            ("1024", "1024", ""),
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
    """Imports the .glb from the finished job, placing it in front of the current camera."""

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
            # Possibly it's a dummy path
            self.report({"ERROR"}, f"No valid result file found for job {job['id']}.")
            return {"CANCELLED"}

        # Import the GLB
        try:
            bpy.ops.import_scene.gltf(filepath=result_file)
            imported_objs = bpy.context.selected_objects
        except Exception as e:
            self.report({"ERROR"}, f"Failed to import: {e}")
            return {"CANCELLED"}

        # Place them in front of the current camera
        camera = context.scene.camera
        if camera:
            cam_matrix = camera.matrix_world
            offset_distance = 5.0
            # camera looks along -Z in local space
            forward_vec = -cam_matrix.col[2].xyz.normalized()
            target_location = cam_matrix.translation + forward_vec * offset_distance

            for obj in imported_objs:
                obj.location = target_location
        else:
            # fallback location if no camera
            for obj in imported_objs:
                obj.location = (0, 0, 2)

        # Remove the job from the list now that it's applied
        jobs.remove(job)

        self.report({"INFO"}, f"Applied job {job['id']}.")
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
        box.prop(props, "text_prompt", text="Prompt")

        row = box.row()
        row.prop(props, "use_image", text="Use Image?")
        if props.use_image:
            box.prop(props, "image_path")

        row = box.row()
        row.prop(props, "use_scene_style", text="Use Scene Style?")

        row = box.row()
        row.prop(props, "resampler", text="Resampler")

        row = box.row()
        row.prop(props, "resolution", text="Resolution")

        box.operator("bcopilot.create_job", text="Start Generation")

        # Active jobs
        layout.separator()
        layout.label(
            text=f"Active Jobs (max {MAX_JOBS}): {number_of_active_jobs()}", icon="INFO"
        )

        for job in jobs:
            row = layout.row()
            row.label(text=f"Job {job['id']}")
            row.label(text=f"Status: {job['status']}")

            if job["status"] == "done":
                op = row.operator("bcopilot.apply_job_result", text="Apply")
                op.job_id = job["id"]


# ------------------------------------------------------------------------
# Timer handler
# ------------------------------------------------------------------------
def check_jobs():
    """Check if any job threads have finished or errored."""
    global jobs
    for job in jobs:
        if job["thread"] is not None:
            # If the thread's still running, do nothing
            if job["thread"].is_alive():
                continue
            # If the thread is dead and the job is still "running", it might have ended unexpectedly
            if job["status"] == "running":
                # Our simulate_generation normally sets status="done" on success
                # so if it's still "running" => error
                job["status"] = "error"
    return 0.5  # check again in half a second


# ------------------------------------------------------------------------
# Registration
# ------------------------------------------------------------------------
classes = (
    BCOPILOT_Properties,
    BCOPILOT_OT_CreateJob,
    BCOPILOT_OT_ApplyJobResult,
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
