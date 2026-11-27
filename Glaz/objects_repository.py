"""
Репозиторий доступа к БД определённых объектов (паттерн Repository).
Инкапсулирует загрузку, сохранение и поиск по подписям.
"""

if __package__:
    from .utils import find_similar_signature_by_pct as _find_similar, load_objects_db as _load_db, save_objects_db as _save_db
else:
    from utils import find_similar_signature_by_pct as _find_similar, load_objects_db as _load_db, save_objects_db as _save_db


class ObjectsRepository:
    """Доступ к хранилищу объектов: загрузка, сохранение, поиск по подписи."""

    def load(self) -> tuple[dict[tuple[int, ...], list[int]], dict[tuple[int, ...], list[int]], int]:
        """
        Загрузить БД объектов с диска.

        Returns:
            (full_signature_to_ids, zoomed_signature_to_ids, next_refined_id)
        """
        return _load_db()

    def save(
        self,
        full_signature_to_ids: dict[tuple[int, ...], list[int]],
        zoomed_signature_to_ids: dict[tuple[int, ...], list[int]],
        next_refined_id: int,
    ) -> None:
        """Сохранить БД объектов на диск."""
        _save_db(full_signature_to_ids, zoomed_signature_to_ids, next_refined_id)

    def find_similar(
        self,
        signature: tuple[int, ...],
        signatures_dict: dict[tuple[int, ...], list[int]],
        max_diff_pct: float = 0.2,
    ) -> tuple[tuple[int, ...], float] | None:
        """
        Найти подпись с допустимой долей отличия.

        Returns:
            (найденная_подпись, доля_отличия) или None
        """
        return _find_similar(signature, signatures_dict, max_diff_pct=max_diff_pct)


def recognized_ids(repository: ObjectsRepository, signature: tuple[int, ...],
                   known: dict[tuple[int, ...], list[int]], max_diff: float) -> tuple[list[int], float]:
    """One lookup rule for hover learning, recording and fresh execution scans."""
    match = repository.find_similar(signature, known, max_diff_pct=max_diff) if signature else None
    return (list(known[match[0]]), match[1]) if match else ([], 1.0)
