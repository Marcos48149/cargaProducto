"""
ShowSport VTEX Loader
Corre automáticamente via GitHub Actions todos los días.
Detecta imágenes nuevas en Drive y las sube a VTEX.
"""

import os
import json
import asyncio
import aiohttp
import base64
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from io import BytesIO

import requests
from PIL import Image
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import google.generativeai as genai

load_dotenv()

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('vtex_loader.log', encoding='utf-8')
    ]
)
log = logging.getLogger(__name__)

# ── Credenciales ─────────────────────────────────────────────
VTEX_ACCOUNT   = os.getenv('VTEX_ACCOUNT', 'showsport')
VTEX_APP_KEY   = os.getenv('VTEX_APP_KEY')
VTEX_APP_TOKEN = os.getenv('VTEX_APP_TOKEN')
VTEX_BASE_URL  = f'https://{VTEX_ACCOUNT}.vtexcommercestable.com.br'
VTEX_HEADERS   = {
    'X-VTEX-API-AppKey':   VTEX_APP_KEY,
    'X-VTEX-API-AppToken': VTEX_APP_TOKEN,
    'Content-Type':        'application/json',
    'Accept':              'application/json',
}

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
genai.configure(api_key=GEMINI_API_KEY)

WAREHOUSE_ID = '1_1'

# ── Google Drive ──────────────────────────────────────────────
def get_drive_service():
    """Autenticar con Google Drive usando credenciales de GitHub Secrets."""
    creds_json = os.getenv('GOOGLE_CREDENTIALS')
    if not creds_json:
        raise ValueError('Falta GOOGLE_CREDENTIALS en los secrets')

    creds_data = json.loads(creds_json)
    creds = Credentials(
        token=creds_data['token'],
        refresh_token=creds_data['refresh_token'],
        token_uri='https://oauth2.googleapis.com/token',
        client_id=creds_data['client_id'],
        client_secret=creds_data['client_secret'],
        scopes=['https://www.googleapis.com/auth/drive']
    )
    if creds.expired:
        creds.refresh(Request())

    return build('drive', 'v3', credentials=creds)


def obtener_imagenes_nuevas(drive_service, horas=24):
    """
    Busca imágenes agregadas en las últimas N horas en la carpeta FOTOS PRODUCTOS.
    Devuelve lista de dicts con {sku, file_id, nombre}.
    """
    # Buscar carpeta
    carpeta = drive_service.files().list(
        q="name='FOTOS PRODUCTOS' and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id, name)"
    ).execute()

    if not carpeta['files']:
        log.error("No encontré la carpeta 'FOTOS PRODUCTOS' en Drive")
        return []

    carpeta_id = carpeta['files'][0]['id']

    # Calcular fecha límite (últimas 24 horas)
    ahora = datetime.now(timezone.utc)
    desde = ahora - timedelta(hours=horas)
    desde_str = desde.strftime('%Y-%m-%dT%H:%M:%S')

    # Buscar imágenes nuevas
    query = (
        f"'{carpeta_id}' in parents "
        f"and trashed=false "
        f"and mimeType contains 'image/' "
        f"and createdTime > '{desde_str}'"
    )
    resultados = drive_service.files().list(
        q=query,
        fields="files(id, name, createdTime)",
        orderBy="name"
    ).execute()

    archivos = resultados.get('files', [])
    log.info(f"Imágenes nuevas en las últimas {horas}h: {len(archivos)}")

    # Extraer SKUs únicos
    skus_vistos = set()
    imagenes = []
    for archivo in archivos:
        nombre = archivo['name']
        sku = nombre.rsplit('.', 1)[0].split(' (')[0].strip()
        if sku not in skus_vistos:
            skus_vistos.add(sku)
            imagenes.append({
                'sku':     sku,
                'file_id': archivo['id'],
                'nombre':  nombre,
            })
            log.info(f"  Nuevo SKU detectado: {sku}")

    return imagenes


def hacer_publico(drive_service, file_id):
    """Hace pública una imagen y devuelve su URL."""
    try:
        drive_service.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()
    except Exception:
        pass
    return f"https://drive.google.com/uc?export=view&id={file_id}"


