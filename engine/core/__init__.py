"""Market Bias Platform — core package."""

# Global SSL certificate handling for Windows environments (proxies / security filters)
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass
try:
    from curl_cffi import requests as c_requests
    _orig_cffi_init = c_requests.Session.__init__
    def _safe_cffi_init(self, *args, **kwargs):
        kwargs.setdefault("verify", False)
        _orig_cffi_init(self, *args, **kwargs)
    c_requests.Session.__init__ = _safe_cffi_init
except ImportError:
    pass

try:
    import requests
    _orig_req_init = requests.Session.__init__
    def _safe_req_init(self, *args, **kwargs):
        _orig_req_init(self, *args, **kwargs)
        self.verify = False
    requests.Session.__init__ = _safe_req_init
except ImportError:
    pass

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
