from django.http import HttpResponse
from django.http.response import Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.utils.text import slugify

from blogs.models import Blog, Post, Upvote, Comment, DangerousReport
from blogs.helpers import salt_and_hash, unmark
from blogs.views.analytics import render_analytics

import os
import tldextract

def resolve_address(request):
    http_host = request.get_host()

    sites = os.getenv('MAIN_SITE_HOSTS').split(',')

    # forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
    # if forwarded_for:
    #     print('X-Forwarded-For: ', forwarded_for.split(',')[0], 'Full URL: ', request.build_absolute_uri())

    if any(http_host == site for site in sites):
        # Homepage
        return None
    elif any(site in http_host for site in sites):
        # Subdomained blog
        subdomain = tldextract.extract(http_host).subdomain
        
        if request.COOKIES.get('admin_passport') == os.getenv('ADMIN_PASSPORT'):
            return get_object_or_404(Blog.objects.select_related('user').select_related('user__settings'), subdomain__iexact=subdomain)
        else:
            return get_object_or_404(Blog.objects.select_related('user').select_related('user__settings'), subdomain__iexact=subdomain, user__is_active=True)
    else:
        # Custom domain blog
        return get_blog_with_domain(http_host)


def get_blog_with_domain(domain):
    if not domain:
        return False
    try:
        return Blog.objects.get(domain=domain, user__is_active=True)
    except Blog.DoesNotExist:
        # Handle www subdomain if necessary
        if 'www.' in domain:
            return get_object_or_404(Blog, domain__iexact=domain.replace('www.', ''), user__is_active=True)
        else:
            return get_object_or_404(Blog, domain__iexact=f'www.{domain}', user__is_active=True)


@csrf_exempt
def ping(request):
    domain = request.GET.get("domain", None)
    
    try:
        if get_blog_with_domain(domain):
            print('Ping! Found correct blog. Issuing certificate.')
            return HttpResponse('Ping', status=200)
    except:
        pass

    print(f'Ping! Could not find blog with domain {domain}')
    return HttpResponse('Invalid domain', status=422)


def home(request):
    blog = resolve_address(request)
    if not blog:
        return render(request, 'landing.html')

    all_posts = blog.posts.filter(publish=True, published_date__lte=timezone.now(), is_page=False).order_by('-published_date')

    meta_description = blog.meta_description or unmark(blog.content)[:157] + '...'
    
    return render(
        request,
        'home.html',
        {
            'blog': blog,
            'posts': all_posts,
            'meta_description': meta_description
        }
    )


def posts(request, blog):
    if not blog:
        blog = resolve_address(request)
        if not blog:
            return not_found(request)
    
    tag_param = request.GET.get('q', '')
    tool_param = request.GET.get('tool', '')
    
    tags = [t.strip() for t in tag_param.split(',')] if tag_param else []
    tags = [t for t in tags if t]  # Remove empty strings
    
    tools = [t.strip() for t in tool_param.split(',')] if tool_param else []
    tools = [t for t in tools if t]  # Remove empty strings

    posts = blog.posts.filter(blog=blog, publish=True, published_date__lte=timezone.now(), is_page=False).order_by('-published_date')
    
    if tags or tools:
        # Filter posts that contain ALL specified tags AND tools
        posts = [post for post in posts if 
                 all(tag in post.tags for tag in tags) and
                 all(tool in post.tools for tool in tools)]
        
        available_tags = set()
        for post in posts:
            available_tags.update(post.tags)
    else:
        available_tags = set(blog.tags)

    meta_description = blog.meta_description or unmark(blog.content)[:157] + '...'

    blog_path_title = blog.blog_path.replace('-', ' ').capitalize() or 'Blog'

    return render(
        request,
        'posts.html',
        {
            'blog': blog,
            'posts': posts,
            'meta_description': meta_description,
            'query': tag_param,
            'tool_query': tool_param,
            'active_tags': tags,
            'active_tools': tools,
            'available_tags': available_tags,
            'blog_path_title': blog_path_title
        }
    )


