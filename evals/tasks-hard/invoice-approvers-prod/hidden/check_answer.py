"""Checks answer.txt names exactly the right users, and that the project was left alone."""

import hashlib
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent

EXPECTED = {"ahoffmann", "dlopez", "hkrueger", "ngarcia", "pschmidt", "tbauer"}

# SHA-256 of every file the task started with, with CRLF read as LF so checkouts on any OS match.
UNCHANGED = {
    "README.md": "cd1a034e010790b7933244b71aecdff08bd2d85ed8514d244a42cd56f51d5001",
    "config/base.toml": "aa27420da7128735aaeaba3417918f2c97ca0fa9ea9110e0ec8e60bc78f354af",
    "config/dev.toml": "85ff916ae84fdace2183b91e1d3ef946195dfd269cad24e4586d82a89eef791d",
    "config/local.toml": "c349b04d0c96cf6e94edcc394fe08cabfcb0e9da685d5b75a05005a83a810e73",
    "config/prod.toml": "28f8848ea3de3f2dc31705abdd4d1248460074fe915a4108625de2263f5f2242",
    "data/absences.json": "26ceb611a31674ed4a615be07d56e38a4366ea13ade78f57be1defe91ae81b79",
    "data/delegations.json": "55f57e7166ff2c3ef56ad3cb19a42a257f1bdc53dbef5addf09985f0ff454ef1",
    "data/directory.json": "ddb9ea078e4be37e221445f92b9576aeb3d5756d43e6355bf2061fcc601ebba2",
    "data/invoices.json": "d67254f8bea2baa04a2568ac11d37093599754dd41bc8531c61e66b5bd3f8a86",
    "data/rates.json": "4939612b09e0390316135568f5307223c21b42f5c49fb5cf57521b630da533a6",
    "ledgerdesk/__init__.py": "a8cae218be7ca73d7fe985dfcc8badc3801d99a9ebd422772957fde14f02eb59",
    "ledgerdesk/__main__.py": "ea90799aaaab076e9ef7cc9b7f4b43052b208da51dde6b60319079bbd1e5d12a",
    "ledgerdesk/cli.py": "351a8856afa6d3d8047f914754e552abdc6427c4a3006d92cf29700ffca46a8c",
    "ledgerdesk/clock.py": "3d84ccc62146252395cc429a5e050be73f45941afee2767522522f35a3d5ce14",
    "ledgerdesk/config/__init__.py": "9fb37e5a40dd3108bfc13835862eb5087e19538ced90a23b2d48eb09af2f48da",
    "ledgerdesk/config/loader.py": "f2707d9941b0d68f13ef1d191f5515a95ec70e63b2a4a661abb35953434c97b3",
    "ledgerdesk/context.py": "8e4e5b5d031eed7f8d1783eddfb6523f54bd76d85c0ab329b80cecb79d70dea6",
    "ledgerdesk/directory.py": "b219555db30e0bbce89793ce7ff925e1a0258dbb58c4c92b54ce9ae0b586601c",
    "ledgerdesk/invoices.py": "264026f1e10553db12611a8eb26ee400a268aa7f7ad65f4d4c5a6c91443f669a",
    "ledgerdesk/money.py": "cfc2e861a90978065b23af49e6f1fc219a16d2324cfe4d9ec6caf7e41ecfc4ef",
    "ledgerdesk/plugins/__init__.py": "5013b87b041bb3b27191bd4fed455f5654e1a6fa60f39bfa603a5b9b0720a552",
    "ledgerdesk/plugins/availability.py": "04bb99b447cdbf1d69b62ac3d8fc65f44d9583a9f9e8e348aa775f9f111d0a2f",
    "ledgerdesk/plugins/conflicts.py": "a4c786766dff9c0c682060a11d94660220f51d0c09d500829af71c27d03fe3fd",
    "ledgerdesk/plugins/debug.py": "17fb2746c0fcdcae99c02b728b888f7f9f18852ceda62f703d0991ca25e20bef",
    "ledgerdesk/plugins/four_eyes.py": "44c2cae059745fa4617a15e611a5453a8b2051a420a13c57e4e3c07902f3a241",
    "ledgerdesk/plugins/hours.py": "d8d26cabf9b6852ece7705bd776137cfdac506e663f0337e08802af7d7cc797c",
    "ledgerdesk/plugins/legacy.py": "c318fbd5e2802f5d2cad1a95ff404cc3162b18dc6468087d07842b69d3449d28",
    "ledgerdesk/policy/__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "ledgerdesk/policy/delegation.py": "511eee1f6cf8b4e81c7971dc085ce73e348cf0f2804d1cd23c5f17359a93750f",
    "ledgerdesk/policy/engine.py": "05011cea0c3a3c9e6db9f8905ecfd5771c24cceeaa962d7b47c6a920b0cbeeee",
    "ledgerdesk/policy/roles.py": "e83e271bc71208ed8056f0d3d0b5b70a5aaa20eaca3cb0a92728e67e313731b2",
    "ledgerdesk/reports.py": "d0b1d15e28f9e6eb0d3da49d4273055fc6a40a41eab9603673c5662a9d8ee27f",
    "tests/test_ledgerdesk.py": "1804acee58f6e3c45b35594ac986277f1e29f7103827f8e2ad329d639190eef4",
}


def usernames(text: str) -> list[str]:
    """One username per line; tolerate bullets, commas, backticks and notes like '(via x)'."""
    names = []
    for line in text.splitlines():
        for piece in line.split(","):
            piece = piece.strip().lstrip("-*\u2022").strip().strip("`")
            if not piece or piece.startswith("#"):
                continue
            match = re.match(r"[A-Za-z][A-Za-z0-9_-]*", piece)
            if match:
                names.append(match.group(0).lower())
    return names


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


problems = []
for name, digest in UNCHANGED.items():
    path = root / name
    if not path.is_file():
        problems.append(f"{name} was deleted")
    elif fingerprint(path) != digest:
        problems.append(f"{name} was changed")

answer_file = root / "answer.txt"
if not answer_file.is_file():
    problems.append("answer.txt is missing")
else:
    names = usernames(answer_file.read_text(encoding="utf-8-sig", errors="replace"))
    if set(names) != EXPECTED or len(names) != len(set(names)):
        problems.append(f"wrong answer: {sorted(names)}")

for problem in problems:
    print(problem)
sys.exit(1 if problems else 0)
