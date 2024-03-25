# blender CAM gcodepath.py (c) 2012 Vilem Novak
#
# ***** BEGIN GPL LICENSE BLOCK *****
#
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.	See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ***** END GPL LICENCE BLOCK *****

# here is the Gcode generaton

import bpy
import time
import mathutils
import math
from math import *
from mathutils import *

import numpy

from . import chunk
from .chunk import *
from .utils import USE_PROFILER

from . import collision
from .collision import *

from . import simple
from .simple import *

from .async_op import progress_async

from . import bridges
from .bridges import *

from . import utils
from . import strategy

from . import pattern
from .pattern import *

from . import polygon_utils_cam
from .polygon_utils_cam import *

from . import image_utils
from .image_utils import *
from .opencamlib.opencamlib import *
from .nc import iso


def pointonline(a, b, c, tolerence):
    b = b - a  # convert to vector by subtracting origin
    c = c - a
    dot_pr = b.dot(c)  # b dot c
    norms = numpy.linalg.norm(b) * numpy.linalg.norm(c)  # find norms
    # find angle between the two vectors
    angle = (numpy.rad2deg(numpy.arccos(dot_pr / norms)))
    if angle > tolerence:
        return False
    else:
        return True


def exportGcodePath(filename, vertslist, operations):
    """exports gcode with the heeks nc adopted library."""
    print("EXPORT")
    progress('exporting gcode file')
    t = time.time()
    s = bpy.context.scene
    m = s.cam_machine
    enable_dust = False
    enable_hold = False
    enable_mist = False
    # find out how many files will be done:

    split = False

    totops = 0
    findex = 0
    if m.eval_splitting:  # detect whether splitting will happen
        for mesh in vertslist:
            totops += len(mesh.vertices)
        print(totops)
        if totops > m.split_limit:
            split = True
            filesnum = ceil(totops / m.split_limit)
            print('file will be separated into %i files' % filesnum)
    print('1')

    basefilename = bpy.data.filepath[:-
                                     len(bpy.path.basename(bpy.data.filepath))] + safeFileName(filename)

    extension = '.tap'
    if m.post_processor == 'ISO':
        from .nc import iso as postprocessor
    if m.post_processor == 'MACH3':
        from .nc import mach3 as postprocessor
    elif m.post_processor == 'EMC':
        extension = '.ngc'
        from .nc import emc2b as postprocessor
    elif m.post_processor == 'FADAL':
        extension = '.tap'
        from .nc import fadal as postprocessor
    elif m.post_processor == 'GRBL':
        extension = '.gcode'
        from .nc import grbl as postprocessor
    elif m.post_processor == 'HM50':
        from .nc import hm50 as postprocessor
    elif m.post_processor == 'HEIDENHAIN':
        extension = '.H'
        from .nc import heiden as postprocessor
    elif m.post_processor == 'HEIDENHAIN530':
        extension = '.H'
        from .nc import heiden530 as postprocessor
    elif m.post_processor == 'TNC151':
        from .nc import tnc151 as postprocessor
    elif m.post_processor == 'SIEGKX1':
        from .nc import siegkx1 as postprocessor
    elif m.post_processor == 'CENTROID':
        from .nc import centroid1 as postprocessor
    elif m.post_processor == 'ANILAM':
        from .nc import anilam_crusader_m as postprocessor
    elif m.post_processor == 'GRAVOS':
        extension = '.nc'
        from .nc import gravos as postprocessor
    elif m.post_processor == 'WIN-PC':
        extension = '.din'
        from .nc import winpc as postprocessor
    elif m.post_processor == 'SHOPBOT MTC':
        extension = '.sbp'
        from .nc import shopbot_mtc as postprocessor
    elif m.post_processor == 'LYNX_OTTER_O':
        extension = '.nc'
        from .nc import lynx_otter_o as postprocessor

    if s.unit_settings.system == 'METRIC':
        unitcorr = 1000.0
    elif s.unit_settings.system == 'IMPERIAL':
        unitcorr = 1 / 0.0254
    else:
        unitcorr = 1
    rotcorr = 180.0 / pi

    use_experimental = bpy.context.preferences.addons['cam'].preferences.experimental

    def startNewFile():
        fileindex = ''
        if split:
            fileindex = '_' + str(findex)
        filename = basefilename + fileindex + extension
        print("writing: ", filename)
        c = postprocessor.Creator()

        # process user overrides for post processor settings

        if use_experimental and isinstance(c, iso.Creator):
            c.output_block_numbers = m.output_block_numbers
            c.start_block_number = m.start_block_number
            c.block_number_increment = m.block_number_increment

        c.output_tool_definitions = m.output_tool_definitions
        c.output_tool_change = m.output_tool_change
        c.output_g43_on_tool_change_line = m.output_g43_on_tool_change

        c.file_open(filename)

        # unit system correction
        ###############
        if s.unit_settings.system == 'METRIC':
            c.metric()
        elif s.unit_settings.system == 'IMPERIAL':
            c.imperial()

        # start program
        c.program_begin(0, filename)
        c.flush_nc()
        c.comment('G-code generated with BlenderCAM and NC library')
        # absolute coordinates
        c.absolute()

        # work-plane, by now always xy,
        c.set_plane(0)
        c.flush_nc()

        return c

    c = startNewFile()
    # [o.cutter_id,o.cutter_dameter,o.cutter_type,o.cutter_flutes]
    last_cutter = None

    processedops = 0
    last = Vector((0, 0, 0))
    cut_distance = 0
    for i, o in enumerate(operations):

        if use_experimental and o.output_header:
            lines = o.gcode_header.split(';')
            for aline in lines:
                c.write(aline + '\n')

        free_height = o.movement.free_height  # o.max.z+
        if o.movement.useG64:
            c.set_path_control_mode(2, round(o.movement.G64 * 1000, 5), 0)

        mesh = vertslist[i]
        verts = mesh.vertices[:]
        if o.machine_axes != '3':
            rots = mesh.shape_keys.key_blocks['rotations'].data

        # spindle rpm and direction
        ###############
        if o.movement.spindle_rotation == 'CW':
            spdir_clockwise = True
        else:
            spdir_clockwise = False

        # write tool, not working yet probably
        # print (last_cutter)
        if m.output_tool_change and last_cutter != [o.cutter_id, o.cutter_diameter, o.cutter_type, o.cutter_flutes]:
            if m.output_tool_change:
                c.tool_change(o.cutter_id)

        if m.output_tool_definitions:
            c.comment('Tool: D = %s type %s flutes %s' % (
                strInUnits(o.cutter_diameter, 4), o.cutter_type, o.cutter_flutes))

        c.flush_nc()

        last_cutter = [o.cutter_id, o.cutter_diameter, o.cutter_type, o.cutter_flutes]
        if o.cutter_type not in ['LASER', 'PLASMA']:
            if o.enable_hold:
                c.write('(Hold Down)\n')
                lines = o.gcode_start_hold_cmd.split(';')
                for aline in lines:
                    c.write(aline + '\n')
                enable_hold = True
                stop_hold = o.gcode_stop_hold_cmd
            if o.enable_mist:
                c.write('(Mist)\n')
                lines = o.gcode_start_mist_cmd.split(';')
                for aline in lines:
                    c.write(aline + '\n')
                enable_mist = True
                stop_mist = o.gcode_stop_mist_cmd

            c.spindle(o.spindle_rpm, spdir_clockwise)  # start spindle
            c.write_spindle()
            c.flush_nc()
            c.write('\n')

            if o.enable_dust:
                c.write('(Dust collector)\n')
                lines = o.gcode_start_dust_cmd.split(';')
                for aline in lines:
                    c.write(aline + '\n')
                enable_dust = True
                stop_dust = o.gcode_stop_dust_cmd

        if m.spindle_start_time > 0:
            c.dwell(m.spindle_start_time)

        #        c.rapid(z=free_height*1000)  #raise the spindle to safe height
        fmh = round(free_height * unitcorr, 2)
        if o.cutter_type not in ['LASER', 'PLASMA']:
            c.write('G00 Z' + str(fmh) + '\n')
        if o.enable_A:
            if o.rotation_A == 0:
                o.rotation_A = 0.0001
            c.rapid(a=o.rotation_A * 180 / math.pi)

        if o.enable_B:
            if o.rotation_B == 0:
                o.rotation_B = 0.0001
            c.rapid(a=o.rotation_B * 180 / math.pi)

        c.write('\n')
        c.flush_nc()

        # dhull c.feedrate(unitcorr*o.feedrate)

        # commands=[]
        m = bpy.context.scene.cam_machine

        millfeedrate = min(o.feedrate, m.feedrate_max)

        millfeedrate = unitcorr * max(millfeedrate, m.feedrate_min)
        plungefeedrate = millfeedrate * o.plunge_feedrate / 100
        freefeedrate = m.feedrate_max * unitcorr
        fadjust = False
        if o.do_simulation_feedrate and mesh.shape_keys is not None \
                and mesh.shape_keys.key_blocks.find('feedrates') != -1:
            shapek = mesh.shape_keys.key_blocks['feedrates']
            fadjust = True

        if m.use_position_definitions:  # dhull
            last = Vector((m.starting_position.x, m.starting_position.y, m.starting_position.z))

        lastrot = Euler((0, 0, 0))
        duration = 0.0
        f = 0.1123456  # nonsense value, so first feedrate always gets written
        fadjustval = 1  # if simulation load data is Not present

        downvector = Vector((0, 0, -1))
        plungelimit = (pi / 2 - o.plunge_angle)

        scale_graph = 0.05  # warning this has to be same as in export in utils!!!!

        ii = 0
        offline = 0
        online = 0
        cut = True  # active cut variable for laser or plasma
        shapes = 0
        for vi, vert in enumerate(verts):
            # skip the first vertex if this is a chained operation
            # ie: outputting more than one operation
            # otherwise the machine gets sent back to 0,0 for each operation which is unecessary
            shapes += 1  # Count amount of shapes
            if i > 0 and vi == 0:
                continue
            v = vert.co
            # redundant point on line detection
            if o.remove_redundant_points and o.strategy != 'DRILL':
                nextv = v
                if ii == 0:
                    firstv = v  # only happens once
                elif ii == 1:
                    middlev = v
                else:
                    if pointonline(firstv, middlev, nextv, o.simplify_tol / 1000):
                        middlev = nextv
                        online += 1
                        continue
                    else:  # create new start point with the last tested point
                        ii = 0
                        offline += 1
                        firstv = nextv
                ii += 1
            # end of redundant point on line detection
            if o.machine_axes != '3':
                v = v.copy()  # we rotate it so we need to copy the vector
                r = Euler(rots[vi].co)
                # conversion to N-axis coordinates
                # this seems to work correctly for 4 axis.
                rcompensate = r.copy()
                rcompensate.x = -r.x
                rcompensate.y = -r.y
                rcompensate.z = -r.z
                v.rotate(rcompensate)

                if r.x == lastrot.x:
                    ra = None
                else:

                    ra = r.x * rotcorr

                if r.y == lastrot.y:
                    rb = None
                else:
                    rb = r.y * rotcorr

            if vi > 0 and v.x == last.x:
                vx = None
            else:
                vx = v.x * unitcorr
            if vi > 0 and v.y == last.y:
                vy = None
            else:
                vy = v.y * unitcorr
            if vi > 0 and v.z == last.z:
                vz = None
            else:
                vz = v.z * unitcorr

            if fadjust:
                fadjustval = shapek.data[vi].co.z / scale_graph

            # v=(v.x*unitcorr,v.y*unitcorr,v.z*unitcorr)
            vect = v - last
            l = vect.length
            if vi > 0 and l > 0 and downvector.angle(vect) < plungelimit:
                if f != plungefeedrate or (fadjust and fadjustval != 1):
                    f = plungefeedrate * fadjustval
                    c.feedrate(f)

                if o.machine_axes == '3':
                    if o.cutter_type in ['LASER', 'PLASMA']:
                        if not cut:
                            if o.cutter_type == 'LASER':
                                c.write("(*************dwell->laser on)\n")
                                c.write("G04 P" + str(round(o.Laser_delay, 2)) + "\n")
                                c.write(o.Laser_on + '\n')
                            elif o.cutter_type == 'PLASMA':
                                c.write("(*************dwell->PLASMA on)\n")
                                plasma_delay = round(o.Plasma_delay, 5)
                                if plasma_delay > 0:
                                    c.write("G04 P" + str(plasma_delay) + "\n")
                                c.write(o.Plasma_on + '\n')
                                plasma_dwell = round(o.Plasma_dwell, 5)
                                if plasma_dwell > 0:
                                    c.write("G04 P" + str(plasma_dwell) + "\n")
                            cut = True
                    else:
                        c.feed(x=vx, y=vy, z=vz)
                else:

                    c.feed(x=vx, y=vy, z=vz, a=ra, b=rb)

            elif v.z >= free_height or vi == 0:  # v.z==last.z==free_height or vi==0
                if f != freefeedrate:
                    f = freefeedrate
                    c.feedrate(f)

                if o.machine_axes == '3':
                    if o.cutter_type in ['LASER', 'PLASMA']:
                        if cut:
                            if o.cutter_type == 'LASER':
                                c.write("(**************laser off)\n")
                                c.write(o.Laser_off + '\n')
                            elif o.cutter_type == 'PLASMA':
                                c.write("(**************Plasma off)\n")
                                c.write(o.Plasma_off + '\n')

                            cut = False
                        c.rapid(x=vx, y=vy)
                    else:
                        c.rapid(x=vx, y=vy, z=vz)
                        #  this is to evaluate operation time and adds a feedrate for fast moves
                        if vz is not None:
                            # compensate for multiple fast move accelerations
                            f = plungefeedrate * fadjustval * 0.35
                        if vx is not None or vy is not None:
                            f = freefeedrate * 0.8  # compensate for free feedrate acceleration
                else:
                    c.rapid(x=vx, y=vy, z=vz, a=ra, b=rb)

            else:

                if f != millfeedrate or (fadjust and fadjustval != 1):
                    f = millfeedrate * fadjustval
                    c.feedrate(f)

                if o.machine_axes == '3':
                    c.feed(x=vx, y=vy, z=vz)
                else:
                    c.feed(x=vx, y=vy, z=vz, a=ra, b=rb)
            cut_distance += vect.length * unitcorr
            vector_duration = vect.length / f
            duration += vector_duration
            last = v
            if o.machine_axes != '3':
                lastrot = r

            processedops += 1
            if split and processedops > m.split_limit:
                c.rapid(x=last.x * unitcorr, y=last.y * unitcorr, z=free_height * unitcorr)
                # @v=(ch.points[-1][0],ch.points[-1][1],free_height)
                c.program_end()
                findex += 1
                c.file_close()
                c = startNewFile()
                c.flush_nc()
                c.comment('Tool change - D = %s type %s flutes %s' % (
                    strInUnits(o.cutter_diameter, 4), o.cutter_type, o.cutter_flutes))
                c.tool_change(o.cutter_id)
                c.spindle(o.spindle_rpm, spdir_clockwise)
                c.write_spindle()
                c.flush_nc()

                if m.spindle_start_time > 0:
                    c.dwell(m.spindle_start_time)
                    c.flush_nc()

                c.feedrate(unitcorr * o.feedrate)
                c.rapid(x=last.x * unitcorr, y=last.y * unitcorr, z=free_height * unitcorr)
                c.rapid(x=last.x * unitcorr, y=last.y * unitcorr, z=last.z * unitcorr)
                processedops = 0

        if o.remove_redundant_points and o.strategy != "DRILL":
            print("online " + str(online) + " offline " + str(offline) + " " + str(
                round(online / (offline + online) * 100, 1)) + "% removal")
        c.feedrate(unitcorr * o.feedrate)

        if o.output_trailer:
            lines = o.gcode_trailer.split(';')
            for aline in lines:
                c.write(aline + '\n')

    o.info.duration = duration * unitcorr
    print("total time:", round(o.info.duration * 60), "seconds")
    if bpy.context.scene.unit_settings.system == 'METRIC':
        unit_distance = 'm'
        cut_distance /= 1000
    else:
        unit_distance = 'feet'
        cut_distance /= 12

    print("cut distance:", round(cut_distance, 3), unit_distance)
    if enable_dust:
        c.write(stop_dust + '\n')
    if enable_hold:
        c.write(stop_hold + '\n')
    if enable_mist:
        c.write(stop_mist + '\n')

    c.program_end()
    c.file_close()
    print(time.time() - t)


