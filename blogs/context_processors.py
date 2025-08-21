import os
from .models import Blog

# Add tz and admin_passport to every page
def extra(request):
    return {
        'tz': request.COOKIES.get('timezone', 'UTC'),
        'admin_passport': request.COOKIES.get('admin_passport') == os.getenv('ADMIN_PASSPORT'),
        'bear_root': 'http://' + os.getenv('MAIN_SITE_HOSTS').split(',')[0]
    }

# Add blog context for authenticated users (single-blog architecture)
def user_blog(request):
    if request.user.is_authenticated:
        try:
            blog = Blog.objects.filter(user=request.user).first()
            return {'blog': blog}
        except:
            pass
    return {}