@csrf_exempt
def post(request, slug):
    # Prevent null characters in path
    slug = slug.replace('\x00', '')

    if slug[0] == '/' and slug[-1] == '/':
        slug = slug[1:-1]

    blog = resolve_address(request)
    if not blog:
        return not_found(request)
    
    # Check for a custom RSS feed path
    if slug == blog.rss_alias:
        from blogs.views.feed import feed
        return feed(request)

    # Find by post slug
    post = Post.objects.filter(blog=blog, slug__iexact=slug).first()

    if not post:
        # Find by post alias
        post = Post.objects.filter(blog=blog, alias__iexact=slug).first()
        
        if post:
            return redirect('post', slug=post.slug)
        else:
            # Check for a custom blogreel or /blog path and render the blog page
            if slug == blog.blog_path or slug == 'blog':
                return posts(request, blog)

            return render(request, '404.html', {'blog': blog}, status=404)
    
    # Check if upvoted
    hash_id = salt_and_hash(request, 'year')
    upvoted = post.upvote_set.filter(hash_id=hash_id).exists()

    meta_description = post.meta_description or unmark(post.content)[:157] + '...'
    full_path = f'{blog.useful_domain}/{post.slug}/'
    canonical_url = full_path
    if post.canonical_url and post.canonical_url.startswith('https://'):
        canonical_url = post.canonical_url

    if post.publish is False and not request.GET.get('token') == post.token:
        return not_found(request)

    # Get user's most recent active report for delete button logic
    user_latest_report = None
    if request.user.is_authenticated:
        user_latest_report = DangerousReport.objects.filter(
            post=post, 
            user=request.user, 
            deleted=False
        ).order_by('-created_at').first()

    context = {
        'blog': blog,
        'post': post,
        'full_path': full_path,
        'canonical_url': canonical_url,
        'meta_description': meta_description,
        'meta_image': post.meta_image or blog.meta_image,
        'upvoted': upvoted,
        'user_has_reported': post.user_has_active_report(request.user),
        'user_latest_report': user_latest_report,
    }

    response = render(request, 'post.html', context)

    if post.publish and not request.GET.get('token'):
        response['Cache-Tag'] = blog.subdomain
        
    return response


@csrf_exempt
def upvote(request, uid):
    hash_id = salt_and_hash(request, 'year')

    if uid == request.POST.get("uid", "") and not request.POST.get("title", False):
        post = get_object_or_404(Post, uid=uid)
        print("Upvoting", post)
        try:
            upvote, created = Upvote.objects.get_or_create(post=post, hash_id=hash_id)
        
            if created:
                return HttpResponse(f'Upvoted {post.title}')
            raise Http404('Duplicate upvote')
        except Upvote.MultipleObjectsReturned:
            return HttpResponse(f'Upvoted {post.title}')
    raise Http404("Someone's doing something dodgy ʕ •`ᴥ•´ʔ")


def public_analytics(request):
    blog = resolve_address(request)
    if not blog:
        return not_found(request)

    if not blog or not blog.user.settings.upgraded or not blog.public_analytics:
        return not_found(request)

    return render_analytics(request, blog, True)


def not_found(request, *args, **kwargs):
    return render(request, '404.html', status=404)


def sitemap(request):
    blog = resolve_address(request)
    if not blog:
        return not_found(request)
    
    try:
        posts = blog.posts.filter(publish=True, published_date__lte=timezone.now()).only('slug', 'last_modified', 'blog_id').order_by('-published_date')
    except AttributeError:
        posts = []

    return render(request, 'sitemap.xml', {'blog': blog, 'posts': posts}, content_type='text/xml')


def robots(request):
    blog = resolve_address(request)
    if not blog:
        return not_found(request)

    return render(request, 'robots.txt',  {'blog': blog}, content_type="text/plain")