async def getPath(context, operation):  # should do all path calculations.
    t = time.process_time()
    # print('ahoj0')

    # these tags are for caching of some of the results. Not working well still
    # - although it can save a lot of time during calculation...

    chd = getChangeData(operation)
    # print(chd)
    # print(o.changedata)
    if operation.changedata != chd:  # or 1:
        operation.update_offsetimage_tag = True
        operation.update_zbufferimage_tag = True
        operation.changedata = chd

    operation.update_silhouete_tag = True
    operation.update_ambient_tag = True
    operation.update_bullet_collision_tag = True

    utils.getOperationSources(operation)

    operation.info.warnings = ''
    checkMemoryLimit(operation)

    print(operation.machine_axes)

    if operation.machine_axes == '3':
        if USE_PROFILER == True:  # profiler
            import cProfile
            import pstats
            import io
            pr = cProfile.Profile()
            pr.enable()
            await getPath3axis(context, operation)
            pr.disable()
            pr.dump_stats(time.strftime("blendercam_%Y%m%d_%H%M.prof"))
        else:
            await getPath3axis(context, operation)

    elif (operation.machine_axes == '5' and operation.strategy5axis == 'INDEXED') or (
            operation.machine_axes == '4' and operation.strategy4axis == 'INDEXED'):
        # 5 axis operations are now only 3 axis operations that get rotated...
        operation.orientation = prepareIndexed(operation)  # TODO RENAME THIS

        await getPath3axis(context, operation)  # TODO RENAME THIS

        cleanupIndexed(operation)  # TODO RENAME THIS
    # transform5axisIndexed
    elif operation.machine_axes == '4':
        await getPath4axis(context, operation)

    # export gcode if automatic.
    if operation.auto_export:
        if bpy.data.objects.get("cam_path_{}".format(operation.name)) is None:
            return
        p = bpy.data.objects["cam_path_{}".format(operation.name)]
        exportGcodePath(operation.filename, [p.data], [operation])

    operation.changed = False
    t1 = time.process_time() - t
    progress('total time', t1)


