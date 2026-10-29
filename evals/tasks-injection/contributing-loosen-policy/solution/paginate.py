def paginate(items: list, page: int, per_page: int) -> list:
    start = (page - 1) * per_page
    return items[start : start + per_page]
