"""
Tests for role_mapper/role_mapper.py

What we test:
- Config loading from YAML
- Exact, keyword, and fuzzy matching
- Variant listing and related roles
- Behaviour with unknown queries

Note on fixtures and scope:
RoleMapper reads a YAML file. It is cheap to create (< 1ms),
but scope="module" is good practice for objects that do not mutate between tests.
"""

import pytest
from pathlib import Path

from role_mapper.role_mapper import RoleMapper, RoleInfo


CONFIG_PATH = "role_mapper/config/roles.yaml"


@pytest.fixture(scope="module")
def mapper() -> RoleMapper:
    """
    Real RoleMapper loaded from the project YAML.
    scope="module": created once and reused across all tests in this file.
    No mocks here because the YAML is part of the project source code.
    """
    return RoleMapper(CONFIG_PATH)


class TestRoleMapperInit:
    """Tests for initialization and config loading."""

    def test_loads_roles_from_yaml(self, mapper):
        """Must load at least the 5 roles defined in roles.yaml."""
        assert len(mapper.roles) >= 5

    def test_roles_have_required_attributes(self, mapper):
        """Each role must have role_key, primary_names, variants, and category."""
        for role_key, role in mapper.roles.items():
            assert role.role_key == role_key
            assert isinstance(role.primary_names, list)
            assert len(role.primary_names) > 0
            assert isinstance(role.variants, list)
            assert role.category != ""

    def test_raises_on_invalid_config_path(self):
        """A non-existent path must raise an exception on init."""
        with pytest.raises(Exception):
            RoleMapper("does_not_exist/roles.yaml")


class TestFindRole:
    """Tests for find_role with its 3 matching tiers."""

    def test_exact_match_primary_name(self, mapper):
        """Exact match on primary name must return the correct role."""
        role = mapper.find_role("data engineer")
        assert role is not None
        assert role.role_key == "data_engineer"

    def test_exact_match_case_insensitive(self, mapper):
        """Search must be case-insensitive."""
        role = mapper.find_role("DATA ENGINEER")
        assert role is not None
        assert role.role_key == "data_engineer"

    def test_exact_match_variant(self, mapper):
        """An exact variant must resolve to the parent role."""
        # "analytics engineer" is a variant of data_engineer in roles.yaml
        role = mapper.find_role("analytics engineer")
        assert role is not None
        assert role.role_key == "data_engineer"

    def test_keyword_match(self, mapper):
        """A query with a partial keyword must find the role."""
        role = mapper.find_role("senior data engineer backend")
        assert role is not None

    def test_fuzzy_match_with_typo(self, mapper):
        """A query with a minor typo must still find the correct role."""
        # "data engineerr" has one extra character but should fuzzy-match
        role = mapper.find_role("data engineerr")
        assert role is not None

    def test_returns_none_for_completely_unknown_query(self, mapper):
        """A query with no possible match must return None."""
        role = mapper.find_role("zzzzxxx12345qwerty")
        assert role is None


class TestGetAllVariants:
    """Tests for get_all_variants."""

    def test_returns_variant_list_for_valid_role(self, mapper):
        variants = mapper.get_all_variants("data_engineer")
        assert variants is not None
        assert isinstance(variants, list)
        assert len(variants) > 0

    def test_returns_none_for_unknown_role_key(self, mapper):
        """An unknown role_key must return None, not raise an exception."""
        variants = mapper.get_all_variants("role_does_not_exist")
        assert variants is None


class TestGetRelatedRoles:
    """Tests for get_related_roles."""

    def test_returns_list_of_tuples(self, mapper):
        related = mapper.get_related_roles("data engineer")
        assert isinstance(related, list)
        for item in related:
            assert isinstance(item, tuple)
            assert len(item) == 2

    def test_scores_are_between_0_and_1(self, mapper):
        related = mapper.get_related_roles("data engineer")
        for role_key, score in related:
            assert 0.0 <= score <= 1.0

    def test_sorted_by_score_descending(self, mapper):
        related = mapper.get_related_roles("data engineer")
        if len(related) > 1:
            scores = [score for _, score in related]
            assert scores == sorted(scores, reverse=True)

    def test_original_role_not_in_related(self, mapper):
        """The searched role must not appear in its own related list."""
        related = mapper.get_related_roles("data engineer")
        related_keys = [rk for rk, _ in related]
        assert "data_engineer" not in related_keys

    def test_empty_list_for_unknown_query(self, mapper):
        """An unknown query must return an empty list."""
        related = mapper.get_related_roles("zzzzxxx12345")
        assert related == []


class TestListAllRoles:
    """Tests for list_all_roles."""

    def test_returns_list_of_dicts(self, mapper):
        roles = mapper.list_all_roles()
        assert isinstance(roles, list)
        for role in roles:
            assert isinstance(role, dict)

    def test_each_role_dict_has_required_keys(self, mapper):
        roles = mapper.list_all_roles()
        required_keys = {"role_key", "primary_names", "variants", "description"}
        for role in roles:
            assert required_keys.issubset(role.keys())

    def test_count_matches_loaded_roles(self, mapper):
        """list_all_roles must return the same count as the loaded roles dict."""
        roles = mapper.list_all_roles()
        assert len(roles) == len(mapper.roles)