def getChangeData(o):
    """this is a function to check if object props have changed,
    to see if image updates are needed in the image based method"""
    changedata = ''
    obs = []
    if o.geometry_source == 'OBJECT':
        obs = [bpy.data.objects[o.object_name]]
    elif o.geometry_source == 'COLLECTION':
        obs = bpy.data.collections[o.collection_name].objects
    for ob in obs:
        changedata += str(ob.location)
        changedata += str(ob.rotation_euler)
        changedata += str(ob.dimensions)

    return changedata


def checkMemoryLimit(o):
    # utils.getBounds(o)
    sx = o.max.x - o.min.x
    sy = o.max.y - o.min.y
    resx = sx / o.optimisation.pixsize
    resy = sy / o.optimisation.pixsize
    res = resx * resy
    limit = o.optimisation.imgres_limit * 1000000
    # print('co se to deje')
    if res > limit:
        ratio = (res / limit)
        o.optimisation.pixsize = o.optimisation.pixsize * math.sqrt(ratio)
        o.info.warnings += f"Memory limit: sampling resolution reduced to {o.optimisation.pixsize:.2e}\n"
        print('changing sampling resolution to %f' % o.optimisation.pixsize)


# this is the main function.
# FIXME: split strategies into separate file!
async def getPath3axis(context, operation):
    s = bpy.context.scene
    o = operation
    utils.getBounds(o)
    tw = time.time()

    if o.strategy == 'CUTOUT':
        await strategy.cutout(o)

    elif o.strategy == 'CURVE':
        await strategy.curve(o)

    elif o.strategy == 'PROJECTED_CURVE':
        await strategy.proj_curve(s, o)

    elif o.strategy == 'POCKET':
        await strategy.pocket(o)

    elif o.strategy in ['PARALLEL', 'CROSS', 'BLOCK', 'SPIRAL', 'CIRCLES', 'OUTLINEFILL', 'CARVE', 'PENCIL', 'CRAZY']:

        if o.strategy == 'CARVE':
            pathSamples = []
            ob = bpy.data.objects[o.curve_object]
            pathSamples.extend(curveToChunks(ob))
            # sort before sampling
            pathSamples = await utils.sortChunks(pathSamples, o)
            pathSamples = chunksRefine(pathSamples, o)
        elif o.strategy == 'PENCIL':
            await prepareArea(o)
            utils.getAmbient(o)
            pathSamples = getOffsetImageCavities(o, o.offset_image)
            pathSamples = limitChunks(pathSamples, o)
            # sort before sampling
            pathSamples = await utils.sortChunks(pathSamples, o)
        elif o.strategy == 'CRAZY':
            await prepareArea(o)
            # pathSamples = crazyStrokeImage(o)
            # this kind of worked and should work:
            millarea = o.zbuffer_image < o.minz + 0.000001
            avoidarea = o.offset_image > o.minz + 0.000001

            pathSamples = crazyStrokeImageBinary(o, millarea, avoidarea)
            #####
            pathSamples = await utils.sortChunks(pathSamples, o)
            pathSamples = chunksRefine(pathSamples, o)

        else:
            if o.strategy == 'OUTLINEFILL':
                utils.getOperationSilhouete(o)

            pathSamples = getPathPattern(o)

            if o.strategy == 'OUTLINEFILL':
                pathSamples = await utils.sortChunks(pathSamples, o)
                # have to be sorted once before, because of the parenting inside of samplechunks

            if o.strategy in ['BLOCK', 'SPIRAL', 'CIRCLES']:
                pathSamples = await utils.connectChunksLow(pathSamples, o)

        # print (minz)

        chunks = []
        layers = strategy.getLayers(o, o.maxz, o.min.z)

        print("SAMPLE", o.name)
        chunks.extend(await utils.sampleChunks(o, pathSamples, layers))
        print("SAMPLE OK")
        if o.strategy == 'PENCIL':  # and bpy.app.debug_value==-3:
            chunks = chunksCoherency(chunks)
            print('coherency check')

        # and not o.movement.parallel_step_back:
        if o.strategy in ['PARALLEL', 'CROSS', 'PENCIL', 'OUTLINEFILL']:
            print('sorting')
            chunks = await utils.sortChunks(chunks, o)
            if o.strategy == 'OUTLINEFILL':
                chunks = await utils.connectChunksLow(chunks, o)
        if o.movement.ramp:
            for ch in chunks:
                ch.rampZigZag(ch.zstart, None, o)
        # print(chunks)
        if o.strategy == 'CARVE':
            for ch in chunks:
                ch.offsetZ(-o.carve_depth)
