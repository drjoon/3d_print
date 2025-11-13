#! python 3
# env: /Users/joonholee/Joon/1-Project/3d_print/rhino

import importlib
importlib.reload(importlib.import_module('lib.reload'))
import lib.reload

modules = {
    'lib.globals': 'all'
}
lib.reload.reload_and_import_modules('crowns', modules)

from Rhino.DocObjects import *
import scriptcontext as sc
import rhinoscriptsyntax as rs
import Rhino.Geometry as rg
from lib.globals import *

def create_support(product_ids):
    """
    새로운 서포트 생성 로직.
    1. 크라운의 바운딩박스를 만들고, Z축으로 1/3 크기로 줄여줘. 그렇게 만들어진 박스를 XY 평면까지 내려줘.
    2. 크라운을 카피해서 0.05mm 만큼 확대해.
    3. 위 1에서 만들어진 박스에서 위 2번에서 만들어진 크라운 복제품을 빼 (mesh boolean difference)
    """
    # 1. 바운딩 박스로 메쉬 박스 생성
    bbox = rs.BoundingBox(product_ids)
    if not bbox:
        print("Error: Cannot get bounding box.")
        return None

    min_pt = bbox.Min
    max_pt = bbox.Max

    # Z축으로 1/3 크기 조정 후 XY 평면으로 이동
    height = (max_pt.Z - min_pt.Z) / 3.0
    
    corners = [
        rg.Point3d(min_pt.X, min_pt.Y, 0),
        rg.Point3d(max_pt.X, min_pt.Y, 0),
        rg.Point3d(max_pt.X, max_pt.Y, 0),
        rg.Point3d(min_pt.X, max_pt.Y, 0),
        rg.Point3d(min_pt.X, min_pt.Y, height),
        rg.Point3d(max_pt.X, min_pt.Y, height),
        rg.Point3d(max_pt.X, max_pt.Y, height),
        rg.Point3d(min_pt.X, max_pt.Y, height)
    ]

    box_brep = rs.AddBox(corners)
    if not box_brep:
        print("Error: Failed to create box brep.")
        return None
    
    mesh_box = BrepToMesh(box_brep)
    rs.DeleteObject(box_brep)

    # 2. 크라운 복제 및 확대
    product_meshes = []
    for pid in product_ids:
        p_mesh = rs.coercemesh(pid)
        if p_mesh:
            product_meshes.append(p_mesh)

    if not product_meshes:
        print("Error: No valid meshes found in product.")
        return None
    
    combined_product_mesh = rg.Mesh()
    for m in product_meshes:
        combined_product_mesh.Append(m)

    offset_mesh = combined_product_mesh.Duplicate()
    offset_mesh.Offset(0.05, True)

    # 3. 불리언 차집합으로 서포트 생성
    support_mesh = rg.Mesh.CreateBooleanDifference([mesh_box], [offset_mesh])

    if support_mesh and support_mesh.Count > 0:
        support_id = sc.doc.Objects.AddMesh(support_mesh[0])
        assign_object([support_id], 'print', 'support')
        return support_id
    else:
        print("Error: Mesh boolean difference failed.")
        # 실패 시 원본 박스라도 보여주기 위해
        box_id = sc.doc.Objects.AddMesh(mesh_box)
        assign_object([box_id], 'print', 'support_failed')
        return None

def main():
    rs.Command(f'!_-SelAll')
    product = rs.SelectedObjects()
    if not product:
        print("No objects selected.")
        return

    # 1. 크라운 뒤집기 및 이동
    rs.RotateObjects(product, (0, 0, 0), 180, (1, 0, 0))
    z_min = get_min(product)[2]
    rs.MoveObjects(product, (0, 0, -z_min + 0.5))
    assign_object(product, 'print', 'product')
    
    # 2. 새로운 서포트 생성
    create_support(product)

if __name__ == "__main__":
    print("AddSupport_v2 started.")
    main()
