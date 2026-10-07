def brand(request):
    from django.conf import settings
    return {'brand': 'Control Empresa', 'section': request.path.split('/')[1] or 'inicio', 'demo_mode': getattr(settings, 'DEMO_MODE', False)}
