import requests
import base64
from urllib.parse import urlparse

def normalize_url(url):
    """Upewnia się, że URL ma protokół i nie ma ukośnika na końcu."""
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url.rstrip('/')

def publish_post_draft(domain, username, app_password, title, content):
    """
    Publikuje post jako szkic (draft) w WordPress.
    
    Args:
        domain (str): Adres strony (np. mojablog.pl)
        username (str): Nazwa użytkownika WP
        app_password (str): Hasło aplikacji (nie hasło do logowania!)
        title (str): Tytuł artykułu
        content (str): Treść HTML
        
    Returns:
        dict: Wynik operacji (success, message, link)
    """
    base_url = normalize_url(domain)
    api_url = f"{base_url}/wp-json/wp/v2/posts"
    
    # Tworzenie nagłówka autoryzacji Basic Auth
    credentials = f"{username}:{app_password}"
    token = base64.b64encode(credentials.encode()).decode('utf-8')
    headers = {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "title": title,
        "content": content,
        "status": "draft" # Publikujemy jako szkic
    }
    
    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=30)
        
        if response.status_code == 201:
            data = response.json()
            return {
                "success": True,
                "id": data.get("id"),
                "link": data.get("link"), # Link do podglądu
                "message": "Opublikowano pomyślnie"
            }
        elif response.status_code == 401:
            return {"success": False, "message": "Błąd autoryzacji (401). Sprawdź hasło aplikacji."}
        else:
            return {"success": False, "message": f"Błąd API: {response.status_code} - {response.text[:200]}"}
            
    except Exception as e:
        return {"success": False, "message": f"Wyjątek połączenia: {str(e)}"}
