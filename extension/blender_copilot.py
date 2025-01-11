# type: ignore
import bpy
import os
import json
import threading
from datetime import datetime
import logging

# ------------------------------------------------------------------------
# Globals
# ------------------------------------------------------------------------

SERVER_URL = "https://blendercopilot.com"
ENDPOINTS = {
    "image": "/infer/image_to_3d",
    "text": "/infer/text_to_3d",
}
REQUEST_TIMEOUT = 5 * 60 # 5 minutes

ROOTDIR = os.path.dirname(os.path.abspath(__file__))

LICENSE_KEY = None # change to liscence key, else will be free tier

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
    log_file = os.path.join(ROOTDIR, "blender_copilot.log")
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
        endpoint = "image" if job["use_image"] else "text"
        config = {
            "model_type": job["model_type"],
            "remesh_option": job["resampler"],
            "texture_resolution": job["resolution"],
            "batch_size": job["batch_size"],
            "prompt": job["text_prompt"],
        }

        if job["use_image"]:
            if not os.path.isfile(job["image_path"]):
                logger.error(f"[generate] Image file {job['image_path']} not found.")
                job["status"] = "error"
                job["error_message"] = f"Image file {job['image_path']} not found."
                return

            with open(job["image_path"], "rb") as image_file:
                files = {"images": image_file.read()}
        else:
            files = None

        logger.info(f"[generate] Requesting {job['text_prompt']}")
        auth_headers = {"Authorization": f"Bearer {LICENSE_KEY}"} if LICENSE_KEY else {}
        response = requests.get(
            f"{SERVER_URL}{ENDPOINTS[endpoint]}",
            headers=auth_headers,
            files=files,
            data=dict(config=json.dumps(config)),
            timeout=REQUEST_TIMEOUT,
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
        elif response.status_code == 429:
            job["status"] = "error"
            job["error_message"] = "Daily limit reached. Upgrade or try again tomorrow."
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

    redraw_ui()

# ------------------------------------------------------------------------
# Utility: Create a new job
# ------------------------------------------------------------------------
def create_new_job(
    model_type, text_prompt, use_image, image_path, use_scene_style, resampler, resolution, batch_size
):
    global jobs, job_counter
    logger.info(f"[create_new_job] Creating job {job_counter}")

    if number_of_active_jobs() >= MAX_JOBS:
        logger.warning(f"[create_new_job] Maximum of {MAX_JOBS} jobs reached.")
        return None  # can't exceed MAX_JOBS

    job_counter += 1
    new_job = {
        "id": job_counter,
        "model_type": model_type,
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
        "batch_size": batch_size,
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
    # Add tab enum property
    generation_type: bpy.props.EnumProperty(
        name="Generation Type",
        items=[
            ("TEXT", "Text to 3D", "Generate 3D models from text descriptions"),
            ("IMAGE", "Image to 3D", "Generate 3D models from reference images"),
        ],
        default="TEXT"
    )

    text_prompt: bpy.props.StringProperty(
        name="Text Prompt", description="Your text prompt for generation", default=""
    )
    batch_size: bpy.props.EnumProperty(
        name="Num Images",
        description="Number of images to generate",
        items=[
            ("1", "1", "1"),
            ("2", "2", "2"),
            ("4", "4", "4"),
        ],
        default="1",
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

    model_type: bpy.props.EnumProperty(
        name="Model",
        description="Choose the model to use for generation",
        items=[
            ("faster", "Faster", "Faster model"),
            ("better", "Better", "Better model"),
        ],
        default="better",
    )

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

        # Set use_image based on generation type
        use_image = props.generation_type == "IMAGE"

        # Validate if an image is needed
        if use_image:
            if (not props.image_path) or (not os.path.isfile(props.image_path)):
                self.report(
                    {"ERROR"},
                    "Please select a valid image file for Image to 3D generation.",
                )
                return {"CANCELLED"}

        new_job = create_new_job(
            model_type=props.model_type,
            text_prompt=props.text_prompt,
            use_image=use_image,
            image_path=props.image_path if use_image else None,
            use_scene_style=False,
            resampler=props.resampler,
            resolution=props.resolution,
            batch_size=props.batch_size,
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

    def execute(self, _):
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
            obj.location = (base_location[0] + i*0.25, base_location[1], base_location[2])

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

    def execute(self, _):
        global jobs
        job = next((j for j in jobs if j["id"] == self.job_id), None)
        if not job:
            self.report({"ERROR"}, "Job not found.")
            return {"CANCELLED"}

        if job["status"] == "running":
            self.report({"INFO"}, f"Cancelled job {job['id']}.")

        remove_job(job)
        return {"FINISHED"}


# ------------------------------------------------------------------------
# Operator: Notification Watcher
# ------------------------------------------------------------------------
class BCOPILOT_OT_StatusNotification(bpy.types.Operator):
    """Operator just to display a banner notification"""
    bl_idname = "bcopilot.status_notification"
    bl_label = "Copilot Notification"

    message: bpy.props.StringProperty(
        name="Message",
        description="Message to display",
        default="Notification"
    )

    def execute(self, _):
        logger.info(f"[Status Notification] {self.message}")
        self.report({'INFO'}, self.message)
        return {'FINISHED'}


class BCOPILOT_OT_NotificationWatcher(bpy.types.Operator):
    """Modal operator that watches for job status changes and shows notifications"""
    bl_idname = "bcopilot.notification_watcher"
    bl_label = "Notification Watcher"

    _timer = None

    def modal(self, _, event):
        if event.type == 'TIMER':
            global jobs
            for job in jobs:
                if job["thread"] is not None and not job["thread"].is_alive() and job["status"] == "running":
                    logger.info(f"[Notification Watcher] Job {job['id']} failed unexpectedly!")
                    job["status"] = "error"
                    bpy.ops.bcopilot.status_notification(message=f"Job {job['id']} failed unexpectedly!")
                elif job["status"] == "error" and "error_message" in job:
                    logger.info(f"[Notification Watcher] Job {job['id']} failed: {job['error_message']}")
                    bpy.ops.bcopilot.status_notification(message=f"Job {job['id']} failed: {job['error_message']}")
                    job.pop("error_message")
                elif job["status"] == "done" and not job["thread"].is_alive():
                    logger.info(f"[Notification Watcher] Job {job['id']} completed successfully.")
                    bpy.ops.bcopilot.status_notification(message=f"Job {job['id']} completed successfully.")
                    job.pop("notification")
        return {"PASS_THROUGH"}

    def execute(self, context):
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.5, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        wm = context.window_manager
        wm.event_timer_remove(self._timer)

def start_notification_watcher():
    """
    Deferred function to start the Notification Watcher with a simple call
    that doesn't require a complex override dictionary.
    """
    def _start():
        try:
            # Start the operator with EXEC_DEFAULT so it doesn't need a special UI context.
            bpy.ops.bcopilot.notification_watcher('EXEC_DEFAULT')
            logger.info("Started notification watcher")
        except Exception as e:
            logger.error(f"Failed to start notification watcher: {e}")

        # Return None so this timer callback runs once and then is removed.
        return None

    # Schedule _start to run after 0.5 seconds, giving Blender time to finish loading UI, etc.
    bpy.app.timers.register(_start, first_interval=0.5)


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

        # Add tab selector
        row = layout.row()
        row.prop(props, "generation_type", expand=True)

        box = layout.box()
        if props.generation_type == "TEXT":
            box.label(text="Text to 3D", icon="FONT_DATA")
            box.label(text="Prompt:")
            box.prop(props, "text_prompt", text="")

            row = box.row()
            row.label(text="Num Images:")
            row.prop(props, "batch_size", text="")

        else:  # IMAGE mode
            box.label(text="Image to 3D", icon="IMAGE_DATA")
            row = box.row().split(factor=0.3)
            row.label(text="Image:")
            row.prop(props, "image_path", text="")

            box.label(text="Prompt (optional):")
            box.prop(props, "text_prompt", text="")

        # Add collapsible advanced section
        box = layout.box()
        row = box.row()
        row.prop(context.scene, "bcopilot_show_advanced",
                icon="TRIA_DOWN" if context.scene.bcopilot_show_advanced else "TRIA_RIGHT",
                icon_only=True, emboss=False)
        row.label(text="More Options")

        if context.scene.bcopilot_show_advanced:
            row = box.row().split(factor=0.28)
            row.label(text="Model:")
            row.prop(props, "model_type", text="")

            row = box.row().split(factor=0.28)
            row.label(text="Resampler:")
            row.prop(props, "resampler", text="")

            row = box.row().split(factor=0.28)
            row.label(text="Resolution:")
            row.prop(props, "resolution", text="")

        layout.operator("bcopilot.create_job", text="Start Generation")

        # Jobs list remains the same
        layout.separator()
        layout.label(
            text=f"Active Jobs (max {MAX_JOBS}): {number_of_active_jobs()}", icon="INFO"
        )

        for job in jobs:
            row = layout.row().split(factor=0.28)
            row.label(text=f"Job {job['id']}")
            row.label(text=f"Status: {job['status']}")

            op = row.operator("bcopilot.cancel_job", text="", icon='X')
            op.job_id = job["id"]

            if job["status"] == "done":
                op = row.operator("bcopilot.apply_job_result", text="Apply")
                op.job_id = job["id"]


# ------------------------------------------------------------------------
# Timer handler
# ------------------------------------------------------------------------
def remove_job(job):
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

# ------------------------------------------------------------------------
# Registration
# ------------------------------------------------------------------------
classes = (
    BCOPILOT_Properties,
    BCOPILOT_OT_CreateJob,
    BCOPILOT_OT_ApplyJobResult,
    BCOPILOT_OT_CancelJob,
    BCOPILOT_OT_NotificationWatcher,
    BCOPILOT_OT_StatusNotification,
    BCOPILOT_PT_MainPanel,
)

def register_addon_classes():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as e:
            logger.error(f"Failed to register {cls.__name__}: {str(e)}")
            raise

    bpy.types.Scene.bcopilot_props = bpy.props.PointerProperty(type=BCOPILOT_Properties)
    bpy.types.Scene.bcopilot_show_advanced = bpy.props.BoolProperty(default=False)
    start_notification_watcher()



def unregister_addon_classes():
    redraw_ui()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.bcopilot_props
    del bpy.types.Scene.bcopilot_show_advanced
