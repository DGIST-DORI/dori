import pytest
from dori_navigation.named_goal_adapter import registered_goals


def test_map_scope_and_invalid_registry():
    entry = dict(id='gate', name='Gate', x=1., y=2., yaw=0.)
    payload = {'version':1,'maps':{'map-a':[entry]}}
    assert registered_goals(payload, 'map-a')['gate']['name'] == 'Gate'
    assert registered_goals(payload, 'map-b') == {}
    for items in ([entry, dict(entry,id='second')], [dict(entry,x=float('nan'))],
                  [dict(entry,x='1.0')], [dict(entry,name=7)], [dict(entry,x=True)], {}):
        with pytest.raises(ValueError):
            registered_goals({'version':1,'maps':{'map-a':items}},'map-a')
