#! python 3
# env: /Users/joonholee/Joon/1-Project/3d_print/rhino
# r: numpy

# 이것도 캐쉬 리셋
import gc
gc.collect()

import Rhino
import rhinoscriptsyntax as rs
import scriptcontext as sc
from Rhino.Geometry import *
import numpy as np
import pickle
import base64



def get_centroid(obj):
    bb = rs.BoundingBox(obj)
    pts = [(pt.X, pt.Y, pt.Z) for pt in bb]
    vectors = np.array(pts)
    return np.mean(vectors, axis=0)
    # bb = rs.BoundingBox(obj)
    # return bb.Center


def get_size(obj):
    bb = rs.BoundingBox(obj)
    x = [100, -100]
    y = [100, -100]
    z = [100, -100]
    for box in bb:
        x[0] = min([x[0], box[0]])
        x[1] = max([x[1], box[0]])
        y[0] = min([y[0], box[1]])
        y[1] = max([y[1], box[1]])
        z[0] = min([z[0], box[2]])
        z[1] = max([z[1], box[2]])
    return np.array([x[1]-x[0], y[1] - y[0], z[1] - z[0]])


def get_max(obj):
    bb = rs.BoundingBox(obj)
    x = -100
    y = -100
    z = -100
    for box in bb:
        x = max([x, box[0]])
        y = max([y, box[1]])
        z = max([z, box[2]])
    return np.array([x, y, z])


def get_min(obj):
    bb = rs.BoundingBox(obj)
    x = 100
    y = 100
    z = 100
    for box in bb:
        x = min([x, box[0]])
        y = min([y, box[1]])
        z = min([z, box[2]])
    return np.array([x, y, z])


def set_user_text(obj, key, value):
    data = pickle.dumps(value)
    text = base64.b64encode(data).decode('ascii')
    rs.SetUserText(obj, key, text)
    return text


def get_user_text(obj, key):
    text = rs.GetUserText(obj, key)
    data = base64.b64decode(text)
    return pickle.loads(data)


def assign_object(obj, layer, name):
    if not rs.IsLayer(layer):
        rs.AddLayer(layer)
    rs.ObjectLayer(obj, layer)
    rs.ObjectName(obj, name)


def assign_group(obj, group_name):
    rs.AddGroup(group_name)
    rs.AddObjectsToGroup(obj, group_name)



def BrepToMesh(brep_id):
    brep = rs.coercebrep(brep_id)
    if brep:
        mesh = Rhino.Geometry.Mesh()
        mesh_parts = Rhino.Geometry.Mesh.CreateFromBrep(
            brep,
            # MeshingParameters.Coarse
            MeshingParameters.Default
        )
        for mesh_part in mesh_parts:
            mesh.Append(mesh_part)
        mesh.Compact()
        return sc.doc.Objects.AddMesh(mesh)


def ExportToSTL(objs):
    rs.UnselectAllObjects()
    rs.SelectObjects(objs)
    e_str = "_ExportFileAs=_Binary _Enter"
    filename = rs.DocumentPath() + rs.DocumentName()[:-4] + '.stl'
    rs.Command('-_Export "{}" {}'.format(filename, e_str), False)


def text_object(text, size, depth, angle, trans=(0, 0, 0), space=0.0, mirror=False):
    text_entity = Rhino.Geometry.TextEntity()
    text_entity.Plane = Rhino.Geometry.Plane.WorldXY
    text_entity.Text = str(text)
    text_entity.Justification = Rhino.Geometry.TextJustification.MiddleCenter
    text_entity.TextHeight = float(size)
    text_entity.FontIndex = sc.doc.Fonts.FindOrCreate(
        "Arial Black", True, False)
    solids = text_entity.CreatePolySurfaces(
        text_entity.DimensionStyle, depth, False, spacing=space)

    objs = []

    for s in solids:
        obj = sc.doc.Objects.AddBrep(s)
        obj = rs.RotateObject(obj, (0, 0, 0), angle, axis=(0, 0, 1))
        if mirror:
            obj = rs.MirrorObject(obj, (0, 0, 0), (0, 1, 0))
        # if not mirror:  # mirror for TD6
        #     obj = rs.MirrorObject(obj, (0, 0, 0), (0, 1, 0))
        obj = rs.MoveObject(obj, trans)
        objs.append(obj)

    return objs


def AddMeshBox(pt0, pt1):
    corners = [pt0,
               (pt1[0], pt0[1], pt0[2]),
               (pt1[0], pt1[1], pt0[2]),
               (pt0[0], pt1[1], pt0[2]),
               (pt0[0], pt0[1], pt1[2]),
               (pt1[0], pt0[1], pt1[2]),
               (pt1[0], pt1[1], pt1[2]),
               (pt0[0], pt1[1], pt1[2])]
    box = rs.AddBox(corners)
    mesh = BrepToMesh(box)
    rs.DeleteObject(box)
    return mesh


def AddBox(pt0, pt1):
    corners = [pt0,
               (pt1[0], pt0[1], pt0[2]),
               (pt1[0], pt1[1], pt0[2]),
               (pt0[0], pt1[1], pt0[2]),
               (pt0[0], pt0[1], pt1[2]),
               (pt1[0], pt0[1], pt1[2]),
               (pt1[0], pt1[1], pt1[2]),
               (pt0[0], pt1[1], pt1[2])]
    return rs.AddBox(corners)
