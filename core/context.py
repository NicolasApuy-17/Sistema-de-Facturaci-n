def brand(request):
    return {'brand': 'Control Empresa', 'section': request.path.split('/')[1] or 'inicio'}
