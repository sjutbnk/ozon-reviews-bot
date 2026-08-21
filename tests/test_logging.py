import logging
import subprocess
import sys
import unittest


class LoggingTests(unittest.TestCase):
    def test_httpx_logs_do_not_expose_request_urls_at_info_level(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import logging; import main; print(logging.getLogger('httpx').getEffectiveLevel())",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertGreaterEqual(int(result.stdout), logging.WARNING)


if __name__ == "__main__":
    unittest.main()
