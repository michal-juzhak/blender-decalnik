bl_info = {
    "name": "DECALNIK: Font Atlas + Decal Generator",
    "blender": (3, 0, 0),
    "category": "Object",
    "version": (1, 0, 1),
    "author": "Mike Y",
    "description": "Generates a font atlas and mesh decals with text",
}

import bpy
import os
import sys
import subprocess
from bpy.props import StringProperty, IntProperty, EnumProperty, PointerProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector


def is_pil_installed():
    try:
        from PIL import Image, ImageFont, ImageDraw
        return True
    except ImportError:
        return False


class FONT_ATLAS_OT_InstallPillow(bpy.types.Operator):
    bl_idname = "fontatlas.install_pillow"
    bl_label = "Install Pillow. Blender restart required."

    def execute(self, context):
        python_exe = sys.executable
        try:
            subprocess.call([python_exe, "-m", "ensurepip"])
            subprocess.call([python_exe, "-m", "pip", "install", "Pillow"])
            self.report({'INFO'}, "Pillow installed successfully! Restart Blender")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to install Pillow: {str(e)}")
        return {'FINISHED'}


class FONT_ATLAS_OT_Generate(bpy.types.Operator):
    bl_idname = "fontatlas.generate"
    bl_label = "Generate Atlas and Place Decal at 3D Cursor"

    def execute(self, context):
        if bpy.data.is_saved and bpy.data.filepath:
            props = context.scene.font_atlas_props

            if not props.text_content:
                self.report({'ERROR'}, "Please enter text content.")
                return {'CANCELLED'}

            img = generate_font_atlas(props)
            create_text_decal(img, props.text_content)

            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "Please save the Blender file before proceeding.")
            return {'CANCELLED'}


def calculate_character_widths(font_path, characters, target_height):
    from PIL import ImageFont
    widths = {}

    font = ImageFont.truetype(font_path, target_height)

    for char in characters:
        width, _ = font.getmask(char).size
        widths[char] = width / target_height * 0.8  # Adjust if needed

    return widths


def generate_font_atlas(props):
    from PIL import Image, ImageFont, ImageDraw
    ATLAS_SIZE = [int(dim) for dim in props.atlas_size.split('x')]
    FONT_PATH = props.font_path
    FONT_SIZE = props.font_size
    ATLAS_NAME = props.atlas_name
    CHARACTERS = list(props.characters)

    background_color = tuple(int(c * 255) for c in props.background_color)
    image = Image.new("RGB", ATLAS_SIZE, background_color)

    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

    cell_size = (ATLAS_SIZE[0] / props.cell_count[0], ATLAS_SIZE[1] / props.cell_count[1])
    target_height = FONT_SIZE

    for i, char in enumerate(CHARACTERS):
        x = i % props.cell_count[0]
        y = i // props.cell_count[0]
        w, h = font.getmask(char).size
        position = (
            x * cell_size[0] + (cell_size[0] - w) / 2,
            y * cell_size[1] + (cell_size[1] - target_height) / 2 - props.symbol_vertical_offset
        )
        font_color = tuple(int(c * 255) for c in props.font_color)
        draw.text(position, char, font_color, font=font)

    atlas_path = os.path.join(bpy.path.abspath("//"), ATLAS_NAME + ".png")
    try:
        image.save(atlas_path)
    except PermissionError:
        self.report({'WARNING'}, "Save the .blend file first!")
        return None

    blender_image_name = ATLAS_NAME + ".png"

    # Load the image into Blender
    if blender_image_name not in bpy.data.images:
        img = bpy.data.images.load(atlas_path)  # Load and directly assign to img
    else:
        img = bpy.data.images[blender_image_name]
        img.reload()

    return img


