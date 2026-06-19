import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vtex_loader import (
    crear_producto as _crear_producto,
    get_talles as _get_talles,
    get_dimensiones as _get_dimensiones,
    PREFIX_TO_MARCA,
)


def _talles_seleccionados(talles_raw, uk_list):
    if not talles_raw:
        return []
    if uk_list:
        return [t for t in talles_raw if t['uk'] in uk_list]
    return talles_raw


def upload_product(prod, log_callback):
    log_callback(f"{'─' * 40}")
    log_callback(f"▶ {prod.sku}")

    prefijo = prod.sku.split('-')[0].upper()
    marca = PREFIX_TO_MARCA.get(prefijo, prefijo.lower())

    if not prod.categoria:
        log_callback("❌ Sin categoría — saltando")
        return False
    if prod.categoria not in _get_categorias_dict():
        log_callback(f"❌ Categoría inválida: {prod.categoria}")
        return False

    log_callback("📦 Creando producto...")
    pid = _crear_producto(
        titulo=prod.titulo or prod.sku,
        descripcion=prod.descripcion or "",
        categoria_key=prod.categoria,
        marca_key=marca,
        codigo_ref=prod.sku,
        palabras_clave=prod.palabras_clave or "",
        url_slug=prod.url_slug or prod.sku.lower(),
    )
    if not pid:
        log_callback("❌ Error creando producto")
        return False
    log_callback(f"✅ Producto ID: {pid}")

    talles_raw = _get_talles(marca, prod.categoria)
    talles = _talles_seleccionados(talles_raw, prod.talles)
    if not talles:
        log_callback("❌ Sin talles válidos — saltando")
        return False
    log_callback(f"   {len(talles)} talles: {', '.join(t['uk'] for t in talles)}")

    dim = _get_dimensiones(prod.categoria)

    log_callback("   Subiendo SKUs, precios y talles...")

    from vtex_loader import subir_skus_async as _subir_skus

    async def _subir():
        return await _subir_skus(
            producto_id=pid,
            talles=talles,
            codigo_sku=prod.sku,
            urls_imagenes=[],
            categoria_key=prod.categoria,
            dim=dim,
        )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        sku_ids = loop.run_until_complete(_subir())
    except Exception as e:
        log_callback(f"❌ Error en subida: {e}")
        return False
    finally:
        loop.close()

    if not sku_ids:
        log_callback("❌ No se crearon SKUs")
        return False

    log_callback(f"🎉 {prod.sku} → ProductID {pid} | {len(sku_ids)} SKUs")
    return True


def _get_categorias_dict():
    from vtex_loader import CATEGORIAS
    return CATEGORIAS
