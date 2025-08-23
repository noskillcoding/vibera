from django.contrib.auth.decorators import login_required
from django.db import DataError
from django.forms import ValidationError
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404, render, redirect
from django.http import HttpResponseBadRequest, JsonResponse
from django.utils import timezone
from django.utils.text import slugify
from django.core.validators import URLValidator

from zoneinfo import ZoneInfo
from datetime import datetime
import json
import random
import re
import string

from blogs.backup import backup_in_thread
from blogs.forms import AdvancedSettingsForm, BlogForm, DashboardCustomisationForm, PostTemplateForm
from blogs.helpers import check_connection, is_protected, salt_and_hash
from blogs.models import Blog, Post, Upvote
from collections import Counter
from blogs.subscriptions import get_subscriptions


def _create_or_update_template_draft(blog, header_content, body_content):
    """Create or update a template draft post for preview purposes"""
    # Get or create template draft post
    template_draft, created = Post.objects.get_or_create(
        blog=blog,
        is_template_draft=True,
        defaults={
            'uid': f'template-{blog.subdomain}',
            'title': 'Template Preview',
            'slug': 'template-preview',
            'content': '',
            'publish': False,  # Always unpublished
            'published_date': timezone.now(),
            'is_page': False,
            'make_discoverable': True,
        }
    )
    
    # Parse header content and populate fields
    if header_content:
        raw_header = [item for item in header_content.split('\r\n') if item]
        
        # Clear out data
        template_draft.title = 'Template Preview'
        template_draft.short_description = ''
        template_draft.all_tags = '[]'
        template_draft.all_tools = '[]'
        template_draft.github_url = ''
        template_draft.comments_enabled = True
        template_draft.media_urls = []
        
        # Parse header data
        for item in raw_header:
            if ':' in item:
                # Strip HTML tags from the item
                clean_item = re.sub(r'<[^>]+>', '', item)
                name, value = clean_item.split(':', 1)
                name = name.strip()
                value = value.strip()
                
                if name == 'title' and value:
                    template_draft.title = value
                elif name == 'short_description':
                    template_draft.short_description = value[:100]
                elif name == 'tags' or name == 'all_tags':
                    tags = [tag.strip() for tag in value.split(',') if tag.strip()]
                    template_draft.all_tags = json.dumps(tags)
                elif name == 'tools' or name == 'all_tools':
                    tools = [tool.strip() for tool in value.split(',') if tool.strip()]
                    template_draft.all_tools = json.dumps(tools)
                elif name == 'github_url':
                    template_draft.github_url = value
                elif name == 'comments_enabled':
                    template_draft.comments_enabled = str(value).lower() != 'false'
    
    # Set content
    template_draft.content = body_content or ''
    
    # Ensure template drafts are discoverable for reports section to show
    template_draft.make_discoverable = True
    
    # Ensure slug is unique and doesn't conflict
    template_draft.slug = 'template-preview'
    
    template_draft.save()
    return template_draft


def get_popular_tags_and_tools(limit=10):
    """Get the most popular tags and tools from published posts"""
    # Get all published posts
    posts = Post.objects.filter(publish=True, is_page=False, is_template_draft=False)
    
    # Count tags
    all_tags = []
    all_tools = []
    
    for post in posts:
        all_tags.extend(json.loads(post.all_tags))
        all_tools.extend(json.loads(post.all_tools))
    
    # Get top counts
    popular_tags = Counter(all_tags).most_common(limit)
    popular_tools = Counter(all_tools).most_common(limit)
    
    return popular_tags, popular_tools


