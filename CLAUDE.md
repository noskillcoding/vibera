# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Vision: Vibera

Vibera is a fork of the Bearblog platform, transforming it from a blogging platform into a **project showcase platform for developers**. Instead of blog posts, users upload and showcase their "vibecoded" projects (coding projects) with descriptions, screenshots, GitHub links, and tags. Personal pages become project portfolios rather than traditional blogs.

**Key Transformation:**
- **From**: Blog posts with Markdown content → **To**: Project showcases with descriptions, images, and GitHub links
- **From**: Personal blogs → **To**: Developer project portfolios  
- **From**: Writing platform → **To**: Developer showcase platform
- **Think**: Like a hybrid of GitHub's project showcase + Dribbble for developers + personal portfolio sites

The existing Bearblog architecture provides the perfect foundation: multi-tenancy, custom domains, discovery feeds, tagging, and user management - but repurposed for project showcasing instead of blogging.

## Development Commands

### Local Development
- `make dev`: Start development server on port 80 at http://lh.co
- `make migrate`: Run database migrations
- `make makemigrations`: Create new database migrations
- `python manage.py runserver 0:80`: Alternative way to start dev server

### Database Management
- Uses SQLite for local development (`dev.db`)
- Uses PostgreSQL in production via `DATABASE_URL` environment variable
- Run `python manage.py migrate` after pulling schema changes

### Django Management Commands
- `python manage.py invalidate_cache`: Invalidates Cloudflare cache for recently published posts
- `python manage.py shell`: Access Django shell
- `python manage.py collectstatic`: Collect static files for production

## Architecture Overview

### Core Concept
Vibera (formerly Bear Blog) is a multi-tenant blogging platform where each blog gets its own subdomain (e.g., `username.bearblog.dev`) or custom domain. The system routes requests based on the Host header to serve the appropriate blog content.

### Django Apps Structure
- **blogs/**: Main application containing all blog functionality
  - Models: `Blog`, `Post`, `UserSettings`, `Upvote`, `Hit`, `Subscriber`, `Media`, `Stylesheet`, `PersistentStore`
  - Views organized in modules: `blog.py`, `dashboard.py`, `studio.py`, `analytics.py`, `discover.py`, `feed.py`, `emailer.py`, `staff.py`, `media.py`, `signup_flow.py`
- **conf/**: Django project configuration

### Database Models
- **Blog**: Core blog entity with subdomain, custom domain support, styling, and content
- **Post**: Blog posts with Markdown content, tags, upvoting, and discovery features
- **UserSettings**: User preferences including upgrade status and dashboard customization
- **Hit/Upvote**: Analytics and engagement tracking
- **Media**: Image uploads stored on Digital Ocean Spaces
- **PersistentStore**: Singleton for platform-wide settings and moderation terms

### Multi-tenancy & Routing
- Primary routing via `main_site_only` decorator that checks host against `MAIN_SITE_HOSTS`
- Main site (`bearblog.dev`) serves landing, discover, dashboard, and admin features
- Blog subdomains/custom domains serve individual blog content
- Custom domains verified via TXT records or meta tag validation

### Key Features
- **Markdown-based content**: Posts written in Markdown with syntax highlighting
- **Custom styling**: Each blog can override default CSS
- **Analytics**: Built-in page view and upvote tracking with GeoIP
- **Discovery feed**: Platform-wide post discovery with scoring algorithm
- **Email subscriptions**: Built-in newsletter functionality
- **Media management**: Image upload and optimization
- **Custom domains**: Users can connect their own domains
- **Moderation system**: Staff review process with dodginess scoring

### Middleware Stack
- **RateLimitMiddleware**: 60 requests per 60 seconds per IP
- **ConditionalXFrameOptionsMiddleware**: Prevents clickjacking on main domains
- **AllowAnyDomainCsrfMiddleware**: Custom CSRF handling for multi-domain setup
- **RequestPerformanceMiddleware**: Tracks request timing and database query performance

### Static Files & Templates
- Templates use Django template inheritance with `base.html`
- CSS styling system with default themes and custom overrides
- Static files served via WhiteNoise with compression
- Pygments integration for code syntax highlighting

### Environment Configuration
- Uses `python-dotenv` for local environment variables
- Production settings via environment variables
- Sentry integration for error tracking
- Redis for performance metrics (optional, falls back to in-memory)
- Mailgun for email delivery

### Content Management
- Posts support Markdown with LaTeX math rendering
- Tag system with automatic tag aggregation
- Post templates for consistent formatting
- RSS/Atom feed generation
- Sitemap generation

### Security & Performance
- CSRF protection adapted for multiple domains
- Rate limiting on all endpoints
- Cloudflare integration for caching and DNS
- Image optimization and CDN delivery
- Performance monitoring and metrics collection

## Development Workflow

### Making Changes
1. Always run migrations after model changes: `make migrate`
2. Test locally at http://lh.co (requires `/etc/hosts` entry)
3. Static files auto-collected in development
4. Use Django admin at `/mothership/` for data management

### Database Changes
- Create migrations: `make makemigrations`
- Apply migrations: `make migrate`
- Models include automatic cache invalidation and scoring updates

### Custom Domain Testing
- Set up local DNS or hosts file entries
- Test subdomain routing with different Host headers
- Verify custom domain validation logic

### Performance Testing
- Monitor via `/staff/dashboard/performance/` (staff only)
- Check request metrics and database query times
- Use rate limiting bypass for testing if needed

## Vibera Transformation Status

### ✅ Completed Tasks
8. **Disable paywall** - ✅ All pro features are free (users upgraded by default)
9. **Add Tags section** - ✅ UI form field with popular suggestions based on usage
10. **Add Tools section** - ✅ UI form field with popular suggestions based on usage  
11. **Add GitHub link section** - ✅ Dedicated URL input field for repository links
12. **Enable comments by default** - ✅ Comments enabled by default with toggle option
14. **Enable media/image uploads** - ✅ Enhanced media system with visual previews

### 🔧 Enhanced Features Implemented
- **Project-focused post creation** - Smaller content textarea for project descriptions
- **Visual media management** - Image/video preview thumbnails with click-to-insert
- **Comprehensive file support** - Images (png, jpg, jpeg, tiff, bmp, gif, svg, webp, avif, ico, heic) + Videos (mp4, webm, mkv)
- **Per-post media limits** - Up to 15 files per post with 10MB per file limit
- **Popular suggestions system** - Shows top tags/tools based on platform usage
- **Persistent draft saving** - All form data (tags, tools, media, etc.) preserved when saving drafts
- **Clean UI/UX** - Removed confusing attributes section, proper form validation

### 🚧 Remaining Tasks
13. **Add downvote/report functionality** with explanation
15. **Upgrade search** with Tags and Tools filter sections  
16. **Update branding** from Bearblog to Vibera

### 🗄️ Database Schema Updates
- `Post.all_tools` (JSONField) - Stores tools used in project
- `Post.github_url` (CharField) - Repository URL
- `Post.comments_enabled` (BooleanField) - Comment toggle (default: True)
- `Post.media_urls` (JSONField) - Tracks uploaded media per post
- `Blog.all_tools` (JSONField) - Aggregated tools across blog posts