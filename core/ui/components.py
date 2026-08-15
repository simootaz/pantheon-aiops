"""Builders restricted to the allowlist.

Named components.py rather than catalog.py: core/llm/catalog.py already exists,
and two catalogs in one tree invites mis-greps - the same reasoning that renamed
registry.py to catalog.py and resolver.py to redemption.py.

Every builder returns an A2UIComponent whose type is an A2UIComponentType
member, so an unrenderable component cannot be constructed in the first place.

Phase: 4 - Delivery Flow
"""

# TODO: Phase 4 - implement one builder per allowlisted component
