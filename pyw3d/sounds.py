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

"""Tools for working with sounds in W3D projects
"""
import logging
LOGGER = logging.getLogger("pyw3d")
import math
import xml.etree.ElementTree as ET
from functools import total_ordering
from .features import W3DFeature
from .validators import IsNumeric, OptionValidator, ValidPyString, IsBoolean,\
    ValidFile
from .errors import ConsistencyError, BadW3DXML
from .xml_tools import bool2text, text2bool
from .names import generate_blender_sound_name
try:
    import bpy
    from _bpy import ops as ops_module
    BPY_OPS_CALL = ops_module.call
except ImportError:
    pass


def audio_playback_object():
    """Get empty used to coordinate audio playback in Blender"""
    try:
        logging.debug("AUDIO object already exists")
        return bpy.data.objects["AUDIO"]
    except KeyError:
        logging.debug("Creating AUDIO object")
        audio_object = bpy.data.objects.new("AUDIO", None)
        bpy.context.scene.objects.link(audio_object)
        audio_object.name = "AUDIO"
        return audio_object


def generate_blender_audio_from_file(filename):
    try:
        return generate_blender_audio_from_file._sounds[
            filename]
    except AttributeError:
        generate_blender_audio_from_file._sounds = {}
    except KeyError:
        BPY_OPS_CALL(
            "sound.open", None, {'filepath': filename}
        )
        generate_blender_audio_from_file._sounds[
            filename] = bpy.data.sounds[0]
    return generate_blender_audio_from_file(filename)


@total_ordering
class W3DSound(W3DFeature):
    """Store data on a sound to be used in the W3D

    :param str name: Unique name of this sound object
    :param str filename: File from which to take audio
    :param bool autostart: Start sound when project starts?
    :param str movement_mode: One of Positional or Fixed, determining if the
    sound is ambient or coming from an apparent position
    :param int repetitions: Number of times to repeat sound. Negative value
    indicates sound should loop forever
    :param float frequency_scale: Factor by which to scale frequency (0.5 to 2)
    :param float volume_scale: Factor by which to scale volume (must be
    0.0-1.0)
    :param float pan: Stereo panning left to right (-1.0 to 1.0)
    """
    argument_validators = {
        "name": ValidPyString(),
        "filename": ValidFile(),
        "autostart": IsBoolean(),
        "movement_mode": OptionValidator("Positional", "Fixed"),
        "repetitions": IsNumeric(),
        "frequency_scale": IsNumeric(min_value=0.5, max_value=2),
        "volume_scale": IsNumeric(min_value=0, max_value=2),
        "pan": IsNumeric(min_value=-1, max_value=1)
    }
    default_arguments = {
        "autostart": False,
        "movement_mode": "Positional",
        "repetitions": 0,
        "frequency_scale": 1,
        "volume_scale": 1,
        "pan": 0}

    def toXML(self, all_sounds_root):
        """Store W3DSound as Sound node within SoundRoot node

        :param :py:class:xml.etree.ElementTree.Element all_sounds_root
        """
        attrib = {}
        try:
            attrib["name"] = str(self["name"])
        except KeyError:
            raise ConsistencyError(
                'W3DSound must set a value for "name" key')
        try:
            attrib["filename"] = str(self["filename"])
        except KeyError:
            raise ConsistencyError(
                'W3DSound must set a value for "filename" key')
        if not self.is_default("autostart"):
            attrib["autostart"] = bool2text(self["autostart"])
        sound_root = ET.SubElement(all_sounds_root, "Sound", attrib=attrib)

        node = ET.SubElement(sound_root, "Mode")
        ET.SubElement(node, self["movement_mode"])

        node = ET.SubElement(sound_root, "Repeat")
        if self["repetitions"] == 0:
            ET.SubElement(node, "NoRepeat")
        if self["repetitions"] < 0:
            ET.SubElement(node, "RepeatForever")
        if self["repetitions"] > 0:
            node = ET.SubElement(node, "RepeatNum")
            node.text = str(self["repetitions"])

        settings = {}
        attrib_map = {
            "frequency_scale": "freq", "volume_scale": "volume", "pan": "pan"}
        for key, xml_attrib in attrib_map.items():
            if not self.is_default(key):
                settings[xml_attrib] = str(self[key])
        node = ET.SubElement(sound_root, "Settings", attrib=settings)

        return sound_root

    @classmethod
    def fromXML(sound_class, sound_root):
        """Create W3DSound from Sound node

        :param :py:class:xml.etree.ElementTree.Element sound_root
        """
        new_sound = sound_class()
        try:
            new_sound["name"] = sound_root.attrib["name"]
        except KeyError:
            raise BadW3DXML(
                "Sound node must specify name attribute")
        try:
            new_sound["filename"] = sound_root.attrib["filename"]
        except KeyError:
            raise BadW3DXML(
                "Sound node must specify filename attribute")
        if "autostart" in sound_root.attrib:
            new_sound["autostart"] = text2bool(sound_root.attrib["autostart"])

        movement_node = sound_root.find("Mode")
        if movement_node is None:
            raise BadW3DXML(
                "Sound node must contain Mode child node")
        for mode in new_sound.argument_validators[
                "movement_mode"].valid_options:
            if movement_node.find(mode) is not None:
                new_sound["movement_mode"] = mode
                break
        if "movement_mode" not in new_sound:
            raise BadW3DXML(
                "Mode node must contain child node specifying a valid mode"
            )

        repeat_node = sound_root.find("Repeat")
        if repeat_node is None:
            raise BadW3DXML(
                "Sound node must contain Repeat child node")
        if repeat_node.find("NoRepeat") is not None:
            new_sound["repetitions"] = 0
        elif repeat_node.find("RepeatForever") is not None:
            new_sound["repetitions"] = -1
        else:
            repeat_node = repeat_node.find("RepeatNum")
            try:
                new_sound["repetitions"] = int(repeat_node.text.strip())
            except AttributeError:
                raise BadW3DXML(
                    "Repeat node must contain child node specifying"
                    " repetitions")

        settings_node = sound_root.find("Settings")
        if settings_node is None:
            raise BadW3DXML(
                "Sound node must have Settings child node")
        xml_map = {
            "freq": "frequency_scale", "volume": "volume_scale", "pan": "pan"}
        for key, value in xml_map.items():
            if key in settings_node.attrib:
                new_sound[value] = float(settings_node.attrib[key])

        return new_sound

    def blend(self):
        """Create representation of W3DSound in Blender"""
        sound_name = generate_blender_sound_name(self["name"])
        LOGGER.debug("Adding sound {} to blend file".format(sound_name))
        blender_sound = generate_blender_audio_from_file(
            self["filename"]
        )
        blender_sound.name = sound_name

        LOGGER.debug("Creating actuator for {}".format(sound_name))
        bpy.context.scene.objects.active = audio_playback_object()
        BPY_OPS_CALL(
            "logic.actuator_add", None,
            {
                'type': 'SOUND',
                'object': "AUDIO",
                'name': sound_name
            }
        )
        actuator = audio_playback_object().game.actuators[-1]
        actuator.name = sound_name
        actuator.sound = blender_sound
        actuator.use_sound_3d = (self["movement_mode"] == "Positional")
        if self["repetitions"] < 0:
            actuator.mode = "LOOPSTOP"
        else:
            actuator.mode = "PLAYSTOP"
        # TODO: Deal with non-infinite loops

        actuator.pitch = 12 * math.log(self["frequency_scale"], 2)
        actuator.volume = self["volume_scale"]
        if not self.is_default("pan"):
            LOGGER.info("Panning audio is not supported at this time")
        return audio_playback_object()