def buscar_todas_imagenes_sku(drive_service, sku, carpeta_id):
    """Busca todas las imágenes de un SKU (principal + adicionales)."""
    query = f"name contains '{sku}' and '{carpeta_id}' in parents and trashed=false"
    resultados = drive_service.files().list(
        q=query,
        fields="files(id, name)",
        orderBy="name"
    ).execute()
    return resultados.get('files', [])


# ── Mapas de referencia ───────────────────────────────────────
PREFIX_TO_MARCA = {
    'NIK': 'nike', 'ADI': 'adidas', 'PUM': 'puma', 'FIL': 'fila',
    'UND': 'under armour', 'REE': 'reebok', 'ASI': 'asics', 'TOP': 'topper',
    'ON':  'on', 'HL': 'hang loose', 'PRO': 'pro one', 'UMB': 'umbro',
    'DIA': 'diadora', 'PEN': 'penalty', 'VAN': 'vans', 'CON': 'converse',
    'ATM': 'atomik', 'ADD': 'addnice', 'FOO': 'footy', 'SAL': 'salomon',
    'NB':  'new balance', 'MON': 'montagne', 'DC': 'dc', 'CRO': 'crocs',
    'UA':  'under armour', 'HEA': 'head', 'KAP': 'kappa', 'SKE': 'skechers',
    'COL': 'columbia', 'QUI': 'quiksilver',
}

MARCAS = {
    'adidas': 2000001, 'puma': 2000002, 'reebok': 2000003,
    'nike': 2000012, 'fila': 2000006, 'under armour': 2000043,
    'asics': 2000071, 'topper': 2000008, 'on': 2000145,
    'vans': 2000027, 'umbro': 2000013, 'diadora': 2000039,
    'penalty': 2000007, 'converse': 2000064, 'atomik': 2000036,
    'addnice': 2000005, 'footy': 2000048, 'salomon': 2000059,
    'new balance': 2000015, 'montagne': 2000029, 'dc': 2000026,
    'crocs': 2000058, 'head': 2000053, 'kappa': 2000049,
    'skechers': 2000128, 'columbia': 2000153, 'hang loose': 2000090,
    'quiksilver': 2000084, 'pro one': 2000074,
}

