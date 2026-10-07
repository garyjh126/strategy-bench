import pytest

from strategybench.estimation.infostates import enumerate_infostates
from strategybench.games import get_game_spec
from strategybench.prompts import TEMPLATES, get_template


@pytest.mark.parametrize("game", ["kuhn", "leduc"])
def test_every_variant_renders_unique_prompts_with_the_same_label_sets(game):
    spec = get_game_spec(game)
    infos = enumerate_infostates(spec.load())
    base = [get_template(game).render(spec, i.state) for i in infos]
    for version in (v for v in TEMPLATES if v.startswith(game)):
        prompts = [get_template(game, version).render(spec, i.state) for i in infos]
        assert len({p.hash for p in prompts}) == len(infos)
        assert all(set(p.labels) == set(b.labels) for p, b in zip(prompts, base, strict=True))
        assert all(p.version == version for p in prompts)


def test_shuffled_order_is_fixed_per_infostate_and_changes_some():
    spec = get_game_spec("leduc")
    infos = enumerate_infostates(spec.load())
    t = get_template("leduc", "leduc-v1+shuffled")
    first = [t.render(spec, i.state).labels for i in infos]
    again = [t.render(spec, i.state).labels for i in infos]
    base = [get_template("leduc").render(spec, i.state).labels for i in infos]
    assert first == again
    assert sum(a != b for a, b in zip(first, base, strict=True)) > 100


def test_unknown_or_mismatched_version_is_rejected():
    with pytest.raises(KeyError):
        get_template("kuhn", "leduc-v1")
    with pytest.raises(KeyError):
        get_template("kuhn", "kuhn-v9")
