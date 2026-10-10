"""Compatibility imports; the schema language implementation lives in jsl.py."""
from .jsl import Parser, Registry, pointer_tokens

__all__ = ['Parser', 'Registry', 'pointer_tokens']
