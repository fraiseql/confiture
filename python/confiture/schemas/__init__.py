"""The JSON schemas confiture publishes: the one source (Phase 06, ENG-10).

Every ``*.schema.json`` here ships in the wheel and is what
``docs/reference/json-schemas/`` copies byte for byte::

    from confiture.core.schema_exporter import load_schema
    load_schema("migrate-up.schema.json")

``confiture.export_all(dir)`` writes them all to a directory.
"""