@csrf_exempt
def add_comment(request, uid):
    if request.method == 'POST':
        post = get_object_or_404(Post, uid=uid)
        
        # Check if user is authenticated
        if not request.user.is_authenticated:
            return redirect(f"/{post.slug}/?error=login_required")
        
        # Check if comments are enabled for this post
        if not post.comments_enabled:
            raise Http404("Comments are disabled for this post")
        
        # Basic validation
        content = request.POST.get('content', '').strip()
        display_option = request.POST.get('display_option', 'email')
        
        # Handle legacy use_email_as_name parameter for backwards compatibility
        use_email_as_name = request.POST.get('use_email_as_name') == 'on'
        if use_email_as_name:
            display_option = 'email'
        
        if not content:
            return redirect(f"/{post.slug}/?error=missing_content")
        
        # Simple spam prevention - check if content is too short or too long
        if len(content) < 5 or len(content) > 1000:
            return redirect(f"/{post.slug}/?error=invalid_content")
        
        try:
            # Determine display settings based on choice
            use_nickname = display_option == 'nickname' and request.user.settings.nickname
            use_email_as_name_final = display_option == 'email'
            
            # Create the comment
            comment = Comment.objects.create(
                post=post,
                user=request.user,
                use_email_as_name=use_email_as_name_final,
                use_nickname=use_nickname,
                content=content
            )
            return redirect(f"/{post.slug}/?comment_added=true")
        except Exception as e:
            return redirect(f"/{post.slug}/?error=submission_failed")
    
    raise Http404("Invalid request method")


@csrf_exempt
def report_dangerous(request, uid):
    if request.method == 'POST':
        post = get_object_or_404(Post, uid=uid)
        
        # Check if user is authenticated
        if not request.user.is_authenticated:
            return redirect(f"/{post.slug}/?error=login_required")
        
        # Basic validation
        comment = request.POST.get('comment', '').strip()
        display_option = request.POST.get('display_option', 'email')
        
        if not comment:
            return redirect(f"/{post.slug}/?error=missing_report_comment")
        
        # Validate comment length (5-100 chars)
        if len(comment) < 5 or len(comment) > 100:
            return redirect(f"/{post.slug}/?error=invalid_report_comment")
        
        try:
            # Check if user already has an active (non-deleted) report
            if post.user_has_active_report(request.user):
                return redirect(f"/{post.slug}/?error=already_reported")
            
            # Determine display settings based on choice
            use_nickname = display_option == 'nickname' and request.user.settings.nickname
            
            # Create a new report (allows multiple reports per user over time)
            DangerousReport.objects.create(
                post=post,
                user=request.user,
                use_nickname=use_nickname,
                comment=comment
            )
            
            return redirect(f"/{post.slug}/?report_added=true")
        except Exception as e:
            return redirect(f"/{post.slug}/?error=submission_failed")
    
    raise Http404("Invalid request method")


@csrf_exempt
def delete_comment(request, comment_id):
    if request.method == 'POST':
        comment = get_object_or_404(Comment, id=comment_id)
        
        # Only allow author to delete their own comment
        if request.user != comment.user:
            raise Http404("Permission denied")
        
        # Soft delete the comment
        comment.soft_delete()
        
        return redirect(f"/{comment.post.slug}/?comment_deleted=true")
    
    raise Http404("Invalid request method")


@csrf_exempt  
def delete_report(request, uid):
    if request.method == 'POST':
        # Get post and most recent active report by user
        post = get_object_or_404(Post, uid=uid)
        
        try:
            # Get the most recent non-deleted report by this user for this post
            report = DangerousReport.objects.filter(
                post=post, 
                user=request.user, 
                deleted=False
            ).order_by('-created_at').first()
            
            if not report:
                raise Http404("No active report found")
            
            # Soft delete the report
            report.soft_delete()
            
            return redirect(f"/{post.slug}/?report_deleted=true")
            
        except Exception as e:
            return redirect(f"/{post.slug}/?error=report_delete_failed")
    
    raise Http404("Invalid request method")
