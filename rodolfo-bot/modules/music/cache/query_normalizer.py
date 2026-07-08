import re
import unicodedata

def normalize_text(text: str) -> str:
    """
    Normaliza el texto: minúsculas, remueve acentos, limpia caracteres especiales y espacios.
    """
    if not text:
        return ""
    # Lowercase
    text = text.lower()
    # Remover acentos
    text = "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )
    return text.strip()

def normalize_query(query: str) -> str:
    """
    Normaliza la query del usuario limpiando prefijos (activadores, verbos de reproducción)
    y sufijos (fórmulas de cortesía).
    
    Ejemplos:
      "Oye Rodolfo pon flaca porfa" -> "flaca"
      "ponme despacito" -> "despacito"
    """
    query = normalize_text(query)
    
    # Remover activador y verbos iniciales
    # "oye rodolfo ponme ", "rodolfo pon ", "ponme ", "pon ", "poner "
    query = re.sub(
        r"^(?:(?:oye\s+)?rodolfo\s+)?(?:ponme\s+|pon\s+|poner\s+|reproduce\s+|busca\s+|quiero\s+escuchar\s+)?",
        "",
        query
    )
    
    # Remover artículos al inicio si son seguidos de más texto (ej: "la flaca" -> "flaca")
    query = re.sub(
        r"^(?:la|el|un|una|los|las)\s+(?=\S)",
        "",
        query
    )
    
    # Remover sufijos comunes de cortesía/cola
    query = re.sub(
        r"\s+(?:por\s+favor|porfa|porfis|a\s+la\s+cola)$",
        "",
        query
    )
    
    # Colapsar espacios múltiples
    query = re.sub(r"\s+", " ", query)
    
    return query.strip()
