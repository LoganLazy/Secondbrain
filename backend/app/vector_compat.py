"""Small, dependency-free helpers for embedding compatibility checks."""


def dimensions_compatible(stored: int | None, current: int | None) -> bool:
    """Unknown/empty dimensions are not a conflict; known unequal ones are."""
    return stored is None or current is None or stored == current


def mismatch_message(stored: int, current: int) -> str:
    return (
        f"知识库向量为 {stored} 维，当前模型输出 {current} 维。"
        "已自动使用关键词检索；请在设置中重建向量索引以恢复语义检索。"
    )
