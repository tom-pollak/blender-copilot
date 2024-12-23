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
from bpy.types import AddonPreferences, Operator, Panel

# ------------------------------------------------------------------------
# Dependencies
# ------------------------------------------------------------------------
from .dependencies import Dependencies
from . import blender_copilot

# ------------------------------------------------------------------------
# "Install Dependencies" operator
# ------------------------------------------------------------------------
class BCOPILOT_OT_InstallDependencies(Operator):
    bl_idname = "bcopilot.install_dependencies"
    bl_label = "Install Dependencies"
    bl_description = (
        "Installs Python libraries locally for this add-on (requests, msgpack, etc.)"
    )
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        # Only show if dependencies are missing
        return not Dependencies.check()

    def execute(self, context):
        if not Dependencies.install():
            self.report({'ERROR'}, "Failed to install dependencies.")
            return {'CANCELLED'}

        blender_copilot.register_addon_classes()

        self.report({'INFO'}, "Dependencies installed successfully!")
        return {'FINISHED'}


# ------------------------------------------------------------------------
# Preferences panel (shows "Install Dependencies" if missing)
# ------------------------------------------------------------------------
class BCOPILOT_AddonPreferences(AddonPreferences):
    bl_idname = __name__

    def draw(self, context):
        layout = self.layout

        layout.label(text="This add-on requires Python packages to function:")
        for name in Dependencies.requirements():
            layout.label(text=f" - {name}")

        if not Dependencies.check():
            layout.label(text="Click below to install required dependencies.")
            layout.operator(BCOPILOT_OT_InstallDependencies.bl_idname, icon="CONSOLE")
        else:
            layout.label(text="All required dependencies are installed.")


# ------------------------------------------------------------------------
# Minimal Panel if dependencies not installed
# ------------------------------------------------------------------------
class BCOPILOT_PT_LitePanel(Panel):
    bl_label = "Blender Copilot"
    bl_idname = "BCOPILOT_PT_LitePanel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Copilot"

    def draw(self, context):
        layout = self.layout
        if Dependencies.check():
            layout.label(text="Dependencies installed!")
            # Optionally direct user to the real panel in blender_copilot.py
        else:
            layout.label(text="Dependencies missing. Go to Preferences to install.")
            layout.operator("screen.userpref_show", text="Open Preferences")


# ------------------------------------------------------------------------
# Blender Hooks
# ------------------------------------------------------------------------
classes = (
    BCOPILOT_AddonPreferences,
    BCOPILOT_OT_InstallDependencies,
    BCOPILOT_PT_LitePanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    if Dependencies.check():
        blender_copilot.register_addon_classes()

def unregister():
    blender_copilot.unregister_addon_classes()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
