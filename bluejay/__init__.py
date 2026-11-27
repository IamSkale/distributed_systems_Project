"""Blue Jay: red federada de micropublicaciones."""

import os

# Con `uv run`, Ray (>= 2.43) hace por defecto que cada worker arranque con su propio
# `uv run` dentro de una copia del proyecto: eso crea un `.venv` nuevo (~280 MB) en
# `/tmp/ray` por cada `ray.init` y llena el disco. La Entrega 1 corre en un solo nodo, así
# que los workers pueden usar el mismo `.venv` del driver. Tiene que fijarse antes de
# `import ray` (Ray lo lee al importarse); `setdefault` deja volver a activarlo con
# `RAY_ENABLE_UV_RUN_RUNTIME_ENV=1`, por ejemplo para un clúster de varios nodos (F.3).
os.environ.setdefault("RAY_ENABLE_UV_RUN_RUNTIME_ENV", "0")