@login_required
def user_account_settings(request):
    """Handle user account settings including nickname"""
    user_settings = request.user.settings
    success_message = None
    error_message = None
    
    if request.method == "POST":
        nickname = request.POST.get('nickname', '').strip()
        
        if nickname and user_settings.nickname:
            error_message = "Nickname cannot be changed once set."
        elif nickname:
            # Validate nickname (basic validation)
            if len(nickname) < 2 or len(nickname) > 30:
                error_message = "Nickname must be between 2 and 30 characters."
            elif not nickname.replace('_', '').replace('-', '').isalnum():
                error_message = "Nickname can only contain letters, numbers, hyphens, and underscores."
            else:
                try:
                    user_settings.nickname = nickname
                    user_settings.save()
                    success_message = "Nickname set successfully!"
                except Exception as e:
                    if 'unique constraint' in str(e).lower():
                        error_message = "This nickname is already taken."
                    else:
                        error_message = "An error occurred. Please try again."
        elif 'clear_nickname' in request.POST and not user_settings.nickname:
            # Allow clearing only if nickname is not set yet (shouldn't happen but just in case)
            pass
    
    # Get subscription information (same logic as the old blog list)
    subscription_cancelled = None
    subscription_link = None
    variant = None
    upgrade_subscription_link = None

    if request.user.settings.order_id:
        try:
            subscription = get_subscriptions(request.user.settings.order_id)
            if subscription:
                subscription_cancelled = subscription['data'][0]['attributes']['cancelled']
                subscription_link = subscription['data'][0]['attributes']['urls']['customer_portal']
                upgrade_subscription_link = subscription['data'][0]['attributes']['urls']['customer_portal_update_subscription']
                variant = subscription['data'][0]['attributes']['variant_name']
        except Exception as e:
            print('No sub found ', e)
    
    return render(request, 'dashboard/user_account_settings.html', {
        'user_settings': user_settings,
        'success_message': success_message,
        'error_message': error_message,
        'subscription_cancelled': subscription_cancelled,
        'subscription_link': subscription_link,
        'upgrade_subscription_link': upgrade_subscription_link,
        'variant': variant,
    })


@login_required
def list(request):
    # In single-blog architecture, redirect to user's blog dashboard
    blog = Blog.objects.filter(user=request.user).first()
    
    if not blog:
        # If somehow user has no blog, redirect to home to create one
        return redirect('/')
    
    # Redirect to the user's single blog dashboard
    return redirect('dashboard', id=blog.subdomain)


@login_required
def studio(request, id):
    if request.user.is_superuser:
        blog = get_object_or_404(Blog, subdomain=id)
    else:
        blog = get_object_or_404(Blog, user=request.user, subdomain=id)

    error_messages = []
    header_content = request.POST.get('header_content', '')
    body_content = request.POST.get('body_content', '')

    if request.method == "POST" and header_content:
        try:
            error_messages.extend(parse_raw_homepage(blog, header_content, body_content))
        except IndexError:
            error_messages.append("One of the header options is invalid")
        except ValueError as error:
            error_messages.append(error)
        except DataError as error:
            error_messages.append(error)

    return render(request, 'studio/studio.html', {
        'blog': blog,
        'error_messages': error_messages,
        'header_content': header_content,
    })


@login_required
def blog_dashboard(request, id):
    """New dashboard page with navigation hub and links"""
    if request.user.is_superuser:
        blog = get_object_or_404(Blog, subdomain=id)
    else:
        blog = get_object_or_404(Blog, user=request.user, subdomain=id)

    return render(request, 'studio/blog_dashboard.html', {
        'blog': blog,
    })


def parse_raw_homepage(blog, header_content, body_content):
    if len(body_content) > 100000:
        return ["Your content is too long. This is a safety feature to prevent abuse. If you're sure you need more, please contact support."]
    
    raw_header = [item for item in header_content.split('\r\n') if item]
    
    # Clear out data
    blog.favicon = ''
    blog.meta_description = ''
    blog.meta_image = ''

    error_messages = []
    # Parse and populate header data
    for item in raw_header:
        item = item.split(':', 1)
        name = item[0].strip()
        value = item[1].strip()
        if str(value).lower() == 'true':
            value = True
        if str(value).lower() == 'false':
            value = False

        if name == 'title':
            blog.title = value
        elif name == 'favicon':
            if len(value) < 100:
                blog.favicon = value
            else:
                error_messages.append("Favicon is too long. Use an emoji.")
        elif name == 'meta_description':
            blog.meta_description = value
        elif name == 'meta_image':
            blog.meta_image = value
        else:
            error_messages.append(f"{name} is an unrecognised header option")

    if not blog.title:
        blog.title = "My blog"
    if not blog.subdomain:
        blog.slug = slugify(blog.user.username)

    blog.content = body_content
    blog.last_modified = timezone.now()
    blog.save()
    return error_messages


