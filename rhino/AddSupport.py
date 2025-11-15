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


def create_support(product_ids, offset, height):
    """
    RhinoCommon API를 사용하여 메모리 효율적으로 서포트를 생성합니다.
    """
    # --- 1. 입력 메쉬 집합 생성 ---
    product_meshes = []
    for obj_id in product_ids:
        obj = sc.doc.Objects.Find(obj_id)
        if obj and isinstance(obj.Geometry, rg.Mesh):
            product_meshes.append(obj.Geometry)
    
    if not product_meshes:
        print("Error: No valid mesh objects found.")
        return None

    # --- 2. 서포트 베이스 박스 메쉬 생성 (메모리 내) ---
    bbox = rg.BoundingBox.Empty
    for mesh in product_meshes:
        bbox.Union(mesh.GetBoundingBox(True))

    if not bbox.IsValid:
        print("Error: Cannot get bounding box for support base.")
        return None

    base_bbox = rg.BoundingBox(bbox.Min.X, bbox.Min.Y, 0, bbox.Max.X, bbox.Max.Y, height)
    support_box_mesh = rg.Mesh.CreateFromBox(base_bbox, 1, 1, 1)
    if not support_box_mesh:
        print("Error: Failed to create support base mesh.")
        return None

    # --- 3. 입력 메쉬들을 Offset (메모리 내) ---
    offset_meshes = []
    for mesh in product_meshes:
        # Rhino.Geometry.Mesh.Offset은 리스트를 반환할 수 있음
        # offset 값을 음수로 전달하고 solid=True 옵션으로 닫힌 메쉬 생성
        offset_results = mesh.Offset(-float(offset), False)
        if offset_results:
            # Offset 결과가 단일 메쉬일 수도 있고, 메쉬 리스트일 수도 있음
            if isinstance(offset_results, rg.Mesh):
                offset_meshes.append(offset_results)
            else: # 리스트인 경우
                offset_meshes.extend(offset_results)

    if not offset_meshes:
        print("Error: Mesh.Offset operation failed.")
        return None

    # for mesh in offset_meshes:
    #     sc.doc.Objects.AddMesh(mesh)
    # return

    # --- 4. 불리언 차집합 실행 (메모리 내) ---
    try:
        final_support_meshes = rg.Mesh.CreateBooleanDifference([support_box_mesh], offset_meshes)
    except Exception as e:
        print("Error during BooleanDifference: {}".format(e))
        return None

    if not final_support_meshes or len(final_support_meshes) == 0:
        print("Error: BooleanDifference resulted in no meshes.")
        return None

    # --- 5. 최종 메쉬 복구 및 Rhino 문서에 추가 ---
    final_support_ids = []
    angle_tolerance = sc.doc.ModelAngleToleranceRadians

    for mesh in final_support_meshes:
        mesh.UnifyNormals()
        mesh.Weld(angle_tolerance)
        mesh.FillHoles()
        mesh.RebuildNormals()
        mesh.Compact()
        final_support_ids.append(sc.doc.Objects.AddMesh(mesh))
    
    return final_support_ids


