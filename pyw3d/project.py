# Copyright (C) 2016 William Hicks
#
# This file is part of Writing3D.
#
# Writing3D is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>

"""Tools for working with W3D projects
"""
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
import logging
import math
import os
import sys
from .features import W3DFeature
from .placement import W3DPlacement, W3DRotation, convert_to_blender_axes
from .validators import ListValidator, IsNumeric, OptionValidator,\
    IsBoolean, FeatureValidator, IsInteger, DictValidator
from .xml_tools import bool2text, text2tuple, attrib2bool, text2bool
from .objects import W3DObject
from .psys import W3DPAction
from .sounds import W3DSound
from .timeline import W3DTimeline
from .groups import W3DGroup
from .triggers import W3DTrigger
from .errors import BadW3DXML
from .blender_scripts import MOVE_TOGGLE_SCRIPT, ANGLES_SCRIPT
from .names import generate_light_object_name
from .pointer import setup_mouselook, setup_click
LOGGER = logging.getLogger("pyw3d")
try:
    import bpy
except ImportError:
    LOGGER.debug(
        "Module bpy not found. Loading pyw3d.project as standalone")


def clear_blender_scene():
    LOGGER.debug("Clearing all objects from Blender scene...")
    for obj in bpy.context.scene.objects:
        obj.select = True
    bpy.ops.object.delete()
    bpy.data.lamps[-1].name = generate_light_object_name("first")


def setup_blender_layout():
    """Put Blender interface in a convenient layout"""
    bpy.context.window.screen = bpy.data.screens["Game Logic"]
    # for area in bpy.context.window.screen.areas:
    #     if area.type == 'VIEW_3D':
    #         for space in area.spaces:
    #             space.region_3d.view_perspective = 'CAMERA'
    #             space.viewport_shade = "TEXTURED"


def add_key_movement(
        blender_object, move_name, key, direction, speed):
    """Convenience function for adding keyboard-controlled motion to
    Blender object

    :param blender_object: object to add motion to
    :param str move_name: Name for controller
    :param str key: Key used to activate motion
    :param int direction: 0, 1, 2 for x, y, z
    :param float speed: Speed of motion"""
    bpy.context.scene.objects.active = blender_object
    bpy.ops.logic.sensor_add(
        type="KEYBOARD",
        object=blender_object.name,
        name=move_name
    )
    blender_object.game.sensors[-1].name = move_name
    sensor = blender_object.game.sensors[move_name]
    sensor.key = key
    bpy.ops.logic.controller_add(
        type='LOGIC_AND',
        object=blender_object.name,
        name=move_name
    )
    blender_object.game.controllers[-1].name = move_name
    controller = blender_object.game.controllers[move_name]
    bpy.ops.logic.actuator_add(
        type="MOTION",
        object=blender_object.name,
        name=move_name
    )
    blender_object.game.actuators[-1].name = move_name
    actuator = blender_object.game.actuators[move_name]
    actuator.mode = "OBJECT_NORMAL"
    actuator.offset_location[direction] = speed
    actuator.use_local_location = True
    controller.link(actuator=actuator)
    controller.link(sensor=sensor)


