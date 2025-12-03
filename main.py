def scrapear_propiedad_generico(url_anuncio: str) -> dict:
    """
    Scraper genérico para portales desconocidos.
    Intenta sacar título, precio, descripción e imágenes usando heurísticas.
    No va a ser perfecto, pero sirve para la mayoría.
    """
    resp = requests.get(url_anuncio, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # ----- TÍTULO -----
    titulo = "Propiedad UrbanRise"

    # 1) og:title
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        titulo = og_title["content"].strip()
    else:
        # 2) primer <h1>
        h1 = soup.find("h1")
        if h1:
            titulo = h1.get_text(strip=True)
        else:
            # 3) <title> del documento
            if soup.title and soup.title.get_text(strip=True):
                titulo = soup.title.get_text(strip=True)

    # ----- PRECIO -----
    precio = "No especificado"
    posibles_precios = soup.find_all(
        string=lambda t: t and any(moeda in t for moeda in ["USD", "US$", "U$S", "UYU", "$"])
    )
    if posibles_precios:
        # nos quedamos con el más corto que parezca precio
        posibles_precios_ordenados = sorted(
            (p.strip() for p in posibles_precios if p.strip()),
            key=len
        )
        precio = posibles_precios_ordenados[0]

    # ----- OPERACIÓN (Alquiler / Venta) -----
    operacion = "No especificado"
    texto_global = soup.get_text(separator=" ", strip=True).lower()
    if "alquiler" in texto_global:
        operacion = "Alquiler"
    elif "venta" in texto_global or "se vende" in texto_global:
        operacion = "Venta"

    # ----- TIPO (Casa / Apartamento / etc.) -----
    tipo = "No especificado"
    if "apartamento" in texto_global or "apart." in texto_global:
        tipo = "Apartamento"
    elif "casa" in texto_global:
        tipo = "Casa"
    elif "local" in texto_global:
        tipo = "Local comercial"
    elif "oficina" in texto_global:
        tipo = "Oficina"

    # ----- DESCRIPCIÓN -----
    descripcion = "Descripción no disponible."
    # Buscamos un bloque de texto largo en <p> o <div>
    parrafos = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    parrafos_largos = [p for p in parrafos if len(p) > 120]
    if parrafos_largos:
        descripcion = "\n\n".join(parrafos_largos[:3])
    else:
        # fallback en algún <div> con "descripcion" en la clase
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

        # filtrar cosas que casi seguro NO son fotos de propiedad
        low = src_abs.lower()
        if any(x in low for x in ["logo", "icon", "avatar", "placeholder", "sprite"]):
            continue
        # pequeños pixeles de tracking típicos (facebook, analytics, etc.)
        if "facebook.com/tr" in low or "doubleclick" in low:
            continue

        if src_abs not in imagenes:
            imagenes.append(src_abs)

    imagenes = imagenes[:12]

    datos = {
        "OPERACION": operacion,
        "TIPO": tipo,
        "TITULO": titulo,
        "UBICACION": "No especificada",
        "PRECIO": precio,
        "SUPERFICIE": superficie,
        "DORMITORIOS_AMBIENTES": dormitorios_amb,
        "BANIOS": "No especificado",
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
