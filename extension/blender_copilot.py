# type: ignore
import bpy
import os
import threading
import time
from mathutils import Vector
from datetime import datetime
import logging

# ------------------------------------------------------------------------
# Globals
# ------------------------------------------------------------------------

MAX_JOBS = 3
jobs = []
job_counter = 0

def setup_logger():
    logger = logging.getLogger('BlenderCopilot')
    logger.setLevel(logging.DEBUG)

    # Console handler (appears in Blender's system console)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')
    console_handler.setFormatter(console_formatter)

    # File handler (writes to a log file in Blender's temp directory)
    log_file = os.path.join(os.path.dirname(__file__), "blender_copilot.log")
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger

logger = setup_logger()

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
#   "status": "running"/"done"/"error"/"cancelled",
#   "thread": <Thread>,
#   "results": ["/path/to/generated.glb", "/path/to/generated.glb", ...] or [],
# }

# ------------------------------------------------------------------------
# Generate a 3D model
# ------------------------------------------------------------------------
def generate(job):
    import requests
    import msgpack

    try:
        files_param = {
            "remesh_option": job["resampler"],
            "texture_resolution": job["resolution"],
        }
        if job["use_image"] and job["image_path"] and os.path.isfile(job["image_path"]):
            with open(job["image_path"], "rb") as image_file:
                files_param["images"] = image_file.read()

        logger.info(f"[generate] Requesting {job['text_prompt']}")
        response = requests.post(
            "https://tom-pollak--stable-fast-3d-model-generate-endpoint-dev.modal.run",
            headers={"Authorization": "Bearer gsOqcfflD-j50tX0OY7vemBkVUeY9k6V"},
            files=files_param
        )

        logger.info(f"[generate] Response: {response.status_code}")
        if response.status_code == 200:
            glb_files = msgpack.unpackb(response.content)

            out_dir = os.path.join(bpy.app.tempdir, f"bcopilot_job_{job['id']}")
            if not os.path.exists(out_dir):
                os.makedirs(out_dir)

            out_paths = []
            for idx, glb_data in enumerate(glb_files):
                out_path = os.path.join(out_dir, f"mesh_{idx}.glb")
                with open(out_path, "wb") as f:
                    f.write(glb_data)
                logger.info(f"[generate] Wrote {out_path}")
                out_paths.append(out_path)

            job["results"] = out_paths
            job["status"] = "done"
            job["notification"] = f"Job {job['id']} finished successfully."
        else:
            error_msg = f"Request failed: {response.status_code} {response.text}"
            logger.error(f"[generate] {error_msg}")
            job["status"] = "error"
            job["error_message"] = error_msg
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[generate] Exception: {error_msg}")
        job["status"] = "error"
        job["error_message"] = error_msg

    # Force UI refresh - redraw only the Copilot panel
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'UI':
                        region.tag_redraw()

