import hashlib
from django.core.cache import cache
from django.http import HttpResponse

class LoginThrottle:
    """Límite compartido por IP en el único proceso Waitress local."""
    def __init__(self, get_response): self.get_response = get_response
    def __call__(self, request):
        login = request.path == '/ingresar/' and request.method == 'POST'
        key = 'login:' + hashlib.sha256(request.META.get('REMOTE_ADDR', '').encode()).hexdigest()
        if login and cache.get(key, 0) >= 8:
            return HttpResponse('<h1>Demasiados intentos</h1><p>Espera 5 minutos e intenta de nuevo.</p><a href="/ingresar/">Volver</a>', status=429, headers={'Retry-After': '300'})
        response = self.get_response(request)
        if login:
            if response.status_code == 302: cache.delete(key)
            elif response.status_code == 200:
                if not cache.add(key, 1, timeout=300): cache.incr(key)
        return response