CATEGORIAS = {
    'hombre_zapatillas':  {'dept_id': 8,  'cat_id': 118, 'cat': 'Zapatillas'},
    'hombre_remeras':     {'dept_id': 8,  'cat_id': 125, 'cat': 'Remeras'},
    'hombre_buzos':       {'dept_id': 8,  'cat_id': 121, 'cat': 'Buzos'},
    'hombre_camperas':    {'dept_id': 8,  'cat_id': 122, 'cat': 'Camperas'},
    'hombre_shorts':      {'dept_id': 8,  'cat_id': 120, 'cat': 'Shorts'},
    'hombre_pantalones':  {'dept_id': 8,  'cat_id': 124, 'cat': 'Pantalones'},
    'hombre_calzas':      {'dept_id': 8,  'cat_id': 128, 'cat': 'Calzas'},
    'hombre_medias':      {'dept_id': 8,  'cat_id': 187, 'cat': 'Medias'},
    'hombre_botines':     {'dept_id': 8,  'cat_id': 119, 'cat': 'Botines'},
    'hombre_mochilas':    {'dept_id': 8,  'cat_id': 186, 'cat': 'Mochilas'},
    'hombre_bolsos':      {'dept_id': 8,  'cat_id': 190, 'cat': 'Bolsos'},
    'hombre_gorras':      {'dept_id': 8,  'cat_id': 188, 'cat': 'Gorras'},
    'hombre_ojotas':      {'dept_id': 8,  'cat_id': 117, 'cat': 'Ojotas'},
    'mujer_zapatillas':   {'dept_id': 9,  'cat_id': 106, 'cat': 'Zapatillas'},
    'mujer_remeras':      {'dept_id': 9,  'cat_id': 113, 'cat': 'Remeras'},
    'mujer_buzos':        {'dept_id': 9,  'cat_id': 108, 'cat': 'Buzos'},
    'mujer_camperas':     {'dept_id': 9,  'cat_id': 110, 'cat': 'Camperas'},
    'mujer_shorts':       {'dept_id': 9,  'cat_id': 114, 'cat': 'Shorts'},
    'mujer_calzas':       {'dept_id': 9,  'cat_id': 109, 'cat': 'Calzas'},
    'mujer_tops':         {'dept_id': 9,  'cat_id': 129, 'cat': 'Tops'},
    'mujer_mallas':       {'dept_id': 9,  'cat_id': 115, 'cat': 'Mallas'},
    'mujer_botines':      {'dept_id': 9,  'cat_id': 107, 'cat': 'Botines'},
    'mujer_mochilas':     {'dept_id': 9,  'cat_id': 199, 'cat': 'Mochilas'},
    'mujer_bolsos':       {'dept_id': 9,  'cat_id': 203, 'cat': 'Bolsos'},
    'mujer_ojotas':       {'dept_id': 9,  'cat_id': 104, 'cat': 'Ojotas'},
    'unisex_zapatillas':  {'dept_id': 8,  'cat_id': 118, 'cat': 'Zapatillas'},
    'ninos_zapatillas':   {'dept_id': 10, 'cat_id': 92,  'cat': 'Zapatillas'},
    'ninos_remeras':      {'dept_id': 10, 'cat_id': 98,  'cat': 'Remeras'},
    'ninos_camperas':     {'dept_id': 10, 'cat_id': 95,  'cat': 'Camperas'},
    'ninos_botines':      {'dept_id': 10, 'cat_id': 93,  'cat': 'Botines'},
    'ninos_shorts':       {'dept_id': 10, 'cat_id': 100, 'cat': 'Shorts'},
    'ninos_buzos':        {'dept_id': 10, 'cat_id': 94,  'cat': 'Buzos'},
    'ninos_conjuntos':    {'dept_id': 10, 'cat_id': 96,  'cat': 'Conjuntos'},
    'ninos_ojotas':       {'dept_id': 10, 'cat_id': 89,  'cat': 'Ojotas'},
}

TALLES_FIELD_VALUE_IDS = {
    '31': 2511, '31.5': 2509, '32': 2313, '32.5': 2314,
    '33': 117,  '33.5': 118,  '34': 82,   '34.5': 83,
    '35': 84,   '35.5': 85,   '36': 86,   '36.5': 87,
    '37': 88,   '37.5': 89,   '38': 90,   '38.5': 91,
    '39': 92,   '39.5': 93,   '40': 94,   '40.5': 95,
    '41': 96,   '41.5': 97,   '42': 98,   '42.5': 107,
    '43': 108,  '43.5': 109,  '44': 110,  '44.5': 111,
    '45': 112,  '45.5': 113,  '46': 114,  '46.5': 2306,
    '47': 1873, '48': 2510,
    'XS': 338,  'S': 339,  'M': 340,  'L': 341,
    'XL': 342,  '2XL': 343, '3XL': 344,
    'unico': 2591, 'MISC': 2534, '0': 723, 'OS': 2148,
}

TALLES_FIELD_VALUE_IDS_NINOS = {
    '16': 252,  '17': 207,  '17.5': 208, '18': 209,
    '19': 211,  '19.5': 212, '20': 213,  '21': 215,
    '21.5': 216, '22': 217, '22.5': 218, '23.5': 220,
    '24': 221,  '24.5': 222, '25': 223,  '26': 225,
    '26.5': 226, '27': 227, '27.5': 228, '28': 229,
    '28.5': 230, '29': 231, '29.5': 232, '30.5': 234,
    '31': 235,  '31.5': 236, '32': 237,  '33': 239,
    '34': 241,  '35.5': 244, '36.5': 293,
}


