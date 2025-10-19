#! python 3
# env: /Users/joonholee/Joon/1-Project/3d_print/rhino

# 이것은 라이브러리 캐쉬 리셋
import importlib
importlib.reload(importlib.import_module('lib.reload'))
import lib.reload

# 모듈 리로드
modules = {
    'lib.globals': 'all'
}
lib.reload.reload_and_import_modules('crowns', modules)

from Rhino.DocObjects import *
import scriptcontext as sc
import rhinoscriptsyntax as rs
import Rhino.Geometry as rg
from lib.globals import *

def lowest_z(product):
    # product mesh의 최저점 찾기
    min_z = float('inf')
    lowest_point = None
    
    for obj_id in product:
        mesh = rs.coercemesh(obj_id)
        if mesh:
            for vertex in mesh.Vertices:
                if vertex.Z < min_z:
                    min_z = vertex.Z
                    lowest_point = rg.Point3d(vertex.X, vertex.Y, vertex.Z)
    
    if lowest_point:
        return lowest_point


def add_support(product, bbox_min=None, bbox_max=None):
    found_points = []
    support_boxes = []
    
    # 박스 크기 (1mm x 1mm)
    width = 0.5
    depth = 0.5
    
    # 서포트 최대 갯수와 최소 간격
    max_iterations = 50
    min_distance = 4.5

    min_distance_sq = min_distance * min_distance  # 거리 제곱으로 비교 (sqrt 연산 제거)
    
    
    # mesh를 한 번만 가져오기
    meshes = []
    for obj_id in product:
        mesh = rs.coercemesh(obj_id)
        if mesh:
            meshes.append(mesh)
    
    # product의 bounding box 계산 (외부에서 전달받으면 재사용)
    if bbox_min is None or bbox_max is None:
        bbox_min = get_min(product)
        bbox_max = get_max(product)
    
    bbox_min_x, bbox_min_y = bbox_min[0], bbox_min[1]
    bbox_max_x, bbox_max_y = bbox_max[0], bbox_max[1]
    
    
    # bounding box 경계값 미리 계산
    bbox_min_x_limit = bbox_min_x + width
    bbox_max_x_limit = bbox_max_x - width
    bbox_min_y_limit = bbox_min_y + depth
    bbox_max_y_limit = bbox_max_y - depth
    
    for i in range(max_iterations):
        min_z = float('inf')
        lowest_point = None
        
        # product mesh에서 최저점 찾기 (모든 found_points와 min_distance 이상 떨어진 점)
        for mesh in meshes:
            for vertex in mesh.Vertices:
                # bounding box - width/depth 범위 내에 있는지 확인 (미리 계산된 값 사용)
                if (vertex.X < bbox_min_x_limit or vertex.X > bbox_max_x_limit or
                    vertex.Y < bbox_min_y_limit or vertex.Y > bbox_max_y_limit):
                    continue
                
                # z값이 현재 최소값보다 크면 스킵 (조기 종료)
                if vertex.Z >= min_z:
                    continue
                
                # 모든 found_points와의 xy 평면 거리 확인 (z 좌표 제외)
                # found_points가 증가할수록 조건을 만족하는 점이 줄어들어 조기 종료됨
                too_close = False
                for found_pt in found_points:
                    dx = vertex.X - found_pt.X
                    dy = vertex.Y - found_pt.Y
                    dist_sq = dx*dx + dy*dy  # z 좌표 제외
                    if dist_sq < min_distance_sq:
                        too_close = True
                        break
                
                # 모든 found_points와 min_distance 이상 떨어져 있고, z값이 가장 낮은 점 찾기
                if not too_close:
                    min_z = vertex.Z
                    lowest_point = rg.Point3d(vertex.X, vertex.Y, vertex.Z)
        
        # 더 이상 조건을 만족하는 점이 없으면 조기 종료 (보통 2~3개 후)
        if lowest_point is None:
            break
        
        # 직육면체 추가 및 기록 (1mm x 1mm 고정 크기)
        # Box 생성
        plane = rg.Plane(rg.Point3d(lowest_point.X, lowest_point.Y, 0), rg.Vector3d.ZAxis)
        interval_x = rg.Interval(-width, width)
        interval_y = rg.Interval(-depth, depth)
        interval_z = rg.Interval(0, lowest_point.Z)
        box = rg.Box(plane, interval_x, interval_y, interval_z)
        
        box_id = rs.AddBox(box.GetCorners())
        support_boxes.append(box_id)
        found_points.append(lowest_point)
    
    return support_boxes

