from django.shortcuts import render
from django.http import Http404
import os


def docs_site_only(view_func):
    """Decorator to ensure only docs subdomain can access docs views"""
    def _wrapped_view(request, *args, **kwargs):
        host = request.get_host()
        # Allow docs.lh.co for local development and docs.vibera.dev for production
        if host not in ['docs.lh.co', 'docs.vibera.dev']:
            raise Http404("Docs only available on docs subdomain")
        return view_func(request, *args, **kwargs)
    return _wrapped_view


@docs_site_only
def privacy_policy(request):
    """Privacy Policy page"""
    return render(request, 'docs/privacy_policy.html')


@docs_site_only
def terms_of_service(request):
    """Terms of Service page"""
    return render(request, 'docs/terms_of_service.html')


@docs_site_only
def documentation(request):
    """Main documentation page"""
    return render(request, 'docs/documentation.html')


@docs_site_only
def roadmap(request):
    """Roadmap page"""
    return render(request, 'docs/roadmap.html')


@docs_site_only
def changelog(request):
    """Changelog page"""
    return render(request, 'docs/changelog.html')


@docs_site_only
def custom_domains(request):
    """Custom domains page"""
    return render(request, 'docs/custom_domains.html')


@docs_site_only
def rss_atom_feeds(request):
    """RSS and Atom feeds page"""
    return render(request, 'docs/rss_atom_feeds.html')


@docs_site_only
def analytics_docs(request):
    """Analytics documentation page"""
    return render(request, 'docs/analytics.html')


@docs_site_only
def email_newsletters(request):
    """Email newsletters documentation page"""
    return render(request, 'docs/email_newsletters.html')


@docs_site_only
def anatomy_home_page(request):
    """Anatomy of the home page documentation"""
    return render(request, 'docs/anatomy_home_page.html')


@docs_site_only
def home(request):
    """Docs homepage - redirects to main docs"""
    return documentation(request)