# ── Gemini — analizar producto ────────────────────────────────
def analizar_producto_con_gemini(codigo_sku, url_imagen, marca):
    model = genai.GenerativeModel("gemini-2.0-flash")

    r = requests.get(url_imagen, timeout=15)
    imagen_pil = Image.open(BytesIO(r.content))

    categorias_str = '\n'.join(f'  - {c}' for c in CATEGORIAS.keys())

    prompt = f"""Sos un experto en categorización de productos deportivos.
Analizá esta imagen de un producto de la marca {marca} con código {codigo_sku}.

Categorías disponibles (elegí la más exacta):
{categorias_str}

Devolvé SOLO este JSON sin texto extra:
{{
  "modelo": "[nombre del modelo exacto]",
  "color": "[color principal en español]",
  "categoria": "[una categoria de la lista de arriba]",
  "talles_manuales": null
}}"""

    response = model.generate_content([imagen_pil, prompt])
    texto = response.text.strip()
    if '```' in texto:
        texto = texto.split('```')[1]
        if texto.startswith('json'):
            texto = texto[4:]
    return json.loads(texto.strip())


# ── VTEX — funciones principales ─────────────────────────────
def crear_producto(titulo, descripcion, categoria_key, marca_key, codigo_ref,
                   palabras_clave, url_slug):
    cat      = CATEGORIAS[categoria_key]
    marca_id = MARCAS.get(marca_key.lower(), 0)
    payload  = {
        'Name':               titulo,
        'CategoryId':         cat['cat_id'],
        'BrandId':            marca_id,
        'RefId':              codigo_ref,
        'Title':              titulo,
        'MetaTagDescription': titulo,
        'Description':        descripcion,
        'IsVisible':          True,
        'IsActive':           True,
        'ShowWithoutStock':   False,
        'KeyWords':           palabras_clave,
        'LinkId':             url_slug,
    }
    r = requests.post(f'{VTEX_BASE_URL}/api/catalog/pvt/product',
                      headers=VTEX_HEADERS, json=payload, timeout=30)
    if r.status_code in [200, 201]:
        pid = r.json()['Id']
        log.info(f'  ✅ Producto creado ID: {pid}')
        return pid
    log.error(f'  ❌ Error producto: {r.status_code} — {r.text[:200]}')
    return None


