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

import re
import requests
from PIL import Image
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
#import google.generativeai as genai

from openai import OpenAI

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


client_oai = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY")
)

OPENAI_API_KEY = os.getenv('OPENROUTER_API_KEY')
#GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
#genai.configure(api_key=GEMINI_API_KEY)

WAREHOUSE_ID = '1_1'

# ── Google Drive ──────────────────────────────────────────────
def get_drive_service():
    """Autenticar con Google Drive usando Service Account."""

    SCOPES = ['https://www.googleapis.com/auth/drive']

    creds = service_account.Credentials.from_service_account_file(
        'service-account.json',
        scopes=SCOPES
    )

    return build(
        'drive',
        'v3',
        credentials=creds
    )

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
    return f"https://drive.google.com/uc?export=download&id={file_id}"


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
# ////////TALLES /////////////

TALLES = {

    'nike': {
        'hombre': {  # US → ARG  (entero = talle, M = medio talle)
            '6':   '37.5', '6M':  '38',
            '7':   '39',   '7M':  '39.5',
            '8':   '40',   '8M':  '41',
            '9':   '41.5', '9M':  '42/42.5',
            '10':  '43',   '10M': '43.5',
            '11':  '44',   '11M': '44.5',
            '12':  '45',   '12M': '46',
            '13':  '46.5', '13M': '47',

        },
        'mujer': {
            '5':   '34.5', '5M':  '35',
            '6':   '35.5', '6M':  '36/36.5',
            '7':   '37',   '7M':  '37.5',
            '8':   '38',   '8M':  '39',
            '9':   '39.5', '9M':  '40',
            '10':  '41',   '10M': '41.5',

        },
        'ninos': {
            '10':  '27',   '10M': '27',
            '11':  '28',   '11M': '28',
            '12':  '29',   '12M': '29',
            '13':  '30',   '13M': '30',
            '1':   '31',   '1M':  '32',
            '2':   '32.5', '2M':  '33',
            '3':   '34',   '3M':  '34.5',
            '4':   '35',   '4M':  '35.5',
            '5':   '36.5', '5M':  '37',
            '6':   '37.5',
        },

        'talle_unico': 'MISC'
    },

    'adidas': {
        'hombre': {  # UK → ARG  (mismo para mujer adulto)

            '7':   '39',   '7M': '39.5',
            '8':   '40',   '8M': '41',
            '9':   '41.5', '9M': '42',
            '10':  '43',   '10M':'43.5',
            '11':  '44',   '11M':'45',
        },
        'mujer': {  # mismo que hombre
            '3':   '34.5', '3M': '34.5',
            '4':   '35.5', '4M': '36',
            '5':   '36.5', '5M': '37.5',
            '6':   '38',   '6M': '38.5',
            '7':   '39',   '7M': '39.5',
            '8':   '40', '9':   '41.5'
        },
        'unisex': {
            '3':   '34.5', '3M': '34.5',
            '4':   '35.5', '4M': '36',
            '5':   '36.5', '5M': '37.5',
            '6':   '38',   '6M': '38.5',
            '7':   '39',   '7M': '39.5',
            '8':   '40',   '8M': '41',
            '9':   '41.5', '9M': '42',
            '10':  '43',   '10M':'43.5',
            '11':  '44',   '11M':'45',
        },
          'ninos': {
        # NIÑOS 0-4 (UK Kids)
        '2k':    '16.5', '2.5k': '17',   '3k':   '17.5',
        '3.5k':  '18',   '4k':   '19',   '4.5k': '19.5',
        '5k':    '20',   '5.5k': '21',   '6k':   '21.5',
        '6.5k':  '22',   '7k':   '22.5', '7.5k': '23.5',
        '8k':    '24',   '8.5k': '24.5', '9k':   '25',
        },
        # NIÑOS 4-8 (UK Kids)
        'ninosJr': {
        '9.5k': '26',   '10k':  '26.5',
        '10.5k': '27',   '11k':  '27.5', '11.5k':'28.5',
        '12k':   '29',   '12.5k':'29.5', '13k':  '30.5',
        '13.5k': '31',   '1':    '31.5', '1.5':  '32',
        '2':     '33',   '2.5':  '33.5', '3':    '34',
        '3.5':   '34.5', '4':    '35.5', '4.5':  '36',
        '5':     '36.5', '5.5':  '37.5', '6':    '38',
        '6.5':   '38.5',
    },
    },

    'puma': {
        'hombre': {  # UK → ARG
            '7':   '39.5', '7M':  '40',
            '8':   '41',   '8M':  '41.5',
            '9':   '42',   '9M':  '43',
            '10':  '43.5', '10M': '44',
            '11':  '45',
            '12':  '46',
            '13':  '47',
        },
        'mujer': {
            '3':   '34.5', '3M':  '35',
            '4':   '36',   '4M':  '36.5',
            '5':   '37',   '5M':  '37.5',
            '6':   '38',   '6M':  '39',
            '7':   '39.5',
        },
        'ninos': {
            '10k': '27',  '11k':   '28',
            '11.5k': '29','12k':   '30',
            '12k': '30',  '13k':   '31',
            '1':   '32', '1M': '33',
            '2':     '34','2M': '34.5',
             '3':   '35', '3M': '35.5',
            '4':     '36',

        },
    },

    'fila': {
        'hombre': {  # ARG directo
            '38': '38', '39': '39', '40': '40', '41': '41',
            '42': '42', '43': '43', '44': '44', '45': '45',
            '46': '46', '47': '47',
        },
        'mujer': {
            '35': '35', '36': '36', '37': '37', '38': '38',
            '39': '39', '40': '40', '41': '41',
        },
        'ninos': {
            '22': '22', '23': '23', '24': '24', '25': '25',
            '26': '26', '27': '27', '28': '28', '29': '29',
            '30': '30', '31': '31', '32': '32', '33': '33', '34': '34',
        },
    },

    'reebok': {
        'hombre': {  # Us → ARG
            '6.5': '38',
            '7':   '38.5', '7M': '39' , '8':   '40',
            '8M': '40.5',   '9':  '41',
            '9M':'42', '10':  '43', '10M': '43.5',
            '11':  '44', '11M': '45',
            '12':  '45.5', '12M': '46',
        },
        'mujer': {  # Us → ARG
                '6': '35.5', '6M': '36',
                '7': '36.5', '7M': '37',
                '8': '38', '8M': '38.5',
                '9': '39', '9M': '40',
                '10': '40.5', '10M': '41',

        },
        'ninos': {
            '2.5': '34',  '3':   '34.5',
            '4':   '35',  '4.5': '35.5',
            '5':   '36',  '5.5': '36.5',
            '6':   '37',  '6.5': '38',
            '7':   '38.5','7.5': '39',
            '8':   '40',  '8.5': '41',
            '9':   '41.5',
        },
    },

    'under armour': {
        'hombre': {  # US → ARG
            '7':   '39',   '7M':  '39.5',
            '8':   '40',   '8M':  '41',
            '9':   '41.5', '9M':  '42',
            '10':  '43',   '10M': '43.5',
            '11':  '44',   '11M': '44.5',
            '12':  '45',   '12M': '46',
        },
        'mujer': {
            '5':   '34.5', '5M':  '35',
            '6':   '35.5', '6M':  '36.5',
            '7':   '37',   '7M':  '37.5',
            '8':   '38',   '8M':  '39',
            '9':   '39.5', '9M':  '40',
            '10':  '40.5', '10M': '41',
            '11':  '43.5', '12':  '43.5',
        },
    },

    'asics': {
        'hombre': {  # US → ARG
            '8':   '40',   '8M':  '40.5',
            '9':   '41',   '9M':  '42',
            '10':  '42.5', '10.5':'43',
            '11':  '43.5', '11M': '44',
            '12':  '45',   '12M': '46',
        },
        'mujer': {
            '6':   '36',   '6M':  '36',
            '7':   '37',   '7M':  '38',
            '8':   '38.5', '8M':  '39',
            '9':   '40',   '9M':  '40.5',
            '10':  '41',
        },
    },

    'new balance': {
        'hombre': {  # US → ARG
            '4':   '35',   '4M':  '36',
            '5':   '36.5', '5M':  '37',
            '6':   '37.5', '6M':  '38.5',
            '7':   '39',   '7M':  '39.5',
            '8':   '40.5', '8M':  '41',
            '9':   '41.5', '9M':  '42',
            '10':  '43',   '10M': '43.5',
            '11':  '44',   '11M': '44.5',
            '12':  '45.5', '12M': '46',
            '13':  '46.5',
            '14':  '48',
            '15':  '49',
        },
        'mujer': {
            '5':   '34',   '5M':  '35',
            '6':   '35.5', '6M':  '36',
            '7':   '36.5', '7M':  '37',
            '8':   '38',   '8M':  '39',
            '9':   '39.5', '9M':  '40',
            '10':  '40.5', '10M': '41.5',
            '11':  '42',
        },
        'ninos': {
            '11':  '27.5', '12':  '29',
            '13':  '30',   '1':   '31.5',
            '1.5': '32',   '2':   '32.5',
            '2.5': '33',   '3':   '34',
            '3.5': '34.5',
        },
    },

    'salomon': {
        'hombre': {  # UK → ARG
            '3':   '35.5',
            '4':   '36',   '4M':  '36.5',
            '5':   '37',   '5M':  '37.5',
            '6':   '38',   '6M':  '39',
            '7':   '39.5', '7M':  '40',
            '8':   '41',   '8M':  '41.5',
            '9':   '42',   '9M':  '42.5',
            '10':  '43',   '10M': '44',
            '11':  '44.5', '11M': '45',
            '12':  '45.5', '12M': '46',
            '13':  '46.5', '13M': '47',
            '14':  '47.5', '14M': '48',
            '15':  '48.5',
        },
    },

    'montagne': {
        'hombre': {  # US → ARG
            '8':   '40',   '8M':  '41',
            '9':   '41.5', '9M':  '42',
            '10':  '43',   '10M': '43.5',
            '11':  '44',   '11M': '44.5',
            '12':  '45',   '12M': '46',
        },
        'mujer': {
            '6':   '36',   '6M':  '36',
            '7':   '37',   '7M':  '37.5',
            '8':   '38',   '8M':  '39',
            '9':   '39.5', '9M':  '40',
        },
    },

    'vans': {
        'hombre': {  # US → ARG
            '4':   '35',   '4.5': '36',
            '5':   '36.5', '5M':  '37',
            '6':   '38',   '6M':  '38.5',
            '7':   '39',   '7M':  '40',
            '8':   '40.5', '8M':  '41',
            '9':   '42',   '9M':  '42.5',
            '10':  '43',   '10M': '44',
            '11':  '44.5',
            '12':  '46',
            '13':  '47',
        },
        'mujer': {
            '5':   '34.5', '5M':  '35',
            '6':   '36',   '6M':  '36.5',
            '7':   '37',   '7M':  '38',
            '8':   '38.5', '8M':  '39',
            '9':   '40',
        },
        'unisex': {  # fallback
            '4':   '35',   '4.5': '36',
            '5':   '36.5', '5M':  '37',
            '6':   '38',   '6M':  '38.5',
            '7':   '39',   '7M':  '40',
            '8':   '40.5', '8M':  '41',
            '9':   '42',   '9M':  '42.5',
            '10':  '43',   '10M': '44',
            '11':  '44.5', '12':  '46', '13': '47',
        },
    },

    'dc': {
        'hombre': {  # US → ARG
            '4':   '34',
            '5':   '35.5',
            '6':   '37.5',
            '7':   '39',
            '8':   '40',
            '9':   '41.5',
            '10':  '43',
            '11':  '44.5',
            '12':  '46',
        },
        'mujer': {
            '5':   '34',   '5M':  '35',
            '6':   '35.5', '6M':  '36',
            '7':   '37',   '7M':  '38',
            '8':   '38.5', '8M':  '39',
            '9':   '40',   '9M':  '41',
            '10':  '41.5',
        },
    },

    'crocs': {
        'hombre': {
            'M7': '39', 'M8': '40', 'M9': '41',
            'M10': '42', 'M11': '43', 'M12': '44', 'M13': '45',
        },
        'mujer': {
            'W4': '34', 'M3/W5': '35', 'M4/W6': '36',
            'M5/W7': '37', 'M6/W8': '38', 'M7/W9': '39',
            'M8/W10': '40', 'M9/W11': '41', 'M10/W12': '42',
        },
        'ninos': {
            'C2': '19', 'C3': '20', 'C4': '21', 'C5': '22',
            'C6': '23', 'C7': '24', 'C8': '25', 'C9': '26',
            'C10': '27', 'C11': '28', 'C12': '29', 'C13': '30',
            'J1': '31', 'J2': '32', 'J3': '33',
        },
    },

    'topper': {
        'hombre': {  # ARG directo
            '35': '35', '36': '36', '37': '37', '38': '38',
            '39': '39', '40': '40', '41': '41', '42': '42',
            '43': '43', '44': '44', '45': '45', '46': '46', '47': '47',
        },
        'mujer': {  # ARG directo
            '35': '35', '36': '36', '37': '37', '38': '38',
            '39': '39', '40': '40', '41': '41', '42': '42',
            '43': '43', '44': '44', '45': '45', '46': '46', '47': '47',
        },
        'ninos': {
            '19': '19', '20': '20', '21': '21', '22': '22',
            '23': '23', '24': '24', '25': '25', '26': '26',
            '27': '27', '28': '28', '29': '29', '30': '30',
            '31': '31', '32': '32', '33': '33', '34': '34',
        },
    },

    'umbro': {
        'adulto': {
            '37': '37', '38': '38', '39': '39', '40': '40',
            '41': '41', '42': '42', '43': '43', '44': '44',
            '45': '45', '46': '46',
        },
        'ninos': {
            '25': '25', '26': '26', '27': '27', '28': '28',
            '29': '29', '30': '30', '31': '31', '32': '32',
            '33': '33', '34': '34', '35': '35', '36': '36', '37': '37',
        },
    },

    'on': {
    'hombre': {  # UK → ARG
        '6':   '39',   '6.5': '39.5',
        '8':   '40.5', '8.5': '41',
        '9':   '42',   '9.5': '42',
        '10':   '43',   '10.5': '43.5',
        '11':  '44',   '11.5': '45',
        '12':  '46',
    },
    'mujer': {  # UK → ARG
        '5':   '35',   '5.5': '35.5',
        '6':   '36',   '6.5': '36.5',
        '7':   '37',   '7.5': '37.5',
        '8':   '38',   '8.5': '39',
        '9':   '39.5', '9.5': '40',

    },
    },

    'footy': {
    'ninos': {
        '22': '22', '23': '23', '24': '24', '25': '25',
        '26': '26', '27': '27', '28': '28', '29': '29',
        '30': '30', '31': '31', '32': '32', '33': '33',
        '34': '34', '35': '35', '36': '36', '37': '37',
        '38': '38',
        },
    },

    'converse': {
    'hombre': {
        '33': '33',
        '34': '34', '35': '35', '36': '36', '37': '37',
        '38': '38', '39': '39', '40': '40', '41': '41',
        '42': '42', '43': '43', '44': '44'
        },
    },

    'atomik': {
      'hombre': {
          '40': '40', '41': '41', '42': '42', '43': '43',
          '44': '44', '45': '45',
          },
      'mujer': {
          '35': '35', '36': '36', '37': '37', '38': '38', '39': '39',
          '40': '40'},
      'unisex': {
          '35': '35', '36': '36', '37': '37', '38': '38', '39': '39',
          '40': '40',},
      'ninos': {
           '24': '24', '25': '25', '26': '26','27': '27',
          '28': '28', '29': '29', '30': '30', '31': '31',
          '32': '32', '33': '33', '34': '34', '35': '35',
          '36': '36', '37': '37', '38': '38',

          },
    },
    'asics ': {
    'hombre': {
        '38': '38', '39': '39', '40': '40', '41': '41',
        '42': '42', '43': '43', '44': '44'
        },
    'mujer': {
        '35': '35', '36': '36', '37': '37', '38': '38', '39': '39',
        '40': '40',
        }
    },
    'head': {
    'hombre': {
        '38': '38', '39': '39', '40': '40', '41': '41',
        '42': '42', '43': '43', '44': '44', '45': '45'
        },
    'mujer': {
        '34':'34', '35': '35', '36': '36', '37': '37', '38': '38', '39': '39',
        '40': '40',
        }
    },

    'addnice': {
        'hombre': {
            '38': '38', '39': '39', '40': '40', '41': '41',
            '42': '42', '43': '43', '44': '44', '45': '45'
            },
        'mujer': {
            '34':'34', '35': '35', '36': '36', '37': '37',
            '38': '38', '39': '39','40': '40',
            },
        'ninos': {
            '24': '24', '25': '25', '26': '26',
            '27': '27', '28': '28', '29': '29',
            '30': '30', '31': '31', '32': '32',
            '33': '33', '34': '34',
            }
    },

}