class W3DProject(W3DFeature):
    """Represent entire project for display in W3D

    :param list objects: List of W3DObjects to be displayed
    :param list groups: Maps names of groups to lists of W3DObjects
    :param list timelines: List of W3DTimelines within project
    :param list sounds: List of W3DSounds within project
    :param list trigger_events: List of W3DEvents within project
    :param W3DPlacement camera_placement: Initial placement of camera
    :param W3DPlacement desktop_camera_placement: Initial placement of camera
    if project is run outside an actual W3D environment
    :param float far_clip: Far clip for camera (how far away from camera
    objects remain visible)
    :param tuple background: Color of background as an RGB tuple of 3 ints
    :param bool allow_movement: Allow user to navigate within project?
    :param bool allow_rotation: Allow user to rotate withing project?
    :param bool debug: Turn on debug-level logging
    :param bool profile: Turn on performance profiling
    :param dict wall_placements: Dictionary mapping names of walls to
    W3DPlacements specifying their position and orientation
    """

    # ui_order = [
    #     "camera_placement", "desktop_camera_placement", "far_clip",
    #     "allow_movement", "allow_rotation", "background"
    # ]
    ui_order = ["camera_placement"]

    argument_validators = {
        "objects": ListValidator(
            FeatureValidator(W3DObject),
            help_string="A list of W3DObjects in the project"
        ),
        "groups": ListValidator(
            FeatureValidator(W3DGroup),
            help_string="A list of W3DObjects in the project"
        ),
        "particle_actions": ListValidator(
            FeatureValidator(W3DPAction),
            help_string="A list of W3DPActions in the project"
        ),
        "timelines": ListValidator(
            FeatureValidator(W3DTimeline),
            help_string="A list of W3DTimelines in the project"),
        "sounds": ListValidator(
            FeatureValidator(W3DSound),
            help_string="A list of W3DSounds in the project"
        ),
        "trigger_events": ListValidator(
            FeatureValidator(W3DTrigger),
            help_string="A list of W3DTriggers in the project"
        ),
        "camera_placement": FeatureValidator(
            W3DPlacement,
            help_string="Orientation and position of camera"
        ),
        "desktop_camera_placement": FeatureValidator(
            W3DPlacement,
            help_string="Orientation and position of camera in desktop preview"
        ),
        "far_clip": IsNumeric(min_value=0),
        "background": ListValidator(
            IsInteger(min_value=0, max_value=255),
            required_length=3,
            help_string="Red, Green, Blue values"),
        "allow_movement": IsBoolean(),
        "allow_rotation": IsBoolean(),
        "debug": IsBoolean(),
        "profile": IsBoolean(),
        "wall_placements": DictValidator(
            OptionValidator(
                "Center", "FrontWall", "LeftWall", "RightWall", "FloorWall"),
            FeatureValidator(W3DPlacement),
            help_string="Dictionary mapping wall names to placements")
    }

    default_arguments = {
        "far_clip": 100,
        "background": (0, 0, 0),
        "allow_movement": True,
        "allow_rotation": True,
        "debug": False,
        "profile": False,
    }

    def __setitem__(self, key, value):
        if key == "debug":
            if value:
                LOGGER.setLevel(logging.DEBUG)
            else:
                LOGGER.setLevel(logging.WARNING)
        super().__setitem__(key, value)

    def __init__(self, *args, **kwargs):
        self.call_directory = kwargs.pop("call_directory", None)
        if self.call_directory is None:
            self.call_directory = os.path.normpath(
                os.path.dirname(sys.argv[0])
            )
        super(W3DProject, self).__init__(*args, **kwargs)
        os.chdir(self.call_directory)
        if "objects" not in self:
            self["objects"] = []
        if "groups" not in self:
            self["groups"] = []
        if "particle_actions" not in self:
            self["particle_actions"] = []
        if "timelines" not in self:
            self["timelines"] = []
        if "sounds" not in self:
            self["sounds"] = []
        if "trigger_events" not in self:
            self["trigger_events"] = []
        if "camera_placement" not in self:
            self["camera_placement"] = W3DPlacement(
                position=convert_to_blender_axes((0, 0, 0)))
        if "desktop_camera_placement" not in self:
            self["desktop_camera_placement"] = W3DPlacement(
                position=convert_to_blender_axes((0, 1.25, 8)))
        # NOTE: This currently does nothing. Need to call
        # _create_relative_to_objects for W3DPlacement in order to change
        # placements
        if "wall_placements" not in self:
            self["wall_placements"] = {
                "Center": W3DPlacement(
                    position=convert_to_blender_axes((0, 0, 0)),
                    rotation=W3DRotation(
                        rotation_mode="Axis",
                        rotation_vector=convert_to_blender_axes((0, 1, 0)),
                        rotation_angle=0
                    )
                ),
                "FrontWall": W3DPlacement(
                    position=convert_to_blender_axes((0, 0, -4)),
                    rotation=W3DRotation(
                        rotation_mode="LookAt",
                        rotation_vector=convert_to_blender_axes((0, 0, 0)),
                        up_vector=convert_to_blender_axes((0, 1, 0))
                    )
                ),
                "LeftWall": W3DPlacement(
                    position=convert_to_blender_axes((-4, 0, 0)),
                    rotation=W3DRotation(
                        rotation_mode="LookAt",
                        rotation_vector=convert_to_blender_axes((0, 0, 0)),
                        up_vector=convert_to_blender_axes((0, 1, 0))
                    )
                ),
                "RightWall": W3DPlacement(
                    position=convert_to_blender_axes((4, 0, 0)),
                    rotation=W3DRotation(
                        rotation_mode="LookAt",
                        rotation_vector=convert_to_blender_axes((0, 0, 0)),
                        up_vector=convert_to_blender_axes((0, 1, 0))
                    )
                ),
                "FloorWall": W3DPlacement(
                    position=convert_to_blender_axes((0, -4, 0)),
                    rotation=W3DRotation(
                        rotation_mode="LookAt",
                        rotation_vector=convert_to_blender_axes((0, 0, 0)),
                        up_vector=convert_to_blender_axes((0, 1, 0))
                    )
                )
            }

    def toXML(self):
        """Store W3DProject as W3D XML tree
        """
        project_root = ET.Element("Story", attrib={"version": "8"})
        object_root = ET.SubElement(project_root, "ObjectRoot")
        for object_ in self["objects"]:
            object_.toXML(object_root)
        group_root = ET.SubElement(project_root, "GroupRoot")
        for group in self["groups"]:
            group.toXML(group_root)
        timeline_root = ET.SubElement(project_root, "TimelineRoot")
        for timeline in self["timelines"]:
            timeline.toXML(timeline_root)
        sound_root = ET.SubElement(project_root, "SoundRoot")
        for sound in self["sounds"]:
            sound.toXML(sound_root)
        paction_root = ET.SubElement(project_root, "ParticleActionRoot")
        for paction in self["particle_actions"]:
            paction.toXML(paction_root)
        event_root = ET.SubElement(project_root, "EventRoot")
        for trigger in self["trigger_events"]:
            trigger.toXML(event_root)
        global_node = ET.SubElement(project_root, "Global")
        camera_node = ET.SubElement(
            global_node, "CameraPos", attrib={
                "far-clip": str(self["far_clip"])})
        self["camera_placement"].toXML(camera_node)
        camera_node = ET.SubElement(
            global_node, "CaveCameraPos", attrib={
                "far-clip": str(self["far_clip"])})
        self["desktop_camera_placement"].toXML(camera_node)
        ET.SubElement(global_node, "Background", attrib={
            "color": "{}, {}, {}".format(*self["background"])})
        ET.SubElement(
            global_node, "WandNavigation",
            attrib={
                "allow-rotation": bool2text(self["allow_rotation"]),
                "allow-movement": bool2text(self["allow_movement"])
            }
        )
        debug_node = ET.SubElement(global_node, "Debug")
        debug_node.text = bool2text(self["debug"])
        profile_node = ET.SubElement(global_node, "Profile")
        profile_node.text = bool2text(self["profile"])
        wall_root = ET.SubElement(project_root, "PlacementRoot")
        for wall, placement in self["wall_placements"].items():
            place_root = placement.toXML(wall_root)
            place_root.attrib["name"] = wall

        return project_root

    @classmethod
    def fromXML(project_class, project_root, call_directory=None):
        """Create W3DProject from Story node of W3D XML

        :param :py:class:xml.etree.ElementTree.Element project_root
        """
        new_project = project_class(call_directory=call_directory)
        object_root = project_root.find("ObjectRoot")
        if object_root is not None:
            for child in object_root.findall("Object"):
                new_project["objects"].append(W3DObject.fromXML(child))
        group_root = project_root.find("GroupRoot")
        if group_root is not None:
            for child in group_root.findall("Group"):
                new_project["groups"].append(W3DGroup.fromXML(child))
        timeline_root = project_root.find("TimelineRoot")
        if timeline_root is not None:
            for child in timeline_root.findall("Timeline"):
                new_project["timelines"].append(W3DTimeline.fromXML(child))
        sound_root = project_root.find("SoundRoot")
        if sound_root is not None:
            for child in sound_root.findall("Sound"):
                new_project["sounds"].append(W3DSound.fromXML(child))
        paction_root = project_root.find("ParticleActionRoot")
        if paction_root is not None:
            for child in paction_root.findall("ParticleActionList"):
                new_project["particle_actions"].append(
                    W3DPAction.fromXML(child))
        trigger_root = project_root.find("EventRoot")
        if trigger_root is not None:
            for child in trigger_root.findall("EventTrigger"):
                new_project["trigger_events"].append(W3DTrigger.fromXML(child))

        global_root = project_root.find("Global")
        if global_root is None:
            raise BadW3DXML("Story root has no Global node")

        camera_node = global_root.find("CaveCameraPos")
        if camera_node is None:
            raise BadW3DXML("Global node has no CaveCameraPos child")
        if "far-clip" in camera_node.attrib:
            new_project["far_clip"] = float(camera_node.attrib["far-clip"])
        place_node = camera_node.find("Placement")
        if camera_node is None:
            raise BadW3DXML("CameraPos node has no Placement child")
        new_project["camera_placement"] = W3DPlacement.fromXML(place_node)

        camera_node = global_root.find("CameraPos")
        if camera_node is None:
            raise BadW3DXML("Global node has no CameraPos child")
        if "far-clip" in camera_node.attrib:
            new_project["far_clip"] = float(camera_node.attrib["far-clip"])
        place_node = camera_node.find("Placement")
        if camera_node is None:
            raise BadW3DXML("CameraPos node has no Placement child")
        new_project["desktop_camera_placement"] = W3DPlacement.fromXML(
            place_node)

        bg_node = global_root.find("Background")
        if bg_node is None:
            raise BadW3DXML("Global node has no Background child")
        if "color" in bg_node.attrib:
            new_project["background"] = text2tuple(
                bg_node.attrib["color"],
                evaluator=int
            )

        wand_node = global_root.find("WandNavigation")
        if wand_node is None:
            raise BadW3DXML("Global node has no WandNavigation child")
        new_project["allow_rotation"] = attrib2bool(
            wand_node, "allow-rotation", default=False)
        new_project["allow_movement"] = attrib2bool(
            wand_node, "allow-movement", default=False)

        debug_node = global_root.find("Debug")
        if debug_node is not None:
            new_project["debug"] = text2bool(debug_node.text)
        profile_node = global_root.find("Profile")
        if profile_node is not None:
            new_project["profile"] = text2bool(profile_node.text)

        wall_root = project_root.find("PlacementRoot")
        for placement in wall_root.findall("Placement"):
            try:
                wall_name = placement.attrib["name"]
            except KeyError:
                raise BadW3DXML(
                    "Placements within PlacementRoot must specify name")
            new_project["wall_placements"][
                wall_name] = W3DPlacement.fromXML(placement)
        return new_project

    @classmethod
    def fromXML_file(project_class, filename):
        """Create W3DProject from XML file of given filename

        :param str filename: Filename of XML file for project
        """
        # For relative paths...
        call_directory = os.path.normpath(os.path.dirname(filename))
        return project_class.fromXML(
            ET.parse(filename).getroot(), call_directory)

    def toprettyxml(self):
        tree = self.toXML()
        xml_string = ET.tostring(tree, encoding="unicode")
        xml_string = minidom.parseString(xml_string).toprettyxml()
        # WARNING: Need to make sure that this doesn't miss up paragraphs of
        # text
        xml_string = "\n".join(
            [line for line in xml_string.split("\n") if line.strip()])
        return xml_string

    def save_XML(self, filename):
        with open(filename, "w") as file_:
            file_.write(self.toprettyxml())

    def sort_groups(self):
        """Sort groups such that no group contains a later group"""
        new_groups = []
        while len(self["groups"]):
            group = self["groups"].pop()
            cur_len = len(new_groups)
            for i in range(cur_len):
                if group["name"] in new_groups[i]["groups"]:
                    new_groups.insert(i, group)
                    break
            if cur_len == len(new_groups):
                new_groups.append(group)
        self["groups"] = new_groups

    def setup_controls(self):
        self.add_move_toggle()

        add_key_movement(self.main_camera, "Forward", "W", 2, -0.15)
        add_key_movement(self.main_camera, "Backward", "S", 2, 0.15)
        add_key_movement(self.main_camera, "Left", "A", 0, -0.15)
        add_key_movement(self.main_camera, "Right", "D", 0, 0.15)

    def setup_scripts(self):
        """Load pre-written scripts into blend"""
        bpy.data.texts.new("angles.py")
        script = bpy.data.texts["angles.py"]
        script.write(ANGLES_SCRIPT)
        return script

    def setup_camera(self):
        bpy.ops.object.camera_add(rotation=(math.pi / 2, 0, 0))
        bpy.data.cameras[-1].clip_end = self["far_clip"]
        # TODO: Does this need to be converted to meters?
        self.main_camera = bpy.context.object
        self.main_camera.name = "CAMERA"
        self.main_camera.layers = [layer == 1 for layer in range(1, 21)]
        self["desktop_camera_placement"].place(self.main_camera)
        bpy.ops.object.add(
            type="EMPTY",
            location=(0, 0, 0),
            layers=[layer == 3 for layer in range(1, 21)]
        )
        vr_center = bpy.context.object
        vr_center.name = "VRCENTER"
        self.main_camera.parent = vr_center
        bpy.data.scenes['Scene'].camera = self.main_camera
        bpy.data.scenes['Scene'].game_settings.resolution_x = 800
        bpy.data.scenes['Scene'].game_settings.resolution_y = 600
        bpy.data.scenes['Scene'].game_settings.frame_type = "EXTEND"

    def setup_settings(self):
        """Put any global settings in w3d_settings.py"""
        bpy.data.texts.new("w3d_settings.py")
        settings_script = bpy.data.texts["w3d_settings.py"]
        script_text = [
            "import logging",
            "W3D_DEBUG = {}".format(self["debug"]),
            "W3D_PROFILE = {}".format(self["profile"]),
            "W3D_LOG = logging.getLogger('W3D')",
            "if W3D_DEBUG:",
            "    logging.basicConfig(",
            "        level=logging.DEBUG,",
            "        format='%(asctime)-15s %(levelname)8s %(name)s "
            "%(message)s')",
        ]
        settings_script.write("\n".join(script_text))

    def add_move_toggle(self):
        bpy.context.scene.objects.active = self.main_camera
        bpy.ops.logic.controller_add(
            type='PYTHON',
            object=self.main_camera.name,
            name="move_toggle")
        self.main_camera.game.controllers[-1].name = "move_toggle"
        controller = self.main_camera.game.controllers["move_toggle"]
        controller.mode = "MODULE"
        controller.module = "move.move_toggle"

        bpy.ops.object.game_property_new(
            type="BOOL",
            name="toggle_movement"
        )
        self.main_camera.game.properties["toggle_movement"].value = False
        bpy.ops.logic.sensor_add(
            type="KEYBOARD",
            object=self.main_camera.name,
            name="toggle_movement"
        )
        self.main_camera.game.sensors[-1].name = "toggle_movement"
        sensor = self.main_camera.game.sensors["toggle_movement"]
        sensor.key = "TAB"

        bpy.data.texts.new("move.py")
        script = bpy.data.texts["move.py"]
        script.write(MOVE_TOGGLE_SCRIPT)

        controller.link(sensor=sensor)

    def blend(self):
        """Create representation of W3DProject in Blender"""
        # if self["debug"]:
        #     LOGGER.debug("Validating project")
        #     self.validate(project=self)
        #     LOGGER.debug("Project validation complete")
        if self["profile"]:
            import cProfile
            cProfile.runctx(
                'self._blend()', {}, {"self": self}, "profile.out"
            )
        else:
            self._blend()

    def _blend(self):
        clear_blender_scene()
        bpy.data.scenes["Scene"].game_settings.physics_gravity = 0
        bpy.data.scenes["Scene"].game_settings.material_mode = "GLSL"
        bpy.data.scenes["Scene"].layers = [
            layer in (1, 3, 20) for layer in range(1, 21)]
        # TODO: Handle non-standard wall placements
        W3DPlacement._create_relative_to_objects()
        self.setup_settings()
        self.setup_camera()
        self.setup_controls()
        self.setup_scripts()
        setup_mouselook(self)
        setup_click(self)
        self.sort_groups()
        bpy.data.texts.new("group_defs.py")  # Script for assigning group names
        bpy.data.worlds["World"].horizon_color = [
            value / 255.0 for value in self["background"]
        ]
        # bpy.data.worlds["World"].ambient_color = [
        #     value / 255.0 for value in self["background"]
        # ]

        # Create assets
        for sound in self["sounds"]:
            sound.blend()

        # Create Objects
        for group in self["groups"]:
            group.blend_objects()
        for group in self["groups"]:
            group.blend_groups()
        for object_ in self["objects"]:
            object_.blend()
        bpy.context.scene.update()

        # Create particle action logic
        for paction in self["particle_actions"]:
            paction.blend()

        # Create Activators
        for timeline in self["timelines"]:
            timeline.blend()
        for trigger in self["trigger_events"]:
            trigger.blend()
        # Write any necessary game engine logic for Activators
        for timeline in self["timelines"]:
            timeline.write_blender_logic()
        for object_ in self["objects"]:
            if object_["link"] is not None:
                object_["link"].write_blender_logic()
        for trigger in self["trigger_events"]:
            trigger.write_blender_logic()
        # Link game engine logic bricks for Activators
        for timeline in self["timelines"]:
            timeline.link_blender_logic()
        for object_ in self["objects"]:
            if object_["link"] is not None:
                object_["link"].link_blender_logic()
        for trigger in self["trigger_events"]:
            trigger.link_blender_logic()

        bpy.context.scene.update()
        setup_blender_layout()
        bpy.ops.file.pack_all()