def engrave_text_on_crown(product_id, bbox, text_to_engrave, text_size, z_ratio, engraving_depth):
    """
    크라운 내부에 텍스트를 음각으로 각인합니다.
    """
    # 1. 위치 계산 (전달받은 bbox 사용)

    # 텍스트를 생성할 Z 위치 계산
    z_pos = bbox.Min.Z + bbox.Diagonal.Z * z_ratio
    # 텍스트를 생성할 YZ 평면의 X 위치 (X=0)
    text_origin = rg.Point3d(0, bbox.Center.Y, z_pos)

    # 2. YZ 평면에 텍스트 커브 생성
    # YZ 평면에 텍스트가 서 있도록 Plane 설정
    text_plane = rg.Plane(text_origin, rg.Vector3d.YAxis, rg.Vector3d.ZAxis)
    
    # 텍스트 객체 생성 (가운데 정렬)
    temp_text_id = rs.AddText(text_to_engrave, text_plane, height=text_size, font="Arial", font_style=1, justification=2) # 2 = Center
    if not temp_text_id:
        print("Error: Failed to create temporary text object.")
        return

    # 텍스트를 커브로 분해
    exploded_curves = rs.ExplodeText(temp_text_id)
    rs.DeleteObject(temp_text_id)
    if not exploded_curves:
        print("Error: Failed to explode text into curves.")
        return

    # 분해된 커브들을 그룹으로 묶음
    group_name = "temp_text_group"
    rs.AddGroup(group_name)
    rs.AddObjectsToGroup(exploded_curves, group_name)

    # 3. _Project 커맨드를 사용하여 크라운 내벽에 커브 투영
    group_objects = rs.ObjectsByGroup(group_name)
    if not group_objects:
        print("Error: No objects found in the group to project.")
        return
    rs.SelectObjects(group_objects)
    rs.SelectObject(product_id)
    
    # Project 커맨드 실행 (CPlane Z 방향으로 투영)
    # 방향을 명시적으로 제어하기 위해 View를 Right 설정하고 투영
    rs.Command('_-SetActiveViewport Right', echo=False)
    rs.Command('_-Project _DeleteInput=Yes', echo=False)
    

    projected_curves = rs.LastCreatedObjects()
    rs.UnselectAllObjects()

    if not projected_curves:
        print("Error: Projection resulted in no curves.")
        rs.DeleteObjects(text_curves)
        return

    # 4. Z축에 가장 가까운 2개의 커브 선택
    def distance_to_z_axis(curve_id):
        center = rs.coercecurve(curve_id).GetBoundingBox(True).Center
        return center.X**2 + center.Y**2 # Z축과의 거리 제곱 (sqrt 불필요)

    projected_curves.sort(key=distance_to_z_axis)
    
    curves_to_loft = projected_curves[:2]
    curves_to_delete = projected_curves[2:]

    if curves_to_delete:
        rs.DeleteObjects(curves_to_delete)

    if len(curves_to_loft) < 2:
        print("Error: Not enough curves found for lofting.")
        rs.DeleteObjects(text_curves + curves_to_loft)
        return

    # 5. 음각 형상 생성 및 적용
    loft_surface = rs.AddLoftSrf(curves_to_loft, loft_type=0) # 0=Normal
    if not loft_surface:
        print("Error: Failed to create loft surface.")
        rs.DeleteObjects(text_curves + projected_curves)
        return

    # 서피스의 법선 방향 계산 (크라운 안쪽을 향하도록)
    srf_center = rs.SurfaceAreaCentroid(loft_surface)[0]
    crown_center = bbox.Center
    extrusion_vector = crown_center - srf_center
    extrusion_vector.Unitize()
    extrusion_vector *= engraving_depth

    extrusion_solid = rs.ExtrudeSurface(loft_surface, extrusion_vector)
    if not extrusion_solid:
        print("Error: Failed to extrude surface for engraving.")
        rs.DeleteObjects(text_curves + projected_curves + [loft_surface])
        return

    # 불리언 차집합으로 음각 적용
    rs.BooleanDifference(product_id, extrusion_solid, delete_input=True)

    # 6. 정리
    rs.DeleteObjects(projected_curves + [loft_surface])
    rs.DeleteGroup(group_name)

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
    
    # 2. 여러 offset 값으로 서포트 생성 및 정렬 (메모리 최적화)
    offsets = [0.10, 0.15, 0.20, 0.25, 0.30]
    total_x_shift = 0.0
    all_created_objects = []

    try:
        rs.EnableRedraw(False)
        for offset_val in offsets:
            # 1. 원본 위치에서 서포트 생성
            current_product_copy = rs.CopyObjects(product)
            support_ids = create_support(current_product_copy, offset=str(offset_val), height=2.2)

            if support_ids:
                # 2. 생성된 객체 그룹화 및 바운딩 박스 계산
                newly_created_group = current_product_copy + support_ids
                bbox = rg.BoundingBox.Empty
                for obj_id in newly_created_group:
                    obj = sc.doc.Objects.Find(obj_id)
                    if obj:
                        bbox.Union(obj.Geometry.GetBoundingBox(True))

                if bbox.IsValid:
                    # 3. 그룹을 X축으로 이동
                    rs.MoveObjects(newly_created_group, (total_x_shift, 0, 0))
                    all_created_objects.extend(newly_created_group)

                    # 4. 다음 그룹을 위한 X축 이동 거리 업데이트
                    width = bbox.Max.X - bbox.Min.X
                    total_x_shift += width + 2.0 # 2mm 간격 추가
                else:
                    # BBox 계산 실패 시 생성된 객체 삭제
                    rs.DeleteObjects(newly_created_group)
            else:
                # 서포트 생성 실패 시 복사본 제거
                rs.DeleteObjects(current_product_copy)

        # 각 루프 후 Undo 기록 삭제하여 메모리 확보
        rs.Command('-_CommandHistory _Purge _Enter', False)

    finally:
        rs.EnableRedraw(True)

    # 원본 product 숨기기
    rs.HideObjects(product)


    # 3. 크라운 내부에 텍스트 각인
    # 각인 관련 파라미터
    text_to_engrave = "abc"
    engraving_text_size = 0.1
    engraving_z_ratio = 3.0 / 4.0
    engraving_depth = 0.3 # 음각 깊이

    # # 3. 크라운 내부에 텍스트 각인
    # # 각인 기능을 사용하려면 아래 코드의 주석을 해제하세요.
    # # 주의: 이 기능은 product 객체를 직접 수정합니다.
    # if product:
    #     # 각인 전에 바운딩 박스 계산
    #     crown_geom = rs.coercegeometry(product[0])
    #     if crown_geom:
    #         bbox = crown_geom.GetBoundingBox(True)
    #         if bbox.IsValid:
    #             engrave_text_on_crown(product[0], bbox, text_to_engrave, engraving_text_size, engraving_z_ratio, engraving_depth)
    #     else:
    #         print("Error: Invalid crown geometry for engraving.")

if __name__ == "__main__":
    print("AddSupport_v2 started.")
    main()
