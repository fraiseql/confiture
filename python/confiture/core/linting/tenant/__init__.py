"""The ``tenant`` lint rules: ``tenant_id`` on every relation, or declared global.

One classification of the tables (:mod:`.scope`) and five rules that read it
(:mod:`.rules`): an ``INSERT`` supplies the discriminator (``tenant_001``), a table
carries it (``tenant_002``), a view publishes it (``tenant_003``), a foreign key
cannot cross tenants (``tenant_004``), a unique key leads with it (``tenant_005``).
"""