@login_required
def post(request, id, uid=None):
    if request.user.is_superuser:
        blog = get_object_or_404(Blog, subdomain=id)
    else:
        blog = get_object_or_404(Blog, user=request.user, subdomain=id)

    is_page = request.GET.get('is_page', '')
    tags = []
    post = None

    if uid:
        post = Post.objects.filter(blog=blog, uid=uid).first()

    error_messages = []
    header_content = request.POST.get("header_content", "")
    body_content = request.POST.get("body_content", "")
    preview = request.POST.get("preview", False) == "true"

    if request.method == "POST" and header_content:
        # Prevent accidental updates to published posts
        # Only process if it's a new post, draft, or explicit save action
        if post and post.publish and not preview:
            # This is a published post - only allow updates if user explicitly clicked a save button
            is_explicit_save = request.POST.get("publish") in ["true", "false"]
            if not is_explicit_save:
                error_messages.append("Published posts cannot be updated automatically. Use 'Save as new draft' to create a draft version.")
                return render(request, 'studio/post_edit.html', {
                    'blog': blog,
                    'post': post,
                    'error_messages': error_messages,
                })
        
        if blog.posts.count() >= 3000:
            error_messages.append("You have reached the maximum number of posts. This is a safety feature to prevent abuse. If you're sure you need more, please contact support.")
            return render(request, 'studio/post_edit.html', {
                'blog': blog,
                'post': post,
                'error_messages': error_messages,
            })
        if len(body_content) > 1000000:
            error_messages.append("Your content is too long. This is a safety feature to prevent abuse. If you're sure you need more, please contact support.")
            return render(request, 'studio/post_edit.html', {
                'blog': blog,
                'post': post,
                'error_messages': error_messages,
            })
        
        raw_header = [item for item in header_content.split('\r\n') if item]
        is_new = False

        if not post:
            post = Post(blog=blog)
            is_new = True

        try:
            # Clear out data
            slug = ''
            post.alias = ''
            post.class_name = ''
            post.canonical_url = ''
            post.meta_description = ''
            post.meta_image = ''
            post.short_description = ''
            post.is_page = False
            post.make_discoverable = True
            post.lang = ''
            post.all_tags = '[]'
            post.all_tools = '[]'
            post.github_url = ''
            post.comments_enabled = True
            post.media_urls = []

            # Parse and populate header data
            for item in raw_header:
                # Strip HTML tags from the item
                clean_item = re.sub(r'<[^>]+>', '', item)
                item = clean_item.split(':', 1)
                name = item[0].strip()

                # Prevent index error
                if len(item) == 2:
                    value = item[1].strip()
                else:
                    value = ''

                if str(value).lower() == 'true':
                    value = True
                if str(value).lower() == 'false':
                    value = False

                if name == 'title':
                    post.title = value
                elif name == 'short_description':
                    post.short_description = value[:100]  # Enforce 100 char limit
                elif name == 'link':
                    slug = value
                elif name == 'alias':
                    post.alias = value
                elif name == 'published_date':
                    if not value:
                        post.published_date = timezone.now()
                    else:
                        value = str(value).replace('/', '-')
                        try:
                            # Convert given date/time from local timezone to UTC
                            naive_datetime = datetime.fromisoformat(value)
                            user_timezone = request.COOKIES.get('timezone', 'UTC')

                            try:
                                user_tz = ZoneInfo(user_timezone)
                            except Exception as e:
                                user_tz = ZoneInfo('UTC')

                            aware_datetime = timezone.make_aware(naive_datetime, user_tz)
                            utc_datetime = aware_datetime.astimezone(ZoneInfo('UTC'))
                            post.published_date = utc_datetime
                        except Exception as e:
                            error_messages.append('Bad date format. Use YYYY-MM-DD HH:MM')
                elif name == 'tags':
                    tags = []
                    for tag in value.split(','):
                        stripped_tag = tag.strip()
                        if stripped_tag and stripped_tag not in tags:
                            tags.append(stripped_tag)
                    post.all_tags = json.dumps(tags)
                elif name == 'tools':
                    tools = []
                    for tool in value.split(','):
                        stripped_tool = tool.strip()
                        if stripped_tool and stripped_tool not in tools:
                            tools.append(stripped_tool)
                    post.all_tools = json.dumps(tools)
                elif name == 'github_url':
                    post.github_url = value
                elif name == 'comments_enabled':
                    if type(value) is bool:
                        post.comments_enabled = value
                    else:
                        error_messages.append('comments_enabled needs to be "true" or "false"')
                elif name == 'media_urls':
                    try:
                        media_urls = json.loads(value) if value else []
                        post.media_urls = media_urls
                    except json.JSONDecodeError:
                        error_messages.append('Invalid media_urls format')
                elif name == 'make_discoverable':
                    if type(value) is bool:
                        post.make_discoverable = value
                    else:
                        error_messages.append('make_discoverable needs to be "true" or "false"')
                elif name == 'is_page':
                    if type(value) is bool:
                        post.is_page = value
                    else:
                        error_messages.append('is_page needs to be "true" or "false"')
                elif name == 'class_name':
                    post.class_name = slugify(value)
                elif name == 'canonical_url':
                    post.canonical_url = value
                elif name == 'meta_description':
                    post.meta_description = value
                elif name == 'meta_image':
                    post.meta_image = value
                else:
                    error_messages.append(f"{name} is an unrecognised header option")

            if not post.title:
                post.title = "New drop"

            post.slug = unique_slug(blog, post, slug)

            if not post.published_date:
                post.published_date = timezone.now()

            post.content = body_content
            is_saving_published_as_draft = post and post.publish and request.POST.get("publish", False) == "false"
            post.publish = request.POST.get("publish", False) == "true"
            post.last_modified = timezone.now()

            if preview:
                return post
            else:
                if is_saving_published_as_draft:
                    # Create a new draft post instead of modifying the published one
                    original_post = post
                    post = Post()
                    post.blog = blog
                    post.title = original_post.title
                    post.slug = unique_slug(blog, post, original_post.slug)
                    post.content = body_content
                    post.publish = False
                    post.is_page = original_post.is_page
                    post.make_discoverable = original_post.make_discoverable
                    post.comments_enabled = original_post.comments_enabled
                    post.all_tags = original_post.all_tags
                    post.all_tools = original_post.all_tools
                    post.github_url = original_post.github_url
                    post.short_description = original_post.short_description
                    post.meta_description = original_post.meta_description
                    post.meta_image = original_post.meta_image
                    post.canonical_url = original_post.canonical_url
                    post.class_name = original_post.class_name
                    post.media_urls = original_post.media_urls.copy() if original_post.media_urls else []
                    post.published_date = timezone.now()
                    # UID will be auto-generated by the Post model's save method
                    is_new = True
                
                post.save()
                
                # Backup blog
                backup_in_thread(blog)
                
                if is_new:
                    # Self-upvote
                    upvote = Upvote(post=post, hash_id=salt_and_hash(request, 'year'))
                    upvote.save()

                # If publishing, redirect to appropriate list page for better UX
                if post.publish:
                    if post.is_page:
                        return redirect('pages_edit', id=blog.subdomain)
                    else:
                        return redirect('posts_edit', id=blog.subdomain)
                else:
                    # If saving as draft
                    if is_saving_published_as_draft:
                        # For "Save as new draft", redirect to appropriate list to show both versions
                        if post.is_page:
                            return redirect('pages_edit', id=blog.subdomain)
                        else:
                            return redirect('posts_edit', id=blog.subdomain)
                    else:
                        # For draft modifications, check if it's an existing draft
                        if post and not is_new and not post.publish:
                            # This is modifying an existing draft - stay on same page
                            # Don't redirect, just continue to render the page with updated post
                            pass
                        else:
                            # For new draft saves, redirect to the edit page
                            return redirect('post_edit', id=blog.subdomain, uid=post.uid)

        except Exception as error:
            error_messages.append(f"Header attribute error - your post has not been saved. Error: {str(error)}")
            post.content = body_content

    template_header = ""
    template_body = ""
    template_data = {}
    
    if blog.post_template:
        template_parts = blog.post_template.split("___", 1)
        if len(template_parts) == 2:
            template_header, template_body = template_parts
        else:
            template_header = blog.post_template.strip()
            
        # Parse template header to extract individual field values for new posts
        if template_header and not post:  # Only for new posts, not editing existing ones
            for line in template_header.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    template_data[key] = value

    # Get popular tags and tools for suggestions
    popular_tags, popular_tools = get_popular_tags_and_tools(10)
    
    return render(request, 'studio/post_edit.html', {
        'blog': blog,
        'post': post,
        'error_messages': error_messages,
        'template_header': template_header,
        'template_body': template_body,
        'template_data': template_data,
        'is_page': is_page,
        'popular_tags': popular_tags,
        'popular_tools': popular_tools
    })


