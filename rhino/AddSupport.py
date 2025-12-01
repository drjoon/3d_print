#! python 3
# env: /Users/joonholee/Joon/1-Project/3d_print/rhino

import importlib
importlib.reload(importlib.import_module('lib.reload'))
import lib.reload
import math

modules = {
    'lib.globals': 'all'
}
lib.reload.reload_and_import_modules('crowns', modules)

from Rhino.DocObjects import *
import scriptcontext as sc
import rhinoscriptsyntax as rs
import Rhino.Geometry as rg
import Rhino.Geometry.Intersect as rgi
from lib.globals import *

def ScaleXY(bbox, factor):
    center_x = (bbox.Min.X + bbox.Max.X) / 2.0
    center_y = (bbox.Min.Y + bbox.Max.Y) / 2.0
    half_width_x = (bbox.Max.X - bbox.Min.X) * 0.5 * factor
    half_width_y = (bbox.Max.Y - bbox.Min.Y) * 0.5 * factor
    min_x = center_x - half_width_x
    max_x = center_x + half_width_x
    min_y = center_y - half_width_y
    max_y = center_y + half_width_y
    # 주의: create_support에서 "min_x, min_y, max_x, max_y, ..." 순서로 언패킹하므로,
    # 여기서도 동일한 순서로 값을 반환해야 bbox가 올바르게 생성된다.
    return min_x, min_y, max_x, max_y, half_width_x, half_width_y, center_x, center_y

def Sample_points(product_meshes, inner_min_x, inner_max_x, inner_min_y, inner_max_y):
    # 샘플 개수 (X:10, Y:20 → 최대 200개 Ray)
    num_samples_x = 15
    num_samples_y = 30
    sample_points = []  # 메모리 상의 샘플 포인트 목록
    cut_brep = None     # 이후 base Brep를 자를 때 사용할 패치 곡면
    cut_brep_id = None  # 문서에 추가된 패치 Brep 객체 id (마지막에 삭제용)

    dx =  (inner_max_x - inner_min_x) / float(num_samples_x - 1) if num_samples_x > 1 else 0.0
    dy = (inner_max_y - inner_min_y) / float(num_samples_y - 1) if num_samples_y > 1 else 0.0

    for iy in range(num_samples_y):
        y = inner_min_y + dy * iy
        for ix in range(num_samples_x):
            x = inner_min_x + dx * ix

            ray_origin = rg.Point3d(x, y, 0.0)
            ray_dir = rg.Vector3d(0.0, 0.0, 1.0)
            ray = rg.Ray3d(ray_origin, ray_dir)

            closest_t = None
            # product_meshes 전체에서 이 Ray에 대한 가장 가까운 hit 찾기
            for mesh in product_meshes:
                if not mesh:
                    continue
                try:
                    t = rgi.Intersection.MeshRay(mesh, ray)
                except Exception:
                    t = -1.0
                if t is None or t < 0:
                    continue
                if closest_t is None or t < closest_t:
                    closest_t = t

            if closest_t is not None:
                hit_point = ray.PointAt(closest_t)
                sample_points.append(hit_point)

    return sample_points

