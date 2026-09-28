from pathlib import Path
from datetime import timedelta
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'storages',
    'accounts',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'midrus.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'midrus.wsgi.application'

# ─── Database ────────────────────────────────────────────────────────────────
# Set DB_ENGINE=postgresql in .env for production; defaults to SQLite for dev.
if config('DB_ENGINE', default='sqlite3') == 'postgresql':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME':     config('DB_NAME'),
            'USER':     config('DB_USER'),
            'PASSWORD': config('DB_PASSWORD'),
            'HOST':     config('DB_HOST', default='localhost'),
            'PORT':     config('DB_PORT', default='5432'),
            'CONN_MAX_AGE': 60,
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
            'OPTIONS': {'timeout': 20},  # wait up to 20s for write lock instead of failing instantly
        }
    }

AUTH_USER_MODEL = 'accounts.User'

# ─── REST Framework ───────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',  # lets Django admin AJAX calls authenticate
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/hour',
        'user': '5000/day',
        'auth': '10/hour',      # stricter limit for login / register / OTP
        'contact': '10/hour',   # public contact form
        'files': '300/hour',    # signed file downloads
        'account': '5/hour',    # sensitive account actions (deletion)
    },
    # Number of reverse proxies in front of Django (nginx = 1). Without this
    # every request appears to come from the proxy's IP, so *all* users would
    # share one throttle bucket (e.g. 10 logins per hour for the whole site).
    # Set NUM_PROXIES=0 if gunicorn is exposed directly.
    'NUM_PROXIES': config('NUM_PROXIES', default=1, cast=int),
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME':  timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS':  True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

# ─── Cache ───────────────────────────────────────────────────────────────────
# Database-backed so every gunicorn worker (and restart) sees the same throttle
# counters and OTP attempt counts. Migration accounts.0015 creates the table, so
# a normal `manage.py migrate` is enough. The backend fails open (and logs an
# error) if the table is ever missing, rather than returning 500 on every login.
CACHES = {
    'default': {
        'BACKEND': 'accounts.cache.ResilientDatabaseCache',
        'LOCATION': 'django_cache',
    }
}

# ─── CORS ────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:3000,http://127.0.0.1:3000',
    cast=Csv(),
)
CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = config(
    'CSRF_TRUSTED_ORIGINS',
    default='http://localhost:8000',
    cast=Csv(),
)

# ─── Security headers ────────────────────────────────────────────────────────
# Always-on headers (safe even without HTTPS)
SECURE_CONTENT_TYPE_NOSNIFF = True
# SAMEORIGIN (not DENY) because the admin document viewer embeds files in an iframe.
X_FRAME_OPTIONS = 'SAMEORIGIN'

# Activated when Django is behind nginx that terminates SSL
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Enable SECURE_SSL_REDIRECT only if nginx is NOT handling the redirect
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=False, cast=bool)

SESSION_COOKIE_SECURE   = config('SESSION_COOKIE_SECURE',   default=not DEBUG, cast=bool)
CSRF_COOKIE_SECURE      = config('CSRF_COOKIE_SECURE',      default=not DEBUG, cast=bool)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY    = True

