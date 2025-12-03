from fastapi import FastAPI
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import re

app = FastAPI()import os
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
    resp = requests.get(url_anuncio, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    texto_global = soup.get_text(separator=" ", strip=True)
    texto_lower = texto_global.lower()

    # ----- TÍTULO -----
    titulo_el = soup.find("h1") or soup.find("h2")
    titulo = titulo_el.get_text(strip=True) if titulo_el else "Propiedad UrbanRise"

    # ----- PRECIO -----
    precio = "No especificado"
    posibles_precios = soup.find_all(
        string=lambda t: t and any(moeda in t for moeda in ["USD", "US$", "U$S", "UYU", "$"])
    )
    if posibles_precios:
        candidatos = [p.strip() for p in posibles_precios if p.strip()]
        candidatos = sorted(candidatos, key=len)
        precio = candidatos[0]

    # ----- UBICACIÓN -----
    ubicacion = "No especificada"
    migas = soup.select("nav.breadcrumb, ol.breadcrumb, .breadcrumb")
    if migas:
        ubicacion = " / ".join(migas[0].get_text(separator=" ", strip=True).split())

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
    desc_el = soup.select_one("div[class*=description], div[class*=descripcion], .property-description")
    if desc_el:
        descripcion = " ".join(desc_el.get_text(" ", strip=True).split())
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

    # ----- DORMITORIOS / BAÑOS / ESTADO -----
    dormitorios_amb = "No especificado"
    m_dorm = re.search(r"(\d+)\s+dormitorio[s]?", texto_lower)
    if m_dorm:
        dormitorios_amb = f"{m_dorm.group(1)} dormitorios"
    elif "monoambiente" in texto_lower:
        dormitorios_amb = "Monoambiente"

    banios = "No especificado"
    m_banio = re.search(r"(\d+(?:[.,]\d+)?)\s*bañ[o|os]", texto_lower)
    if m_banio:
        cant = m_banio.group(1).replace(",", ".")
        banios = f"{cant} baños"

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

    for img in soup.select("div.row.gx-1.gy-1 img"):
        src = img.get("src")
        if not src:
            continue
        src_abs = urljoin(url_anuncio, src)
        low = src_abs.lower()
        if any(x in low for x in ["logo", "icon", "avatar", "placeholder"]):
            continue
        if src_abs not in imagenes:
            imagenes.append(src_abs)

    if not imagenes:
        for img in soup.find_all("img"):
            src = img.get("src")
            if not src:
                continue
            src_abs = urljoin(url_anuncio, src)
            low = src_abs.lower()
            if any(x in low for x in ["logo", "icon", "avatar", "placeholder"]):
                continue
            if "propiedades" not in low and "/uploads/" not in low:
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
    Scraper genérico para portales desconocidos.
    Intenta sacar título, precio, descripción, ubicación, dormitorios, baños, superficie,
    estado, cochera e imágenes usando heurísticas.
    """
    resp = requests.get(url_anuncio, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    texto_global = soup.get_text(separator=" ", strip=True)
    texto_lower = texto_global.lower()

    # ----- TÍTULO -----
    titulo = "Propiedad UrbanRise"
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        titulo = og_title["content"].strip()
    else:
        h1 = soup.find("h1")
        if h1:
            titulo = h1.get_text(strip=True)
        elif soup.title and soup.title.get_text(strip=True):
            titulo = soup.title.get_text(strip=True)

    # ----- PRECIO -----
    precio = "No especificado"
    posibles_precios = soup.find_all(
        string=lambda t: t and any(moeda in t for moeda in ["USD", "US$", "U$S", "UYU", "$"])
    )
    if posibles_precios:
        candidatos = [p.strip() for p in posibles_precios if p.strip()]
        candidatos = sorted(candidatos, key=len)
        precio = candidatos[0]

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

    # ----- UBICACIÓN -----
    ubicacion = "No especificada"
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        texto_og = og_desc["content"]
        m = re.search(r"en (.+?,\s*[^.,]+)", texto_og)
        if m:
            ubicacion = m.group(1).strip()

    if ubicacion == "No especificada":
        migas = soup.select("nav.breadcrumb, ol.breadcrumb, .breadcrumb")
        if migas:
            ubicacion = " / ".join(
                migas[0].get_text(separator=" ", strip=True).split()
            )

    # ----- SUPERFICIE -----
    superficie = "No especificado"
    m_sup = re.search(r"(\d{2,4})\s*(m²|m2|m\.2)", texto_lower)
    if m_sup:
        superficie = f"{m_sup.group(1)} m² (aprox.)"

    # ----- DORMITORIOS / AMBIENTES -----
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

    # ----- DESCRIPCIÓN -----
    descripcion = "Descripción no disponible."
    parrafos = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    parrafos_largos = [p for p in parrafos if len(p) > 120]
    if parrafos_largos:
        descripcion = "\n\n".join(parrafos_largos[:3])
    else:
        desc_el = soup.select_one("div[class*=description], div[class*=descripcion]")
        if desc_el:
            descripcion = " ".join(desc_el.get_text(" ", strip=True).split())

    # ----- IMÁGENES -----
    imagenes: list[str] = []
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("data-lazy") or img.get("src")
        if not src:
            continue
        src_abs = urljoin(url_anuncio, src)
        low = src_abs.lower()

        if any(x in low for x in ["logo", "icon", "avatar", "placeholder", "sprite"]):
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
        "EXPENSAS": expensas,
        "DESTACADOS": "No especificado",
        "ANIO_CONSTRUCCION": "No especificado",
        "PISOS": "No especificado",
        "ORIENTACION": orientacion,
        "MASCOTAS": mascotas,
        "MOBILIARIO": "No especificado",
        "DESCRIPCION": descripcion,
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


class FichaRequest(BaseModel):
    url: str
    slug: str

# ----------------------------------------------------------
# Funciones utilitarias
# ----------------------------------------------------------

def limpiar_texto(t):
    if not t:
        return "No especificado"
    t = t.replace("\n", " ").replace("\t", " ").strip()
    t = re.sub(r"\s+", " ", t)
    return t

def normalizar_valor(v):
    if not v or "preg" in v.lower():
        return "No especificado"
    return limpiar_texto(v)

# ----------------------------------------------------------
# EXTRAER COCHERA / GARAGE DE MANERA INTELIGENTE
# ----------------------------------------------------------

def extraer_cochera(soup):
    """
    Detecta variantes:
    garage, garajes, cochera, estacionamiento, parking, parqueo, etc.
    """
    patrones = [
        r"cochera",
        r"garage",
        r"garajes",
        r"estacionamiento",
        r"parking",
        r"parqueo",
        r"espacio.*auto",
        r"autos?",
    ]

    texto_total = soup.get_text(separator=" ").lower()

    # 1) Buscar frases como "1 garage", "2 cocheras", etc.
    for p in patrones:
        match = re.search(rf"(\d+)\s+{p}", texto_total)
        if match:
            return match.group(1)

    # 2) Buscar campos en tablas o listas de características
    labels = soup.find_all(["li", "div", "span", "p", "td", "th"])

    for lbl in labels:
        t = lbl.get_text(" ", strip=True).lower()
        for p in patrones:
            if p in t:
                # Caso "Garage: No", "Garajes: 2", etc
                if ":" in t:
                    valor = t.split(":", 1)[1].strip()
                    return normalizar_valor(valor)
                # Caso de solo la palabra → es cochera pero sin detalle
                return "Sí"

    # 3) Si no aparece ninguna referencia
    return "No especificado"


# ----------------------------------------------------------
# SCRAPPER GENÉRICO
# ----------------------------------------------------------

def scrappear(url):
    r = requests.get(url, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")

    # Extraer cochera
    cochera = extraer_cochera(soup)

    # ------------------------------------------------------
    # Aquí puedes agregar más extractores genéricos:
    # dormitorios, baños, superficie, etc.
    # ------------------------------------------------------

    data = {
        "titulo": "No especificado",
        "cochera": cochera,
        "imagenes": [],
    }

    # Título genérico
    title = soup.find("h1")
    if title:
        data["titulo"] = limpiar_texto(title.text)

    # Imágenes genéricas
    for img in soup.find_all("img"):
        src = img.get("src")
        if src and src.startswith("http"):
            data["imagenes"].append(src)

    return data


# ----------------------------------------------------------
# ENDPOINT PRINCIPAL
# ----------------------------------------------------------

@app.post("/crear-ficha")
def crear_ficha(req: FichaRequest):
    datos = scrappear(req.url)
    return {
        "ok": True,
        "slug": req.slug,
        "datos": datos
    }

