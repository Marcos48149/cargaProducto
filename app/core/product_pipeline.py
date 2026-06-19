import base64
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))


def image_to_data_url(path):
    with open(path, 'rb') as f:
        data = base64.b64encode(f.read()).decode()
    ext = os.path.splitext(path)[1].lower().lstrip('.')
    mime = {
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'png': 'image/png', 'webp': 'image/webp',
        'gif': 'image/gif',
    }.get(ext, 'image/jpeg')
    return f'data:{mime};base64,{data}'


def generate_product(sku, images):
    from vtex_loader import (
        PREFIX_TO_MARCA, analizar_producto_con_gpt, buscar_en_web, get_talles
    )

    prefijo = sku.split('-')[0].upper()
    marca = PREFIX_TO_MARCA.get(prefijo, prefijo.lower())

    if not images:
        return None

    image_url = image_to_data_url(images[0])
    web_title, _ = buscar_en_web(sku, marca)
    datos = analizar_producto_con_gpt(sku, image_url, marca, web_title)
    datos = {k.lower(): v for k, v in datos.items()}

    cat = datos.get('categoria')
    talles = get_talles(marca, cat) if cat else []

    datos['talles'] = [t['uk'] for t in talles]
    datos['marca'] = marca
    return datos