def create_text_decal(img, text):
    props = bpy.context.scene.font_atlas_props

    # Replace the '\n' sequence with an actual newline character
    text = text.replace('\\n', '\n')

    ATLAS_NAME = props.atlas_name
    CHARACTERS = list(props.characters)
    CELL_COUNT = (props.cell_count[0], props.cell_count[1])
    FONT_PATH = props.font_path

    if ATLAS_NAME not in bpy.data.materials:
        mat = bpy.data.materials.new(name=ATLAS_NAME)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        texture_node = nodes.new(type='ShaderNodeTexImage')
        texture_node.image = img
        shader = nodes["Principled BSDF"]
        mat.node_tree.links.new(texture_node.outputs["Color"], shader.inputs["Alpha"])
        mat.blend_method = 'CLIP'
    else:
        mat = bpy.data.materials[ATLAS_NAME]

    # Calculate UVs for each character
    uv_dict = {}
    for i, char in enumerate(CHARACTERS):
        col = i % CELL_COUNT[0]
        row = i // CELL_COUNT[1]
        u_min = col / CELL_COUNT[0]
        u_max = (col + 1) / CELL_COUNT[0]
        v_min = 1 - (row + 1) / CELL_COUNT[1]
        v_max = 1 - row / CELL_COUNT[1]
        uv_dict[char] = [(u_min, v_min), (u_max, v_min), (u_max, v_max), (u_min, v_max)]

    # Create a shared material
    if ATLAS_NAME not in bpy.data.materials:
        mat = bpy.data.materials.new(name=ATLAS_NAME)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        texture_node = nodes.new(type='ShaderNodeTexImage')
        texture_node.image = bpy.data.images.get(ATLAS_NAME, None)
        shader = nodes["Principled BSDF"]
        mat.node_tree.links.new(texture_node.outputs["Color"], shader.inputs["Alpha"])
        mat.blend_method = 'CLIP'
    else:
        mat = bpy.data.materials[ATLAS_NAME]

    # Calculate character widths if FONT_PATH is provided
    if FONT_PATH:
        char_widths = calculate_character_widths(FONT_PATH, CHARACTERS, props.font_size)
    else:
        char_widths = {char: 1 for char in CHARACTERS}  # Default: All CHARACTERS have width of 1

    # Split the text into lines and center
    lines = text.split("\n")
    num_lines = len(lines)
    cursor_location = bpy.context.scene.cursor.location.copy()

    created_objects = []

    line_offset = 0
    line_cursor = cursor_location.x

    for line in lines:
        total_width = sum([char_widths[char.upper()] for char in line if char.upper() in uv_dict])
        line_cursor = cursor_location.x - (total_width / 2)

        for char in line:
            if char.upper() in uv_dict:
                bpy.ops.mesh.primitive_plane_add(size=1, enter_editmode=False, align='WORLD',
                                                 location=(line_cursor, cursor_location.y, cursor_location.z))
                plane = bpy.context.active_object
                created_objects.append(plane)

                # Adjust plane size based on character width
                scale_factor = char_widths[char.upper()]
                plane.scale[0] = scale_factor

                bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
                plane.location.x += scale_factor * 0.5
                plane.data.materials.append(mat)

                # Adjust the UVs of the plane based on its width
                uv_center = ((uv_dict[char.upper()][0][0] + uv_dict[char.upper()][1][0]) / 2,
                             (uv_dict[char.upper()][0][1] + uv_dict[char.upper()][3][1]) / 2)
                uv_layer = plane.data.uv_layers.active
                for i, loop in enumerate(plane.data.loops):
                    uv_offset = (uv_dict[char.upper()][i][0] - uv_center[0], uv_dict[char.upper()][i][1] - uv_center[1])
                    uv = uv_layer.data[loop.index].uv
                    uv[0] = uv_center[0] + uv_offset[0] * scale_factor
                    uv[1] = uv_center[1] + uv_offset[1]

                bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
                line_cursor += char_widths[char.upper()]

        cursor_location.y -= 1

    # Join all planes into a single object
    bpy.ops.object.select_all(action='DESELECT')
    for obj in created_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = created_objects[0]
    bpy.ops.object.join()
    bpy.context.active_object.name = "TextDecal"

    # Set the origin to the geometry's center
    bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_VOLUME', center='BOUNDS')

    # Set the object's location to the 3D cursor's location
    decal = bpy.context.active_object
    decal.location = bpy.context.scene.cursor.location

    # Align the object's orientation with the 3D cursor's orientation
    cursor_rotation = bpy.context.scene.cursor.rotation_euler
    decal.rotation_euler = cursor_rotation

    # Scale the combined decal mesh
    decal.scale *= props.decal_scale
    bpy.ops.object.transform_apply(scale=True)

    # Offset a bit towards view vector to avoid Z-fighting
    view_vector = bpy.context.region_data.view_rotation @ Vector((0.0, 0.0, 1.0))
    decal.location += view_vector * 0.001

    bpy.ops.object.origin_set(type='ORIGIN_CURSOR')