# ── Subida async ──────────────────────────────────────────────
async def subir_skus_async(producto_id, talles, codigo_sku, urls_imagenes,
                            categoria_key, dim):
    categoria_base = categoria_key.replace('_jr', '')

    if 'ninos' in categoria_base:
        field_id = 21
        mapa_fvid = TALLES_FIELD_VALUE_IDS_NINOS
    elif any(x in categoria_base for x in ['zapatillas', 'botines', 'crocs', 'ojotas']):
        field_id = 18 if 'mujer' in categoria_base else 19
        mapa_fvid = TALLES_FIELD_VALUE_IDS
    elif any(x in categoria_base for x in ['mochilas', 'bolsos', 'gorras', 'medias']):
        field_id = 29
        mapa_fvid = TALLES_FIELD_VALUE_IDS
    elif 'mujer' in categoria_base:
        field_id = 27
        mapa_fvid = TALLES_FIELD_VALUE_IDS
    else:
        field_id = 25
        mapa_fvid = TALLES_FIELD_VALUE_IDS

    headers_async = {
        'X-VTEX-API-AppKey':   VTEX_APP_KEY,
        'X-VTEX-API-AppToken': VTEX_APP_TOKEN,
        'Content-Type':        'application/json',
        'Accept':              'application/json',
    }

    async with aiohttp.ClientSession(headers=headers_async) as session:
        # Crear SKUs
        async def crear_sku(talle):
            payload = {
                'ProductId':          producto_id,
                'Name':               str(talle['uk']),
                'RefId':              f'{codigo_sku} {talle["uk"]}',
                'ManufacturerCode':   codigo_sku,
                'IsActive':           False,
                'ActivateIfPossible': True,
                'IsKit':              False,
                'PackagedWeightKg':   dim['peso'] / 1000,
                'PackagedWidth':      dim['ancho'],
                'PackagedHeight':     dim['alto'],
                'PackagedLength':     dim['largo'],
            }
            async with session.post(
                f'{VTEX_BASE_URL}/api/catalog/pvt/stockkeepingunit',
                json=payload
            ) as r:
                if r.status in [200, 201]:
                    data = await r.json()
                    return data['Id']
                return None

        sku_ids_raw = await asyncio.gather(*[crear_sku(t) for t in talles])
        skus_ok = [(talles[i], sid) for i, sid in enumerate(sku_ids_raw) if sid]
        log.info(f'  ✅ {len(skus_ok)} SKUs creados')

        # Precio y stock
        async def set_precio(sid):
            async with session.put(
                f'{VTEX_BASE_URL}/api/pricing/prices/{sid}',
                json={'basePrice': 0, 'listPrice': 0}
            ) as r:
                return r.status

        async def set_stock(sid):
            async with session.put(
                f'{VTEX_BASE_URL}/api/logistics/pvt/inventory/skus/{sid}/warehouses/{WAREHOUSE_ID}',
                json={'quantity': 0, 'unlimitedQuantity': False}
            ) as r:
                return r.status

        await asyncio.gather(
            *[set_precio(sid) for _, sid in skus_ok],
            *[set_stock(sid)  for _, sid in skus_ok],
        )

        # Imágenes
        tareas_img = []
        for i, (_, sid) in enumerate(skus_ok):
            for j, img in enumerate(urls_imagenes):
                async def asignar_img(s=sid, u=img['url'], n=img['nombre'], p=(j == 0)):
                    async with session.post(
                        f'{VTEX_BASE_URL}/api/catalog/pvt/stockkeepingunit/{s}/file',
                        json={'IsMain': p, 'Label': n, 'Name': n, 'Text': n, 'Url': u}
                    ) as r:
                        return r.status
                tareas_img.append(asignar_img())
        await asyncio.gather(*tareas_img)
        log.info(f'  ✅ Imágenes asignadas')

        await asyncio.sleep(3)

        # Talles y activación
        async def asignar_talle(sid, talle):
            fvid = mapa_fvid.get(str(talle['arg']))
            if not fvid:
                return
            async with session.put(
                f'{VTEX_BASE_URL}/api/catalog/pvt/stockkeepingunit/{sid}/specificationvalue',
                json={'FieldId': field_id, 'FieldValue': str(talle['arg'])}
            ) as r:
                return r.status

        async def activar(sid):
            async with session.get(
                f'{VTEX_BASE_URL}/api/catalog/pvt/stockkeepingunit/{sid}'
            ) as r:
                data = await r.json()
            data['IsActive'] = True
            data['ActivateIfPossible'] = True
            async with session.put(
                f'{VTEX_BASE_URL}/api/catalog/pvt/stockkeepingunit/{sid}',
                json=data
            ) as r:
                return r.status

        await asyncio.gather(
            *[asignar_talle(sid, t) for t, sid in skus_ok],
            *[activar(sid)          for _, sid in skus_ok],
        )
        log.info(f'  ✅ Talles y activación completos')

    return [sid for _, sid in skus_ok]


