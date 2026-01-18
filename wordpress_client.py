import requests
from requests.auth import HTTPBasicAuth
from urllib.parse import urlparse

def normalize_url(url):
    """Upewnia się, że URL ma protokół i jest czystą domeną."""
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url.rstrip('/')

def publish_post_draft(domain, api_user, api_key, title, content):
    """
    Publikuje post przez WordPress REST API.
    
    Args:
        domain (str): Adres strony (np. https://mojablog.pl)
        api_user (str): Nazwa użytkownika (login) powiązana z kluczem
        api_key (str): Wygenerowane Hasło Aplikacji (API Token)
        title (str): Tytuł artykułu
        content (str): Treść HTML
    """
    base_url = normalize_url(domain)
    # Endpoint API WordPressa
    api_endpoint = f"{base_url}/wp-json/wp/v2/posts"
    
    # Payload dla API
    post_data = {
        'title': title,
        'content': content,
        'status': 'draft'  # Publikujemy jako szkic
    }
    
    try:
        # Wysyłamy żądanie do API używając Basic Auth (Standard WP API)
        response = requests.post(
            api_endpoint,
            auth=HTTPBasicAuth(api_user, api_key),
            json=post_data,
            timeout=30
        )
        
        if response.status_code == 201:
            data = response.json()
            return {
                "success": True,
                "link": data.get('link'),
                "id": data.get('id'),
                "message": "Opublikowano pomyślnie"
            }
        elif response.status_code == 401:
            return {"success": False, "message": "Błąd 401: Nieautoryzowany dostęp. Sprawdź nazwę użytkownika i Hasło Aplikacji (Klucz API)."}
        elif response.status_code == 403:
            return {"success": False, "message": "Błąd 403: Brak uprawnień. Użytkownik musi mieć rolę Autora lub Administratora."}
        else:
            return {"success": False, "message": f"Błąd API ({response.status_code}): {response.text[:200]}"}
            
    except Exception as e:
        return {"success": False, "message": f"Błąd połączenia: {str(e)}"}