def Cut_brep(sample_points, min_x, max_x, min_y, max_y, center_x, center_y):
    if sample_points:
        try:
            # Z값 기반 2 sigma 필터링
            zs = [p.Z for p in sample_points]
            mean_z = sum(zs) / float(len(zs))
            var_z = sum((z - mean_z) ** 2 for z in zs) / float(len(zs)) if len(zs) > 1 else 0.0
            sigma_z = math.sqrt(var_z)

            if sigma_z > 1e-9:
                threshold = 2.0 * sigma_z
                filtered_points = [p for p in sample_points if abs(p.Z - mean_z) <= threshold]
            else:
                filtered_points = list(sample_points)

            print("[create_support] filtered point count (2 sigma) =", len(filtered_points))

            if len(filtered_points) >= 3:
                tol = sc.doc.ModelAbsoluteTolerance
                # 필터된 포인트들을 통과하는 패치 곡면 생성
                # Point3d를 GeometryBase(Rhino.Geometry.Point)로 래핑해서 전달
                geo_points = [rg.Point(p) for p in filtered_points]
                try:
                    patch_brep = rg.Brep.CreatePatch(geo_points, 36, 36, tol)
                except Exception as e:
                    print("[create_support] Warning: Brep.CreatePatch failed:", e)
                    patch_brep = None

                if patch_brep:
                    # 곡면을 +Z 방향으로 소량만 이동 (샘플 포인트에 더 근접하게 유지)
                    move_up = rg.Transform.Translation(0.0, 0.0, 0.2)
                    patch_brep.Transform(move_up)

                    # support base bbox 크기(X,Y)를 약간만 키워서(1.1배) 과도하게 평탄해지지 않도록 스케일
                    try:
                        srf_bbox = patch_brep.GetBoundingBox(True)
                        if srf_bbox.IsValid:
                            curr_wx = srf_bbox.Max.X - srf_bbox.Min.X
                            curr_wy = srf_bbox.Max.Y - srf_bbox.Min.Y

                            target_wx = (max_x - min_x) * 1.1
                            target_wy = (max_y - min_y) * 1.1

                            sx = target_wx / curr_wx if curr_wx > 1e-6 else 1.0
                            sy = target_wy / curr_wy if curr_wy > 1e-6 else 1.0

                            origin_z = srf_bbox.Center.Z
                            origin = rg.Point3d(center_x, center_y, origin_z)

                            # 먼저 Brep을 문서에 추가한 뒤, 해당 객체를 기준으로 스케일
                            cut_brep_id = sc.doc.Objects.AddBrep(patch_brep)
                            rs.ScaleObject(cut_brep_id, origin, (sx, sy, 1.0), copy=False)
                            print("[create_support] patch surface scaled via rs.ScaleObject.")

                            # 잘라내기에 사용할 최종 패치 곡면을 메모리에 보관하고,
                            # 문서에 추가된 임시 패치 객체는 바로 삭제하여 화면에 남지 않도록 한다.
                            obj = sc.doc.Objects.Find(cut_brep_id)
                            if obj and obj.Geometry:
                                cut_brep = obj.Geometry.DuplicateBrep()
                                try:
                                    rs.DeleteObject(cut_brep_id)
                                except Exception as e:
                                    print("[create_support] Warning: failed to delete helper patch brep:", e)
                                return cut_brep

                            # doc에 이미 추가했으므로 아래에서 다시 추가하지 않도록 None 처리
                            patch_brep = None
                    except Exception as e:
                        print("[create_support] Warning: failed to scale patch to target bbox:", e)

                    if patch_brep is not None:
                        sc.doc.Objects.AddBrep(patch_brep)
            else:
                print("[create_support] Warning: not enough filtered points for patch (need >=3).")
        except Exception as e:
            print("[create_support] Warning: failed to create in-memory patch surface:", e)

def Brep2Mesh(breps):
    """주어진 Brep 리스트를 메쉬 리스트로 변환하고, 각 메쉬를 용접/노멀 정리 후 반환한다."""
    if not breps:
        return []

    mp = rg.MeshingParameters.QualityRenderMesh
    angle_tolerance = sc.doc.ModelAngleToleranceRadians

    result_meshes = []
    for b in breps:
        if not b:
            continue
        meshes = rg.Mesh.CreateFromBrep(b, mp)
        if not meshes:
            continue
        for mesh in meshes:
            mesh.Weld(angle_tolerance)
            mesh.UnifyNormals()
            mesh.RebuildNormals()
            result_meshes.append(mesh)

    # 여러 조각이면 하나로 merge해서 반환 (기존 로직 유지)
    if not result_meshes:
        return []

    if len(result_meshes) > 1:
        base_mesh = result_meshes[0]
        base_mesh.Append(result_meshes[1:])
        base_mesh.Weld(angle_tolerance)
        base_mesh.UnifyNormals()
        base_mesh.RebuildNormals()
        return [base_mesh]

    return result_meshes

