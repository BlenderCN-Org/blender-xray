import bpy

from .edit_helpers import base as base_edit_helper, bone_shape, bone_center
from .plugin_prefs import get_preferences
from .ui import dynamic_menu, list_helper, collapsible
from .ops import fake_bones
from .utils import create_cached_file_data, parse_shaders, parse_shaders_xrlc, parse_gamemtl, \
    is_helper_object
from . import details


def _build_label(subtext=''):
    prefix = 'X-Ray Engine'
    return prefix + ': ' + subtext if subtext else prefix


class PropClipOp(bpy.types.Operator):
    bl_idname = 'io_scene_xray.propclip'
    bl_label = ''

    items = (
        ('copy', '', '', 'COPYDOWN', 0),
        ('paste', '', '', 'PASTEDOWN', 1),
        ('clear', '', '', 'X', 2)
    )
    oper: bpy.props.EnumProperty(items=items)
    path: bpy.props.StringProperty()

    def execute(self, context):
        *path, prop = self.path.split('.')
        obj = context
        for name in path:
            obj = getattr(obj, name)
        if self.oper == 'copy':
            context.window_manager.clipboard = getattr(obj, prop)
        elif self.oper == 'paste':
            setattr(obj, prop, context.window_manager.clipboard)
        elif self.oper == 'clear':
            setattr(obj, prop, '')
        return {'FINISHED'}

    @classmethod
    def drawall(cls, layout, path, value):
        for item in cls.items:
            lay = layout
            if item[0] in ('copy', 'clear') and not value:
                lay = lay.split(align=True)
                lay.enabled = False
            props = lay.operator(cls.bl_idname, icon=item[3])
            props.oper = item[0]
            props.path = path


class XRayPanel(bpy.types.Panel):
    reg_order = 1

    bl_label = "XRay"

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "XRay"

    bl_idname = "XRayPanel"

    def draw_header(self, _context):
        self.layout.label(icon='PLUGIN')

    def draw(self, context):
        pass


