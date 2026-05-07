from bid_knowledge.parsing.toc_leaf_builder import (
    build_toc_leaf_candidates,
    toc_leaf_section_paths,
    top_level_modules_from_toc_candidates,
)


def test_build_toc_leaf_candidates_uses_only_lowest_level_sections() -> None:
    candidates = build_toc_leaf_candidates(
        toc=[
            {"level": 1, "title": "补充文件", "page": 10},
            {"level": 2, "title": "投标保证金", "page": 11},
            {"level": 3, "title": "汇款凭证", "page": 12},
            {"level": 1, "title": "法定代表人授权委托书", "page": 14},
        ],
        page_count=20,
        path_root="PDF",
    )

    paths = toc_leaf_section_paths(candidates)

    assert paths == [
        "PDF / 补充文件 / 投标保证金 / 汇款凭证",
        "PDF / 法定代表人授权委托书",
    ]
    assert candidates[0].title == "汇款凭证"
    assert candidates[0].source_container_title == "投标保证金"
    assert candidates[0].source_page == 12
    assert candidates[0].source_page_end == 13
    assert candidates[1].title == "法定代表人授权委托书"
    assert candidates[1].source_page == 14
    assert candidates[1].source_page_end == 20


def test_top_level_modules_from_toc_candidates_uses_first_toc_level_below_root() -> None:
    candidates = build_toc_leaf_candidates(
        toc=[
            {"level": 1, "title": "补充文件", "page": 10},
            {"level": 2, "title": "投标保证金", "page": 11},
            {"level": 1, "title": "商务文件正文", "page": 20},
        ],
        page_count=30,
        path_root="PDF",
    )

    assert top_level_modules_from_toc_candidates(candidates) == ["补充文件", "商务文件正文"]