def create_support(product_ids, offset):
    """
    RhinoCommon API를 사용하여 메모리 효율적으로 서포트를 생성합니다.
    """
    # 디버그용 플래그: 단계별 기능 온/오프
    ENABLE_OFFSET_BOOLEAN = True       # product 메쉬를 -Z 방향으로 내린 후 support에서 차집합
    ENABLE_PATCH_CUT = True            # 패치 곡면으로 베이스 윗부분을 잘라낼지 여부 (False이면 꽉 찬 박스 유지)

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

    # XY 평면에서 중심 기준으로 1.05배 스케일링
    min_x, min_y, max_x, max_y, half_width_x, half_width_y, center_x, center_y = ScaleXY(bbox, 1.05)
    base_bbox = rg.BoundingBox(min_x, min_y, 0, max_x, max_y, 5)
    # 서포트 기본 박스 메쉬 (기본값)
    support_box_mesh = rg.Mesh.CreateFromBox(base_bbox, 1,1,1)
    if not support_box_mesh:
        print("[create_support] Error: Failed to create support base mesh.")
        return None

    # 패치 컷과 offset Boolean이 모두 꺼져 있으면 단순 박스만 생성하고 바로 리턴
    if (not ENABLE_PATCH_CUT) and (not ENABLE_OFFSET_BOOLEAN):
        support_id = sc.doc.Objects.AddMesh(support_box_mesh)
        try:
            assign_object([support_id], 'print_support', 'support')
        except Exception as e:
            print('[create_support] Warning: failed to assign simple support box to layer:', e)
        print("[create_support] simple box only | id =", support_id)
        return [support_id]

    # 비대칭 스케일된 내부 영역 계산 (X:50%, Y:100%)
    inner_scale_x = 0.5 * 2
    inner_scale_y = 1.0 * 2
    inner_half_width_x = half_width_x * inner_scale_x
    inner_half_width_y = half_width_y * inner_scale_y
    inner_min_x = center_x - inner_half_width_x
    inner_max_x = center_x + inner_half_width_x
    inner_min_y = center_y - inner_half_width_y
    inner_max_y = center_y + inner_half_width_y

    # --- 2-1. 패치 곡면 샘플 포인트 생성 ---
    # 1단계: 샘플 포인트는 메모리에서만 보관하고,
    sample_points = Sample_points(product_meshes, inner_min_x, inner_max_x, inner_min_y, inner_max_y)
    print("[create_support] in-memory sample point count =", len(sample_points))
    
    # 2단계: Z 기준 2 sigma 필터 후, 필터된 포인트들을 통과하는 곡면 패치 생성
    cut_brep = Cut_brep(sample_points, min_x, max_x, min_y, max_y, center_x, center_y)
    
    # base 박스를 Brep으로 생성하고 result_breps 초기화 (cut_brep 및 이후 union에서 사용)
    base_box = rg.Box(base_bbox)
    base_brep = rg.Brep.CreateFromBox(base_box)
    if not base_brep:
        print("[create_support] Error: Failed to create base Brep, using simple box mesh")
        support_meshes = [support_box_mesh]
        result_breps = []
    else:
        result_breps = [base_brep]
        support_meshes = []
    
    # --- 2-2. 패치 곡면으로 base Brep 윗부분 잘라내기 ---
    if cut_brep is not None and ENABLE_PATCH_CUT:
        tol = sc.doc.ModelAbsoluteTolerance
        cut_center_z = cut_brep.GetBoundingBox(True).Center.Z
        cut_result = []
        for b in result_breps:
            try:
                pieces = b.Split(cut_brep, tol)
            except Exception as e:
                print("[create_support] Warning: base Brep split by patch failed:", e)
                pieces = None

            if not pieces or len(pieces) == 0:
                cut_result.append(b)
                continue

            for piece in pieces:
                bb = piece.GetBoundingBox(True)
                if not bb.IsValid:
                    continue
                # 패치 곡면보다 아래(Z가 더 작은) 조각만 유지
                if bb.Center.Z < cut_center_z:
                    cut_result.append(piece)

        if cut_result:
            result_breps = cut_result
            print("[create_support] base Brep cut by patch surface; piece count =", len(result_breps))
        else:
            print("[create_support] Warning: patch cut produced no lower pieces; using original result_breps.")

    # --- 2-3. 패시 서피스를 포함한 Brep 솔리드 생성 후, offset Brep과 boolean 차집합, 마지막에 메쉬 변환 ---
    # 1) base Brep 결과(result_breps)에 패시 서피스와의 교집합(cap_intersections)을 추가
    union_sources = list(result_breps)
    if cut_brep is not None and result_breps:
        try:
            tol_cap = sc.doc.ModelAbsoluteTolerance
            cap_intersections = rg.Brep.CreateBooleanIntersection([cut_brep], result_breps, tol_cap)
        except Exception as e:
            print("[create_support] Warning: BooleanIntersection(cut_brep, result_breps) failed:", e)
            cap_intersections = None

        if cap_intersections:
            union_sources.extend(cap_intersections)

    # 2) 패시 서피스를 포함한 base Brep들을 BooleanUnion으로 합치기 (offset 차집합은 현재 비활성화)
    try:
        tol_union = sc.doc.ModelAbsoluteTolerance
        union_breps = rg.Brep.CreateBooleanUnion(union_sources, tol_union)
        if union_breps and len(union_breps) > 0:
            result_breps = list(union_breps)
    except Exception as e:
        print("[create_support] Warning: BooleanUnion(result_breps + caps) failed:", e)

    # 3) 최종 Brep들을 메쉬로 변환
    support_meshes = Brep2Mesh(result_breps)
    if not support_meshes:
        print("Error: Brep->Mesh conversion produced no meshes, using simple box mesh")
        support_meshes = [support_box_mesh]

    # --- 3. 입력 메쉬들을 Z-방향으로 이동한 복사본 생성 (offset 메쉬: Z축만 사용, 디버그용으로만 문서에 추가) ---
    offset_meshes = []
    try:
        dz = float(offset)
    except Exception:
        dz = 0.0

    if abs(dz) > 1e-6:
        move_down = rg.Transform.Translation(0.0, 0.0, -dz)

        for mesh in product_meshes:
            if not mesh:
                continue
            moved = mesh.DuplicateMesh()
            if not moved:
                continue
            moved.Transform(move_down)
            # 디버그용 offset 메쉬를 문서에 추가하고 id만 보관
            mid = sc.doc.Objects.AddMesh(moved)
            offset_meshes.append(mid)

    # --- 4. support_meshes를 문서에 추가하고, moved crown(offset_meshes)과 MeshBooleanDifference 실행 ---
    support_ids = []
    for mesh in support_meshes:
        sid = sc.doc.Objects.AddMesh(mesh)
        support_ids.append(sid)

    # Rhino 커맨드로 MeshBooleanDifference 실행: support_ids - offset_meshes
    result_support_ids = support_ids[:]
    if support_ids and offset_meshes:
        try:
            rs.UnselectAllObjects()

            # 첫 번째 집합(A): 서포트 메쉬 선택
            rs.SelectObjects(support_ids)

            # 두 번째 집합(B): offset 메쉬들은 _SelID로 커맨드 안에서 지정
            selid_tokens = " ".join("_SelID {}".format(str(mid)) for mid in offset_meshes)
            cmd = "!_-MeshBooleanDifference _DeleteInput=Yes {} _Enter".format(selid_tokens)
            rs.Command(cmd, echo=False)

            # moved crown(offset) 메쉬는 항상 제거해서 장면에 남지 않도록 정리
            try:
                rs.DeleteObjects(offset_meshes)
            except Exception:
                pass
        except Exception as e:
            print('[create_support] Warning: MeshBooleanDifference command failed:', e)

    return result_support_ids


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
    
    # 2. 여러 offset 값으로 서포트 생성 및 정렬 (한 열만 사용)
    # offsets = [0.10]
    offsets = [0.14, 0.16,.18]
    total_x_shift = 0.0
    all_created_objects = []

    try:
        rs.EnableRedraw(False)
        for offset_val in offsets:
            # 각 offset 값에 대해 서포트 한 세트만 생성
            copy_objs = rs.CopyObjects(product)
            support_ids = create_support(copy_objs, offset=str(offset_val))

            if support_ids:
                group = copy_objs + support_ids

                # create_support에서 ENABLE_OFFSET_DEBUG=True 인 경우 생성된 offset 디버그 메쉬도 함께 이동
                debug_ids = sc.sticky.get("offset_debug_ids", []) if hasattr(sc, "sticky") else []
                if debug_ids:
                    group = group + debug_ids
                bbox = rg.BoundingBox.Empty
                for obj_id in group:
                    obj = sc.doc.Objects.Find(obj_id)
                    if obj:
                        bbox.Union(obj.Geometry.GetBoundingBox(True))

                if bbox.IsValid:
                    # 바운딩박스를 이용해 X 이동량 계산
                    width = bbox.Max.X - bbox.Min.X

                    # X축 정렬 (offset 별로 오른쪽으로 차례대로 배치)
                    rs.MoveObjects(group, (total_x_shift, 0, 0))
                    # 이번 offset 세트에 사용한 debug ids는 재사용되지 않도록 초기화
                    if hasattr(sc, "sticky") and "offset_debug_ids" in sc.sticky:
                        sc.sticky["offset_debug_ids"] = []
                    all_created_objects.extend(group)

                    # 다음 offset을 위한 X축 이동량 갱신
                    total_x_shift += width + 2.0  # 서포트 사이 2mm 간격
                else:
                    rs.DeleteObjects(group)
            else:
                # 서포트 생성 실패 시 복사본 제거
                rs.DeleteObjects(copy_objs)

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