class XRayMotionList(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        data = context.object.xray
        motion = data.motions_collection[index]

        if data.motions_collection_index == index:
            icon = 'CHECKBOX_HLT'
        else:
            icon = 'CHECKBOX_DEHLT'

        row = layout.row()
        row.label(text='', icon=icon)
        row.prop_search(motion, 'name', bpy.data, 'actions', text='')


class XRayObjectPanel(bpy.types.Panel):
    reg_order = 10
    bl_context = 'object'

    bl_label = 'Object'

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    bl_idname = "XRayObjectPanel"

    bl_category = XRayPanel.bl_category
    bl_parent_id = XRayPanel.bl_idname

    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return (
            context.active_object
            and not is_helper_object(context.active_object)
        )

    def draw(self, context):
        layout = self.layout
        data = context.object.xray
        layout.prop(data, 'isroot', text='Object', toggle=True)

        if data.isroot:
            object_box = layout.box()
            if not data.flags_use_custom:
                object_box.prop(data, 'flags_simple', text='Type')
            else:
                row = object_box.row(align=True)
                row.prop(data, 'flags_simple', text='Type')
                row.prop(data, 'flags_custom_type', text='')
                col = object_box.column(align=True)
                row = col.row(align=True)
                row.prop(data, 'flags_custom_progressive', text='Progressive', toggle=True)
                row.prop(data, 'flags_custom_lod', text='LOD', toggle=True)
                row.prop(data, 'flags_custom_hom', text='HOM', toggle=True)
                row = col.row(align=True)
                row.prop(data, 'flags_custom_musage', text='Multi Usage', toggle=True)
                row.prop(data, 'flags_custom_soccl', text='Sound Occluder', toggle=True)
                row.prop(data, 'flags_custom_hqexp', text='HQ Export', toggle=True)
            object_box.prop(data, 'lodref')
            object_box.prop(data, 'export_path')
            row, box = collapsible.draw(
                object_box,
                'object:userdata',
                'User Data',
                enabled=data.userdata != '',
                icon='VIEWZOOM'
            )
            PropClipOp.drawall(row, 'object.xray.userdata', data.userdata)
            if box:
                box = box.column(align=True)
                for line in data.userdata.splitlines():
                    box.label(line)

            if data.motions:
                split = object_box.split()
                split.alert = True
                split.prop(data, 'motions')
            _, box = collapsible.draw(
                object_box,
                'object:motions',
                'Motions (%d)' % len(data.motions_collection)
            )
            if box:
                row = box.row()
                row.template_list(
                    'XRayMotionList', 'name',
                    data, 'motions_collection',
                    data, 'motions_collection_index'
                )
                col = row.column(align=True)
                list_helper.draw_list_ops(
                    col, data,
                    'motions_collection', 'motions_collection_index',
                )

            if data.motionrefs:
                split = object_box.split()
                split.alert = True
                split.prop(data, 'motionrefs')
            _, box = collapsible.draw(
                object_box,
                'object:motionsrefs',
                'Motion Refs (%d)' % len(data.motionrefs_collection)
            )
            if box:
                row = box.row()
                row.template_list(
                    'UI_UL_list', 'name',
                    data, 'motionrefs_collection',
                    data, 'motionrefs_collection_index'
                )
                col = row.column(align=True)
                list_helper.draw_list_ops(
                    col, data,
                    'motionrefs_collection', 'motionrefs_collection_index',
                )

            box = object_box.box()
            box.prop(data.revision, 'owner', text='Owner')
            box.prop(data.revision, 'ctime_str', text='Created')

        if context.object.type in {'MESH', 'EMPTY'}:
            layout.prop(data, 'is_details', text='Details', toggle=True)
            if data.is_details:
                details.ui.draw_function(self, context)


class XRayMeshPanel(bpy.types.Panel):
    reg_order = 10

    bl_context = 'data'
    bl_label = 'Mesh'

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    bl_idname = "XRayMeshPanel"

    bl_category = XRayPanel.bl_category
    bl_parent_id = XRayPanel.bl_idname

    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return (
            context.active_object
            and context.active_object.type in {'MESH'}
            and not is_helper_object(context.active_object)
            and get_preferences().expert_mode
        )

    def draw(self, context):
        layout = self.layout
        data = context.object.data.xray
        row = layout.row(align=True)
        row.prop(data, 'flags_visible', text='Visible', toggle=True)
        row.prop(data, 'flags_locked', text='Locked', toggle=True)
        row.prop(data, 'flags_sgmask', text='SGMask', toggle=True)


class XRayEditHelperObjectPanel(bpy.types.Panel):
    reg_order = 10

    bl_context = 'object'
    bl_label = 'Edit Helper'

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    bl_idname = "XRayEditHelperObjectPanel"

    bl_category = XRayPanel.bl_category
    bl_parent_id = XRayPanel.bl_idname

    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return base_edit_helper.get_object_helper(context) is not None

    def draw(self, context):
        helper = base_edit_helper.get_object_helper(context)
        helper.draw(self.layout, context)


class XRayXrMenuTemplate(dynamic_menu.DynamicMenu):
    @staticmethod
    def parse(data, fparse):
        def push_dict(dct, split, value):
            if len(split) == 1:
                dct[split[0]] = value
            else:
                nested = dct.get(split[0], None)
                if nested is None:
                    dct[split[0]] = nested = dict()
                push_dict(nested, split[1:], value)

        def dict_to_array(dct):
            result = []
            root_result = []
            for (key, val) in dct.items():
                if isinstance(val, str):
                    root_result.append((key, val))
                else:
                    result.append((key, dict_to_array(val)))
            result = sorted(result, key=lambda e: e[0])
            root_result = sorted(root_result, key=lambda e: e[0])
            result.extend(root_result)
            return result

        tmp = dict()
        for (name, _) in fparse(data):
            split = name.split('\\')
            push_dict(tmp, split, name)
        return dict_to_array(tmp)

    @classmethod
    def create_cached(cls, pref_prop, fparse):
        return create_cached_file_data(
            lambda: getattr(get_preferences(), pref_prop, None),
            lambda data: cls.parse(data, fparse)
        )

    @classmethod
    def items_for_path(cls, path):
        data = cls.cached()
        if data is None:
            return []
        for pth in path:
            data = data[pth][1]
        return data


class XRayEShaderMenu(XRayXrMenuTemplate):
    bl_idname = 'io_scene_xray.dynmenu.eshader'
    prop_name = 'eshader'
    cached: XRayXrMenuTemplate.create_cached('gamemtl_file', parse_shaders)


class XRayCShaderMenu(XRayXrMenuTemplate):
    bl_idname = 'io_scene_xray.dynmenu.cshader'
    prop_name = 'cshader'
    cached: XRayXrMenuTemplate.create_cached('cshader_file', parse_shaders_xrlc)


class XRayGameMtlMenu(XRayXrMenuTemplate):
    bl_idname = 'io_scene_xray.dynmenu.gamemtl'
    prop_name = 'gamemtl'
    cached: XRayXrMenuTemplate.create_cached('gamemtl_file', parse_gamemtl)


def _gen_xr_selector(layout, data, name, text):
    row = layout.row(align=True)
    row.prop(data, name, text=text)
    dynamic_menu.DynamicMenu.set_layout_context_data(row, data)
    row.menu('io_scene_xray.dynmenu.' + name, icon='TRIA_DOWN')


class XRayMaterialPanel(bpy.types.Panel):
    reg_order = 10

    bl_context = 'material'
    bl_label = 'Material'

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    bl_idname = "XRayMaterialPanel"

    bl_category = XRayPanel.bl_category
    bl_parent_id = XRayPanel.bl_idname

    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.object.active_material

    def draw(self, context):
        layout = self.layout
        data = context.object.active_material.xray
        layout.prop(data, 'flags_twosided', text='Two sided', toggle=True)
        _gen_xr_selector(layout, data, 'eshader', 'EShader')
        _gen_xr_selector(layout, data, 'cshader', 'CShader')
        _gen_xr_selector(layout, data, 'gamemtl', 'GameMtl')


class XRayArmaturePanel(bpy.types.Panel):
    reg_order = 10

    bl_context = 'data'
    bl_label = 'Skeleton'

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    bl_idname = "XRayArmaturePanel"

    bl_category = XRayPanel.bl_category
    bl_parent_id = XRayPanel.bl_idname

    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return (
            context.active_object
            and context.active_object.type == 'ARMATURE'
        )

    def draw(self, context):
        layout = self.layout
        data = context.active_object.data.xray
        verdif = data.check_different_version_bones()
        if verdif != 0:
            from io_scene_xray.xray_inject import XRayBoneProperties
            layout.label(
                'Found bones, edited with '
                + XRayBoneProperties.ShapeProperties.fmt_version_different(verdif)
                + ' version of this plugin',
                icon='ERROR'
            )
        layout.prop(data, 'display_bone_shapes', toggle=True)

        lay = layout.column(align=True)
        lay.label(text='Fake Bones:')
        row = lay.row(align=True)
        row.operator(fake_bones.CreateFakeBones.bl_idname, text='Create', icon='CONSTRAINT_BONE')
        row.operator(fake_bones.DeleteFakeBones.bl_idname, text='Delete', icon='X')
        lay.operator(
            fake_bones.ToggleFakeBonesVisibility.bl_idname,
            text='Show/Hide',
            icon='VISIBLE_IPO_ON',
        )


class XRayBonePanel(bpy.types.Panel):
    reg_order = 10

    bl_context = 'bone'
    bl_label = 'Bone'

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    bl_idname = "XRayBonePanel"

    bl_category = XRayPanel.bl_category
    bl_parent_id = XRayPanel.bl_idname

    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return (
            context.active_object
            and context.active_object.type in {'ARMATURE'}
            and context.active_bone
        )

    def draw_header(self, context):
        layout = self.layout
        bone = context.active_object.data.bones[context.active_bone.name]
        data = bone.xray
        layout.prop(data, 'exportable', text='')

    def draw(self, context):
        layout = self.layout
        bone = context.active_object.data.bones[context.active_bone.name]
        data = bone.xray
        layout.enabled = data.exportable
        layout.prop(data, 'length')
        _gen_xr_selector(layout, data, 'gamemtl', 'GameMtl')
        box = layout.box()
        box.prop(data.shape, 'type', text='Shape Type')
        verdif = data.shape.check_version_different()
        if verdif != 0:
            box.label(
                'shape edited with '
                + data.shape.fmt_version_different(verdif)
                + ' version of this plugin',
                icon='ERROR'
            )
        bone_shape.HELPER.draw(box.column(align=True), context)

        row = box.row(align=True)
        row.prop(data.shape, 'flags_nopickable', text='No Pickable', toggle=True)
        row.prop(data.shape, 'flags_nophysics', text='No Physics', toggle=True)
        row.prop(data.shape, 'flags_removeafterbreak', text='Remove After Break', toggle=True)
        row.prop(data.shape, 'flags_nofogcollider', text='No Fog Collider', toggle=True)
        box = layout.box()
        box.prop(data.ikjoint, 'type', text='Joint Type')
        if int(data.ikjoint.type):
            box.prop(data, 'friction')
        col = box.column(align=True)
        col.prop(data.ikjoint, 'spring', text='Spring')
        col.prop(data.ikjoint, 'damping', text='Damping')
        col = box.column(align=True)
        col.label(text='Limit X:')
        col.prop(data.ikjoint, 'lim_x_spr', text='Spring')
        col.prop(data.ikjoint, 'lim_x_dmp', text='Damping')
        col = box.column(align=True)
        col.label(text='Limit Y:')
        col.prop(data.ikjoint, 'lim_y_spr', text='Spring')
        col.prop(data.ikjoint, 'lim_y_dmp', text='Damping')
        col = box.column(align=True)
        col.label(text='Limit Z:')
        col.prop(data.ikjoint, 'lim_z_spr', text='Spring')
        col.prop(data.ikjoint, 'lim_z_dmp', text='Damping')
        col = box.column(align=True)
        col.prop(data, 'ikflags_breakable', text='Breakable', toggle=True)
        if data.ikflags_breakable:
            col.prop(data.breakf, 'force', text='Force')
            col.prop(data.breakf, 'torque', text='Torque')
        box = layout.box()
        box.prop(data.mass, 'value')
        box.prop(data.mass, 'center')
        bone_center.HELPER.draw(box.column(align=True), context)


class XRayActionPanel(bpy.types.Panel):
    reg_order = 10

    bl_category = 'F-Curve'
    bl_space_type = 'DOPESHEET_EDITOR' if bpy.app.version >= (2, 78, 0) else 'GRAPH_EDITOR'
    bl_region_type = 'UI'
    bl_context = 'object'
    bl_label = 'Action'

    @classmethod
    def poll(cls, context):
        return (
            context.active_object and
            context.active_object.animation_data and
            context.active_object.animation_data.action
        )

    def draw(self, context):
        from .plugin import OpExportSkl
        layout = self.layout
        obj = context.active_object
        action = obj.animation_data.action
        data = action.xray
        box = layout.column(align=True) if data.autobake != 'off' else layout
        if data.autobake_auto:
            box.prop(data, 'autobake_auto', toggle=True, icon='RENDER_STILL')
        else:
            row = box.row(align=True)
            row.prop(data, 'autobake_auto', toggle=True, text='Auto Bake:', icon='RENDER_STILL')
            text = 'On' if data.autobake_on else 'Off'
            row.prop(data, 'autobake_on', toggle=True, text=text)
        if box != layout:
            if data.autobake_custom_refine:
                row = box.row(align=True)
                row.prop(
                    data, 'autobake_custom_refine',
                    toggle=True, text='', icon='BUTS'
                )
                row.prop(data, 'autobake_refine_location', text='L')
                row.prop(data, 'autobake_refine_rotation', text='R')
            else:
                box.prop(data, 'autobake_custom_refine', toggle=True)
        layout.prop(data, 'fps')
        if obj.type != 'ARMATURE':
            return
        layout.prop(data, 'speed')
        layout.prop(data, 'accrue')
        layout.prop(data, 'falloff')
        layout.prop(data, 'flags_fx', text='Type FX', toggle=True)
        if data.flags_fx:
            row = layout.row(align=True)
            row.label(text='Start Bone:')
            row.prop_search(data, 'bonestart_name', obj.pose, 'bones', text='')
            layout.prop(data, 'power', text='Power')
        else:
            row = layout.row(align=True)
            row.label(text='Bone Part:')
            row.prop_search(data, 'bonepart_name', obj.pose, 'bone_groups', text='')
            row = layout.row(align=True)
            row.prop(data, 'flags_stopatend', text='Stop', toggle=True)
            row.prop(data, 'flags_nomix', text='!Mix', toggle=True)
            row.prop(data, 'flags_syncpart', text='Sync', toggle=True)
        layout.context_pointer_set(OpExportSkl.bl_idname + '.action', action)
        layout.operator(OpExportSkl.bl_idname, icon='EXPORT')


class XRayScenePanel(bpy.types.Panel):
    bl_context = 'scene'
    bl_label = "Scene"

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    bl_idname = "XRayScenePanel"

    bl_category = XRayPanel.bl_category
    bl_parent_id = XRayPanel.bl_idname

    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        from .plugin import OpExportProject

        obj = context.scene
        data = obj.xray

        def gen_op(layout, text, enabled=True, icon='NONE'):
            if not enabled:
                layout = layout.split()
                layout.enabled = False
            props = layout.operator(OpExportProject.bl_idname, text=text, icon=icon)
            return props

        layout = self.layout
        row = layout.row()
        if not data.export_root:
            row.enabled = False
        selection = OpExportProject.find_objects(context, use_selection=True)
        if not selection:
            gen_op(row, 'No Roots Selected', enabled=False)
        elif len(selection) == 1:
            gen_op(
                row,
                text=selection[0].name + '.object',
                icon='OUTLINER_OB_MESH'
            ).use_selection = True
        else:
            gen_op(
                row,
                text='Selected Objects (%d)' % len(selection),
                icon='GROUP'
            ).use_selection = True
        scene = OpExportProject.find_objects(context)
        gen_op(
            row,
            text='Scene Export (%d)' % len(scene),
            icon='SCENE_DATA',
            enabled=len(scene) != 0
        ).use_selection = False
        lay = layout
        if not data.export_root:
            lay = lay.split()
            lay.alert = True
        lay.prop(data, 'export_root')
        row = layout.split(factor=0.33)
        row.label(text='Format Version:')
        row.row().prop(data, 'fmt_version', expand=True)
        _, box = collapsible.draw(layout, 'scene:object', 'Object Export Properties')
        if box:
            box.prop(data, 'object_export_motions')
            box.prop(data, 'object_texture_name_from_image_path')


class XRayColorizeMaterials(bpy.types.Operator):
    bl_idname = 'io_scene_xray.colorize_materials'
    bl_label = 'Colorize Materials'
    bl_description = 'Set a pseudo-random diffuse color for each surface (material)'

    seed: bpy.props.IntProperty(min=0, max=255)
    power: bpy.props.FloatProperty(default=0.5, min=0.0, max=1.0)

    def execute(self, context):
        from zlib import crc32

        objects = context.selected_objects
        if not objects:
            self.report({'ERROR'}, 'No objects selected')
            return {'CANCELLED'}

        seed = self.seed
        power = self.power
        materials = set()
        for obj in objects:
            for slot in obj.material_slots:
                materials.add(slot.material)

        for mat in materials:
            data = bytearray(mat.name, 'utf8')
            data.append(seed)
            hsh = crc32(data)
            mat.diffuse_color.hsv = (
                (hsh & 0xFF) / 0xFF,
                (((hsh >> 8) & 3) / 3 * 0.5 + 0.5) * power,
                ((hsh >> 2) & 1) * (0.5 * power) + 0.5
            )
        return {'FINISHED'}


class XRayMaterialToolsPanel(bpy.types.Panel):
    bl_label = 'Materials'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    bl_idname = "XRayMaterialToolsPanel"

    bl_category = XRayPanel.bl_category
    bl_parent_id = XRayPanel.bl_idname

    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, _context):
        self.layout.label(icon='PLUGIN')

    def draw(self, context):
        data = context.scene.xray
        layout = self.layout
        column = layout.column(align=True)
        operator = column.operator(XRayColorizeMaterials.bl_idname, icon='COLOR')
        operator.seed = data.materials_colorize_random_seed
        operator.power = data.materials_colorize_color_power
        column.prop(data, 'materials_colorize_random_seed', text='Seed')
        column.prop(data, 'materials_colorize_color_power', text='Power', slider=True)

