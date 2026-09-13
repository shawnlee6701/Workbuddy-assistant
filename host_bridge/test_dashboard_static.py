import os
import unittest


WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DASHBOARD_FILE = os.path.join(WORKSPACE_DIR, "bridge_dashboard.html")


class DashboardStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DASHBOARD_FILE, "r", encoding="utf-8") as handle:
            cls.html = handle.read()

    def test_file_mode_targets_local_bridge_api(self):
        self.assertIn("window.location.protocol === 'file:'", self.html)
        self.assertIn("'http://127.0.0.1:5200/api/bridge'", self.html)

    def test_dashboard_fetch_uses_resolved_api_url(self):
        self.assertIn("fetch(BRIDGE_API_URL", self.html)
        self.assertNotIn("fetch('/api/bridge'", self.html)


if __name__ == "__main__":
    unittest.main()