# ------------------------------------------------------------------------
# Utility: Create a new job
# ------------------------------------------------------------------------
def create_new_job(
    text_prompt, use_image, image_path, use_scene_style, resampler, resolution
):
    global jobs, job_counter
    logger.info(f"[create_new_job] Creating job {job_counter}")

    if number_of_active_jobs() >= MAX_JOBS:
        logger.warning(f"[create_new_job] Maximum of {MAX_JOBS} jobs reached.")
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
        "status": "running",
        "thread": None,
        "results": [],
    }
    logger.debug(f"Parameters: {new_job}")

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
            logger.info(f"[Create Job] Error rendering scene style: {e}")
            new_job["style_image"] = None
            bpy.ops.wm.report_info({'ERROR'}, f"Error rendering scene style: {e}")
    jobs.append(new_job)

    # Spawn the thread to do the real generation
    thread = threading.Thread(target=generate, args=(new_job,))
    new_job["thread"] = thread
    thread.start()

    logger.info(f"[create_new_job] Job {job_counter} started.")

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

    # use_scene_style: bpy.props.BoolProperty(
    #     name="Use Scene Style",
    #     description="Render the current scene/camera as a style image to pass in",
    #     default=False,
    # )

    # Resampler dropdown
    resampler: bpy.props.EnumProperty(
        name="Resampler",
        description="Choose how to resample the mesh or textures",
        items=[
            ("triangle", "Triangle", "Use triangle resampling (default)"),
            ("quad", "Quad", "Use quad-based resampling"),
            ("none", "None", "No resampling"),
        ],
        default="triangle",
    )

    # Resolution dropdown
    resolution: bpy.props.EnumProperty(
        name="Resolution",
        description="Output resolution for generated textures/meshes",
        items=[
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
            use_scene_style=False,
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

        results = job["results"]
        if not results:
            self.report({"ERROR"}, f"No valid result files found for job {job['id']}.")
            return {"CANCELLED"}

        imported_objs = []
        for res in results:
            if not os.path.isfile(res):
                self.report({"ERROR"}, f"Result file {res} is missing.")
                return {"CANCELLED"}

            try:
                bpy.ops.import_scene.gltf(filepath=res)
                imported_objs.extend(bpy.context.selected_objects)
            except Exception as e:
                self.report({"ERROR"}, f"Failed to import: {e}")
                return {"CANCELLED"}

        # Place them in a row around (0, 0, 2)
        base_location = (0, 0, 2)
        for i, obj in enumerate(imported_objs):
            # e.g. put each object 2 Blender units offset in X
            obj.location = (base_location[0] + i*2, base_location[1], base_location[2])

        # Remove temporary files
        for res in results:
            if os.path.exists(res):
                os.remove(res)

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

        # row = box.row()
        # row.prop(props, "use_scene_style", text="Use Scene Style?")

        # Add collapsible advanced section
        box = layout.box()
        row = box.row()
        row.prop(context.scene, "bcopilot_show_advanced",
                icon="TRIA_DOWN" if context.scene.bcopilot_show_advanced else "TRIA_RIGHT",
                icon_only=True, emboss=False)
        row.label(text="More Options")

        if context.scene.bcopilot_show_advanced:
            row = box.row().split(factor=0.28)
            row.label(text="Resampler:")
            row.prop(props, "resampler", text="")

            row = box.row().split(factor=0.28)
            row.label(text="Resolution:")
            row.prop(props, "resolution", text="")

        layout.operator("bcopilot.create_job", text="Start Generation")

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

def redraw_ui():
    """Force UI refresh - redraw only the Copilot panel"""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'UI':
                        region.tag_redraw()

def show_message(message, title="Message", icon='INFO'):
    def draw(self, context):
        self.layout.label(text=message)

    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)

def check_jobs():
    """Check if any job threads have finished or errored."""
    global jobs
    for job in jobs:
        if job["thread"] is not None:
            if job["thread"].is_alive():
                continue

            # Thread is finished, check status and show notification
            if job["status"] == "running":
                job["status"] = "error"
                job["error_message"] = "Job terminated unexpectedly"

            # Show notification if needed
            if job["status"] == "error" and "error_message" in job:
                logger.error(f"Job {job['id']} failed: {job['error_message']}")
                show_message(f"Job {job['id']} failed: {job['error_message']}", title="Error", icon='ERROR')
            elif job["status"] == "done" and "notification" in job:
                logger.info(f"Job {job['id']} completed successfully")
                show_message(job["notification"], title="Success", icon='INFO')

            # Clear notification flags
            job.pop("error_message", None)
            job.pop("notification", None)

    redraw_ui()
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


def register_addon_classes():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.bcopilot_props = bpy.props.PointerProperty(type=BCOPILOT_Properties)
    bpy.types.Scene.bcopilot_show_advanced = bpy.props.BoolProperty(default=False)
    bpy.app.timers.register(check_jobs)


def unregister_addon_classes():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.bcopilot_props
    del bpy.types.Scene.bcopilot_show_advanced