def unique_slug(blog, post, new_slug):
    # Clean the new_slug to be alphanumeric lowercase with only '/', '_' and '-' allowed
    cleaned_slug = ''.join(c for c in new_slug.lower() if c.isalnum() or c == '/' or c == '-' or c == '_')

    # Remove trailing and leading slashes
    if len(cleaned_slug) > 0 and cleaned_slug[-1] == '/':
        cleaned_slug = cleaned_slug[:-1]
    if len(cleaned_slug) > 0 and cleaned_slug[0] == '/':
        cleaned_slug = cleaned_slug[1:]

    # If the cleaned slug is empty, use the title
    if cleaned_slug == '':
        slug = slugify(post.title) or slugify(str(random.randint(0,9999)))
    else:
        slug = cleaned_slug
    
    new_stack = "-new"

    while Post.objects.filter(blog=blog, slug=slug).exclude(pk=post.pk).exists():
        slug = f"{slug}{new_stack}"
        new_stack += "-new"

    return slug


@csrf_exempt
@login_required
def preview(request, id):
    if request.user.is_superuser:
        blog = get_object_or_404(Blog, subdomain=id)
    else:
        blog = get_object_or_404(Blog, user=request.user, subdomain=id)

    post = Post(blog=blog)

    header_content = request.POST.get("header_content", "")
    body_content = request.POST.get("body_content", "")
    try:
        if header_content:
            raw_header = [item for item in header_content.split('\r\n') if item]

            if post is None:
                post = Post(blog=blog)

            # Clear out data
            # post.slug = ''
            post.alias = ''
            post.class_name = ''
            post.canonical_url = ''
            post.meta_description = ''
            post.meta_image = ''
            post.short_description = ''
            post.is_page = False
            post.make_discoverable = True
            post.lang = ''
            post.all_tools = '[]'
            post.github_url = ''
            post.comments_enabled = True
            post.media_urls = []

            # Parse and populate header data
            for item in raw_header:
                item = item.split(':', 1)
                name = item[0].strip()
                value = item[1].strip()
                if str(value).lower() == 'true':
                    value = True
                if str(value).lower() == 'false':
                    value = False

                if name == 'title':
                    post.title = value
                elif name == 'short_description':
                    post.short_description = value[:100]  # Enforce 100 char limit
                elif name == 'alias':
                    post.alias = value
                elif name == 'published_date':
                    # Check if previously posted 'now'
                    value = value.replace('/', '-')
                    if not str(post.published_date).startswith(value):
                        post.published_date = timezone.datetime.fromisoformat(value)
                elif name == 'make_discoverable':
                    post.make_discoverable = value
                elif name == 'is_page':
                    post.is_page = value
                elif name == 'class_name':
                    post.class_name = slugify(value)
                elif name == 'canonical_url':
                    post.canonical_url = value
                elif name == 'meta_description':
                    post.meta_description = value
                elif name == 'meta_image':
                    post.meta_image = value
                elif name == 'media_urls':
                    try:
                        media_urls = json.loads(value) if value else []
                        post.media_urls = media_urls
                    except (json.JSONDecodeError, TypeError):
                        pass  # Keep default empty list
                elif name == 'tags' or name == 'all_tags':
                    # Handle tags
                    tags = []
                    for tag in value.split(','):
                        stripped_tag = tag.strip()
                        if stripped_tag and stripped_tag not in tags:
                            tags.append(stripped_tag)
                    post.all_tags = json.dumps(tags)
                elif name == 'tools' or name == 'all_tools':
                    # Handle tools
                    tools = []
                    for tool in value.split(','):
                        stripped_tool = tool.strip()
                        if stripped_tool and stripped_tool not in tools:
                            tools.append(stripped_tool)
                    post.all_tools = json.dumps(tools)
                elif name == 'github_url':
                    post.github_url = value
                elif name == 'comments_enabled':
                    post.comments_enabled = value

            if not post.title:
                post.title = "New drop"
            if not post.slug:
                post.slug = slugify(post.title)
                if not post.slug or post.slug == "":
                    post.slug = ''.join(random.SystemRandom().choice(string.ascii_letters) for _ in range(10))
            if not post.published_date:
                post.published_date = timezone.now()

            post.content = body_content

    except ValidationError:
        return HttpResponseBadRequest("One of the header options is invalid")
    except IndexError:
        return HttpResponseBadRequest("One of the header options is invalid")
    except ValueError as error:
        return HttpResponseBadRequest(error)
    except DataError as error:
        return HttpResponseBadRequest(error)

    full_path = f'{blog.useful_domain}/{post.slug}/'
    canonical_url = full_path
    if post.canonical_url and post.canonical_url.startswith('https://'):
        canonical_url = post.canonical_url
    return render(
        request,
        'post.html',
        {
            'blog': blog,
            'content': post.content,
            'post': post,
            'full_path': full_path,
            'canonical_url': canonical_url,
            'meta_image': post.meta_image or blog.meta_image,
            'tz': request.COOKIES.get('timezone', 'UTC'),
            'preview': True,
        }
    )


