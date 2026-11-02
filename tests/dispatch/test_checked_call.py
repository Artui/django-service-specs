"""What ``check_call`` returns: the checked arguments and the grant, carrying the call's seeds."""

from __future__ import annotations

import pickle
from typing import Any

import pytest

from django_service_specs.dispatch.check_call import check_call
from django_service_specs.dispatch.grant import Grant
from tests.dispatch.utils import Tenancy, make_user

pytestmark = pytest.mark.django_db


def test_check_call_still_unpacks_to_two() -> None:
    ada, tenancy = make_user("ada"), Tenancy()
    spec = tenancy.spec()

    checked = check_call(spec, principal=ada, arguments={"pk": 1}, pool_seeds=tenancy.pool_seeds)
    arguments, grant = checked

    assert isinstance(checked, tuple)
    assert len(checked) == 2
    assert checked[0] is arguments
    assert arguments == {"pk": 1}
    assert isinstance(grant, Grant)
    assert checked[1] is grant
    assert tuple(checked) == (arguments, grant)
    assert checked.seeds.covers(spec, ada, checked.seeds.call_context, tenancy.pool_seeds)


def test_it_cannot_be_pickled_for_the_seeds_it_carries() -> None:
    ada, tenancy = make_user("ada"), Tenancy()
    checked: Any = check_call(
        tenancy.spec(), principal=ada, arguments={"pk": 1}, pool_seeds=tenancy.pool_seeds
    )
    assert checked.seeds is checked.seeds

    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(checked)
