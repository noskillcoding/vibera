import os
from .models import Blog
from django.utils import timezone

# Add tz and admin_passport to every page
def extra(request):
    return {
        'tz': request.COOKIES.get('timezone', 'UTC'),
        'admin_passport': request.COOKIES.get('admin_passport') == os.getenv('ADMIN_PASSPORT'),
        'bear_root': 'http://' + os.getenv('MAIN_SITE_HOSTS').split(',')[0]
    }

# Add blog/space template variables for the current blog context
def blog_space_variables(request):
    """
    Add template variables for both legacy (blog_*) and new (space_*) naming.
    This allows templates to use {{ blog_title }} or {{ space_title }} etc.
    """
    # Try to get blog from various sources
    blog = None
    
    # First, try to get from URL resolution (for blog pages)
    from .views.blog import resolve_address
    try:
        blog = resolve_address(request)
    except:
        pass
    
    # If no blog from URL, try user's blog (for dashboard pages)
    if not blog and request.user.is_authenticated:
        try:
            blog = Blog.objects.filter(user=request.user).first()
        except:
            pass
    
    if blog:
        # Calculate relative dates
        now = timezone.now()
        blog_last_modified_days = (now - blog.last_modified).days if blog.last_modified else None
        
        # Get latest post date
        latest_post = blog.posts.filter(publish=True, published_date__lte=now, is_page=False, is_template_draft=False).order_by('-published_date').first()
        blog_last_posted_days = (now - latest_post.published_date).days if latest_post else None
        
        # Create template variables (both legacy and new naming)
        template_vars = {
            # Legacy blog_* variables (for Bear compatibility and docs)
            'blog_title': blog.title,
            'blog_description': blog.meta_description or blog.content[:157] + '...' if blog.content else '',
            'blog_link': blog.useful_domain,
            'blog_created_date': blog.created_date,
            'blog_last_modified': f"{blog_last_modified_days} days" if blog_last_modified_days is not None else "unknown",
            'blog_last_posted': f"{blog_last_posted_days} days" if blog_last_posted_days is not None else "unknown",
            
            # New space_* variables (for Vibera branding)
            'space_title': blog.title,
            'space_description': blog.meta_description or blog.content[:157] + '...' if blog.content else '',
            'space_link': blog.useful_domain,
            'space_created_date': blog.created_date,
            'space_last_modified': f"{blog_last_modified_days} days" if blog_last_modified_days is not None else "unknown",
            'space_last_posted': f"{blog_last_posted_days} days" if blog_last_posted_days is not None else "unknown",
        }
        
        return template_vars
    
    return {}

# Add blog context for authenticated users (single-blog architecture)
def user_blog(request):
    if request.user.is_authenticated:
        try:
            blog = Blog.objects.filter(user=request.user).first()
            return {'blog': blog}
        except:
            pass
    return {}