@login_required
def post_template(request, id):
    if request.user.is_superuser:
        blog = get_object_or_404(Blog, subdomain=id)
    else:
        blog = get_object_or_404(Blog, user=request.user, subdomain=id)

    error_messages = []
    success_message = ""
    
    # Get template data
    current_template = blog.post_template

    if request.method == "POST":
        header_content = request.POST.get("header_content", "")
        body_content = request.POST.get("body_content", "")
        action = request.POST.get("action", "")
        
        # Combine header and body content
        if header_content and body_content:
            template_content = header_content + "\n___\n" + body_content
        elif header_content:
            template_content = header_content
        elif body_content:
            template_content = body_content
        else:
            template_content = ""

        if action == "save_template":
            # Save template to blog.post_template and create/update template draft post
            was_existing = bool(blog.post_template)
            blog.post_template = template_content
            blog.save()
            
            # Create or update template draft post for preview
            template_draft = _create_or_update_template_draft(blog, header_content, body_content)
            
            # Handle AJAX requests for preview functionality
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                preview_url = f"{blog.dynamic_useful_domain}/{template_draft.slug}?token={template_draft.token}"
                return JsonResponse({
                    'success': True,
                    'message': 'Template updated' if was_existing else 'Template saved',
                    'preview_url': preview_url
                })
            
            success_message = "Template updated" if was_existing else "Template saved"
            current_template = blog.post_template
            
        elif action == "delete_template":
            # Delete template and template draft post
            blog.post_template = ""
            blog.save()
            
            # Delete template draft post
            Post.objects.filter(blog=blog, is_template_draft=True).delete()
            
            success_message = "Template deleted"
            current_template = ""

    # Split template content for display
    template_header = ""
    template_body = ""
    template_data = {}
    
    if current_template:
        if '___' in current_template:
            template_parts = current_template.split('___', 1)
            template_header = template_parts[0].strip()
            template_body = template_parts[1].strip()
        else:
            template_header = current_template.strip()
            
        # Parse template header to extract individual field values
        if template_header:
            for line in template_header.split('\n'):
                if ':' in line:
                    # Strip HTML tags from the line
                    clean_line = re.sub(r'<[^>]+>', '', line)
                    key, value = clean_line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    template_data[key] = value

    # Get popular tags and tools for suggestions
    popular_tags, popular_tools = get_popular_tags_and_tools(10)
    
    # Get template draft for preview URL (if it exists)
    template_draft = None
    if blog.post_template:
        try:
            template_draft = Post.objects.get(blog=blog, is_template_draft=True)
        except Post.DoesNotExist:
            pass

    return render(request, 'studio/post_template_edit.html', {
        'blog': blog,
        'template_header': template_header,
        'template_body': template_body,
        'template_data': template_data,
        'popular_tags': popular_tags,
        'popular_tools': popular_tools,
        'error_messages': error_messages,
        'success_message': success_message,
        'template_draft': template_draft,
    })


