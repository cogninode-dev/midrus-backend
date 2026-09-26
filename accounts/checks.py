"""Deploy-time sanity checks, shown by `manage.py check` / `migrate` and in the
server log at startup, so a missing dependency is noticed before a customer
taps Download."""
import importlib.util

from django.core.checks import Warning, register


@register()
def pdf_engine_installed(app_configs, **kwargs):
    """Invoice PDFs are generated with xhtml2pdf. If it is missing every
    invoice download fails with a 503, so say so loudly."""
    if importlib.util.find_spec('xhtml2pdf') is not None:
        return []
    return [Warning(
        'xhtml2pdf is not installed, so invoice PDFs cannot be generated.',
        hint='Run: pip install -r requirements.txt  (then restart the server).',
        id='accounts.W001',
    )]