# ── Flujo principal ───────────────────────────────────────────
async def main():
    log.info('=' * 60)
    log.info(f'Iniciando ShowSport VTEX Loader — {datetime.now()}')
    log.info('=' * 60)

    # 1. Conectar Drive
    drive_service = get_drive_service()

    # 2. Obtener imágenes nuevas de las últimas 24h
    imagenes_nuevas = obtener_imagenes_nuevas(drive_service, horas=24)
    if not imagenes_nuevas:
        log.info('Sin imágenes nuevas hoy. Nada que subir.')
        return

    # Obtener carpeta ID para buscar imágenes adicionales
    carpeta = drive_service.files().list(
        q="name='FOTOS PRODUCTOS' and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id)"
    ).execute()
    carpeta_id = carpeta['files'][0]['id']

    # 3. Procesar cada SKU nuevo
    resultados = []
    for item in imagenes_nuevas:
        codigo_sku = item['sku']
        log.info(f'\n{"─"*50}')
        log.info(f'Procesando: {codigo_sku}')

        try:
            # Detectar marca
            prefijo = codigo_sku.split('-')[0].upper()
            marca   = PREFIX_TO_MARCA.get(prefijo, prefijo.lower())

            # URL imagen principal para Gemini
            url_principal = hacer_publico(drive_service, item['file_id'])

            # Gemini analiza
            log.info('🤖 Analizando con Gemini...')
            datos = analizar_producto_con_gemini(codigo_sku, url_principal, marca)

            categoria = datos['categoria']
            if categoria not in CATEGORIAS:
                log.warning(f'Categoría inválida: {categoria} — saltando')
                continue

            log.info(f'   Modelo: {datos["modelo"]}')
            log.info(f'   Color:  {datos["color"]}')
            log.info(f'   Cat:    {categoria}')

            # Generar contenido con GPT-4o
            from openai import OpenAI
            client_oai = OpenAI(api_key=OPENAI_API_KEY)
            genero = ('Mujer' if 'mujer' in categoria else
                      'Niños' if 'ninos' in categoria else
                      'Unisex' if 'unisex' in categoria else 'Hombre')

            prompt_gpt = (
                f"Sos redactor e-commerce argentino para Showsport.\n"
                f"Producto: {datos['modelo']} | Marca: {marca.title()} | "
                f"Color: {datos['color']} | Género: {genero}\n"
                f"Generá este JSON sin texto extra:\n"
                f'{{"titulo":"{marca.title()} {datos["modelo"]} {datos["color"].title()} {genero}","descripcion":"[4 párrafos]","palabras_clave":"[keywords]","url_slug":"[slug]-{codigo_sku}"}}'
            )
            resp = client_oai.chat.completions.create(
                model='gpt-4o-mini',
                messages=[{'role': 'user', 'content': prompt_gpt}],
                max_tokens=600
            )
            texto = resp.choices[0].message.content.strip()
            if '```' in texto:
                texto = texto.split('```')[1]
                if texto.startswith('json'):
                    texto = texto[4:]
            contenido = json.loads(texto.strip())

            # Crear producto en VTEX
            producto_id = crear_producto(
                titulo         = contenido['titulo'],
                descripcion    = contenido['descripcion'],
                categoria_key  = categoria,
                marca_key      = marca,
                codigo_ref     = codigo_sku,
                palabras_clave = contenido['palabras_clave'],
                url_slug       = contenido['url_slug'],
            )
            if not producto_id:
                continue

            # Buscar todas las imágenes del SKU
            todos_archivos = buscar_todas_imagenes_sku(drive_service, codigo_sku, carpeta_id)
            urls_imagenes  = [
                {
                    'url':    hacer_publico(drive_service, a['id']),
                    'nombre': a['name'].rsplit('.', 1)[0],
                }
                for a in todos_archivos
            ]

            # Talles
            talles = get_talles(marca, categoria)

            # Dimensiones
            dim = get_dimensiones(categoria)

            # Subir SKUs async
            sku_ids = await subir_skus_async(
                producto_id    = producto_id,
                talles         = talles,
                codigo_sku     = codigo_sku,
                urls_imagenes  = urls_imagenes,
                categoria_key  = categoria,
                dim            = dim,
            )

            log.info(f'🎉 {codigo_sku} → ProductID {producto_id} | {len(sku_ids)} SKUs')
            resultados.append({'sku': codigo_sku, 'ok': True, 'producto_id': producto_id})

        except Exception as e:
            log.error(f'❌ Error en {codigo_sku}: {e}')
            resultados.append({'sku': codigo_sku, 'ok': False, 'error': str(e)})

        time.sleep(1)

    # Resumen
    ok    = sum(1 for r in resultados if r['ok'])
    error = sum(1 for r in resultados if not r['ok'])
    log.info(f'\n{"="*60}')
    log.info(f'RESUMEN: ✅ {ok} OK | ❌ {error} errores | Total: {len(resultados)}')


# Funciones de talles (copiar desde tu Colab)
def get_talles(marca, categoria_key):
    # ... (igual que en tu Colab)
    return [{'uk': 'unico', 'arg': 'unico'}]  # placeholder

def get_dimensiones(categoria_key):
    # ... (igual que en tu Colab)
    return {'peso': 500, 'ancho': 10, 'alto': 10, 'largo': 25}  # placeholder


if __name__ == '__main__':
    asyncio.run(main())