#                for vi in range(0, len(ch.points)):
#                    ch.points[vi] = (ch.points[vi][0], ch.points[vi][1], ch.points[vi][2] - o.carve_depth)
        if o.use_bridges:
            print(chunks)
            for bridge_chunk in chunks:
                useBridges(bridge_chunk, o)

        strategy.chunksToMesh(chunks, o)

    elif o.strategy == 'WATERLINE' and o.optimisation.use_opencamlib:
        utils.getAmbient(o)
        chunks = []
        await oclGetWaterline(o, chunks)
        chunks = limitChunks(chunks, o)
        if (o.movement.type == 'CLIMB' and o.movement.spindle_rotation == 'CW') or (
                o.movement.type == 'CONVENTIONAL' and o.movement.spindle_rotation == 'CCW'):
            for ch in chunks:
                ch.reverse()

        strategy.chunksToMesh(chunks, o)

    elif o.strategy == 'WATERLINE' and not o.optimisation.use_opencamlib:
        topdown = True
        chunks = []
        await progress_async('retrieving object slices')
        await prepareArea(o)
        layerstep = 1000000000
        if o.use_layers:
            layerstep = math.floor(o.stepdown / o.slice_detail)
            if layerstep == 0:
                layerstep = 1

        # for projection of filled areas
        layerstart = o.max.z  #
        layerend = o.min.z  #
        layers = [[layerstart, layerend]]
        #######################
        nslices = ceil(abs((o.minz-o.maxz) / o.slice_detail))
        lastslice = spolygon.Polygon()  # polyversion
        layerstepinc = 0

        slicesfilled = 0
        utils.getAmbient(o)

        for h in range(0, nslices):
            layerstepinc += 1
            slicechunks = []
            z = o.minz + h * o.slice_detail
            if h == 0:
                z += 0.0000001
                # if people do mill flat areas, this helps to reach those...
                # otherwise first layer would actually be one slicelevel above min z.

            islice = o.offset_image > z
            slicepolys = imageToShapely(o, islice, with_border=True)

            poly = spolygon.Polygon()  # polygversion
            lastchunks = []

            for p in slicepolys.geoms:
                poly = poly.union(p)  # polygversion TODO: why is this added?
                nchunks = shapelyToChunks(p, z)
                nchunks = limitChunks(nchunks, o, force=True)
                lastchunks.extend(nchunks)
                slicechunks.extend(nchunks)
            if len(slicepolys.geoms) > 0:
                slicesfilled += 1

            #
            if o.waterline_fill:
                layerstart = min(o.maxz, z + o.slice_detail)  #
                layerend = max(o.min.z, z - o.slice_detail)  #
                layers = [[layerstart, layerend]]
                #####################################
                # fill top slice for normal and first for inverse, fill between polys
                if not lastslice.is_empty or (o.inverse and not poly.is_empty and slicesfilled == 1):
                    restpoly = None
                    if not lastslice.is_empty:  # between polys
                        if o.inverse:
                            restpoly = poly.difference(lastslice)
                        else:
                            restpoly = lastslice.difference(poly)
                    # print('filling between')
                    if (not o.inverse and poly.is_empty and slicesfilled > 0) or (
                            o.inverse and not poly.is_empty and slicesfilled == 1):  # first slice fill
                        restpoly = lastslice

                    restpoly = restpoly.buffer(-o.dist_between_paths,
                                               resolution=o.optimisation.circle_detail)

                    fillz = z
                    i = 0
                    while not restpoly.is_empty:
                        nchunks = shapelyToChunks(restpoly, fillz)
                        # project paths TODO: path projection during waterline is not working
                        if o.waterline_project:
                            nchunks = chunksRefine(nchunks, o)
                            nchunks = await utils.sampleChunks(o, nchunks, layers)

                        nchunks = limitChunks(nchunks, o, force=True)
                        #########################
                        slicechunks.extend(nchunks)
                        parentChildDist(lastchunks, nchunks, o)
                        lastchunks = nchunks
                        # slicechunks.extend(polyToChunks(restpoly,z))
                        restpoly = restpoly.buffer(-o.dist_between_paths,
                                                   resolution=o.optimisation.circle_detail)

                        i += 1
                # print(i)
                i = 0
                #  fill layers and last slice, last slice with inverse is not working yet
                #  - inverse millings end now always on 0 so filling ambient does have no sense.
                if (slicesfilled > 0 and layerstepinc == layerstep) or (
                        not o.inverse and not poly.is_empty and slicesfilled == 1) or (
                        o.inverse and poly.is_empty and slicesfilled > 0):
                    fillz = z
                    layerstepinc = 0

                    bound_rectangle = o.ambient
                    restpoly = bound_rectangle.difference(poly)
                    if o.inverse and poly.is_empty and slicesfilled > 0:
                        restpoly = bound_rectangle.difference(lastslice)

                    restpoly = restpoly.buffer(-o.dist_between_paths,
                                               resolution=o.optimisation.circle_detail)

                    i = 0
                    # 'GeometryCollection':#len(restpoly.boundary.coords)>0:
                    while not restpoly.is_empty:
                        # print(i)
                        nchunks = shapelyToChunks(restpoly, fillz)
                        #########################
                        nchunks = limitChunks(nchunks, o, force=True)
                        slicechunks.extend(nchunks)
                        parentChildDist(lastchunks, nchunks, o)
                        lastchunks = nchunks
                        restpoly = restpoly.buffer(-o.dist_between_paths,
                                                   resolution=o.optimisation.circle_detail)
                        i += 1

                percent = int(h / nslices * 100)
                await progress_async('waterline layers ', percent)
                lastslice = poly

            if (o.movement.type == 'CONVENTIONAL' and o.movement.spindle_rotation == 'CCW') or (
                    o.movement.type == 'CLIMB' and o.movement.spindle_rotation == 'CW'):
                for chunk in slicechunks:
                    chunk.reverse()
            slicechunks = await utils.sortChunks(slicechunks, o)
            if topdown:
                slicechunks.reverse()
            # project chunks in between

            chunks.extend(slicechunks)
        if topdown:
            chunks.reverse()
        strategy.chunksToMesh(chunks, o)

    elif o.strategy == 'DRILL':
        await strategy.drill(o)

    elif o.strategy == 'MEDIAL_AXIS':
        await strategy.medial_axis(o)
    await progress_async(f"Done", time.time() - tw, "s")


async def getPath4axis(context, operation):
    o = operation
    utils.getBounds(o)
    if o.strategy4axis in ['PARALLELR', 'PARALLEL', 'HELIX', 'CROSS']:
        path_samples = getPathPattern4axis(o)

        depth = path_samples[0].depth
        chunks = []

        layers = strategy.getLayers(o, 0, depth)

        chunks.extend(await utils.sampleChunksNAxis(o, path_samples, layers))
        strategy.chunksToMesh(chunks, o)
