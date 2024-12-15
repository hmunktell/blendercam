"""Fabex 'info_props.py'

'CAM Info Properties'
"""

from datetime import timedelta

import bpy
from bpy.props import (
    StringProperty,
    FloatProperty,
)
from bpy.types import (
    PropertyGroup,
)
from ..utils import (
    update_operation,
)
from ..constants import (
    PRECISION,
    CHIPLOAD_PRECISION,
    MAX_OPERATION_TIME,
)


class CAM_INFO_Properties(PropertyGroup):

    warnings: StringProperty(
        name="Warnings",
        description="Warnings",
        default="",
        update=update_operation,
    )

    chipload: FloatProperty(
        name="Chipload",
        description="Calculated chipload",
        default=0.0,
        unit="LENGTH",
        precision=CHIPLOAD_PRECISION,
    )

    duration: FloatProperty(
        name="Estimated Time",
        default=0.01,
        min=0.0000,
        max=MAX_OPERATION_TIME,
        precision=PRECISION,
        unit="TIME",
    )