# HSTS — set SECURE_HSTS_SECONDS=31536000 in .env once the site is stable on HTTPS
SECURE_HSTS_SECONDS             = config('SECURE_HSTS_SECONDS', default=0, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS  = True
SECURE_HSTS_PRELOAD             = True

# ─── Internationalisation ────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

# ─── Static & media files ────────────────────────────────────────────────────
STATIC_URL  = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Client-uploaded documents and generated invoice PDFs live in Cloudflare R2
# (an S3-compatible bucket) rather than on local disk, so they survive
# deploys/restarts and don't fill up the app server. Falls back to local
# FileSystemStorage when R2 isn't configured (e.g. running tests locally).
R2_BUCKET_NAME       = config('R2_BUCKET_NAME', default='')
R2_ACCESS_KEY_ID     = config('R2_ACCESS_KEY_ID', default='')
R2_SECRET_ACCESS_KEY = config('R2_SECRET_ACCESS_KEY', default='')
R2_ACCOUNT_ID        = config('R2_ACCOUNT_ID', default='')
R2_ENDPOINT_URL      = config(
    'R2_ENDPOINT_URL',
    default=f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com' if R2_ACCOUNT_ID else '',
)
USE_R2_STORAGE = bool(R2_BUCKET_NAME and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_ENDPOINT_URL)

if USE_R2_STORAGE:
    STORAGES = {
        'default': {'BACKEND': 'storages.backends.s3.S3Storage'},
        'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
    }
    AWS_ACCESS_KEY_ID        = R2_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY    = R2_SECRET_ACCESS_KEY
    AWS_STORAGE_BUCKET_NAME  = R2_BUCKET_NAME
    AWS_S3_ENDPOINT_URL      = R2_ENDPOINT_URL
    AWS_S3_REGION_NAME       = 'auto'
    AWS_S3_ADDRESSING_STYLE  = 'path'
    AWS_S3_SIGNATURE_VERSION = 's3v4'
    AWS_DEFAULT_ACL          = None  # R2 has no ACL concept; the bucket is private by default
    AWS_QUERYSTRING_AUTH     = False  # files are never linked to directly (see accounts/files.py)
    AWS_S3_FILE_OVERWRITE    = False
    AWS_S3_VERIFY            = True
else:
    STORAGES = {
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        # Compressed but not manifest-hashed, so a missed `collectstatic` degrades
        # gracefully instead of turning every admin page into a 500.
        'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
    }

MEDIA_URL  = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
# Client documents are private. Do NOT expose /media/ (or the R2 bucket)
# directly; files are delivered via signed links (see accounts/files.py) that
# expire after this.
FILE_URL_TTL_SECONDS = config('FILE_URL_TTL_SECONDS', default=3600, cast=int)

# ─── Legal ───────────────────────────────────────────────────────────────────
# Bump when the Terms / Privacy Policy change; stored with each acceptance.
TERMS_VERSION = '2026-09-21'
# Reject sign-ups that don't send accepted_terms=true. Off by default so
# clients that predate the consent checkbox (e.g. the web frontend) keep
# working; switch on once every sign-up form asks for consent.
REQUIRE_TERMS_ACCEPTANCE = config('REQUIRE_TERMS_ACCEPTANCE', default=False, cast=bool)

# ─── One-time codes ──────────────────────────────────────────────────────────
OTP_TTL_SECONDS  = 600   # a code is valid for 10 minutes
OTP_MAX_ATTEMPTS = config('OTP_MAX_ATTEMPTS', default=5, cast=int)

# ─── Email / SMTP ────────────────────────────────────────────────────────────
EMAIL_BACKEND     = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST        = config('EMAIL_HOST',         default='smtp.gmail.com')
EMAIL_PORT        = config('EMAIL_PORT',         default=587, cast=int)
# Exactly one of these should be True: TLS is STARTTLS on a plaintext
# connection (port 587), SSL is implicit-TLS from the first byte (port 465).
# Mixing the wrong pair for the port (e.g. EMAIL_USE_TLS with port 465) makes
# the server drop the connection immediately (SMTPServerDisconnected) rather
# than give a useful error.
EMAIL_USE_TLS     = config('EMAIL_USE_TLS',      default=True, cast=bool)
EMAIL_USE_SSL     = config('EMAIL_USE_SSL',      default=False, cast=bool)
EMAIL_HOST_USER   = config('EMAIL_HOST_USER',    default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL  = config('DEFAULT_FROM_EMAIL',  default='MIDRUS <noreply@midrus.com>')
ADMIN_EMAIL         = config('ADMIN_EMAIL',         default='')   # receives new-signup notifications
FRONTEND_URL        = config('FRONTEND_URL',        default='http://localhost:3000')
BACKEND_URL         = config('BACKEND_URL',         default='http://localhost:8000')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ─── Logging ─────────────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {'format': '{levelname} {asctime} {module} {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'verbose'},
    },
    'root': {'level': 'INFO', 'handlers': ['console']},
    'loggers': {
        'django': {'level': 'WARNING', 'handlers': ['console'], 'propagate': False},
        'django.request': {'level': 'ERROR', 'handlers': ['console'], 'propagate': False},
        'accounts': {'level': 'INFO', 'handlers': ['console'], 'propagate': False},
    },
}

# ─── Push notifications ──────────────────────────────────────────────────────
# Dotted path of a class in the style of accounts.push.PushBackend. The default
# only logs, so nothing is sent until a real backend (e.g. Firebase) is added.
PUSH_BACKEND = config('PUSH_BACKEND', default='accounts.push.LoggingPushBackend')