# Ropa genérica (para marcas sin tabla específica de ropa)
TALLES_ROPA_ADULTO = ['XXS','XS','S','M','L','XL','2XL','3XL']
TALLES_ROPA_NINOS  = ['2','4','6','8','10','12','14','16']


DIMENSIONES = {
    'zapatillas_adulto': {'peso': 800, 'ancho': 15, 'alto': 15, 'largo': 30},
    'zapatillas_ninos':  {'peso': 500, 'ancho': 10, 'alto': 10, 'largo': 25},
    'indumentaria':      {'peso': 300, 'ancho': 10, 'alto': 5,  'largo': 20},
    'accesorios':        {'peso': 250, 'ancho': 10, 'alto': 5,  'largo': 15},
    'medias':            {'peso': 200, 'ancho': 5,  'alto': 5,  'largo': 10},
}



def convertir_talle_a_arg(talle_uk, marca, categoria_key):
    """
    Convierte talle UK/US → ARG.
    talle_uk debe ser string (ej: '7', '7M', 'M8', 'C4')
    """
    marca_lower = marca.lower()
    tabla_marca = TALLES.get(marca_lower)
    if not tabla_marca:
        return str(talle_uk)

    if 'ninosJr' in categoria_key:
        genero = 'ninosJr'
    elif 'ninos' in categoria_key:
        genero = 'ninos'
    elif 'mujer' in categoria_key:
        genero = 'mujer'
    elif 'hombre' in categoria_key:
        genero = 'hombre'
    else:
        genero = 'adulto'

    tabla = (tabla_marca.get(genero)
             or tabla_marca.get('adulto')
             or tabla_marca.get('unisex'))

    if not tabla:
        return str(talle_uk)

    return str(tabla.get(str(talle_uk), talle_uk))




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

    categorias_str = '\n'.join(f'  - {c}' for c in CATEGORIAS.keys())

    prompt = f"""Sos un experto en categorización de productos deportivos.
Analizá esta imagen de un producto de la marca {marca} con código {codigo_sku}.

Categorías disponibles (elegí la más exacta):
{categorias_str}

Identificá el modelo exacto mirando la imagen y el código del producto.
Prestá atención al género del producto (hombre/mujer/ninos).
Devolvé SOLO UN JSON DE ESTA FORMA (sin texto extra, sin markdown):
{{
        "CODIGO_SKU":      "{codigo_sku}",
        "MODELO":          "[modelo exacto con tipo, marca y género]",
        "COLOR":           "[colores principales separados por /]",
        "CATEGORIA":       "[categoría exacta de la lista]",
        "MARCA":           "{marca}",
        "PRECIO":          0,
        "PRECIO_TACHADO":  null,
        "WAREHOUSE_ID":    "1_1",
        "STOCK_POR_TALLE": null,
        "TALLES_MANUALES": null
}}"""

    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY, base_url="https://openrouter.ai/api/v1")
    response = client.chat.completions.create(
        model="google/gemini-3.1-flash-lite",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": url_imagen}}
                ]
            }
        ],
        max_tokens=800
    )
    texto = response.choices[0].message.content.strip()
    log.info(f'  📝 Respuesta cruda IA (primeros 300): {texto[:300]}')

    if '```' in texto:
        texto = texto.split('```')[1]
        if texto.startswith('json'):
            texto = texto[4:]
    else:
        match = re.search(r'\{.*\}', texto, re.DOTALL)
        if match:
            texto = match.group()

    texto = texto.strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError as e:
        log.error(f'  ❌ JSON inválido — {e}')
        log.error(f'  📄 Texto que se intentó parsear: {texto[:500]}')
        raise

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

    sem = asyncio.Semaphore(3)
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(headers=headers_async, timeout=timeout) as session:
        # Crear SKUs
        async def crear_sku(talle):
            async with sem:
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
                        log.info(f'  ✅ SKU {talle["uk"]} creado (ID {data["Id"]})')
                        return data['Id']
                    texto = await r.text()
                    log.error(f'  ❌ Error creando SKU {talle["uk"]}: {r.status} — {texto[:200]}')
                    return None

        sku_ids_raw = await asyncio.gather(*[crear_sku(t) for t in talles])
        skus_ok = [(talles[i], sid) for i, sid in enumerate(sku_ids_raw) if sid]
        log.info(f'  ✅ {len(skus_ok)}/{len(talles)} SKUs creados')

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
    resultado = drive_service.files().list(
    pageSize=10,
    fields="files(id,name)"
    ).execute()

    print("ARCHIVOS VISIBLES:")
    for f in resultado.get("files", []):
        print(f["name"])

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
            log.info('🤖 Analizando con OpenAI...')
            datos = analizar_producto_con_gemini(codigo_sku, url_principal, marca)
            log.info(f"JSON IA: {datos}")
            datos = {
                k.lower(): v
                    for k, v in datos.items()
            }

            categoria = datos['categoria']
            if categoria not in CATEGORIAS:
                log.warning(f'Categoría inválida: {categoria} — saltando')
                continue

            log.info(f'   Modelo: {datos["modelo"]}')
            log.info(f'   Color:  {datos["color"]}')
            log.info(f'   Cat:    {categoria}')

            # Generar contenido con GPT-4o
            from openai import OpenAI
            client_oai = OpenAI(api_key=OPENAI_API_KEY, base_url="https://openrouter.ai/api/v1")
            genero = ('Mujer' if 'mujer' in categoria else
                      'Niños' if 'ninos' in categoria else
                      'Unisex' if 'unisex' in categoria else 'Hombre')

            prompt_gpt = (
                f"Sos redactor e-commerce argentino para Showsport.\n"
                f"Datos del producto:\n"
                f"  - Modelo completo (extraído por IA de la imagen): {datos['modelo']}\n"
                f"  - Marca: {marca.title()}\n"
                f"  - Color: {datos['color']}\n"
                f"  - Género: {genero}\n"
                f"  - Código: {codigo_sku}\n\n"
                f"Instrucciones para el título:\n"
                f"- El modelo completo puede incluir tipo de artículo, marca y género.\n"
                f"- El título final debe tener este orden: Tipo de artículo + Marca + Modelo (sin marca ni género repetidos) + Color + Género.\n"
                f"- NO repetir palabras. Asegurate de que marca y género aparezcan UNA SOLA VEZ.\n"
                f"- Ejemplo correcto: 'Campera Puma Running Hooded Woven Jacket Vino/Rosa Mujer'\n"
                f"- Ejemplo INCORRECTO: 'Puma Campera Puma Running Hooded Woven Jacket Mujer Vino/Rosa Mujer'\n\n"
                f"Generá este JSON sin texto extra:\n"
                f'{{"titulo":"[título limpio sin repeticiones]","descripcion":"[4 párrafos describiendo el producto]","palabras_clave":"[keywords separadas por coma]","url_slug":"[slug]-{codigo_sku}"}}'
            )
            resp = client_oai.chat.completions.create(
                model='qwen/qwen3-32b',
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
    marca_lower = marca.lower()
    talles_marca = TALLES.get(marca_lower, {})

    if 'ninos' in categoria_key:
        genero = 'ninos'
    elif 'ninosJr' in categoria_key:
        genero = 'ninosJr'
    elif 'mujer' in categoria_key:
        genero = 'mujer'
    elif 'hombre' in categoria_key:
        genero = 'hombre'
    else:
        genero = 'adulto'

    tipo = 'ropa'
    if any(x in categoria_key for x in ['zapatillas', 'botines', 'crocs', 'ojotas']):
        tipo = 'zapatillas'
    elif any(x in categoria_key for x in ['bolsos', 'mochilas', 'gorras', 'accesorios',
                                           'pelotas', 'canilleras', 'guantes', 'medias',
                                           'riñonera', 'morral']):
        tipo = 'unico'   # ← accesorios siempre talle único

    if tipo == 'unico':
      talle_unico = talles_marca.get('talle_unico', 'unico')
      return [{'uk': talle_unico, 'arg': talle_unico}]   # ← devuelve solo talle único

    elif tipo == 'zapatillas':
        for key in [genero, 'adulto', 'unisex']:
            if key in talles_marca and talles_marca[key]:
                talles_uk = list(talles_marca[key].keys())
                break
        else:
            talles_uk = ['8', '8M', '9', '9M', '10', '10M', '11']

        resultado = []
        for t in talles_uk:
            arg = convertir_talle_a_arg(str(t), marca, categoria_key)
            resultado.append({'uk': str(t), 'arg': arg})
        return resultado

    else:
        # ROPA — buscar clave específica de ropa, no de zapatillas
        ropa_keys = [f'ropa_{genero}', 'ropa_adulto', f'ropa_ninos']
        for key in ropa_keys:
            if key in talles_marca and talles_marca[key]:
                t = talles_marca[key]
                if isinstance(t, list):
                    return [{'uk': str(x), 'arg': str(x)} for x in t]

        # Fallback genérico — nunca usar talles de zapatillas para ropa
        if 'ninos' in categoria_key:
            return [{'uk': t, 'arg': t} for t in TALLES_ROPA_NINOS]
        return [{'uk': t, 'arg': t} for t in TALLES_ROPA_ADULTO]

def get_dimensiones(categoria_key):
    if 'ninos' in categoria_key and any(x in categoria_key for x in ['zapatillas', 'botines']):
        return DIMENSIONES['zapatillas_ninos']
    elif any(x in categoria_key for x in ['zapatillas', 'botines', 'crocs']):
        return DIMENSIONES['zapatillas_adulto']
    elif 'medias' in categoria_key:
        return DIMENSIONES['medias']
    elif any(x in categoria_key for x in ['remeras', 'shorts', 'buzos', 'camperas',
                                            'calzas', 'pantalones', 'tops', 'mallas']):
        return DIMENSIONES['indumentaria']
    else:
        return DIMENSIONES['accesorios']


print("✅ Tabla de conversión de talles cargada")
print()
print("Test Nike Hombre  US 7  → ARG:", convertir_talle_a_arg('7',  'nike',  'hombre_zapatillas'))
print("Test Nike Hombre  US 7M → ARG:", convertir_talle_a_arg('7M', 'nike',  'hombre_zapatillas'))
print("Test Nike Mujer   US 7  → ARG:", convertir_talle_a_arg('7',  'nike',  'mujer_zapatillas'))
print("Test Puma Hombre  UK 9  → ARG:", convertir_talle_a_arg('9',  'puma',  'hombre_zapatillas'))
print("Test Adidas H     UK 8  → ARG:", convertir_talle_a_arg('8',  'adidas','hombre_zapatillas'))
print("Test Salomon H    UK 9  → ARG:", convertir_talle_a_arg('9',  'salomon','hombre_zapatillas'))
print("Test Vans Unisex  US 8  → ARG:", convertir_talle_a_arg('8',  'vans',  'hombre_zapatillas'))
print("Test Crocs Hombre M9    → ARG:", convertir_talle_a_arg('M9', 'crocs', 'hombre_zapatillas'))
print("Test addnice Hombre M9    → ARG:", convertir_talle_a_arg('24', 'addnice', 'ninos_zapatillas'))


if __name__ == '__main__':
    asyncio.run(main())