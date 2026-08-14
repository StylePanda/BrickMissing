from django.test import override_settings
from django.test.runner import DiscoverRunner


class ProductionSettingsDiscoverRunner(DiscoverRunner):
    """Run application tests without converting every test-client request to HTTPS.

    Production still enforces ``SECURE_SSL_REDIRECT``. The Django test client models
    an in-process request rather than the Nginx TLS boundary, so redirect middleware
    must not intercept the views under test.
    """

    def setup_test_environment(self, **kwargs):
        self._transport_override = override_settings(SECURE_SSL_REDIRECT=False)
        self._transport_override.enable()
        try:
            return super().setup_test_environment(**kwargs)
        except BaseException:
            self._transport_override.disable()
            raise

    def teardown_test_environment(self, **kwargs):
        try:
            return super().teardown_test_environment(**kwargs)
        finally:
            self._transport_override.disable()
