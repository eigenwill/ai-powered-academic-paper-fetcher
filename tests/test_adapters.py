"""Adapter registry sanity checks — no live browser involved."""
from __future__ import annotations


def test_pick_adapter_matches_by_domain():
    from paper_fetch.download.adapters import pick_adapter
    from paper_fetch.download.adapters.elsevier import ElsevierAdapter
    from paper_fetch.download.adapters.generic import GenericAdapter
    from paper_fetch.download.adapters.springer import SpringerAdapter

    assert isinstance(pick_adapter("https://www.sciencedirect.com/abc"), ElsevierAdapter)
    assert isinstance(pick_adapter("https://link.springer.com/article/x"), SpringerAdapter)
    assert isinstance(pick_adapter("https://some-random.example"), GenericAdapter)


def test_every_adapter_has_required_fields():
    from paper_fetch.download.adapters import REGISTRY

    for cls in REGISTRY:
        inst = cls()
        assert inst.name
        assert isinstance(inst.domain_patterns, list)