# UI
class FONT_ATLAS_PT_Panel(bpy.types.Panel):
    bl_label = "Font Atlas / Decal Generator"
    bl_idname = "FONT_ATLAS_PT_Panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Tools'

    def draw(self, context):
        layout = self.layout
        props = context.scene.font_atlas_props

        if is_pil_installed():
            layout.prop(props, "atlas_size")
            layout.prop(props, "atlas_name")
            layout.prop(props, "font_path")
            layout.prop(props, "font_size")
            layout.prop(props, "symbol_vertical_offset")
            layout.prop(props, "text_content")
            layout.prop(props, "decal_scale")

            layout.operator("fontatlas.generate")

        else:
            layout.label(text="Pillow is not installed.", icon='ERROR')
            layout.operator(FONT_ATLAS_OT_InstallPillow.bl_idname, icon='CONSOLE')


# Properties
class FontAtlasProperties(bpy.types.PropertyGroup):
    atlas_size: EnumProperty(
        name="Atlas Size",
        items=[
            ('512x512', '512x512', ''),
            ('1024x1024', '1024x1024', ''),
            ('2048x2048', '2048x2048', '')
        ],
        default='1024x1024'
    )

    font_path: StringProperty(
        name="Font Path",
        subtype='FILE_PATH',
        default="arial.ttf"
    )

    font_size: IntProperty(
        name="Font Size (pt)",
        default=95,
        min=10,
        max=200
    )

    symbol_vertical_offset: IntProperty(
        name="Symbol Vertical Offset",
        description="Vertical offset for the symbols in the atlas (px)",
        default=15,
        min=0,
        max=100
    )

    atlas_name: StringProperty(
        name="Atlas Name",
        default="font_atlas_1"
    )

    text_content: StringProperty(
        name="Decal Text",
        description="...",
        default=""
    )

    characters: StringProperty(
        name="Characters",
        default="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789&-+/.,!? "
    )

    font_color: bpy.props.FloatVectorProperty(
        name="Font Color",
        subtype='COLOR',
        default=(1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
        description="color picker"
    )

    background_color: bpy.props.FloatVectorProperty(
        name="Background Color",
        subtype='COLOR',
        default=(0.0, 0.0, 0.0),
        min=0.0,
        max=1.0,
        description="color picker"
    )

    cell_count: bpy.props.IntVectorProperty(
        name="Cell Count",
        default=(8, 8),
        size=2
    )

    decal_scale: bpy.props.FloatProperty(
        name="Decal Scale",
        description="Scale",
        default=0.01,
        min=0.001,
        max=100,
        precision=3
    )


def register():
    bpy.utils.register_class(FONT_ATLAS_OT_InstallPillow)
    bpy.utils.register_class(FONT_ATLAS_OT_Generate)
    bpy.utils.register_class(FONT_ATLAS_PT_Panel)
    bpy.utils.register_class(FontAtlasProperties)

    bpy.types.Scene.font_atlas_props = PointerProperty(type=FontAtlasProperties)


def unregister():
    bpy.utils.unregister_class(FONT_ATLAS_OT_InstallPillow)
    bpy.utils.unregister_class(FONT_ATLAS_OT_Generate)
    bpy.utils.unregister_class(FONT_ATLAS_PT_Panel)
    bpy.utils.unregister_class(FontAtlasProperties)
    del bpy.types.Scene.font_atlas_props
