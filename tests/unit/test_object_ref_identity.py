"""``ObjectRef.identity``: one key whichever reader built the model (#815).

``display`` is a spelling: the DDL reader writes what the author wrote
(``tb_probe``), the live reader what the catalog holds (``public.tb_probe``), and
generated DDL prints it, so it never invents ``public.`` for a project whose
``search_path`` is elsewhere. A consumer keys by the ref itself or by
``identity``, never by ``display``.
"""

from confiture.core.schema_model import ObjectRef, RelationName, ref_for
from confiture.core.schema_read import read_text

PROBE = (
    "CREATE TABLE tb_probe (pk_probe INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
    "id UUID NOT NULL UNIQUE);"
)


def test_an_unqualified_and_a_qualified_spelling_are_one_identity() -> None:
    bare, qualified = ref_for("table", None, "tb_probe"), ref_for("table", "public", "tb_probe")
    assert (bare.display, qualified.display) == ("tb_probe", "public.tb_probe")
    assert bare.identity == qualified.identity == ("public", "tb_probe")
    assert bare == qualified and hash(bare) == hash(qualified)


def test_identity_is_a_relation_names_identity() -> None:
    ref = ref_for("table", "app", "tb_line")
    assert ref.identity == RelationName("app", "tb_line").identity


def test_the_ddl_reader_keys_the_table_by_identity() -> None:
    (ref,) = read_text(PROBE).model.tables
    assert ref.identity == ("public", "tb_probe")
    assert ref.display == "tb_probe"


def test_identity_is_a_property_of_the_seam_type() -> None:
    assert isinstance(ObjectRef.__dict__["identity"], property)
