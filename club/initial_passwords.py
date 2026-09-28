"""Name-based initial passwords; used only when creating or migrating accounts."""

import re
from pypinyin import lazy_pinyin, Style
from club.errors import fail

# Common surname readings differ from a general-purpose word dictionary.
# Other polyphonic names still require roster review before release.
SURNAMES = {
    "单": "shan",
    "解": "xie",
    "曾": "zeng",
    "仇": "qiu",
    "区": "ou",
    "查": "zha",
    "朴": "piao",
    "乐": "yue",
}
COMPOUND_SURNAMES = {"单于": "chanyu", "尉迟": "yuchi", "长孙": "zhangsun", "万俟": "moqi"}


def initial_password(name: str) -> str:
    compact = re.sub(r"[\s·・.'’-]", "", name.strip())
    surname = COMPOUND_SURNAMES.get(compact[:2])
    split = 2 if surname else 1
    surname = surname or SURNAMES.get(compact[:1], "")
    remaining = compact[split:] if surname else compact
    value = (surname + "".join(lazy_pinyin(remaining, style=Style.NORMAL, v_to_u=False))).lower()
    if not re.fullmatch(r"[a-z0-9]{1,72}", value):
        fail(422, "NAME_PINYIN_REQUIRED", "姓名无法自动生成拼音密码，请核对姓名或手动指定初始密码")
    return value
