bl_info = {
    "name": "Blender Copilot",
    "author": "Tom Pollak",
    "version": (1, 0),
    "blender": (2, 93, 0),
    "location": "3D View > Sidebar > Copilot",
    "description": "A simple prototype to generate/import 3D models from a text prompt",
    "warning": "",
    "doc_url": "",
    "category": "3D View",
}

import bpy

# ------------------------------------------------------------------------
#   Property Group
# ------------------------------------------------------------------------
class BCOPILOT_Properties(bpy.types.PropertyGroup):
    text_prompt: bpy.props.StringProperty(
        name="Prompt",
        description="Enter your text prompt here",
        default=""
    )

# ------------------------------------------------------------------------
#   Operator
# ------------------------------------------------------------------------
class BCOPILOT_OT_ImportDummy(bpy.types.Operator):
    """Generate or import a mesh based on prompt"""
    bl_idname = "bcopilot.import_dummy"
    bl_label = "Import Dummy Mesh"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.bcopilot_properties
        user_prompt = props.text_prompt

        # In a future version, you would call your text-to-3D code here.
        # For now, we just import a dummy .glb file as a placeholder.
        dummy_filepath = "/Users/tom/fun/stable-fast-3d/output/0/mesh.glb"  # Replace with your path!
        try:
            bpy.ops.import_scene.gltf(filepath=dummy_filepath)
            self.report({'INFO'}, f"Imported dummy mesh for prompt: {user_prompt}")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to import dummy file: {e}")

        return {'FINISHED'}

# ------------------------------------------------------------------------
#   Panel
# ------------------------------------------------------------------------
class BCOPILOT_PT_MainPanel(bpy.types.Panel):
    """Main Panel for Blender Copilot"""
    bl_label = "Blender Copilot"
    bl_idname = "BCOPILOT_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Copilot"

    def draw(self, context):
        layout = self.layout
        props = context.scene.bcopilot_properties

        layout.prop(props, "text_prompt")
        layout.operator("bcopilot.import_dummy", text="Generate Mesh")

# ------------------------------------------------------------------------
#   Registration
# ------------------------------------------------------------------------
classes = (
    BCOPILOT_Properties,
    BCOPILOT_OT_ImportDummy,
    BCOPILOT_PT_MainPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.bcopilot_properties = bpy.props.PointerProperty(
        type=BCOPILOT_Properties
    )

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.bcopilot_properties


if __name__ == "__main__":
    register()
