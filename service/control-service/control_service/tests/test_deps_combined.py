"""require_teacher_or_device_token — import + signature smoke."""
def test_dep_import():
    from control_service.deps import require_teacher_or_device_token
    assert callable(require_teacher_or_device_token)
