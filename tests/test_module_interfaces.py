import ast
import importlib
from pathlib import Path

from core.transformer import (
    DataTransformError,
    TRANSFORM_RULE_VERSION,
    TransformResult,
    transform_data,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_PACKAGES = {
    "ai",
    "config",
    "core",
    "database",
    "exporters",
    "followers",
    "models",
    "services",
    "ui",
}


def test_transformer_public_interface_is_importable():
    assert issubclass(DataTransformError, ValueError)
    assert TRANSFORM_RULE_VERSION == "2.1.0"
    assert TransformResult.__name__ == "TransformResult"
    assert callable(transform_data)


def test_all_local_from_imports_reference_existing_names():
    failures: list[str] = []
    python_files = [PROJECT_ROOT / "app.py"]
    for package in LOCAL_PACKAGES:
        python_files.extend((PROJECT_ROOT / package).glob("*.py"))

    for path in python_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if node.module.split(".", maxsplit=1)[0] not in LOCAL_PACKAGES:
                continue
            module = importlib.import_module(node.module)
            for imported_name in node.names:
                if imported_name.name != "*" and not hasattr(module, imported_name.name):
                    failures.append(
                        f"{path.name}: {node.module}.{imported_name.name} is missing"
                    )

    assert failures == []
