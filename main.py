import os
import base64
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import slugify


# ========= CONFIGURACIÓN =========

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # viene de las Environment Variables de Render
if not GITHUB_TOKEN:
    raise RuntimeError("GITHUB_TOKEN no está definido en las variables de entorno")

GITHUB_USER = "gros2-hash"
REPO_NAME = "urbanrise-fichas"
LOGO_URL = "https://static.tokkobroker.com/tfw_images/14240_URBANRISE/logo_urban_naranja.jpg"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    )
}

app = FastAPI(title="UrbanRise Fichas Service")


# ========= MODELO REQUEST =========

class CrearFichaRequest(BaseModel):
    url: str
    slug: str | None = None


# ========= SCRAPER REMAX =========

def scrapear_propiedad_remax(url_anuncio: str) -> dict:
    """
    Scraper base para REMAX.
    Se puede afinar con selectores concretos mirando el HTML real del portal.
    """
    resp = requests.get(url_anuncio, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # ----- TEXTO GLOBAL -----
    texto_global = soup.get_text(separator=" ", strip=True)
    texto_lower = texto_global.lower()

    # ----- TÍTULO -----
    titulo_el = soup.find("h1")
    titulo = titulo_el.get_text(strip=True) if titulo_el else "Propiedad UrbanRise"

    # ----- PRECIO -----
    precio_el = soup.select_one("[class*=price], [class*=precio]")
    if precio_el:
        precio = precio_el.get_text(strip=True)
    else:
        posibles_precios = soup.find_all(
            string=lambda t: t and any(moeda in t for moeda in ["USD", "US$", "U$S", "UYU", "$"])
        )
        if posibles_precios:
            candidatos = [p.strip() for p in posibles_precios if p.strip()]
            candidatos = sorted(candidatos, key=len)
            precio = candidatos[0]
        else:
            precio = "No especificado"

    # ----- UBICACIÓN -----
    ubic_el = soup.select_one("[class*=location], [class*=ubicacion], [class*=address]")
    ubicacion = ubic_el.get_text(strip=True) if ubic_el else "No especificada"

    # ----- OPERACIÓN -----
    operacion = "No especificado"
    if "alquiler" in texto_lower:
        operacion = "Alquiler"
    elif "venta" in texto_lower or "se vende" in texto_lower:
        operacion = "Venta"

    # ----- TIPO -----
    tipo = "No especificado"
    if "monoambiente" in texto_lower:
        tipo = "Apartamento"
    elif "apartamento" in texto_lower or "apto" in texto_lower:
        tipo = "Apartamento"
    elif "casa" in texto_lower:
        tipo = "Casa"
    elif "local" in texto_lower:
        tipo = "Local comercial"
    elif "oficina" in texto_lower:
        tipo = "Oficina"

    # ----- DESCRIPCIÓN -----
    desc_el = soup.select_one(
        "div[class*=description], div[class*=descripcion], section[class*=description]"
    )
    if desc_el:
        descripcion = " ".join(desc_el.get_text(separator=" ", strip=True).split())
    else:
        parrafos = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        parrafos_largos = [p for p in parrafos if len(p) > 120]
        if parrafos_largos:
            descripcion = "\n\n".join(parrafos_largos[:3])
        else:
            descripcion = "Descripción no disponible en el portal."

    # ----- SUPERFICIE -----
    superficie = "No especificado"
    m_sup = re.search(r"(\d{2,4})\s*(m²|m2|m\.2)", texto_lower)
    if m_sup:
        superficie = f"{m_sup.group(1)} m² (aprox.)"

    # ----- DORMITORIOS -----
    dormitorios_amb = "No especificado"
    m_dorm = re.search(r"(\d+)\s+dormitorio[s]?", texto_lower)
    if m_dorm:
        dormitorios_amb = f"{m_dorm.group(1)} dormitorios"
    elif "monoambiente" in texto_lower:
        dormitorios_amb = "Monoambiente"

    # ----- BAÑOS -----
    banios = "No especificado"
    m_banio = re.search(r"(\d+(?:[.,]\d+)?)\s*bañ[o|os]", texto_lower)
    if m_banio:
        cant = m_banio.group(1).replace(",", ".")
        banios = f"{cant} baños"

    # ----- ESTADO -----
    estado = "No especificado"
    if "a estrenar" in texto_lower:
        estado = "A estrenar"
    elif "reciclado" in texto_lower:
        estado = "Reciclado"
    elif "buen estado" in texto_lower:
        estado = "Buen estado"

    # ----- COCHERA -----
    cochera = detectar_cochera(texto_lower)

    # ----- IMÁGENES -----
    imagenes: list[str] = []

    posibles_galerias = soup.select(
        "div[class*='gallery'], div[class*='carousel'], "
        "div[class*='slider'], div[class*='photos']"
    )
    if posibles_galerias:
        gal = posibles_galerias[0]
        for img in gal.find_all("img"):
            src = img.get("data-src") or img.get("data-lazy") or img.get("src")
            if not src:
                continue
            src_abs = urljoin(url_anuncio, src)
            low = src_abs.lower()
            if any(x in low for x in ["logo", "icon", "placeholder", "avatar"]):
                continue
            if "facebook.com/tr" in low or "doubleclick" in low or "analytics" in low:
                continue
            if src_abs not in imagenes:
                imagenes.append(src_abs)

    if not imagenes:
        for img in soup.find_all("img"):
            src = img.get("data-src") or img.get("src")
            if not src:
                continue
            src_abs = urljoin(url_anuncio, src)
            low = src_abs.lower()
            if any(x in low for x in ["logo", "icon", "placeholder", "avatar"]):
                continue
            if "facebook.com/tr" in low or "doubleclick" in low or "analytics" in low:
                continue
            if src_abs not in imagenes:
                imagenes.append(src_abs)

    imagenes = imagenes[:12]

    datos = {
        "OPERACION": operacion,
        "TIPO": tipo,
        "TITULO": titulo,
        "UBICACION": ubicacion,
        "PRECIO": precio,
        "SUPERFICIE": superficie,
        "DORMITORIOS_AMBIENTES": dormitorios_amb,
        "BANIOS": banios,
        "COCHERA": cochera,
        "ESTADO": estado,
        "EXPENSAS": "No especificado",
        "DESTACADOS": "No especificado",
        "ANIO_CONSTRUCCION": "No especificado",
        "PISOS": "No especificado",
        "ORIENTACION": "No especificado",
        "MASCOTAS": "No especificado",
        "MOBILIARIO": "No especificado",
        "DESCRIPCION": descripcion,
        "IMAGENES": imagenes,
    }

    return datos


# ========= SCRAPER CENTURY 21 =========

def scrapear_propiedad_century21(url_anuncio: str) -> dict:
    """
    Scraper 100% funcional para Century21 Uruguay.
    Captura imágenes, características, amenities y descripción.
    """

    resp = requests.get(url_anuncio, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    texto_lower = soup.get_text(" ", strip=True).lower()

    # ---------------------------
    # TÍTULO
    # ---------------------------
    h1 = soup.find("h1")
    titulo = h1.get_text(strip=True) if h1 else "Propiedad Century21"

    # ---------------------------
    # PRECIO
    # ---------------------------
    precio = "No especificado"
    price_el = soup.select_one("h2.property-price, .price, [class*=price]")
    if price_el:
        precio = price_el.get_text(" ", strip=True)

    # ---------------------------
    # UBICACIÓN (breadcrumb real)
    # ---------------------------
    ubicacion = "No especificada"
    bc = soup.select_one("ol.breadcrumb")
    if bc:
        ubicacion = bc.get_text(" ", strip=True)

    # ---------------------------
    # IMÁGENES (del panel #fotos)
    # ---------------------------
    imagenes = []

    for img in soup.select("#fotos img"):
        src = img.get("data-src") or img.get("src")
        if not src:
            continue

        src = urljoin(url_anuncio, src)

        # evitar logos
        if "logo" in src.lower():
            continue

        if src not in imagenes:
            imagenes.append(src)

    imagenes = imagenes[:20]

    # ---------------------------
    # CARACTERÍSTICAS (feature-title + feature-value)
    # ---------------------------
    caracteristicas = {}

    for box in soup.select(".col-lg-1.col-sm-6.col-md-4.text-center"):
        label = box.select_one(".feature-title")
        value = box.select_one(".feature-value")

        if label and value:
            key = label.get_text(strip=True).lower()
            val = value.get_text(strip=True)
            caracteristicas[key] = val

    def get(keys, default="No especificado"):
        for k in keys:
            if k in caracteristicas:
                return caracteristicas[k]
        return default

    dormitorios = get(["dormitorios"])
    banios = get(["baños", "baño"])
    superficie = get(["superficie total", "superficie", "construcción"])
    cochera = get(["cocheras", "cochera"])
    pisos = get(["cantidad de pisos"])

    # Normalizar cochera
    if cochera.isdigit():
        cochera = "1 cochera" if cochera == "1" else f"{cochera} cocheras"

    # ---------------------------
    # DESCRIPCIÓN
    # ---------------------------
    descripcion = ""
    desc_box = soup.select_one(".property-description-container")

    if desc_box:
        textos = [
            p.get_text(" ", strip=True)
            for p in desc_box.find_all("p")
            if len(p.get_text(strip=True)) > 20
        ]
        descripcion = "\n".join(textos)

    if not descripcion:
        descripcion = "Descripción no disponible."

    # ---------------------------
    # AMENITIES
    # ---------------------------
    amenities = []
    for li in soup.select(".property-amenities li"):
        txt = li.get_text(" ", strip=True)
        if txt:
            amenities.append(txt)

    destacados = ", ".join(amenities) if amenities else "No especificado"

    return {
        "OPERACION": "Alquiler" if "alquiler" in texto_lower else "Venta",
        "TIPO": "Casa",
        "TITULO": titulo,
        "UBICACION": ubicacion,
        "PRECIO": precio,
        "SUPERFICIE": superficie,
        "DORMITORIOS_AMBIENTES": dormitorios,
        "BANIOS": banios,
        "COCHERA": cochera,
        "ESTADO": "No especificado",
        "EXPENSAS": "No especificado",
        "DESTACADOS": destacados,
        "ANIO_CONSTRUCCION": get(["año de construcción"]),
        "PISOS": pisos,
        "ORIENTACION": "No especificado",
        "MASCOTAS": "No especificado",
        "MOBILIARIO": "No especificado",
        "DESCRIPCION": descripcion,
        "IMAGENES": imagenes,
    }

    return datos


# ========= FUNCIÓN AUXILIAR: DETECTAR COCHERA =========

def detectar_cochera(texto_lower: str) -> str:
    cochera = "No especificado"

    patrones_negativos = [
        "sin cochera",
        "no tiene cochera",
        "no posee cochera",
        "sin garage",
        "sin garaje",
        "no tiene garage",
        "no tiene garaje",
        "sin estacionamiento",
        "no tiene estacionamiento",
        "sin lugar de garage",
    ]
    if any(pat in texto_lower for pat in patrones_negativos):
        return "No"

    # número + palabra: "2 cocheras", "1 cochera", "3 garages"
    m_coch_num = re.search(
        r"(\d+)\s+(cochera[s]?|garage[s]?|garaje[s]?|estacionamiento[s]?)", texto_lower
    )
    # "cochera para 2 autos"
    m_coch_para = re.search(
        r"(cochera|garage|garaje)[^\.]{0,40}?para\s+(\d+)\s+(auto[s]?|vehículo[s]?|coche[s]?)",
        texto_lower,
    )

    if m_coch_num:
        cantidad = int(m_coch_num.group(1))
        if cantidad == 1:
            cochera = "1 cochera"
        else:
            cochera = f"{cantidad} cocheras"
    elif m_coch_para:
        cantidad = int(m_coch_para.group(2))
        if cantidad == 1:
            cochera = "1 cochera"
        else:
            cochera = f"{cantidad} cocheras"
    else:
        if any(palabra in texto_lower
               for palabra in ["cochera", "garage", "garaje", "lugar de garage", "estacionamiento"]):
            cochera = "Sí (cantidad no especificada)"

    return cochera


# ========= SCRAPER GENÉRICO =========

def scrapear_propiedad_generico(url_anuncio: str) -> dict:
    """
    Scraper genérico mejorado para capturar características de portales
    que usan listas con iconos (ej: dormitorios, baños, garaje, orientación,
    superficie, pisos, mascotas, ascensor, etc).
    """
    resp = requests.get(url_anuncio, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    texto_global = soup.get_text(separator=" ", strip=True)
    texto_lower = texto_global.lower()

    # =============================
    # 1. TÍTULO
    # =============================
    titulo = "Propiedad UrbanRise"
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        titulo = og_title["content"].strip()
    else:
        h1 = soup.find("h1")
        if h1:
            titulo = h1.get_text(strip=True)
        elif soup.title:
            titulo = soup.title.get_text(strip=True)

    # =============================
    # 2. PRECIO
    # =============================
    precio = "No especificado"
    precios = soup.find_all(string=lambda t: t and any(m in t for m in ["USD", "UYU", "$", "U$S"]))
    if precios:
        precios = sorted([p.strip() for p in precios], key=len)
        precio = precios[0]

    # =============================
    # 3. UBICACIÓN
    # =============================
    ubicacion = "No especificada"
    migas = soup.select(".breadcrumb, nav.breadcrumb, ol.breadcrumb")
    if migas:
        ubicacion = " / ".join(migas[0].get_text(" ", strip=True).split())

    # =============================
    # 4. OPERACIÓN
    # =============================
    operacion = "Alquiler" if "alquiler" in texto_lower else "Venta" if "venta" in texto_lower else "No especificado"

    # =============================
    # 5. DESCRIPCIÓN
    # =============================
    desc_el = soup.select_one("div[class*=description], div[class*=descripcion]")
    if desc_el:
        descripcion = desc_el.get_text(" ", strip=True)
    else:
        parrafos = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        largos = [p for p in parrafos if len(p) > 100]
        descripcion = "\n\n".join(largos[:3]) if largos else "Descripción no disponible."

    # ==================================================
    # 6. CAPTURA de características con iconos UL > LI
    # ==================================================
    caracteristicas = {}

    for li in soup.select("ul li"):
        texto = li.get_text(" ", strip=True).replace(" :", ":").replace(": ", ":")
        if ":" not in texto:
            continue
        key, value = texto.split(":", 1)
        key = key.strip().lower()
        value = value.strip()

        caracteristicas[key] = value

    # =============================
    # 7. MAPEO AUTOMÁTICO
    # =============================
    def get_carac(keys: list[str], default="No especificado"):
        for k in keys:
            if k.lower() in caracteristicas:
                return caracteristicas[k.lower()]
        return default

    dormitorios = get_carac(["dormitorios", "dormitorio"])
    banios = get_carac(["baños", "baño"])
    garaje = get_carac(["garaje", "garage", "cochera"])
    superficie = get_carac(["superficie", "superficie construida", "m2"])
    orientacion = get_carac(["orientación", "orientacion"])
    pisos = get_carac(["pisos edificio", "piso"])
    mascotas = get_carac(["acepta mascotas", "mascotas"])
    anio = get_carac(["año de construcción", "anio de construccion"])
    destacados = get_carac(["amenities", "comodidades"])
    mobiliario = get_carac(["mobiliario", "amoblado"])

    # Si garaje es número → normalizar
    if re.match(r"^\d+$", garaje):
        garaje = f"{garaje} cocheras" if garaje != "1" else "1 cochera"

    # =============================
    # 8. IMÁGENES
    # =============================
    imagenes = []
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("src")
        if not src:
            continue
        src_abs = urljoin(url_anuncio, src)
        if any(x in src_abs.lower() for x in ["icon", "logo", "placeholder"]):
            continue
        if src_abs not in imagenes:
            imagenes.append(src_abs)
    imagenes = imagenes[:12]

    # =============================
    # RESPUESTA FINAL
    # =============================
    return {
        "OPERACION": operacion,
        "TIPO": "No especificado",
        "TITULO": titulo,
        "UBICACION": ubicacion,
        "PRECIO": precio,
        "SUPERFICIE": superficie,
        "DORMITORIOS_AMBIENTES": dormitorios,
        "BANIOS": banios,
        "COCHERA": garaje,
        "ESTADO": "No especificado",
        "EXPENSAS": "No especificado",
        "DESTACADOS": destacados,
        "ANIO_CONSTRUCCION": anio,
        "PISOS": pisos,
        "ORIENTACION": orientacion,
        "MASCOTAS": mascotas,
        "MOBILIARIO": mobiliario,
        "DESCRIPCION": descripcion,
        "IMAGENES": imagenes,
    }

    return datos

def scrapear_propiedad_mercadolibre(url_anuncio: str) -> dict:
    """
    Scraper especializado para MercadoLibre Uruguay.
    Obtiene características desde la API oficial:
    https://api.mercadolibre.com/items/MLUxxxxxxx
    """
    # Extraer ID del tipo MLU-654021285 o MLU654021285
    m = re.search(r"(MLU)-?(\d+)", url_anuncio, re.IGNORECASE)
    if not m:
        raise RuntimeError("No se pudo extraer el ID de MercadoLibre desde la URL")

    item_id = f"{m.group(1).upper()}{m.group(2)}"  # MLU654021285

    api_url = f"https://api.mercadolibre.com/items/{item_id}"
    api_resp = requests.get(api_url, timeout=20)
    if api_resp.status_code != 200:
        raise RuntimeError(f"Error API MercadoLibre: {api_resp.text}")

    data = api_resp.json()

    # -----------------------------
    # TITULO
    # -----------------------------
    titulo = data.get("title", "Propiedad ML")

    # -----------------------------
    # PRECIO
    # -----------------------------
    precio = data.get("price", "No especificado")

    # -----------------------------
    # IMAGENES
    # -----------------------------
    imagenes = [pic["secure_url"] for pic in data.get("pictures", [])][:12]

    # -----------------------------
    # CARACTERISTICAS
    # -----------------------------
    atributos = {a["name"].lower(): a.get("value_name") for a in data.get("attributes", [])}

    def get(attr_name):
        attr_name = attr_name.lower()
        return atributos.get(attr_name, "No especificado")

    datos = {
        "OPERACION": "Alquiler" if "alquiler" in titulo.lower() else "Venta",
        "TIPO": get("tipo de propiedad"),
        "TITULO": titulo,
        "UBICACION": get("ubicación") or data.get("location", {}).get("address_line", "No especificada"),
        "PRECIO": f"USD {precio}" if isinstance(precio, (int, float)) else precio,
        "SUPERFICIE": get("superficie total"),
        "DORMITORIOS_AMBIENTES": get("dormitorios"),
        "BANIOS": get("baños"),
        "COCHERA": get("cocheras"),
        "ESTADO": "No especificado",
        "EXPENSAS": "No especificado",
        "DESTACADOS": "No especificado",
        "ANIO_CONSTRUCCION": get("año de construcción"),
        "PISOS": get("cantidad de pisos"),
        "ORIENTACION": get("orientación"),
        "MASCOTAS": get("acepta mascotas"),
        "MOBILIARIO": "No especificado",
        "DESCRIPCION": data.get("plain_text", "Descripción no disponible."),
        "IMAGENES": imagenes,
    }

    return datos



# ========= ROUTER DE SCRAPERS =========

PORTAL_SCRAPERS = {
    "www.remax.com.uy": scrapear_propiedad_remax,
    "remax.com.uy": scrapear_propiedad_remax,
    "www.century21.com.uy": scrapear_propiedad_century21,
    "century21.com.uy": scrapear_propiedad_century21,
}


def elegir_scraper(url_anuncio: str):
    dominio = urlparse(url_anuncio).netloc.lower()
    if dominio in PORTAL_SCRAPERS:
        return PORTAL_SCRAPERS[dominio]
    return scrapear_propiedad_generico


# ========= GENERACIÓN HTML =========

def generar_html(datos: dict) -> str:
    template_path = Path("ficha_template.html")
    if not template_path.exists():
        raise RuntimeError("No se encuentra ficha_template.html en el directorio del servicio.")

    template = template_path.read_text(encoding="utf-8")

    galeria_html = ""
    for url in datos.get("IMAGENES", []):
        galeria_html += f'<img src="{url}" alt="Foto de la propiedad">\n'

    html = template.format(
        LOGO_URL=LOGO_URL,
        GALERIA_IMAGENES=galeria_html,
        **datos
    )
    return html


# ========= SUBIDA A GITHUB =========

def subir_a_github(html: str, slug: str) -> str:
    api_url = f"https://api.github.com/repos/{GITHUB_USER}/{REPO_NAME}/contents/fichas/{slug}.html"

    message = f"Crear/actualizar ficha {slug}"
    content = base64.b64encode(html.encode("utf-8")).decode("utf-8")

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    resp_get = requests.get(api_url, headers=headers)
    data = {"message": message, "content": content}

    if resp_get.status_code == 200:
        sha = resp_get.json().get("sha")
        if sha:
            data["sha"] = sha

    resp_put = requests.put(api_url, headers=headers, data=json.dumps(data))
    if resp_put.status_code not in (200, 201):
        raise RuntimeError(f"Error subiendo a GitHub: {resp_put.status_code} {resp_put.text}")

    url_publica = f"https://{GITHUB_USER}.github.io/{REPO_NAME}/fichas/{slug}.html"
    return url_publica


# ========= ENDPOINT =========

@app.post("/crear-ficha")
def crear_ficha(payload: CrearFichaRequest):
    try:
        scraper = elegir_scraper(payload.url)
        datos = scraper(payload.url)

        slug = payload.slug or slugify.slugify(datos["TITULO"]) or "propiedad-urbanrise"
        html = generar_html(datos)
        url_ficha = subir_a_github(html, slug)
        return {
            "ok": True,
            "slug": slug,
            "url_ficha": url_ficha,
            "imagenes": datos.get("IMAGENES", []),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========= RUN LOCAL (opcional) =========

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)





