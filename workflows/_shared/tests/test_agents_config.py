import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agents_config  # noqa: E402


class TempAgentsHome:
    """Point agents_config at a scratch dir and restore os.environ after."""

    def __init__(self, tmpdir, env_text=None, config_text=None):
        self.tmpdir = Path(tmpdir)
        self.env_text = env_text
        self.config_text = config_text

    def __enter__(self):
        self._saved = dict(os.environ)
        os.environ["AGENTS_HOME"] = str(self.tmpdir)
        if self.env_text is not None:
            (self.tmpdir / ".env").write_text(self.env_text, encoding="utf-8")
        if self.config_text is not None:
            (self.tmpdir / ".config").write_text(self.config_text, encoding="utf-8")
        return self

    def __exit__(self, *exc):
        os.environ.clear()
        os.environ.update(self._saved)
        return False


class ParseFileTests(unittest.TestCase):
    def parse(self, text):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "f"
            p.write_text(text, encoding="utf-8")
            return agents_config.parse_file(p)

    def test_basic_assignment(self):
        self.assertEqual(self.parse("A=1\nB=two\n"), {"A": "1", "B": "two"})

    def test_comments_and_blank_lines_ignored(self):
        text = "# a comment\n\n   \nA=1\n#B=2\n"
        self.assertEqual(self.parse(text), {"A": "1"})

    def test_matched_quotes_stripped(self):
        parsed = self.parse("A=\"quoted\"\nB='single'\nC=\"mixed'\n")
        self.assertEqual(parsed["A"], "quoted")
        self.assertEqual(parsed["B"], "single")
        self.assertEqual(parsed["C"], "\"mixed'")

    def test_value_may_contain_equals(self):
        self.assertEqual(self.parse("URL=https://x/y?a=b\n")["URL"], "https://x/y?a=b")

    def test_empty_value_allowed(self):
        self.assertEqual(self.parse("A=\n"), {"A": ""})

    def test_lines_without_equals_ignored(self):
        self.assertEqual(self.parse("garbage\nA=1\n"), {"A": "1"})

    def test_export_prefix_rejected(self):
        # `export FOO=bar` is outside the supported subset -- systemd rejects
        # it too. It must be skipped, never stored as a key named "export FOO".
        self.assertEqual(self.parse("export B=2\nA=1\n"), {"A": "1"})

    def test_non_identifier_keys_rejected(self):
        self.assertEqual(self.parse("a-b=1\n1ABC=2\nA B=3\nOK=4\n"), {"OK": "4"})

    def test_surrounding_whitespace_trimmed(self):
        self.assertEqual(self.parse("  A  =  1  \n"), {"A": "1"})

    def test_missing_file_returns_empty(self):
        self.assertEqual(agents_config.parse_file("/nonexistent/nope/.env"), {})

    def test_directory_instead_of_file_returns_empty(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(agents_config.parse_file(d), {})


class PrecedenceTests(unittest.TestCase):
    def test_env_file_beats_config_file(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            with TempAgentsHome(d, env_text="K=from_env\n", config_text="K=from_config\n"):
                self.assertEqual(agents_config.read_files()["K"], "from_env")

    def test_real_environment_beats_both_files(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            with TempAgentsHome(d, env_text="K=from_env\n", config_text="K=from_config\n"):
                os.environ["K"] = "from_shell"
                agents_config.load(force=True)
                self.assertEqual(os.environ["K"], "from_shell")

    def test_load_fills_unset_names(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            with TempAgentsHome(d, env_text="ONLY_IN_ENV=yes\n", config_text="ONLY_IN_CFG=also\n"):
                os.environ.pop("ONLY_IN_ENV", None)
                os.environ.pop("ONLY_IN_CFG", None)
                agents_config.load(force=True)
                self.assertEqual(os.environ["ONLY_IN_ENV"], "yes")
                self.assertEqual(os.environ["ONLY_IN_CFG"], "also")

    def test_missing_files_are_tolerated(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            with TempAgentsHome(d):
                self.assertEqual(agents_config.read_files(), {})


class CredentialsDirTests(unittest.TestCase):
    def test_defaults_under_agents_home(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            with TempAgentsHome(d):
                os.environ.pop("GOOGLE_CREDENTIALS_DIR", None)
                self.assertEqual(
                    agents_config.google_credentials_dir(), Path(d) / "credentials"
                )

    def test_explicit_value_wins(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            with TempAgentsHome(d):
                os.environ["GOOGLE_CREDENTIALS_DIR"] = "/tmp/creds"
                self.assertEqual(
                    agents_config.google_credentials_dir(), Path("/tmp/creds")
                )

    def test_blank_value_falls_back_to_default(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            with TempAgentsHome(d):
                os.environ["GOOGLE_CREDENTIALS_DIR"] = "   "
                self.assertEqual(
                    agents_config.google_credentials_dir(), Path(d) / "credentials"
                )


if __name__ == "__main__":
    unittest.main()
