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


def create_support(product_ids, offset, center_only_holes=False):
    """
    RhinoCommon API를 사용하여 메모리 효율적으로 서포트를 생성합니다.
    """
    # 디버그용 플래그: 단계별 기능 온/오프
    ENABLE_GROOVES = True          # 바닥 홈 패턴
    ENABLE_HOLES = True            # 수직 배기홀
    ENABLE_OFFSET_BOOLEAN = True   # 제품 offset 메쉬와의 최종 BooleanDifference

    # --- 1. 입력 메쉬 집합 생성 ---
    product_meshes = []
    for obj_id in product_ids:
        obj = sc.doc.Objects.Find(obj_id)
        if obj and isinstance(obj.Geometry, rg.Mesh):
            product_meshes.append(obj.Geometry)
    
    if not product_meshes:
        print("[create_support] Error: No valid mesh objects found.")
        return None

    # --- 2. 서포트 베이스 박스 메쉬 생성 (메모리 내) ---
    bbox = rg.BoundingBox.Empty
    for mesh in product_meshes:
        bbox.Union(mesh.GetBoundingBox(True))

    if not bbox.IsValid:
        print("[create_support] Error: Cannot get bounding box for support base.")
        return None

    # 서포트 높이를 제품 높이의 1/3로 자동 결정
    product_height = bbox.Max.Z - bbox.Min.Z
    height = max(product_height / 3.0, 2)  # 최소 2mm 보장

    # XY 평면에서 중심 기준으로 1.05배 스케일링
    center_x = (bbox.Min.X + bbox.Max.X) / 2.0
    center_y = (bbox.Min.Y + bbox.Max.Y) / 2.0
    half_width_x = (bbox.Max.X - bbox.Min.X) * 0.5 * 1.1
    half_width_y = (bbox.Max.Y - bbox.Min.Y) * 0.5 * 1.1
    min_x = center_x - half_width_x
    max_x = center_x + half_width_x
    min_y = center_y - half_width_y
    max_y = center_y + half_width_y
    base_bbox = rg.BoundingBox(min_x, min_y, 0, max_x, max_y, height)
    # 서포트 기본 박스 메쉬 (기본값)
    support_box_mesh = rg.Mesh.CreateFromBox(base_bbox, 1, 1, 1)
    if not support_box_mesh:
        print("[create_support] Error: Failed to create support base mesh.")
        return None

    # 모든 기능이 꺼져 있으면 단순 박스만 생성하고 바로 리턴
    if not ENABLE_GROOVES and not ENABLE_HOLES and not ENABLE_OFFSET_BOOLEAN:
        support_id = sc.doc.Objects.AddMesh(support_box_mesh)
        try:
            assign_object([support_id], 'print_support', 'support')
        except Exception as e:
            print('[create_support] Warning: failed to assign simple support box to layer:', e)
        print("[create_support] simple box only | id =", support_id)
        return [support_id]

    # --- 2-1. 바닥 홈 패턴 생성 (50% 접촉 / 50% 홈) ---
    groove_breps = []
    groove_depth = min(0.3, height * 0.6)  # 홈 깊이
    solid_ratio = 0.5                       # 접촉 비율
    target_groove_count = 8                 # 목표 홈 개수

    base_width_y = max_y - min_y
    if base_width_y > 0 and target_groove_count > 0:
        # 양쪽 끝이 항상 solid가 되도록 피치 계산 (n개의 홈, n+1개의 solid)
        solid_parts = target_groove_count + 1
        total_solid_width = base_width_y * solid_ratio
        total_gap_width = base_width_y - total_solid_width
        
        single_solid_width = total_solid_width / solid_parts
        single_gap_width = total_gap_width / target_groove_count

        current_y = min_y
        for i in range(target_groove_count):
            current_y += single_solid_width
            groove_start = current_y
            groove_end = groove_start + single_gap_width
            
            if groove_end > groove_start:
                groove_bbox = rg.BoundingBox(
                    min_x,
                    groove_start,
                    -0.01,
                    max_x,
                    groove_end,
                    groove_depth + 0.01,
                )
                groove_box = rg.Box(groove_bbox)
                groove_brep = rg.Brep.CreateFromBox(groove_box)
                if groove_brep:
                    groove_breps.append(groove_brep)
            current_y = groove_end

    # --- 2-2. 수직 배기홀 Brep 생성 ---
    hole_breps = []
    hole_radius = 0.7

    if ENABLE_HOLES and groove_breps:
        # center_only_holes=True 이면 각 홈당 가운데 한 줄만, False면 여러 줄
        default_row_count = 3
        for groove_brep in groove_breps:
            groove_bb = groove_brep.GetBoundingBox(True)
            if not groove_bb.IsValid:
                continue

            groove_width_x = groove_bb.Max.X - groove_bb.Min.X

            if center_only_holes:
                center_x_list = [groove_bb.Center.X]
            else:
                hole_row_count = default_row_count
                # 행 간격 계산 (양 끝에 여유 공간 확보)
                row_spacing = groove_width_x / (hole_row_count + 1)
                center_x_list = [
                    groove_bb.Min.X + row_spacing * (i + 1)
                    for i in range(hole_row_count)
                ]

            for center_x in center_x_list:
                center_y = groove_bb.Center.Y

                base_point = rg.Point3d(center_x, center_y, 0)
                top_point = rg.Point3d(center_x, center_y, height)
                axis = rg.Line(base_point, top_point)
                circle = rg.Circle(rg.Plane(base_point, rg.Vector3d.ZAxis), hole_radius)
                cylinder = rg.Cylinder(circle, axis.Length)
                brep = cylinder.ToBrep(True, True)
                if brep:
                    hole_breps.append(brep)

    # 홈/홀 모두 꺼져 있으면 Brep 파이프라인을 건너뛰고 단순 박스 메쉬만 사용
    if not ENABLE_GROOVES and not ENABLE_HOLES:
        current_support_meshes = [support_box_mesh]
    else:
        # --- 2-3. 바닥 홈 + 수직홀을 base Brep에서 차집합 ---
        base_box = rg.Box(base_bbox)
        base_brep = rg.Brep.CreateFromBox(base_box)
        if not base_brep:
            print("[create_support] Error: Failed to create base Brep, using simple box mesh")
            current_support_meshes = [support_box_mesh]
        else:
            tool_breps = []
            if ENABLE_GROOVES:
                tool_breps.extend(groove_breps)
            if ENABLE_HOLES:
                tool_breps.extend(hole_breps)

            result_breps = [base_brep]
            if tool_breps:
                try:
                    diff_result = rg.Brep.CreateBooleanDifference([base_brep], tool_breps, sc.doc.ModelAbsoluteTolerance)
                    if diff_result:
                        result_breps = list(diff_result)
                        pass
                    else:
                        pass
                except Exception as e:
                    print("Error: base Brep boolean (grooves+holes) failed: {}".format(e))

            # --- 2-4. Brep -> 메쉬 변환 ---
            current_support_meshes = []
            mp = rg.MeshingParameters.QualityRenderMesh
            angle_tolerance = sc.doc.ModelAngleToleranceRadians
            for b in result_breps:
                meshes = rg.Mesh.CreateFromBrep(b, mp)
                if meshes:
                    for mesh in meshes:
                        mesh.Weld(angle_tolerance)
                        mesh.UnifyNormals()
                        mesh.RebuildNormals()
                        current_support_meshes.append(mesh)

            if not current_support_meshes:
                print("Error: Brep->Mesh conversion produced no meshes, using simple box mesh")
                current_support_meshes = [support_box_mesh]
            elif len(current_support_meshes) > 1:
                base_mesh = current_support_meshes[0]
                base_mesh.Append(current_support_meshes[1:])
                base_mesh.Weld(angle_tolerance)
                base_mesh.UnifyNormals()
                base_mesh.RebuildNormals()
                current_support_meshes = [base_mesh]

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
            else:  # 리스트인 경우
                offset_meshes.extend(offset_results)

    print("[create_support] offset mesh count =", len(offset_meshes))
    if not offset_meshes:
        print("[create_support] Error: Mesh.Offset operation failed.")
        return None

    # for mesh in offset_meshes:
    #     sc.doc.Objects.AddMesh(mesh)
    # return

    # --- 4. 불리언 차집합 실행 (메모리 내) ---
    final_support_meshes = None

    if ENABLE_OFFSET_BOOLEAN:
        try:
            print("[create_support] running final boolean with offset meshes...")
            final_support_meshes = rg.Mesh.CreateBooleanDifference(current_support_meshes, offset_meshes)
        except Exception as e:
            print("[create_support] Error during BooleanDifference with offset meshes: {}".format(e))

    if not ENABLE_OFFSET_BOOLEAN or not final_support_meshes or len(final_support_meshes) == 0:
        # BooleanDifference를 끄거나 실패 시, 홈/홀만 적용된(혹은 없는) 기본 서포트를 사용
        if ENABLE_OFFSET_BOOLEAN:
            print("[create_support] Warning: BooleanDifference resulted in no meshes. Using support without product offset.")
        final_support_meshes = current_support_meshes

    print("[create_support] final_support_meshes count =", len(final_support_meshes))

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

    # 서포트를 전용 레이어에 배치하고 이름 지정
    if final_support_ids:
        try:
            assign_object(final_support_ids, 'print_support', 'support')
        except Exception as e:
            print('[create_support] Warning: failed to assign support objects to layer:', e)

    print("[create_support] created support object ids:", final_support_ids)
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
    offsets = [0.10, 0.15, 0.20]
    total_x_shift = 0.0
    all_created_objects = []

    try:
        rs.EnableRedraw(False)
        for offset_val in offsets:
            # 1-1. 원본 위치에서 서포트 생성 (3행 배기홀 버전)
            full_copy = rs.CopyObjects(product)
            full_support_ids = create_support(full_copy, offset=str(offset_val), center_only_holes=False)

            if full_support_ids:
                full_group = full_copy + full_support_ids
                bbox = rg.BoundingBox.Empty
                for obj_id in full_group:
                    obj = sc.doc.Objects.Find(obj_id)
                    if obj:
                        bbox.Union(obj.Geometry.GetBoundingBox(True))

                if bbox.IsValid:
                    # full_group의 바운딩박스를 이용해 X, Y 이동량 계산
                    width = bbox.Max.X - bbox.Min.X
                    full_height_y = bbox.Max.Y - bbox.Min.Y
                    y_gap = full_height_y + 2.0  # 서포트 높이 + 2mm 여유

                    # X축 정렬 (offset 별로 오른쪽으로 차례대로 배치)
                    rs.MoveObjects(full_group, (total_x_shift, 0, 0))
                    all_created_objects.extend(full_group)

                    # 1-2. 같은 offset에 대해 가운데 1행 버전 생성
                    center_copy = rs.CopyObjects(product)
                    center_support_ids = create_support(center_copy, offset=str(offset_val), center_only_holes=True)

                    if center_support_ids:
                        center_group = center_copy + center_support_ids
                        # full_group 과 같은 X 위치에서 Y 방향으로만 위로 이동
                        rs.MoveObjects(center_group, (total_x_shift, y_gap, 0))
                        all_created_objects.extend(center_group)

                    # 다음 offset을 위한 X축 이동량 갱신
                    total_x_shift += width + 2.0  # 서포트 사이 2mm 간격
                else:
                    rs.DeleteObjects(full_group)
            else:
                # 서포트 생성 실패 시 복사본 제거
                rs.DeleteObjects(full_copy)

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
