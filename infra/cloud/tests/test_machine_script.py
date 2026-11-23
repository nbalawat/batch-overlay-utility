"""The machine's own `batchiq` command (infra/modules/common/machine-bootstrap/files/batchiq.sh), run locally with
systemctl and shutdown replaced by recorders, so every subcommand that does not need Docker is exercised."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "modules" / "common" / "machine-bootstrap" / "files" / "batchiq.sh"


class MachineScriptTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.conf = self.tmp / "machine.env"
        self.conf.write_text("GIT_REF=main\nAUTO_STOP_HOURS=10\n")
        self.src = self.tmp / "src"
        self.src.mkdir()
        self.log = self.tmp / "calls"
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for tool in ("systemctl", "shutdown"):
            stub = bin_dir / tool
            body = f'echo "{tool} $*" >> "{self.log}"'
            stub.write_text(f"#!/usr/bin/env bash\n{body}\n")
            stub.chmod(0o755)
        self.env = dict(os.environ, BATCHIQ_CONF=str(self.conf), BATCHIQ_SRC=str(self.src),
                        PATH=f"{bin_dir}:{os.environ['PATH']}", SYSTEMCTL="systemctl", SHUTDOWN="shutdown", BATCHIQ_SKIP_ROOT="1")

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, *args, check=True):
        result = subprocess.run(["bash", str(SCRIPT), *args], env=self.env, text=True, capture_output=True, timeout=30)
        if check and result.returncode != 0:
            self.fail(f"batchiq {' '.join(args)} failed: {result.stderr}")
        return result

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_help_lists_the_commands(self):
        out = self.run_script("help").stdout
        for word in ("status", "wait", "logs", "restart", "update", "env", "extend", "reset"):
            self.assertIn(f"batchiq {word}", out)

    def test_extend_reschedules_the_stop(self):
        out = self.run_script("extend", "3").stdout
        self.assertIn("stops itself in 3h", out)
        self.assertIn("shutdown -c", self.calls())
        self.assertTrue(any(c.startswith("shutdown -h +180 ") for c in self.calls()))

    def test_extend_zero_turns_it_off(self):
        self.assertIn("automatic stop is off", self.run_script("extend", "0").stdout)
        self.assertFalse(any(c.startswith("shutdown -h") for c in self.calls()))

    def test_extend_refuses_nonsense(self):
        self.assertNotEqual(self.run_script("extend", "soon", check=False).returncode, 0)

    def test_env_sets_and_replaces_values_privately(self):
        self.run_script("env", "ANTHROPIC_API_KEY=one")
        self.run_script("env", "OTHER=x")
        self.run_script("env", "ANTHROPIC_API_KEY=two")
        env_file = self.src / ".env"
        self.assertEqual(sorted(env_file.read_text().splitlines()), ["ANTHROPIC_API_KEY=two", "OTHER=x"])
        self.assertEqual(oct(env_file.stat().st_mode & 0o777), "0o600")
        self.assertNotEqual(self.run_script("env", "bad key=1", check=False).returncode, 0)

    def test_reset_needs_yes(self):
        result = self.run_script("reset", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reset --yes", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_escalation_cannot_loop(self):
        env = dict(self.env, BATCHIQ_SKIP_ROOT="0", BATCHIQ_ESCALATED="1")
        if os.getuid() == 0:
            self.skipTest("running as root: nothing to escalate")
        result = subprocess.run(["bash", str(SCRIPT), "extend", "1"], env=env, text=True, capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sudo did not provide it", result.stderr)

    def _stub(self, tool, body):
        stub = self.tmp / "bin" / tool
        stub.write_text(f"#!/usr/bin/env bash\n{body}\n")
        stub.chmod(0o755)

    def test_run_is_docker_compose_in_the_checkout(self):
        self._stub("docker", f'echo "docker $* in $PWD" >> "{self.log}"')
        self.run_script("run")
        self.assertEqual(self.calls(), [f"docker compose up --build --remove-orphans in {self.src}"])

    def test_wait_returns_once_the_console_answers(self):
        self._stub("curl", f'echo "curl $*" >> "{self.log}"; exit 0')
        self.assertIn("ready", self.run_script("wait", "1").stdout)
        self.assertTrue(any("http://localhost:8080/api/meta" in c for c in self.calls()))

    def test_wait_gives_up_after_its_deadline(self):
        self._stub("curl", "exit 7")
        result = self.run_script("wait", "0", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not answer", result.stderr)

    def test_status_says_whether_claude_is_configured(self):
        self._stub("curl", "exit 7")
        self._stub("docker", "exit 0")
        self.assertIn("offline rules", self.run_script("status").stdout)
        self.run_script("env", "ANTHROPIC_API_KEY=sk-test")
        out = self.run_script("status").stdout
        self.assertIn("ANTHROPIC_API_KEY is set", out)
        self.assertNotIn("sk-test", out, "the key itself is never printed")

    def test_update_refuses_odd_refs(self):
        result = self.run_script("update", "main;rm -rf /", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a branch", result.stderr)

    def test_update_installs_this_command_from_the_new_source(self):
        files = self.src / "infra" / "modules" / "common" / "machine-bootstrap" / "files"
        files.mkdir(parents=True)
        (files / "batchiq.sh").write_text("#!/usr/bin/env bash\necho new\n")
        self._stub("git", 'case "$*" in *"rev-parse --verify"*) exit 0 ;; *rev-parse*) echo abc123 ;; esac')
        (self.src / ".git").mkdir()
        import getpass
        with self.conf.open("a") as f:
            f.write(f"OWNER={getpass.getuser()}\n")
        target = self.tmp / "installed-batchiq"
        self.env["BATCHIQ_BIN"] = str(target)
        self.run_script("update", "main")
        self.assertEqual(target.read_text(), "#!/usr/bin/env bash\necho new\n")
        self.assertIn("systemctl restart batchiq.service", self.calls())

    def test_unknown_command(self):
        self.assertNotEqual(self.run_script("explode", check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
