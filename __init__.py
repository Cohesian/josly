"""Josly: schema-driven local JSON tooling with no domain policy."""
from .jsl import Registry
from .storage import JsonAdapter, new_id
from .query import Queries
from .volume import Volume, initialize

__version__ = '0.2.1'
__all__ = ['Registry', 'JsonAdapter', 'Queries', 'new_id', 'Volume', 'initialize']
