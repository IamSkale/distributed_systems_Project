"""Configuración común a todas las pruebas."""

# Importar `bluejay` antes que cualquier conftest o prueba importe `ray`: así se aplica
# `RAY_ENABLE_UV_RUN_RUNTIME_ENV=0` (ver `bluejay/__init__.py`).
import bluejay  # noqa: F401
