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

from . import blender_copilot
from .dependencies import Dependencies

# Auto-install dependencies on register if needed
def ensure_dependencies():
    if not Dependencies.check():
        return Dependencies.install()
    return True

# ------------------------------------------------------------------------
# Preferences panel
# ------------------------------------------------------------------------
class BCOPILOT_AddonPreferences(AddonPreferences):
    bl_idname = __name__

    def draw(self, context):
        layout = self.layout
        layout.label(text="Required Python packages:")
        for name in Dependencies.requirements():
            layout.label(text=f" - {name}")
        layout.label(text="All required dependencies are installed." if Dependencies.check()
                    else "Dependencies installation failed. Please check console for errors.")

# ------------------------------------------------------------------------
# Blender Hooks
# ------------------------------------------------------------------------

classes = (
    BCOPILOT_AddonPreferences,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    if ensure_dependencies():
        blender_copilot.register_addon_classes()
    else:
        raise Exception("Failed to install required dependencies. Please check console for errors.")

def unregister():
    blender_copilot.unregister_addon_classes()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
