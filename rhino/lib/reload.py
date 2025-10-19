#! python 3
# env: /Users/joonholee/Joon/1-Project/3d_print/rhino/lib

def reload_and_import_modules(prefix='ortho', modules_to_reload={}):
    """
    특정 접두사로 시작하는 모든 모듈과 특정 모듈들을 리로드하고 자동으로 임포트합니다.
    
    Args:
        prefix (str): 리로드할 모듈의 접두사
        modules_to_reload (dict): 리로드할 모듈 정보 (키: 모듈 경로, 값: 임포트 방식)
                                 임포트 방식은 'all'(* 임포트) 또는 특정 객체 리스트가 될 수 있습니다.
    
    Returns:
        dict: 임포트된 모듈과 객체들
    """
    import sys
    import importlib
    import gc
    
    # 결과를 저장할 딕셔너리
    imported_objects = {}
    
    # 1. 접두사로 시작하는 모든 모듈 제거
    for key in list(sys.modules.keys()):
        if key.startswith(prefix):
            del sys.modules[key]
    
    # 2. 특정 모듈 리로드 및 임포트
    for module_path, import_type in modules_to_reload.items():
        try:
            # 모듈 리로드
            module = importlib.import_module(module_path)
            reloaded_module = importlib.reload(module)
            
            # 모듈 자체를 결과에 저장
            imported_objects[module_path] = reloaded_module
            
            # 글로벌 네임스페이스에 모듈 추가
            calling_frame = sys._getframe(1)
            
            # import_type에 따라 다르게 처리
            if import_type == 'all':
                # * 임포트: 모든 공개 객체 임포트
                for attr_name in dir(reloaded_module):
                    # 언더스코어로 시작하지 않는 속성만 임포트
                    if not attr_name.startswith('_'):
                        attr_value = getattr(reloaded_module, attr_name)
                        calling_frame.f_globals[attr_name] = attr_value
                        imported_objects[attr_name] = attr_value
            elif isinstance(import_type, list):
                # 특정 객체만 임포트
                for attr_name in import_type:
                    if hasattr(reloaded_module, attr_name):
                        attr_value = getattr(reloaded_module, attr_name)
                        calling_frame.f_globals[attr_name] = attr_value
                        imported_objects[attr_name] = attr_value
            
            print(f"{module_path} reload and import completed")
            
        except Exception as e:
            print(f"{module_path} reload and import failed: {e}")
    
    # 3. 가비지 컬렉션 실행
    collected = gc.collect()
    print(f"Garbage collection: {collected} objects collected")
    
    return imported_objects