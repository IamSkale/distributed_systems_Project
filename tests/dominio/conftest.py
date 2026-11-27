"""Federación simulada sin Ray: `RedLocal` conecta varios `ServidorBlueJay` a mano."""

import pytest

from bluejay.transporte_local import RedLocal as Red


@pytest.fixture
def red() -> Red:
    """alpha, beta y gamma con Ana, Beto y Caro (el guion de la demo)."""
    red = Red("alpha.local", "beta.local", "gamma.local")
    red["alpha.local"].registrar_usuario("ana", "Ana")
    red["beta.local"].registrar_usuario("beto", "Beto")
    red["gamma.local"].registrar_usuario("caro", "Caro")
    return red
