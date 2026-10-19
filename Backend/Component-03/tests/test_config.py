from app.config import parse_dotenv


def test_dotenv_inline_comments_quotes_and_hashes_in_values():
    env = parse_dotenv("""
# a full-line comment
C03_LLM_TIMEOUT=8              # audit trace line
KG_MODE=auto                   # auto | mock | live
C03_MONGODB_URI=mongodb+srv://user:pa#ss@cluster0.example.net/
QUOTED="keep # this"   # but not this
SINGLE='x'
EMPTY=
not a setting
""")
    assert env == {"C03_LLM_TIMEOUT": "8", "KG_MODE": "auto",
                   "C03_MONGODB_URI": "mongodb+srv://user:pa#ss@cluster0.example.net/",
                   "QUOTED": "keep # this", "SINGLE": "x", "EMPTY": ""}