@login_required
def custom_domain_edit(request, id):
    if request.user.is_superuser:
        blog = get_object_or_404(Blog, subdomain=id)
    else:
        blog = get_object_or_404(Blog, user=request.user, subdomain=id)

    if not blog.user.settings.upgraded:
        return redirect('upgrade')

    error_messages = []

    if request.method == "POST":
        custom_domain = request.POST.get("custom-domain", "").lower().strip().replace('https://', '').replace('http://', '')

        if Blog.objects.filter(domain__iexact=custom_domain).exclude(pk=blog.pk).count() == 0:
            try:
                validator = URLValidator()
                validator('http://' + custom_domain)
                blog.domain = custom_domain
                blog.save()
            except ValidationError:
                error_messages.append(f'{custom_domain} is an invalid domain')
                print("error")
        elif not custom_domain:
            blog.domain = ''
            blog.save()
        else:
            error_messages.append(f"{custom_domain} is already registered with another blog")

    # If records not set correctly
    if blog.domain and not check_connection(blog):
        error_messages.append(f"The DNS records for { blog.domain } have not been set.")

    return render(request, 'studio/custom_domain_edit.html', {
        'blog': blog,
        'error_messages': error_messages
    })


@login_required
def directive_edit(request, id):
    if request.user.is_superuser:
        blog = get_object_or_404(Blog, subdomain=id)
    else:
        blog = get_object_or_404(Blog, user=request.user, subdomain=id)

    if not blog.user.settings.upgraded:
        return redirect('upgrade')

    header = request.POST.get("header", "")
    footer = request.POST.get("footer", "")

    if request.method == "POST":
        blog.header_directive = header
        blog.footer_directive = footer
        blog.save()

    return render(request, 'studio/directive_edit.html', {
        'blog': blog
    })


@login_required
def advanced_settings(request, id):
    if request.user.is_superuser:
        blog = get_object_or_404(Blog, subdomain=id)
    else:
        blog = get_object_or_404(Blog, user=request.user, subdomain=id)

    if request.method == "POST":
        form = AdvancedSettingsForm(request.POST, instance=blog)
        if form.is_valid():
            blog_info = form.save(commit=False)
            blog_info.save()
    else:
        form = AdvancedSettingsForm(instance=blog)

    return render(request, 'dashboard/advanced_settings.html', {
        'blog': blog,
        'form': form
    })


@login_required
def dashboard_customisation(request):
    if request.method == "POST":
        form = DashboardCustomisationForm(request.POST, instance=request.user.settings)
        if form.is_valid():
            user_settings = form.save(commit=False)
            user_settings.save()
    else:
        form = DashboardCustomisationForm(instance=request.user.settings)

    return render(request, 'dashboard/dashboard_customisation.html', {
        'form': form
    })