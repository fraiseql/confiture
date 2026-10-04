"""Two build orders compared: renames paired, and only the files whose relative order moved (#580)."""

import pytest

from confiture.core.build_order import compare_orders

ORDER = ["a.sql", "b.sql", "c.sql", "d.sql", "e.sql"]


def test_identical_orders_move_nothing():
    result = compare_orders(ORDER, ORDER, {})
    assert result.moved == ()
    assert result.files == 5
    assert result.refused == ()


def test_one_file_moved_is_reported_alone_with_its_neighbours():
    new = ["a.sql", "c.sql", "d.sql", "b.sql", "e.sql"]
    result = compare_orders(ORDER, new, {})
    assert [m.path for m in result.moved] == ["b.sql"]
    move = result.moved[0]
    assert (move.was_after, move.was_before) == ("a.sql", "c.sql")
    assert (move.now_after, move.now_before) == ("d.sql", "e.sql")


def test_a_file_moved_to_the_front_has_nothing_before_it():
    new = ["d.sql", "a.sql", "b.sql", "c.sql", "e.sql"]
    move = compare_orders(ORDER, new, {}).moved[0]
    assert move.path == "d.sql"
    assert (move.now_after, move.now_before) == (None, "a.sql")


def test_two_swapped_adjacent_files_report_one_move():
    new = ["a.sql", "c.sql", "b.sql", "d.sql", "e.sql"]
    result = compare_orders(ORDER, new, {})
    assert len(result.moved) == 1
    assert result.moved[0].path in {"b.sql", "c.sql"}


def test_a_rename_that_keeps_its_place_is_one_rename_and_no_move():
    new = ["a.sql", "b2.sql", "c.sql", "d.sql", "e.sql"]
    result = compare_orders(ORDER, new, {"b.sql": "b2.sql"})
    assert result.moved == ()
    assert result.renamed == (("b.sql", "b2.sql"),)
    assert result.added == ()
    assert result.removed == ()


def test_a_rename_that_moves_is_reported_under_its_new_name():
    new = ["a.sql", "c.sql", "d.sql", "z.sql", "e.sql"]
    result = compare_orders(ORDER, new, {"b.sql": "z.sql"})
    assert [m.path for m in result.moved] == ["z.sql"]
    assert result.moved[0].was_after == "a.sql"
    assert result.renamed == (("b.sql", "z.sql"),)


def test_an_add_and_a_remove_are_counted_never_moved():
    new = ["a.sql", "b.sql", "x.sql", "d.sql", "e.sql"]
    result = compare_orders(ORDER, new, {})
    assert result.moved == ()
    assert result.added == ("x.sql",)
    assert result.removed == ("c.sql",)


def test_a_rename_out_of_the_selection_is_a_remove():
    new = ["a.sql", "c.sql", "d.sql", "e.sql"]
    result = compare_orders(ORDER, new, {"b.sql": "elsewhere/b.sql"})
    assert result.renamed == ()
    assert result.removed == ("b.sql",)


@pytest.mark.parametrize("named", ["b.sql", "b0.sql"])
def test_an_allowed_move_is_listed_and_refuses_nothing(named):
    new = ["a.sql", "c.sql", "d.sql", "b0.sql", "e.sql"]
    result = compare_orders(ORDER, new, {"b.sql": "b0.sql"}, allow=[named])
    assert [m.path for m in result.moved] == ["b0.sql"]
    assert result.allowed == ("b0.sql",)
    assert result.refused == ()


def test_an_allow_that_names_no_moved_file_allows_nothing():
    new = ["a.sql", "c.sql", "d.sql", "b.sql", "e.sql"]
    result = compare_orders(ORDER, new, {}, allow=["c.sql"])
    assert result.allowed == ()
    assert [m.path for m in result.refused] == ["b.sql"]


def test_the_fewest_files_explain_the_change():
    """One file moved from last to first is one move, not four."""
    new = ["e.sql", "a.sql", "b.sql", "c.sql", "d.sql"]
    assert [m.path for m in compare_orders(ORDER, new, {}).moved] == ["e.sql"]


def test_the_payload_names_every_field():
    new = ["a.sql", "c.sql", "d.sql", "b.sql", "e.sql"]
    payload = compare_orders(ORDER, new, {}).to_dict()
    assert payload == {
        "files": 5,
        "renamed": [],
        "added": [],
        "removed": [],
        "moved": [
            {
                "path": "b.sql",
                "was_after": "a.sql",
                "was_before": "c.sql",
                "now_after": "d.sql",
                "now_before": "e.sql",
            }
        ],
        "allowed": [],
    }
