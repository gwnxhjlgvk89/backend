"""Use the roster name verbatim as the initial password."""

from club.errors import fail


def initial_password(name: str) -> str:
    # Input models strip surrounding whitespace; preserve internal spaces,
    # middle dots, Chinese characters and Latin letter case exactly.
    value = name.strip()
    if not value or len(value.encode("utf-8")) > 72:
        fail(422, "INITIAL_PASSWORD_INVALID", "姓名不能为空且不能超过72字节，请核对姓名或手动指定初始密码")
    return value