def add_base(product, bbox_min=None, bbox_max=None):
    # product mesh의 bounding box를 찾아서 x,y 평면에 투영시키기
    # 투영된 사각형을 +z축으로 2mm만큼 올려서 box를 만들기
    
    # bounding box 재사용 (외부에서 전달받으면 중복 계산 방지)
    if bbox_min is None or bbox_max is None:
        bbox_min = get_min(product)
        bbox_max = get_max(product)
    
    min_x, min_y = bbox_min[0], bbox_min[1]
    max_x, max_y = bbox_max[0], bbox_max[1]
    
    # xy 평면에 투영된 사각형으로 2mm 높이의 box 생성
    base_height = 2.0
    bottom_plane = rg.Plane(rg.Point3d(min_x, min_y, 0), rg.Vector3d.ZAxis)
    interval_x = rg.Interval(0, max_x - min_x)
    interval_y = rg.Interval(0, max_y - min_y)
    interval_z = rg.Interval(0, base_height)
    
    base_box = rg.Box(bottom_plane, interval_x, interval_y, interval_z)
    base_id = rs.AddBox(base_box.GetCorners())
    return base_id

def add_text(product, id, bbox_min=None, bbox_max=None):
    # product의 xy 평면 크기 계산 (bounding box 재사용)
    if bbox_min is None or bbox_max is None:
        bbox_min = get_min(product)
        bbox_max = get_max(product)
    
    width = bbox_max[0] - bbox_min[0]
    height = bbox_max[1] - bbox_min[1]
    target_width = min(width, height) * 0.8
    
    # 텍스트 길이에 따른 대략적인 너비 비율 (Arial Black 기준)
    # 3자리 숫자의 경우 대략 text_height * 2.5 정도의 너비
    text_length = len(str(id))
    estimated_width_ratio = text_length * 0.8  # 글자당 약 0.8배
    
    # 전체 텍스트가 target_width가 되도록 text_size 계산
    text_size = target_width / estimated_width_ratio
    text_depth = 1.0
    
    # product의 중심 위치 계산 (bounding box로 계산)
    center_x = (bbox_min[0] + bbox_max[0]) / 2.0
    center_y = (bbox_min[1] + bbox_max[1]) / 2.0
    text_position = (center_x, center_y, 0)
    
    text = text_object(id, text_size, text_depth, 0, text_position, 0, True)
    return text

def main():
    rs.Command(f'!_-SelAll')
    product = rs.SelectedObjects()

    # flip by x axis
    product = rs.RotateObjects(product, (0, 0, 0), 180, (1, 0, 0))
    
    # move z up by 4mm
    z_min = get_min(product)[2]
    rs.MoveObjects(product, (0, 0, -z_min + 4))
    assign_object(product, 'print', 'product')
    
    # bounding box를 한 번만 계산하여 재사용
    bbox_min = get_min(product)
    bbox_max = get_max(product)

    # add support
    support = add_support(product, bbox_min, bbox_max)
    
    # add base
    base = add_base(product, bbox_min, bbox_max)
    
    # add text
    text = add_text(product, '003', bbox_min, bbox_max)
    
    # boolean op.
    # 1. support와 base를 union
    support_base = support + [base]
    union_result = rs.BooleanUnion(support_base, delete_input=True)
    
    # 2. union 결과에서 text를 difference
    if union_result and text:
        final_result = rs.BooleanDifference(union_result, text, delete_input=True)
        if final_result:
            assign_object(final_result, 'print', 'support_base')
    

if __name__ == "__main__":
    print("AddSupport started.")
    main()