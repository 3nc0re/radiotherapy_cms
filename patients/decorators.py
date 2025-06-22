from django.shortcuts import render
from django.contrib.auth.decorators import login_required as django_login_required
from functools import wraps

def login_required(view_func):
    """
    Власний декоратор для перевірки авторизації з кращим UX
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.user.is_authenticated:
            return view_func(request, *args, **kwargs)
        else:
            # Показуємо красиву сторінку замість перенаправлення на логін
            return render(request, 'patients/unauthorized.html')
    
    return _wrapped_view

def staff_required(view_func):
    """
    Декоратор для перевірки прав персоналу
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return render(request, 'patients/unauthorized.html')
        
        if not request.user.is_staff:
            return render(request, 'patients/forbidden.html', status=403)
        
        return view_func(request, *args, **kwargs)
    
    return _wrapped_view

def admin_required(view_func):
    """
    Декоратор для перевірки прав адміністратора
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return render(request, 'patients/unauthorized.html')
        
        if request.user.role != 'admin':
            return render(request, 'patients/forbidden.html', status=403)
        
        return view_func(request, *args, **kwargs)
    
    return _wrapped_view 