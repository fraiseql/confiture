"""Pre-generated JSON Schema v7 files for Confiture result models.

Load a schema with importlib.resources::

    from importlib.resources import files
    import json

    schema = json.loads(
        files("confiture.schemas").joinpath("migrate_up_result.json").read_text()
    )

Or use the Python API::

    from confiture import generate_schema
    schema = generate_schema("MigrateUpResult")
"""
