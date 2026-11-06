import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="codingapp-test-")
os.environ["DATA_DIR"] = _tmp
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test-pass"
os.environ["SECRET_KEY"] = "test-secret-key-for-unit-tests-only-123456"
os.environ["LLM_BASE_URL"] = "http://127.0.0.1:9/v1"  # unreachable on purpose
os.environ["LLM_CONTEXT_TOKENS"] = "8192"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
